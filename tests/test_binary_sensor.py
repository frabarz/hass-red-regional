"""Unit tests for the Red Regional service alert sensor."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.const import (
    CONF_STOP_CODE,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"

ALERT_PAYLOAD: dict[str, Any] = {
    "routeInfo": [],
    "predictions": [],
    "alerts": [
        {
            "title": "Corte",
            "description": "Puente cerrado",
            "routes": ["44B"],
            "valid_from": "2026-03-01T00:00:00-03:00",
            "valid_until": "2026-12-31T23:59:00-03:00",
        }
    ],
    "events": [
        {
            "name": "Mala Iluminación",
            "description": "",
            "expiryTime": "2026-12-13T21:16:49.980Z",
        }
    ],
}


async def _setup_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, payload: Any
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
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    return entry


def _alert_state(hass: HomeAssistant) -> Any:
    states = hass.states.async_entity_ids("binary_sensor")
    assert len(states) == 1
    return hass.states.get(states[0])


async def test_alert_on_with_populated_attributes(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operator alerts and live events switch the sensor on."""
    await _setup_entry(hass, monkeypatch, ALERT_PAYLOAD)
    state = _alert_state(hass)
    assert state.state == "on"
    alerts = state.attributes["alerts"]
    assert [alert["title"] for alert in alerts] == ["Corte", "Mala Iluminación"]
    assert alerts[0]["routes"] == ["44B"]
    assert alerts[0]["description"] == "Puente cerrado"
    assert alerts[0]["valid_from"] == "2026-03-01T00:00:00-03:00"
    assert alerts[0]["valid_until"] == "2026-12-31T23:59:00-03:00"
    entities = er.async_get(hass)
    entity_id = entities.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{ZONE}_P45068_alert"
    )
    assert entity_id == state.entity_id


async def test_no_alerts_is_off(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quiet boards read off with empty attributes."""
    await _setup_entry(hass, monkeypatch, {"routeInfo": [], "predictions": []})
    state = _alert_state(hass)
    assert state.state == "off"
    assert state.attributes["alerts"] == []


async def test_alert_shares_stop_device(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Alert and departure sensors attach to the same stop device."""
    await _setup_entry(hass, monkeypatch, ALERT_PAYLOAD)
    entities = er.async_get(hass)
    alert_id = entities.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{ZONE}_P45068_alert"
    )
    next_id = entities.async_get_entity_id("sensor", DOMAIN, f"{ZONE}_P45068_next")
    assert alert_id is not None and next_id is not None
    alert_entry = entities.async_get(alert_id)
    next_entry = entities.async_get(next_id)
    assert alert_entry is not None and next_entry is not None
    assert alert_entry.device_id == next_entry.device_id
