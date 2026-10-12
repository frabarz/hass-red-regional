"""Unit tests for the Red Regional entry lifecycle."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.red_regional import (
    RedRegionalRuntimeData,
    async_migrate_entry,
)
from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.const import (
    CONF_PHONE_ID,
    CONF_SCAN_INTERVAL_S,
    CONF_STOP_CODE,
    CONF_TRACK_VEHICLES,
    CONF_TRACKED_ROUTES,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

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
    ],
}


def _entry(data: dict[str, Any] | None = None) -> MockConfigEntry:
    base: dict[str, Any] = {
        CONF_ZONE_UUID: ZONE,
        CONF_ZONE_NAME: "Gran Concepción",
        CONF_STOP_CODE: "P45068",
    }
    if data:
        base.update(data)
    return MockConfigEntry(domain=DOMAIN, data=base, version=1)


async def _setup(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    entry: MockConfigEntry,
) -> MockConfigEntry:
    async def fake_stop_info(
        self: TransAppClient,
        zone_uuid: str,
        stop_code: str,
    ) -> Any:
        return BOARD_PAYLOAD

    async def fake_machines(
        self: TransAppClient,
        zone_uuid: str,
        route: str,
        direction: str,
    ) -> Any:
        return {"machines": []}

    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop_info)
    monkeypatch.setattr(TransAppClient, "async_get_machines", fake_machines)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    return entry


async def test_setup_creates_runtime_and_persists_phone_id(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setup stores coordinators and generates the phone id once."""
    entry = await _setup(hass, monkeypatch, _entry())
    data: RedRegionalRuntimeData = entry.runtime_data
    assert data.zone_uuid == ZONE
    assert data.stop_code == "P45068"
    assert data.vehicles is None
    assert data.board.data is not None
    assert [d.route for d in data.board.data.departures] == ["44B"]
    stored = entry.data[CONF_PHONE_ID]
    UUID(stored)


async def test_setup_reuses_persisted_phone_id(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored phone id survives restarts instead of regenerating."""
    first = await _setup(hass, monkeypatch, _entry())
    stored = first.data[CONF_PHONE_ID]
    second = await _setup(hass, monkeypatch, _entry())
    assert second.data[CONF_PHONE_ID] != stored
    injected = _entry(data={CONF_PHONE_ID: stored})
    injected = await _setup(hass, monkeypatch, injected)
    assert injected.data[CONF_PHONE_ID] == stored
    assert injected.runtime_data.phone_id == stored


async def test_setup_with_tracking_creates_vehicle_coordinator(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opt-in tracking creates the vehicle coordinator."""
    entry = await _setup(
        hass,
        monkeypatch,
        _entry(
            data={
                CONF_TRACK_VEHICLES: True,
                CONF_TRACKED_ROUTES: [{"route": "44B", "direction": "I"}],
            },
        ),
    )
    data: RedRegionalRuntimeData = entry.runtime_data
    assert data.vehicles is not None
    assert data.vehicles.data == ()


async def test_full_config_entry_setup_and_unload(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end setup through the config-entries controller unloads."""
    entry = _entry()
    await _setup(hass, monkeypatch, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(entry.entry_id) is True
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_migrate_entry_is_noop(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V1 entries migrate trivially."""
    entry = await _setup(hass, monkeypatch, _entry())
    assert await async_migrate_entry(hass, entry) is True


async def test_options_update_applies_without_recreate(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Option changes retune the live coordinators in place."""
    entry = await _setup(hass, monkeypatch, _entry())
    board = entry.runtime_data.board
    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL_S: 30})
    await hass.async_block_till_done()
    assert board.update_interval == timedelta(seconds=30)
    assert board.data is not None


async def test_options_update_retunes_vehicle_coordinator(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Option changes reach the vehicle coordinator when tracking."""
    entry = await _setup(
        hass,
        monkeypatch,
        _entry(
            data={
                CONF_TRACK_VEHICLES: True,
                CONF_TRACKED_ROUTES: ["44B"],
            }
        ),
    )
    vehicles = entry.runtime_data.vehicles
    assert vehicles is not None
    hass.config_entries.async_update_entry(entry, options={CONF_SCAN_INTERVAL_S: 45})
    await hass.async_block_till_done()
    assert vehicles.update_interval == timedelta(seconds=45)
