"""Unit tests for Red Regional repairs."""

from __future__ import annotations

from typing import Any, cast

import pytest
from homeassistant import data_entry_flow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.const import (
    CONF_STOP_CODE,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DOMAIN,
)
from custom_components.red_regional.coordinator import RedRegionalCoordinator
from custom_components.red_regional.exceptions import TransAppConnectionError
from custom_components.red_regional.models import Zone
from custom_components.red_regional.repairs import (
    BackendUnreachableRepairFlow,
    InvalidStopRepairFlow,
    async_create_fix_flow,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"

INVALID_PAYLOAD: dict[str, Any] = {"events": [], "alerts": [], "predictions": []}
VALID_EMPTY: dict[str, Any] = {"routeInfo": [], "predictions": []}


class _FakeClient:
    """Stub TransAppClient with a swappable outcome."""

    def __init__(self, outcome: Any = None, exc: Exception | None = None) -> None:
        """Store the canned outcome."""
        self.outcome = outcome
        self.exc = exc

    async def async_get_stop_info(self, zone_uuid: str, stop_code: str) -> Any:
        """Replay the canned outcome."""
        if self.exc is not None:
            raise self.exc
        return self.outcome


def _coordinator(
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


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ZONE_UUID: ZONE,
            CONF_ZONE_NAME: "Gran Concepción",
            CONF_STOP_CODE: "P45068",
        },
        version=1,
    )


async def test_unknown_stop_raises_and_clears_issue(hass: HomeAssistant) -> None:
    """Unknown-stop signatures raise fixable issues, resolved on recovery."""
    client = _FakeClient(outcome=INVALID_PAYLOAD)
    entry = _entry()
    coordinator = _coordinator(hass, entry, client)
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    issue_id = f"invalid_stop_{entry.entry_id}"
    issue = ir.async_get(hass).issues.get((DOMAIN, issue_id))
    assert issue is not None
    assert issue.is_fixable is True
    assert issue.translation_key == "invalid_stop"
    assert issue.data == {"entry_id": entry.entry_id}
    client.outcome = VALID_EMPTY
    await coordinator.async_refresh()
    assert (DOMAIN, issue_id) not in ir.async_get(hass).issues


async def test_sustained_outage_raises_and_clears_issue(
    hass: HomeAssistant,
) -> None:
    """Three straight transport failures raise an unreachable issue."""
    client = _FakeClient(exc=TransAppConnectionError("down"))
    entry = _entry()
    coordinator = _coordinator(hass, entry, client)
    issue_id = f"backend_unreachable_{entry.entry_id}"
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    assert (DOMAIN, issue_id) not in ir.async_get(hass).issues
    await coordinator.async_refresh()
    issue = ir.async_get(hass).issues.get((DOMAIN, issue_id))
    assert issue is not None
    assert issue.translation_key == "backend_unreachable"
    client.exc = None
    client.outcome = VALID_EMPTY
    await coordinator.async_refresh()
    assert (DOMAIN, issue_id) not in ir.async_get(hass).issues


async def test_fix_flow_routing(hass: HomeAssistant) -> None:
    """Issue ids route to their flows; unknown ids are rejected."""
    assert isinstance(
        await async_create_fix_flow(hass, "invalid_stop_x", {}),
        InvalidStopRepairFlow,
    )
    assert isinstance(
        await async_create_fix_flow(hass, "backend_unreachable_x", {}),
        BackendUnreachableRepairFlow,
    )
    with pytest.raises(data_entry_flow.UnknownHandler):
        await async_create_fix_flow(hass, "something_else", {})


async def _repairs_manager(hass: HomeAssistant) -> Any:
    assert await async_setup_component(hass, "repairs", {})
    return hass.data["repairs"]["flow_manager"]


async def test_invalid_stop_fix_opens_reconfigure(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirming the invalid-stop fix hands off to reconfiguration."""
    from custom_components.red_regional.models import Zone as ZoneModel

    async def fake_zones(self: TransAppClient) -> list[ZoneModel]:
        return [Zone(uuid=ZONE, name="concepcion", public_name="Gran Concepción")]

    async def fake_stop(self: TransAppClient, zone_uuid: str, stop_code: str) -> Any:
        return VALID_EMPTY

    monkeypatch.setattr(TransAppClient, "async_get_zones", fake_zones)
    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    issue_id = f"invalid_stop_{entry.entry_id}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="invalid_stop",
        data={"entry_id": entry.entry_id},
    )
    manager = await _repairs_manager(hass)
    flow = await manager.async_init(DOMAIN, data={"issue_id": issue_id})
    assert flow["type"] == FlowResultType.FORM
    assert flow["step_id"] == "confirm"
    done = await manager.async_configure(flow["flow_id"], {})
    assert done["type"] == FlowResultType.ABORT
    assert done["reason"] == "reconfigure"
    assert (DOMAIN, issue_id) not in ir.async_get(hass).issues


async def test_unreachable_fix_reloads_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirming the unreachable fix reloads the entry and closes out."""
    from homeassistant.config_entries import ConfigEntryState

    async def fake_stop(self: TransAppClient, zone_uuid: str, stop_code: str) -> Any:
        return VALID_EMPTY

    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop)
    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is True
    await hass.async_block_till_done()
    issue_id = f"backend_unreachable_{entry.entry_id}"
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="backend_unreachable",
        data={"entry_id": entry.entry_id},
    )
    manager = await _repairs_manager(hass)
    flow = await manager.async_init(DOMAIN, data={"issue_id": issue_id})
    assert flow["type"] == FlowResultType.FORM
    assert flow["step_id"] == "confirm"
    await hass.async_block_till_done()
    done = await manager.async_configure(flow["flow_id"], {})
    assert done["type"] == FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert (DOMAIN, issue_id) not in ir.async_get(hass).issues
    assert entry.state is ConfigEntryState.LOADED


async def test_single_failure_creates_no_issue(hass: HomeAssistant) -> None:
    """Transient blips stay below the repair threshold."""
    client = _FakeClient(exc=TransAppConnectionError("down"))
    coordinator = _coordinator(hass, _entry(), client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert ir.async_get(hass).issues == {}
