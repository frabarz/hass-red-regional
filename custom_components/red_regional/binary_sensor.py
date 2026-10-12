"""Service alert binary sensor for one stop."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import RedRegionalCoordinator
from .entity import RedRegionalStopEntity
from .models import ServiceAlert


def _alert_dict(alert: ServiceAlert) -> dict[str, Any]:
    """Serialize one alert for state attributes."""
    return {
        "title": alert.title,
        "description": alert.description,
        "routes": list(alert.routes),
        "valid_from": alert.valid_from.isoformat() if alert.valid_from else None,
        "valid_until": alert.valid_until.isoformat() if alert.valid_until else None,
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the service alert sensor for one stop."""
    board: RedRegionalCoordinator = entry.runtime_data.board
    async_add_entities([ServiceAlertSensor(board)])


class ServiceAlertSensor(RedRegionalStopEntity, BinarySensorEntity):
    """On while the board carries any active alert or event."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "service_alert"

    def __init__(self, coordinator: RedRegionalCoordinator) -> None:
        """Bind the sensor and fix its stable unique id."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.zone_uuid}_{coordinator.stop_code}_alert"

    @property
    def is_on(self) -> bool:
        """Return True while any alert affects the stop."""
        return bool(self.coordinator.data.alerts)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the active alerts backing the state."""
        board = self.coordinator.data
        alerts = board.alerts if board else ()
        return {"alerts": [_alert_dict(alert) for alert in alerts]}
