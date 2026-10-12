"""Unit tests for the Red Regional services."""

from __future__ import annotations

import io
import zipfile
from typing import Any, cast

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.red_regional import async_setup
from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.const import (
    CONF_STOP_CODE,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DOMAIN,
)
from custom_components.red_regional.services import async_setup_services
from tests.conftest import device_by_identifier

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"
LOOKUP_ZONE = "11111111-1111-4111-8111-111111111111"

BOARD_PAYLOAD: dict[str, Any] = {
    "routeInfo": [],
    "services": [{"name": "44B", "arrival_time": 5}],
}

BUS_PAYLOAD: dict[str, Any] = {
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


def _comma_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "stops.txt",
            "stop_id,stop_name,stop_lat,stop_lon,stop_code\n"
            "1,Parada Uno,-36.8,-73.0,P00001\n",
        )
        archive.writestr(
            "routes.txt",
            "route_id,route_short_name,route_long_name,route_color\n"
            "r1,44B,Hualpencillo,EC6907\n",
        )
    return buffer.getvalue()


async def _setup_entry(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    calls: list[tuple[str, str]],
) -> MockConfigEntry:
    async def fake_stop_info(
        self: TransAppClient, zone_uuid: str, stop_code: str
    ) -> Any:
        calls.append((zone_uuid, stop_code))
        return BOARD_PAYLOAD

    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop_info)
    async_setup_services(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ZONE_UUID: ZONE,
            CONF_ZONE_NAME: "Gran Concepción",
            CONF_STOP_CODE: "P45068",
        },
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    return entry


async def test_services_register_once(hass: HomeAssistant) -> None:
    """Registration is idempotent and exposed via integration setup."""
    assert await async_setup(hass, {}) is True
    async_setup_services(hass)
    for service in ("refresh", "lookup_stop", "get_vehicles"):
        assert hass.services.has_service(DOMAIN, service)


async def test_refresh_by_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh by entry polls the board coordinator again."""
    calls: list[tuple[str, str]] = []
    entry = await _setup_entry(hass, monkeypatch, calls)
    before = len(calls)
    await hass.services.async_call(
        DOMAIN, "refresh", {"config_entry_id": entry.entry_id}, blocking=True
    )
    assert len(calls) == before + 1


async def test_refresh_by_device(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh by device resolves the owning entry."""
    calls: list[tuple[str, str]] = []
    entry = await _setup_entry(hass, monkeypatch, calls)
    device = device_by_identifier(
        dr.async_get(hass), (DOMAIN, f"{ZONE}_P45068"), entry.entry_id
    )
    assert device is not None
    before = len(calls)
    await hass.services.async_call(
        DOMAIN, "refresh", {"device_id": device.id}, blocking=True
    )
    assert len(calls) == before + 1


async def test_refresh_with_tracking_refreshes_vehicles(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh also polls the vehicle coordinator when tracking."""
    from custom_components.red_regional.const import (
        CONF_TRACK_VEHICLES,
        CONF_TRACKED_ROUTES,
    )

    stop_calls: list[tuple[str, str]] = []
    machine_calls: list[tuple[str, str, str]] = []

    async def fake_stop_info(
        self: TransAppClient, zone_uuid: str, stop_code: str
    ) -> Any:
        stop_calls.append((zone_uuid, stop_code))
        return BOARD_PAYLOAD

    async def fake_machines(
        self: TransAppClient, zone_uuid: str, route: str, direction: str
    ) -> Any:
        machine_calls.append((zone_uuid, route, direction))
        return {"machines": []}

    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop_info)
    monkeypatch.setattr(TransAppClient, "async_get_machines", fake_machines)
    async_setup_services(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ZONE_UUID: ZONE,
            CONF_ZONE_NAME: "Gran Concepción",
            CONF_STOP_CODE: "P45068",
            CONF_TRACK_VEHICLES: True,
            CONF_TRACKED_ROUTES: [{"route": "44B", "direction": "I"}],
        },
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    stops_before = len(stop_calls)
    machines_before = len(machine_calls)
    await hass.services.async_call(
        DOMAIN, "refresh", {"config_entry_id": entry.entry_id}, blocking=True
    )
    assert len(stop_calls) == stops_before + 1
    assert len(machine_calls) == machines_before + 1


async def test_refresh_rejects(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresh without a target or with unknown ids fails cleanly."""
    calls: list[tuple[str, str]] = []
    await _setup_entry(hass, monkeypatch, calls)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "refresh", {}, blocking=True)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "refresh", {"config_entry_id": "nope"}, blocking=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "refresh", {"device_id": "nope"}, blocking=True
        )


