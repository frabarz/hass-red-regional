"""Shared base entity for one Red Regional stop."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import APP_VERSION, DOMAIN
from .coordinator import RedRegionalCoordinator


class RedRegionalStopEntity(CoordinatorEntity[RedRegionalCoordinator]):
    """Base entity reading from the stop board coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: RedRegionalCoordinator) -> None:
        """Bind the entity to its stop coordinator."""
        super().__init__(coordinator)
        self._refresh_device_info()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh device metadata when the board updates."""
        self._refresh_device_info()
        super()._handle_coordinator_update()

    def _refresh_device_info(self) -> None:
        """Rebuild the shared stop device from the latest board."""
        stop_code = self.coordinator.stop_code
        board = self.coordinator.data
        stop_name = board.stop_name if board and board.stop_name else stop_code
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator.zone_uuid}_{stop_code}")},
            name=stop_code if stop_name == stop_code else f"{stop_name} ({stop_code})",
            manufacturer="DTPR / Red Regional",
            model=self.coordinator.zone_name or "Red Regional",
            sw_version=APP_VERSION,
        )
