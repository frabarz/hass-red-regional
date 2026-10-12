"""Typed services: refresh, stop lookup, and live vehicles."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TransAppClient
from .config_flow import _validate_stop
from .const import DOMAIN
from .gtfs import async_ensure_gtfs, find_stops
from .models import VehiclePosition
from .parse import default_now, parse_machines

_REFRESH_SCHEMA = vol.Schema(
    {
        vol.Exclusive("config_entry_id", "target"): str,
        vol.Exclusive("device_id", "target"): str,
    }
)

_LOOKUP_SCHEMA = vol.Schema(
    {
        vol.Required("zone_uuid"): str,
        vol.Required("query"): str,
        vol.Optional("limit", default=8): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=25)
        ),
    }
)

_VEHICLES_SCHEMA = vol.Schema(
    {
        vol.Required("zone_uuid"): str,
        vol.Required("route"): str,
        vol.Optional("direction", default="I"): vol.In(["I", "R"]),
    }
)


def _vehicle_dict(position: VehiclePosition) -> dict[str, Any]:
    """Serialize one vehicle position for service responses."""
    return {
        "plate": position.plate,
        "latitude": position.latitude,
        "longitude": position.longitude,
        "speed_kmh": position.speed_kmh,
        "route": position.route,
        "direction": position.direction,
        "last_update": position.last_update.isoformat()
        if position.last_update
        else None,
    }


def _entry_for_refresh(hass: HomeAssistant, call: ServiceCall) -> ConfigEntry:
    """Resolve the config entry backing a refresh call."""
    entry_id = call.data.get("config_entry_id")
    if entry_id is not None:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None and entry.domain == DOMAIN:
            return entry
        raise ServiceValidationError(f"Unknown Red Regional entry: {entry_id}")
    device_id = call.data.get("device_id")
    if device_id is not None:
        device = next(
            (item for item in dr.async_get(hass).devices if item.id == device_id),
            None,
        )
        if device is not None:
            for candidate_id in device.config_entries:
                candidate = hass.config_entries.async_get_entry(candidate_id)
                if candidate is not None and candidate.domain == DOMAIN:
                    return candidate
        raise ServiceValidationError(f"Unknown Red Regional device: {device_id}")
    raise ServiceValidationError("Provide config_entry_id or device_id")


def async_setup_services(hass: HomeAssistant) -> None:
    """Register Red Regional services once per Home Assistant instance."""
    if hass.data.get(DOMAIN, {}).get("services_registered"):
        return
    hass.data.setdefault(DOMAIN, {})["services_registered"] = True

    async def handle_refresh(call: ServiceCall) -> None:
        """Force an immediate poll of the entry coordinators."""
        data = _entry_for_refresh(hass, call).runtime_data
        await data.board.async_request_refresh()
        if data.vehicles is not None:
            await data.vehicles.async_request_refresh()

    async def handle_lookup_stop(call: ServiceCall) -> dict[str, Any]:
        """Search cached GTFS stops, validating live codes as fallback."""
        zone_uuid: str = call.data["zone_uuid"]
        query: str = call.data["query"]
        limit: int = call.data["limit"]
        client = TransAppClient(async_get_clientsession(hass), str(uuid4()))
        index = await async_ensure_gtfs(hass, client, zone_uuid)
        candidates = [
            {
                "stop_code": code,
                "stop_name": stop.name,
                "latitude": stop.latitude,
                "longitude": stop.longitude,
            }
            for code, stop in find_stops(index, query, limit)
        ]
        if not candidates:
            board, _ = await _validate_stop(client, zone_uuid, query.strip().upper())
            if board is not None:
                candidates.append(
                    {
                        "stop_code": board.stop_code,
                        "stop_name": board.stop_name,
                        "latitude": None,
                        "longitude": None,
                    }
                )
        return {"candidates": candidates}

    async def handle_get_vehicles(call: ServiceCall) -> dict[str, Any]:
        """Return live GPS telemetry for one route and direction."""
        client = TransAppClient(async_get_clientsession(hass), str(uuid4()))
        raw = await client.async_get_machines(
            call.data["zone_uuid"], call.data["route"], call.data["direction"]
        )
        positions = parse_machines(raw, now=default_now())
        return {"vehicles": [_vehicle_dict(position) for position in positions]}

    hass.services.async_register(
        DOMAIN, "refresh", handle_refresh, schema=_REFRESH_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        "lookup_stop",
        handle_lookup_stop,
        schema=_LOOKUP_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "get_vehicles",
        handle_get_vehicles,
        schema=_VEHICLES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
