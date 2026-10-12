"""Board sensors: next departure timestamp and departures count."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTRIBUTION
from .coordinator import RedRegionalCoordinator
from .entity import RedRegionalStopEntity
from .models import Departure


def _departure_dict(departure: Departure) -> dict[str, Any]:
    """Serialize one departure for state attributes."""
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
        "route_color": departure.route_color,
        "cancelled": departure.cancelled,
        "occupancy": departure.occupancy,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the board sensors for one stop."""
    board: RedRegionalCoordinator = entry.runtime_data.board
    async_add_entities([NextDepartureSensor(board), DeparturesCountSensor(board)])


class NextDepartureSensor(RedRegionalStopEntity, SensorEntity):
    """Soonest predicted arrival as a timestamp with full board attributes."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "next_departure"

    def __init__(self, coordinator: RedRegionalCoordinator) -> None:
        """Bind the sensor and fix its stable unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.zone_uuid}_{coordinator.stop_code}_next"

    @property
    def native_value(self) -> datetime | None:
        """Return the soonest expected arrival, or unknown when empty."""
        board = self.coordinator.data
        if not board or not board.departures:
            return None
        return board.departures[0].expected_at

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the filtered board backing templates and TTS."""
        board = self.coordinator.data
        departures = board.departures if board else ()
        language = self.hass.config.language
        connector = "in" if language.startswith("en") else "en"
        return {
            "stop_code": self.coordinator.stop_code,
            "stop_name": board.stop_name if board else None,
            "zone": self.coordinator.zone_name,
            "departure_count": len(departures),
            "departures": [_departure_dict(departure) for departure in departures],
            "departures_text": ", ".join(
                f"{departure.route} {connector} {departure.due_in_min} min"
                for departure in departures
            ),
            "attribution": ATTRIBUTION,
            "last_update": board.fetched_at.isoformat()
            if board and board.fetched_at
            else None,
        }


class DeparturesCountSensor(RedRegionalStopEntity, SensorEntity):
    """Count of visible departures, disabled by default."""

    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "departures_count"

    def __init__(self, coordinator: RedRegionalCoordinator) -> None:
        """Bind the sensor and fix its stable unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.zone_uuid}_{coordinator.stop_code}_count"

    @property
    def native_value(self) -> int:
        """Return the number of departures on the filtered board."""
        return len(self.coordinator.data.departures)
