"""Red Regional integration entry lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import TransAppClient
from .const import (
    CONF_PHONE_ID,
    CONF_STOP_CODE,
    CONF_TRACK_VEHICLES,
    CONF_TRACKED_ROUTES,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
)
from .coordinator import (
    RedRegionalCoordinator,
    VehicleCoordinator,
    normalize_tracked_routes,
)
from .services import async_setup_services

PLATFORMS: list[str] = ["sensor", "binary_sensor", "device_tracker"]


@dataclass
class RedRegionalRuntimeData:
    """Shared objects for one configured stop."""

    client: TransAppClient
    board: RedRegionalCoordinator
    vehicles: VehicleCoordinator | None
    zone_uuid: str
    zone_name: str | None
    stop_code: str
    phone_id: str


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration services once."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one stop: client, coordinators, then platforms."""
    phone_id = entry.data.get(CONF_PHONE_ID) or str(uuid4())
    if CONF_PHONE_ID not in entry.data:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_PHONE_ID: phone_id},
        )
    client = TransAppClient(async_get_clientsession(hass), phone_id)
    zone_uuid: str = entry.data[CONF_ZONE_UUID]
    stop_code: str = entry.data[CONF_STOP_CODE]
    zone_name: str | None = entry.data.get(CONF_ZONE_NAME)
    board = RedRegionalCoordinator(
        hass,
        entry,
        client,
        zone_uuid=zone_uuid,
        zone_name=zone_name,
        stop_code=stop_code,
    )
    await board.async_config_entry_first_refresh()
    vehicles: VehicleCoordinator | None = None
    wants_tracking = entry.options.get(
        CONF_TRACK_VEHICLES,
        entry.data.get(CONF_TRACK_VEHICLES, False),
    )
    tracked = normalize_tracked_routes(
        entry.options.get(
            CONF_TRACKED_ROUTES,
            entry.data.get(CONF_TRACKED_ROUTES, ()),
        ),
    )
    if wants_tracking and tracked:
        vehicles = VehicleCoordinator(hass, entry, client, zone_uuid=zone_uuid)
        await vehicles.async_refresh()
    entry.runtime_data = RedRegionalRuntimeData(
        client=client,
        board=board,
        vehicles=vehicles,
        zone_uuid=zone_uuid,
        zone_name=zone_name,
        stop_code=stop_code,
        phone_id=phone_id,
    )
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply option changes to the coordinators without re-creating them."""
    data: RedRegionalRuntimeData = entry.runtime_data
    data.board.refresh_options()
    if data.vehicles is not None:
        data.vehicles.refresh_options()
    await data.board.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries; v1 has nothing to migrate yet."""
    return True
