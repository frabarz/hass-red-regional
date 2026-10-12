"""Diagnostics for Red Regional config entries."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_PHONE_ID
from .models import Departure, ServiceAlert

TO_REDACT = {CONF_PHONE_ID}


def _departure_dict(departure: Departure) -> dict[str, Any]:
    """Serialize one departure for the diagnostics payload."""
    return {
        "route": departure.route,
        "destination": departure.destination,
        "scheduled_at": (
            departure.scheduled_at.isoformat() if departure.scheduled_at else None
        ),
        "expected_at": departure.expected_at.isoformat(),
        "due_in_min": departure.due_in_min,
        "delay_min": departure.delay_min,
        "realtime": departure.realtime,
        "direction": departure.direction,
        "vehicle_id": departure.vehicle_id,
        "cancelled": departure.cancelled,
        "occupancy": departure.occupancy,
    }


def _alert_dict(alert: ServiceAlert) -> dict[str, Any]:
    """Serialize one alert for the diagnostics payload."""
    return {
        "title": alert.title,
        "description": alert.description,
        "routes": list(alert.routes),
        "valid_from": alert.valid_from.isoformat() if alert.valid_from else None,
        "valid_until": alert.valid_until.isoformat() if alert.valid_until else None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted entry data and the latest board snapshot.

    Stop and vehicle positions are public transit data already exposed by
    the backend; only the per-entry phone id is sensitive and redacted.
    """
    data = entry.runtime_data
    board = data.board.data
    vehicles = (
        [
            {
                "plate": position.plate,
                "latitude": position.latitude,
                "longitude": position.longitude,
                "route": position.route,
                "direction": position.direction,
            }
            for position in data.vehicles.data
        ]
        if data.vehicles is not None and data.vehicles.data is not None
        else []
    )
    return {
        "entry": async_redact_data(
            {"data": dict(entry.data), "options": dict(entry.options)}, TO_REDACT
        ),
        "board": {
            "stop_code": data.stop_code,
            "zone_uuid": data.zone_uuid,
            "departures": [_departure_dict(departure) for departure in board.departures]
            if board
            else [],
            "alerts": [_alert_dict(alert) for alert in board.alerts] if board else [],
        },
        "vehicles": vehicles,
    }
