"""Unit tests for the Red Regional options flow."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.const import (
    CONF_DESTINATIONS,
    CONF_LOOK_AHEAD_MIN,
    CONF_MAX_DEPARTURES,
    CONF_ROUTES_WHITELIST,
    CONF_SCAN_INTERVAL_S,
    CONF_STOP_CODE,
    CONF_TRACK_VEHICLES,
    CONF_TRACKED_ROUTES,
    CONF_WALK_OFFSET_MIN,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"


async def _setup_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> MockConfigEntry:
    async def fake_stop_info(
        self: TransAppClient, zone_uuid: str, stop_code: str
    ) -> Any:
        return {"routeInfo": [], "predictions": []}

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


async def test_options_save_normalizes_and_retunes(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Saved options normalize and reach the live coordinator."""
    entry = await _setup_entry(hass, monkeypatch)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    assert flow["type"] == FlowResultType.FORM
    done = await hass.config_entries.options.async_configure(
        flow["flow_id"],
        {
            CONF_ROUTES_WHITELIST: "44B, 63b",
            CONF_DESTINATIONS: "Hualpen",
            CONF_MAX_DEPARTURES: 3,
            CONF_LOOK_AHEAD_MIN: 90,
            CONF_WALK_OFFSET_MIN: 2,
            CONF_TRACK_VEHICLES: False,
            CONF_TRACKED_ROUTES: "",
            CONF_SCAN_INTERVAL_S: 45,
        },
    )
    assert done["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ROUTES_WHITELIST] == ["44B", "63b"]
    assert entry.options[CONF_DESTINATIONS] == ["Hualpen"]
    assert entry.options[CONF_MAX_DEPARTURES] == 3
    assert entry.options[CONF_LOOK_AHEAD_MIN] == 90
    assert entry.options[CONF_WALK_OFFSET_MIN] == 2
    assert entry.options[CONF_SCAN_INTERVAL_S] == 45
    board = entry.runtime_data.board
    assert board.update_interval == timedelta(seconds=45)
    assert board.routes_whitelist == ("44B", "63b")


async def test_options_reject_out_of_range(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Out-of-range values fail validation and save nothing."""
    entry = await _setup_entry(hass, monkeypatch)
    flow = await hass.config_entries.options.async_init(entry.entry_id)
    with pytest.raises(InvalidData) as err:
        await hass.config_entries.options.async_configure(
            flow["flow_id"],
            {
                CONF_ROUTES_WHITELIST: "",
                CONF_DESTINATIONS: "",
                CONF_MAX_DEPARTURES: 99,
                CONF_LOOK_AHEAD_MIN: 120,
                CONF_WALK_OFFSET_MIN: 0,
                CONF_TRACK_VEHICLES: False,
                CONF_TRACKED_ROUTES: "",
                CONF_SCAN_INTERVAL_S: 60,
            },
        )
    assert "max_departures" in err.value.schema_errors
    assert CONF_MAX_DEPARTURES not in entry.options


async def test_options_prefill_from_saved_lists(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reopening options renders stored lists back into the form."""
    entry = await _setup_entry(hass, monkeypatch)
    first = await hass.config_entries.options.async_init(entry.entry_id)
    done = await hass.config_entries.options.async_configure(
        first["flow_id"],
        {
            CONF_ROUTES_WHITELIST: "44B",
            CONF_DESTINATIONS: "",
            CONF_MAX_DEPARTURES: 5,
            CONF_LOOK_AHEAD_MIN: 120,
            CONF_WALK_OFFSET_MIN: 0,
            CONF_TRACK_VEHICLES: True,
            CONF_TRACKED_ROUTES: "44B:R",
            CONF_SCAN_INTERVAL_S: 60,
        },
    )
    assert done["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_TRACKED_ROUTES] == [{"route": "44B", "direction": "R"}]
    second = await hass.config_entries.options.async_init(entry.entry_id)
    assert second["type"] == FlowResultType.FORM
    redone = await hass.config_entries.options.async_configure(
        second["flow_id"],
        {
            CONF_ROUTES_WHITELIST: "63B",
            CONF_DESTINATIONS: "",
            CONF_MAX_DEPARTURES: 5,
            CONF_LOOK_AHEAD_MIN: 120,
            CONF_WALK_OFFSET_MIN: 0,
            CONF_TRACK_VEHICLES: True,
            CONF_TRACKED_ROUTES: "44B:R",
            CONF_SCAN_INTERVAL_S: 60,
        },
    )
    assert redone["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_ROUTES_WHITELIST] == ["63B"]
