"""Unit tests for Red Regional diagnostics redaction."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.const import (
    CONF_PHONE_ID,
    CONF_STOP_CODE,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DOMAIN,
)
from custom_components.red_regional.diagnostics import (
    async_get_config_entry_diagnostics,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"

BOARD_PAYLOAD: dict[str, Any] = {
    "routeInfo": [],
    "services": [
        {
            "name": "44B",
            "arrival_time": 5,
            "plate": "ABCD12",
            "direction": "I",
        }
    ],
    "alerts": [{"title": "Corte", "description": "Obras"}],
}


async def test_diagnostics_redact_phone_id(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Diagnostics expose the board but never the phone id."""
    phone = "11111111-1111-4111-8111-111111111111"

    async def fake_stop_info(
        self: TransAppClient, zone_uuid: str, stop_code: str
    ) -> Any:
        return BOARD_PAYLOAD

    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop_info)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ZONE_UUID: ZONE,
            CONF_ZONE_NAME: "Gran Concepción",
            CONF_STOP_CODE: "P45068",
            CONF_PHONE_ID: phone,
        },
        version=1,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    payload = await async_get_config_entry_diagnostics(hass, entry)
    assert payload["entry"]["data"][CONF_PHONE_ID] == "**REDACTED**"
    assert phone not in str(payload)
    assert payload["board"]["stop_code"] == "P45068"
    assert payload["board"]["departures"][0]["route"] == "44B"
    assert payload["board"]["departures"][0]["vehicle_id"] == "ABCD12"
    assert payload["board"]["alerts"][0]["title"] == "Corte"
    assert payload["vehicles"] == []
