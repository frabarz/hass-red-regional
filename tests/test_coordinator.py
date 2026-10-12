"""Unit tests for the polling coordinators."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.const import (
    CONF_DESTINATIONS,
    CONF_LOOK_AHEAD_MIN,
    CONF_MAX_DEPARTURES,
    CONF_ROUTES_WHITELIST,
    CONF_SCAN_INTERVAL_S,
    CONF_STOP_CODE,
    CONF_TRACKED_ROUTES,
    CONF_WALK_OFFSET_MIN,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DOMAIN,
)
from custom_components.red_regional.coordinator import (
    RedRegionalCoordinator,
    VehicleCoordinator,
    normalize_tracked_routes,
)
from custom_components.red_regional.exceptions import (
    TransAppAuthError,
    TransAppConnectionError,
    TransAppRateLimitError,
)
from custom_components.red_regional.gtfs import GtfsIndex, GtfsRoute, GtfsStop
from custom_components.red_regional.models import StopBoard

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"

BOARD_PAYLOAD = {
    "services": [
        {
            "name": "44B",
            "arrival_time": 5,
            "distance": 1200,
            "plate": "ABCD12",
            "direction": "I",
            "alert": None,
        },
        {"name": "63B", "arrival_time": 9, "direction": "R"},
    ]
}

MACHINES_PAYLOAD = {
    "machines": [
        {
            "license_plate": "ABCD12",
            "latitude": -36.82,
            "longitude": -73.05,
            "speed": 32,
            "route": "44B",
            "direction": "I",
        }
    ]
}


class _FakeClient:
    """Stub TransAppClient recording calls and replaying outcomes."""

    def __init__(self, outcome: Any = None, exc: Exception | None = None) -> None:
        """Store the canned payload or error."""
        self.outcome = outcome
        self.exc = exc
        self.stop_calls: list[tuple[str, str]] = []
        self.machine_calls: list[tuple[str, str, str]] = []

    async def async_get_stop_info(self, zone_uuid: str, stop_code: str) -> Any:
        """Record the call and replay the canned outcome."""
        self.stop_calls.append((zone_uuid, stop_code))
        if self.exc is not None:
            raise self.exc
        return self.outcome

    async def async_get_machines(
        self, zone_uuid: str, route: str, direction: str
    ) -> Any:
        """Record the call and replay the canned outcome."""
        self.machine_calls.append((zone_uuid, route, direction))
        if self.exc is not None:
            raise self.exc
        return self.outcome


def _board_entry(
    options: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> MockConfigEntry:
    base: dict[str, Any] = {
        CONF_ZONE_UUID: ZONE,
        CONF_ZONE_NAME: "Gran Concepción",
        CONF_STOP_CODE: "P45068",
    }
    if data:
        base.update(data)
    return MockConfigEntry(domain=DOMAIN, data=base, options=options or {}, version=1)


def _board_coordinator(
    hass: HomeAssistant, entry: MockConfigEntry, client: _FakeClient
) -> RedRegionalCoordinator:
    return RedRegionalCoordinator(
        hass,
        entry,
        cast(TransAppClient, client),
        zone_uuid=ZONE,
        zone_name="Gran Concepción",
        stop_code="P45068",
    )


async def test_board_success_and_request_shape(hass: HomeAssistant) -> None:
    """A successful tick stores departures and polls once per stop."""
    client = _FakeClient(outcome=BOARD_PAYLOAD)
    coordinator = _board_coordinator(hass, _board_entry(), client)
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert isinstance(coordinator.data, StopBoard)
    assert [d.route for d in coordinator.data.departures] == ["44B", "63B"]
    assert client.stop_calls == [(ZONE, "P45068")]


async def test_board_empty_is_unknown_safe(hass: HomeAssistant) -> None:
    """Off-hours payloads succeed with zero departures, no exception."""
    client = _FakeClient(outcome={"events": [], "alerts": [], "predictions": []})
    coordinator = _board_coordinator(hass, _board_entry(), client)
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator.data is not None
    assert coordinator.data.departures == ()


async def test_board_options_filters_apply(hass: HomeAssistant) -> None:
    """Whitelist and window options narrow the stored board."""
    client = _FakeClient(outcome=BOARD_PAYLOAD)
    entry = _board_entry(
        options={CONF_ROUTES_WHITELIST: ["44b"], CONF_MAX_DEPARTURES: 5}
    )
    coordinator = _board_coordinator(hass, entry, client)
    await coordinator.async_refresh()
    assert coordinator.data is not None
    assert [d.route for d in coordinator.data.departures] == ["44B"]


async def test_board_auth_error(hass: HomeAssistant) -> None:
    """Auth rejections surface for the reauth flow."""
    client = _FakeClient(exc=TransAppAuthError("denied"))
    coordinator = _board_coordinator(hass, _board_entry(), client)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_board_rate_limit_backs_off(hass: HomeAssistant) -> None:
    """429 maps to UpdateFailed carrying a retry delay."""
    client = _FakeClient(exc=TransAppRateLimitError("slow down"))
    coordinator = _board_coordinator(hass, _board_entry(), client)
    with pytest.raises(UpdateFailed) as err:
        await coordinator._async_update_data()
    assert err.value.retry_after == 120


async def test_board_failure_keeps_last_known(hass: HomeAssistant) -> None:
    """Transient failures keep prior data instead of clearing it."""
    client = _FakeClient(outcome=BOARD_PAYLOAD)
    coordinator = _board_coordinator(hass, _board_entry(), client)
    await coordinator.async_refresh()
    before = coordinator.data
    client.exc = TransAppConnectionError("down")
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert coordinator.data is before


async def test_board_interval_from_options(hass: HomeAssistant) -> None:
    """Scan interval follows options and refresh_options picks changes."""
    entry = _board_entry(options={CONF_SCAN_INTERVAL_S: 30})
    coordinator = _board_coordinator(hass, entry, _FakeClient())
    assert coordinator.update_interval == timedelta(seconds=30)
    coordinator.refresh_options()
    assert coordinator.update_interval == timedelta(seconds=30)


async def test_board_data_options_override(hass: HomeAssistant) -> None:
    """Filter setup data applies when no options exist yet."""
    entry = _board_entry(
        data={
            CONF_ROUTES_WHITELIST: ["63B"],
            CONF_DESTINATIONS: [],
            CONF_MAX_DEPARTURES: 5,
            CONF_LOOK_AHEAD_MIN: 120,
            CONF_WALK_OFFSET_MIN: 0,
        }
    )
    client = _FakeClient(outcome=BOARD_PAYLOAD)
    coordinator = _board_coordinator(hass, entry, client)
    await coordinator.async_refresh()
    assert coordinator.data is not None
    assert [d.route for d in coordinator.data.departures] == ["63B"]


def test_normalize_tracked_routes() -> None:
    """Tracked-route config normalizes; junk drops out."""
    assert normalize_tracked_routes("44B") == ()
    assert normalize_tracked_routes(["44B"]) == (("44B", "I"),)
    assert normalize_tracked_routes(
        [{"route": "44B", "direction": "R"}, {"route": "x"}, 5, {"route": ""}]
    ) == (("44B", "R"), ("x", "I"))
    assert normalize_tracked_routes([{"route": "44B", "direction": "X"}]) == (
        ("44B", "I"),
    )


async def test_vehicles_aggregate_per_route(hass: HomeAssistant) -> None:
    """One machines request goes out per watched route per tick."""
    entry = _board_entry(
        options={CONF_TRACKED_ROUTES: ["44B", {"route": "63B", "direction": "R"}]}
    )
    client = _FakeClient(outcome=MACHINES_PAYLOAD)
    coordinator = VehicleCoordinator(
        hass, entry, cast(TransAppClient, client), zone_uuid=ZONE
    )
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator.data is not None
    assert len(coordinator.data) == 2
    assert client.machine_calls == [(ZONE, "44B", "I"), (ZONE, "63B", "R")]


async def test_vehicles_untracked_is_empty_without_http(
    hass: HomeAssistant,
) -> None:
    """No watched routes means no requests and no positions."""
    client = _FakeClient(outcome=MACHINES_PAYLOAD)
    coordinator = VehicleCoordinator(
        hass, _board_entry(), cast(TransAppClient, client), zone_uuid=ZONE
    )
    await coordinator.async_refresh()
    assert coordinator.data == ()
    assert client.machine_calls == []


async def test_vehicles_auth_error(hass: HomeAssistant) -> None:
    """Vehicle auth rejections surface for the reauth flow."""
    entry = _board_entry(options={CONF_TRACKED_ROUTES: ["44B"]})
    client = _FakeClient(exc=TransAppAuthError("denied"))
    coordinator = VehicleCoordinator(
        hass, entry, cast(TransAppClient, client), zone_uuid=ZONE
    )
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_vehicles_rate_limit_backs_off(hass: HomeAssistant) -> None:
    """Vehicle 429 maps to UpdateFailed carrying a retry delay."""
    entry = _board_entry(options={CONF_TRACKED_ROUTES: ["44B"]})
    client = _FakeClient(exc=TransAppRateLimitError("slow down"))
    coordinator = VehicleCoordinator(
        hass, entry, cast(TransAppClient, client), zone_uuid=ZONE
    )
    with pytest.raises(UpdateFailed) as err:
        await coordinator._async_update_data()
    assert err.value.retry_after == 120


async def test_vehicles_failure_keeps_last_known(hass: HomeAssistant) -> None:
    """Vehicle outages keep prior positions instead of clearing them."""
    entry = _board_entry(options={CONF_TRACKED_ROUTES: ["44B"]})
    client = _FakeClient(outcome=MACHINES_PAYLOAD)
    coordinator = VehicleCoordinator(
        hass, entry, cast(TransAppClient, client), zone_uuid=ZONE
    )
    await coordinator.async_refresh()
    before = coordinator.data
    client.exc = TransAppConnectionError("down")
    await coordinator.async_refresh()
    assert coordinator.last_update_success is False
    assert coordinator.data is before


async def test_setup_enriches_board_from_gtfs(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GTFS loaded at setup fills stop names, colors, and destinations."""
    from custom_components.red_regional import coordinator as coordinator_module

    async def fake_ensure(hass: object, client: object, zone_uuid: str) -> GtfsIndex:
        return GtfsIndex(
            stops={"P45068": GtfsStop(name="GTFS Stop")},
            routes={"44B": GtfsRoute(long_name="Hualpencillo", color="#EC6907")},
        )

    monkeypatch.setattr(coordinator_module, "async_ensure_gtfs", fake_ensure)
    client = _FakeClient(outcome={"services": [{"name": "44B", "arrival_time": 5}]})
    coordinator = _board_coordinator(hass, _board_entry(), client)
    await coordinator._async_setup()
    await coordinator.async_refresh()
    assert coordinator.data is not None
    assert coordinator.data.stop_name == "GTFS Stop"
    departure = coordinator.data.departures[0]
    assert departure.destination == "Hualpencillo"
    assert departure.route_color == "#EC6907"