async def test_lookup_stop_from_cache(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cached GTFS answers stop searches without live calls."""
    stop_calls: list[tuple[str, str]] = []

    async def fake_version(self: TransAppClient, zone_uuid: str) -> Any:
        return {"version": "v1"}

    async def fake_fetch(self: TransAppClient, zone_uuid: str) -> bytes:
        return _comma_zip()

    async def fake_stop(self: TransAppClient, zone_uuid: str, stop_code: str) -> Any:
        stop_calls.append((zone_uuid, stop_code))
        raise AssertionError("live fallback must not run")

    monkeypatch.setattr(TransAppClient, "async_get_gtfs_version", fake_version)
    monkeypatch.setattr(TransAppClient, "async_fetch_gtfs", fake_fetch)
    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop)
    async_setup_services(hass)
    response = cast(
        dict[str, Any],
        await hass.services.async_call(
            DOMAIN,
            "lookup_stop",
            {"zone_uuid": LOOKUP_ZONE, "query": "p00001"},
            blocking=True,
            return_response=True,
        ),
    )
    assert response is not None
    (candidate,) = response["candidates"]
    assert candidate["stop_code"] == "P00001"
    assert candidate["stop_name"] == "Parada Uno"
    assert candidate["latitude"] == -36.8
    assert stop_calls == []


async def test_lookup_stop_live_fallback(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown codes validate live when the cache has no answer."""
    payload = _comma_zip()

    async def fake_version(self: TransAppClient, zone_uuid: str) -> Any:
        return {"version": "v1"}

    async def fake_fetch(self: TransAppClient, zone_uuid: str) -> bytes:
        return payload

    async def fake_stop(self: TransAppClient, zone_uuid: str, stop_code: str) -> Any:
        return {
            "routeInfo": [],
            "stop": {"code": stop_code, "name": "Live Stop"},
        }

    monkeypatch.setattr(TransAppClient, "async_get_gtfs_version", fake_version)
    monkeypatch.setattr(TransAppClient, "async_fetch_gtfs", fake_fetch)
    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop)
    async_setup_services(hass)
    response = cast(
        dict[str, Any],
        await hass.services.async_call(
            DOMAIN,
            "lookup_stop",
            {"zone_uuid": LOOKUP_ZONE, "query": "P99999"},
            blocking=True,
            return_response=True,
        ),
    )
    assert response is not None
    (candidate,) = response["candidates"]
    assert candidate["stop_code"] == "P99999"
    assert candidate["stop_name"] == "Live Stop"
    assert candidate["latitude"] is None


async def test_get_vehicles(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Vehicle queries return serialized telemetry, defaulting to I."""
    seen: list[tuple[str, str, str]] = []

    async def fake_machines(
        self: TransAppClient, zone_uuid: str, route: str, direction: str
    ) -> Any:
        seen.append((zone_uuid, route, direction))
        return BUS_PAYLOAD

    monkeypatch.setattr(TransAppClient, "async_get_machines", fake_machines)
    async_setup_services(hass)
    response = cast(
        dict[str, Any],
        await hass.services.async_call(
            DOMAIN,
            "get_vehicles",
            {"zone_uuid": ZONE, "route": "44B"},
            blocking=True,
            return_response=True,
        ),
    )
    assert response is not None
    (bus,) = response["vehicles"]
    assert bus["plate"] == "ABCD12"
    assert (bus["latitude"], bus["longitude"]) == (-36.82, -73.05)
    assert bus["speed_kmh"] == 32
    assert bus["last_update"] is not None
    assert seen == [(ZONE, "44B", "I")]
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "get_vehicles",
            {"zone_uuid": ZONE, "route": "44B", "direction": "X"},
            blocking=True,
            return_response=True,
        )
