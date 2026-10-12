"""Unit tests for the Red Regional live bus trackers."""

from __future__ import annotations

from typing import Any, cast

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.const import (
    CONF_STOP_CODE,
    CONF_TRACK_VEHICLES,
    CONF_TRACKED_ROUTES,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DOMAIN,
)
from custom_components.red_regional.coordinator import VehicleCoordinator
from custom_components.red_regional.device_tracker import RedRegionalBusTracker
from custom_components.red_regional.models import VehiclePosition

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"

BUS = {
    "license_plate": "ABCD12",
    "latitude": -36.82,
    "longitude": -73.05,
    "speed": 32,
    "route": "44B",
    "direction": "I",
}


async def _setup_entry(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    machines: Any,
    tracked: Any = None,
) -> MockConfigEntry:
    if tracked is None:
        tracked = [{"route": "44B", "direction": "I"}]

    async def fake_stop_info(
        self: TransAppClient, zone_uuid: str, stop_code: str
    ) -> Any:
        return {"routeInfo": [], "predictions": []}

    async def fake_machines(
        self: TransAppClient, zone_uuid: str, route: str, direction: str
    ) -> Any:
        return machines() if callable(machines) else machines

    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop_info)
    monkeypatch.setattr(TransAppClient, "async_get_machines", fake_machines)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ZONE_UUID: ZONE,
            CONF_ZONE_NAME: "Gran Concepción",
            CONF_STOP_CODE: "P45068",
            CONF_TRACK_VEHICLES: True,
            CONF_TRACKED_ROUTES: tracked,
        },
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    return entry


def _tracker_states(hass: HomeAssistant) -> list[Any]:
    return [
        hass.states.get(entity_id)
        for entity_id in hass.states.async_entity_ids("device_tracker")
    ]


async def test_bus_in_service_is_mapped(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An active bus yields a GPS tracker with telemetry attributes."""
    await _setup_entry(hass, monkeypatch, {"machines": [BUS], "stops": []})
    states = _tracker_states(hass)
    assert len(states) == 1
    state = states[0]
    assert state.attributes["latitude"] == -36.82
    assert state.attributes["longitude"] == -73.05
    assert state.attributes["source_type"] == "gps"
    assert state.attributes["route"] == "44B"
    assert state.attributes["direction"] == "I"
    assert state.attributes["speed_kmh"] == 32
    assert state.attributes["plate"] == "ABCD12"
    assert state.attributes["last_update"] is not None
    entities = er.async_get(hass)
    assert (
        entities.async_get_entity_id("device_tracker", DOMAIN, f"{ZONE}_ABCD12")
        == state.entity_id
    )


async def test_no_buses_means_no_trackers(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty machines create zero tracker entities."""
    await _setup_entry(hass, monkeypatch, {"machines": [], "stops": []})
    assert _tracker_states(hass) == []


async def test_retired_bus_is_removed(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Buses leaving service take their trackers with them."""
    box: dict[str, Any] = {"payload": {"machines": [BUS], "stops": []}}
    entry = await _setup_entry(hass, monkeypatch, lambda: box["payload"])
    assert len(_tracker_states(hass)) == 1
    box["payload"] = {"machines": [], "stops": []}
    await entry.runtime_data.vehicles.async_refresh()
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    assert _tracker_states(hass) == []
    entities = er.async_get(hass)
    leftovers = [
        entity
        for entity in entities.entities.values()
        if entity.platform == DOMAIN and entity.domain == "device_tracker"
    ]
    assert leftovers == []


async def test_plate_collision_splits_by_direction(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One plate in both directions yields two direction-suffixed trackers."""
    other = dict(BUS, direction="R", latitude=-36.9)
    await _setup_entry(
        hass,
        monkeypatch,
        {"machines": [BUS, other], "stops": []},
        tracked=["44B", {"route": "44B", "direction": "R"}],
    )
    states = _tracker_states(hass)
    assert len(states) == 2
    entities = er.async_get(hass)
    ids = {
        entities.async_get_entity_id("device_tracker", DOMAIN, f"{ZONE}_ABCD12_I"),
        entities.async_get_entity_id("device_tracker", DOMAIN, f"{ZONE}_ABCD12_R"),
    }
    assert ids == {state.entity_id for state in states}
    assert {state.attributes["direction"] for state in states} == {"I", "R"}


async def test_untracked_entry_has_no_trackers(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Entries without vehicle tracking set up no tracker platform."""
    await _setup_entry(hass, monkeypatch, {"machines": [BUS]}, tracked=[])
    assert _tracker_states(hass) == []


def test_position_skips_other_plates(hass: HomeAssistant) -> None:
    """Trackers ignore positions belonging to other vehicles."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    coordinator = VehicleCoordinator(
        hass, entry, cast(TransAppClient, None), zone_uuid=ZONE
    )
    coordinator.data = (VehiclePosition(plate="OTHER", latitude=0.0, longitude=0.0),)
    tracker = RedRegionalBusTracker(
        coordinator,
        unique_id=f"{ZONE}_ABCD12",
        zone_uuid=ZONE,
        zone_name=None,
        plate="ABCD12",
        direction=None,
    )
    assert tracker.latitude is None
    assert tracker.longitude is None
    assert tracker.extra_state_attributes["route"] is None
