"""Unit tests for the Red Regional config flow."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.config_flow import (
    _parse_csv,
    _parse_tracked_routes,
)
from custom_components.red_regional.const import (
    CONF_MAX_DEPARTURES,
    CONF_ROUTES_WHITELIST,
    CONF_SCAN_INTERVAL_S,
    CONF_STOP_CODE,
    CONF_TRACKED_ROUTES,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DOMAIN,
)
from custom_components.red_regional.exceptions import TransAppConnectionError
from custom_components.red_regional.models import Zone

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"
TALCA = "50cde66c-2b67-4702-afa8-1f190249d9b8"

ZONES = [
    Zone(uuid=ZONE, name="concepcion", public_name="Gran Concepción"),
    Zone(uuid=TALCA, name="talca", public_name="Talca"),
]

STOP_OK: dict[str, Any] = {
    "routeInfo": [],
    "predictions": [],
    "alerts": [],
    "stop": {"code": "P45068", "name": "Plaza Tribunales de Justicia"},
}

STOP_EMPTY_NOROUTEINFO: dict[str, Any] = {"events": [], "alerts": [], "predictions": []}


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    zones: list[Zone] | Exception = ZONES,
    stop: Any | Exception = STOP_OK,
) -> None:
    async def fake_zones(self: TransAppClient) -> list[Zone]:
        if isinstance(zones, Exception):
            raise zones
        return zones

    async def fake_stop(self: TransAppClient, zone_uuid: str, stop_code: str) -> Any:
        if isinstance(stop, Exception):
            raise stop
        return stop

    monkeypatch.setattr(TransAppClient, "async_get_zones", fake_zones)
    monkeypatch.setattr(TransAppClient, "async_get_stop_info", fake_stop)


async def _to_filters(
    hass: HomeAssistant, stop_code: str = "P45068"
) -> ConfigFlowResult:
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert flow["step_id"] == "user"
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_ZONE_UUID: ZONE}
    )
    assert flow["step_id"] == "stop"
    return await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_STOP_CODE: stop_code}
    )


async def test_full_flow_creates_entry_with_defaults(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zone, stop, and empty filters create a normalized entry."""
    _patch(monkeypatch)
    flow = await _to_filters(hass, stop_code="p45068")
    assert flow["step_id"] == "filters"
    entry = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert entry["type"] == FlowResultType.CREATE_ENTRY
    assert entry["title"] == "Plaza Tribunales de Justicia (P45068)"
    data = entry["data"]
    assert data[CONF_ZONE_UUID] == ZONE
    assert data[CONF_ZONE_NAME] == "Gran Concepción"
    assert data[CONF_STOP_CODE] == "P45068"
    assert data[CONF_MAX_DEPARTURES] == 5
    assert data[CONF_ROUTES_WHITELIST] == []
    assert data[CONF_TRACKED_ROUTES] == []
    assert data[CONF_SCAN_INTERVAL_S] == 60


async def test_filters_input_is_normalized(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CSV text and tracked routes normalize into entry data."""
    _patch(monkeypatch)
    flow = await _to_filters(hass)
    entry = await hass.config_entries.flow.async_configure(
        flow["flow_id"],
        {
            CONF_ROUTES_WHITELIST: "44b, 63B",
            CONF_MAX_DEPARTURES: 3,
            CONF_TRACKED_ROUTES: "44B, 63B:R",
        },
    )
    assert entry["type"] == FlowResultType.CREATE_ENTRY
    assert entry["data"][CONF_ROUTES_WHITELIST] == ["44b", "63B"]
    assert entry["data"][CONF_TRACKED_ROUTES] == [
        {"route": "44B", "direction": "I"},
        {"route": "63B", "direction": "R"},
    ]


async def test_zones_fallback_when_offline(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pinned zones keep setup working when /zones is unreachable."""
    _patch(monkeypatch, zones=TransAppConnectionError("down"))
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert flow["step_id"] == "user"
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_ZONE_UUID: ZONE}
    )
    assert flow["step_id"] == "stop"


