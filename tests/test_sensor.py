"""Unit tests for the Red Regional board sensors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.const import (
    CONF_ROUTES_WHITELIST,
    CONF_STOP_CODE,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DOMAIN,
)
from custom_components.red_regional.sensor import DeparturesCountSensor

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"

BOARD_PAYLOAD: dict[str, Any] = {
    "routeInfo": [{"route": "44B"}],
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
    ],
    "stop": {"code": "P45068", "name": "Plaza Tribunales de Justicia"},
}


async def _setup_entry(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    payload: Any,
    options: dict[str, Any] | None = None,
) -> MockConfigEntry:
    async def fake_stop_info(
        self: TransAppClient, zone_uuid: str, stop_code: str
    ) -> Any:
        return payload

    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop_info)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ZONE_UUID: ZONE,
            CONF_ZONE_NAME: "Gran Concepción",
            CONF_STOP_CODE: "P45068",
        },
        options=options or {},
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    return entry


def _next_state(hass: HomeAssistant) -> Any:
    states = hass.states.async_entity_ids("sensor")
    assert len(states) == 1
    return hass.states.get(states[0])


async def test_next_departure_state_and_attributes(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timestamp state matches the soonest departure with rich attributes."""
    await _setup_entry(hass, monkeypatch, BOARD_PAYLOAD)
    state = _next_state(hass)
    attrs = state.attributes
    assert attrs["stop_code"] == "P45068"
    assert attrs["stop_name"] == "Plaza Tribunales de Justicia"
    assert attrs["zone"] == "Gran Concepción"
    assert attrs["departure_count"] == 2
    assert len(attrs["departures"]) == 2
    first = attrs["departures"][0]
    assert first["route"] == "44B"
    assert first["vehicle_id"] == "ABCD12"
    assert first["direction"] == "I"
    assert first["realtime"] is True
    assert first["cancelled"] is False
    assert datetime.fromisoformat(state.state).replace(
        microsecond=0
    ) == datetime.fromisoformat(first["expected_at"]).replace(microsecond=0)
    assert attrs["departures_text"] == ", ".join(
        f"{dep['route']} in {dep['due_in_min']} min" for dep in attrs["departures"]
    )
    assert attrs["attribution"].startswith("Datos:")
    assert datetime.fromisoformat(attrs["last_update"]) is not None


async def test_empty_board_is_unknown(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off-hours boards read unknown with zeroed attributes."""
    await _setup_entry(hass, monkeypatch, {"routeInfo": [], "predictions": []})
    state = _next_state(hass)
    assert state.state == "unknown"
    assert state.attributes["departure_count"] == 0
    assert state.attributes["departures"] == []
    assert state.attributes["departures_text"] == ""


async def test_filters_narrow_sensor(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whitelists set at setup narrow the sensor state and attributes."""
    await _setup_entry(
        hass, monkeypatch, BOARD_PAYLOAD, options={CONF_ROUTES_WHITELIST: ["44B"]}
    )
    state = _next_state(hass)
    assert state.attributes["departure_count"] == 1
    assert state.attributes["departures"][0]["route"] == "44B"


async def test_options_change_updates_sensor(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Option edits propagate live to the sensor."""
    entry = await _setup_entry(hass, monkeypatch, BOARD_PAYLOAD)
    assert _next_state(hass).attributes["departure_count"] == 2
    hass.config_entries.async_update_entry(
        entry, options={CONF_ROUTES_WHITELIST: ["63B"]}
    )
    await hass.async_block_till_done()
    state = _next_state(hass)
    assert state.attributes["departure_count"] == 1
    assert state.attributes["departures"][0]["route"] == "63B"


async def test_unique_ids_device_and_disabled_count(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stable ids, shared stop device, and opt-in count sensor."""
    entry = await _setup_entry(hass, monkeypatch, BOARD_PAYLOAD)
    entities = er.async_get(hass)
    next_id = entities.async_get_entity_id("sensor", DOMAIN, f"{ZONE}_P45068_next")
    count_id = entities.async_get_entity_id("sensor", DOMAIN, f"{ZONE}_P45068_count")
    assert next_id is not None
    assert count_id is not None
    count_entry = entities.async_get(count_id)
    assert count_entry is not None
    assert count_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    devices = dr.async_get(hass)
    device = devices.async_get_device_by_identifier(
        (DOMAIN, f"{ZONE}_P45068"), entry.entry_id
    )
    assert device is not None
    assert device.manufacturer == "DTPR / Red Regional"
    assert device.model == "Gran Concepción"
    assert device.name == "Plaza Tribunales de Justicia (P45068)"


async def test_count_sensor_reports_board_size(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The count sensor mirrors the filtered board length."""
    entry = await _setup_entry(hass, monkeypatch, BOARD_PAYLOAD)
    assert DeparturesCountSensor(entry.runtime_data.board).native_value == 2