async def test_invalid_stop_is_rejected(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown stop codes show an error and create nothing."""
    _patch(monkeypatch, stop=STOP_EMPTY_NOROUTEINFO)
    flow = await _to_filters(hass, stop_code="NOEXISTE99")
    assert flow["type"] == FlowResultType.FORM
    assert flow["errors"] == {"base": "invalid_stop"}
    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_unreachable_backend_is_rejected(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Connection failures during validation show an error."""
    _patch(monkeypatch, stop=TransAppConnectionError("down"))
    flow = await _to_filters(hass)
    assert flow["type"] == FlowResultType.FORM
    assert flow["errors"] == {"base": "cannot_connect"}


async def test_off_hours_empty_board_is_allowed(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty boards with routeInfo create entries (off-hours proof)."""
    _patch(monkeypatch, stop={"routeInfo": [], "predictions": []})
    flow = await _to_filters(hass)
    assert flow["step_id"] == "filters"


async def test_duplicate_stop_aborts(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same zone and stop cannot be configured twice."""
    _patch(monkeypatch)
    flow = await _to_filters(hass)
    created = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert created["type"] == FlowResultType.CREATE_ENTRY
    repeat = await _to_filters(hass)
    assert repeat["type"] == FlowResultType.ABORT
    assert repeat["reason"] == "already_configured"


async def test_reconfigure_changes_stop(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reconfigure validates and updates the entry without adding one."""
    _patch(monkeypatch)
    flow = await _to_filters(hass)
    created = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    entry_id = created["result"].entry_id
    reconfig = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry_id,
        },
    )
    done = await hass.config_entries.flow.async_configure(
        reconfig["flow_id"],
        {CONF_ZONE_UUID: TALCA, CONF_STOP_CODE: "PA151"},
    )
    assert done["type"] == FlowResultType.ABORT
    assert done["reason"] == "reconfigure_successful"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry is not None
    assert entry.data[CONF_ZONE_UUID] == TALCA
    assert entry.data[CONF_STOP_CODE] == "PA151"
    assert entry.unique_id == f"{TALCA}_PA151"


async def test_reconfigure_rejects_invalid_stop(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Invalid stops keep the existing entry untouched."""
    _patch(monkeypatch)
    flow = await _to_filters(hass)
    created = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    entry_id = created["result"].entry_id
    _patch(monkeypatch, stop=STOP_EMPTY_NOROUTEINFO)
    reconfig = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry_id,
        },
    )
    done = await hass.config_entries.flow.async_configure(
        reconfig["flow_id"],
        {CONF_ZONE_UUID: ZONE, CONF_STOP_CODE: "NOEXISTE99"},
    )
    assert done["type"] == FlowResultType.FORM
    assert done["errors"] == {"base": "invalid_stop"}
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry is not None
    assert entry.data[CONF_STOP_CODE] == "P45068"


async def test_reauth_confirm_reloads(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reauth confirmation reloads the entry for a fresh attempt."""
    _patch(monkeypatch)

    async def fake_machines(
        self: TransAppClient, zone_uuid: str, route: str, direction: str
    ) -> Any:
        return {"machines": []}

    monkeypatch.setattr(TransAppClient, "async_get_machines", fake_machines)
    flow = await _to_filters(hass)
    created = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    entry_id = created["result"].entry_id
    await hass.async_block_till_done()
    assert created["result"].state is not None
    reauth = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry_id,
        },
        data=created["result"].data,
    )
    done = await hass.config_entries.flow.async_configure(reauth["flow_id"], {})
    assert done["type"] == FlowResultType.ABORT
    assert done["reason"] == "reauth_successful"


def test_parse_helpers() -> None:
    """CSV and tracked-route parsing trims, skips junk, defaults direction."""
    assert _parse_csv("44B, , 63B ") == ["44B", "63B"]
    assert _parse_tracked_routes("44B, 63B:R, :R, 60Z:X, ") == [
        {"route": "44B", "direction": "I"},
        {"route": "63B", "direction": "R"},
        {"route": "60Z", "direction": "I"},
    ]


async def test_empty_zones_list_falls_back(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An empty live zone list falls back to pinned zones."""
    _patch(monkeypatch, zones=[])
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    configured = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_ZONE_UUID: ZONE}
    )
    assert configured["step_id"] == "stop"


async def test_reauth_confirm_reshows_without_input(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening reauth confirm without input redisplays the form."""
    _patch(monkeypatch)
    flow = await _to_filters(hass)
    created = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    reauth = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": created["result"].entry_id,
        },
        data=created["result"].data,
    )
    reshown = await hass.config_entries.flow.async_configure(reauth["flow_id"])
    assert reshown["type"] == FlowResultType.FORM
    assert reshown["step_id"] == "reauth_confirm"


async def test_gtfs_stop_name_enriches_title(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GTFS names title the entry when the backend omits the stop name."""
    from custom_components.red_regional import config_flow as flow_module
    from custom_components.red_regional.gtfs import GtfsIndex, GtfsStop

    _patch(monkeypatch, stop={"routeInfo": []})

    async def fake_ensure(hass: object, client: object, zone_uuid: str) -> GtfsIndex:
        return GtfsIndex(stops={"P45068": GtfsStop(name="GTFS Stop")})

    monkeypatch.setattr(flow_module, "async_ensure_gtfs", fake_ensure)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_ZONE_UUID: ZONE}
    )
    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {CONF_STOP_CODE: "P45068"}
    )
    assert flow["step_id"] == "filters"
    entry = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert entry["type"] == FlowResultType.CREATE_ENTRY
    assert entry["title"] == "GTFS Stop (P45068)"


async def test_reconfigure_to_existing_stop_aborts(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reconfiguring onto another entry's stop aborts as configured."""
    _patch(monkeypatch)
    first = await _to_filters(hass)
    await hass.config_entries.flow.async_configure(first["flow_id"], {})
    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    second = await hass.config_entries.flow.async_configure(
        second["flow_id"], {CONF_ZONE_UUID: TALCA}
    )
    second = await hass.config_entries.flow.async_configure(
        second["flow_id"], {CONF_STOP_CODE: "PA151"}
    )
    created = await hass.config_entries.flow.async_configure(second["flow_id"], {})
    assert created["type"] == FlowResultType.CREATE_ENTRY
    reconfig = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": created["result"].entry_id,
        },
    )
    done = await hass.config_entries.flow.async_configure(
        reconfig["flow_id"],
        {CONF_ZONE_UUID: ZONE, CONF_STOP_CODE: "P45068"},
    )
    assert done["type"] == FlowResultType.ABORT
    assert done["reason"] == "already_configured"
    entry = hass.config_entries.async_get_entry(created["result"].entry_id)
    assert entry is not None
    assert entry.data[CONF_STOP_CODE] == "PA151"
