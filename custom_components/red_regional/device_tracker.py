"""Live bus GPS trackers, one per vehicle in service."""

from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VehicleCoordinator
from .models import VehiclePosition


def _tracker_suffixes(
    positions: tuple[VehiclePosition, ...],
) -> dict[VehiclePosition, str]:
    """Map positions to id suffixes, splitting plate collisions by direction.

    A plate seen in both directions yields `{plate}_I` and `{plate}_R`;
    otherwise the bare plate keeps `unique_id` stable across ticks.
    """
    by_plate: dict[str, list[VehiclePosition]] = {}
    for position in positions:
        by_plate.setdefault(position.plate, []).append(position)
    suffixes: dict[VehiclePosition, str] = {}
    for plate, group in by_plate.items():
        if len({position.direction for position in group}) > 1:
            for position in group:
                suffixes[position] = f"{plate}_{position.direction or 'X'}"
        else:
            for position in group:
                suffixes[position] = plate
    return suffixes


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add and retire bus trackers as vehicles enter service."""
    vehicles: VehicleCoordinator | None = entry.runtime_data.vehicles
    if vehicles is None:
        return
    zone_uuid: str = entry.runtime_data.zone_uuid
    zone_name: str | None = entry.runtime_data.zone_name
    known: dict[str, RedRegionalBusTracker] = {}
    registry = er.async_get(hass)

    @callback
    def _sync_trackers() -> None:
        positions = vehicles.data or ()
        wanted = {
            f"{zone_uuid}_{suffix}" for suffix in _tracker_suffixes(positions).values()
        }
        for unique_id in set(known) - wanted:
            tracker = known.pop(unique_id)
            if tracker.entity_id is not None:
                registry.async_remove(tracker.entity_id)
            hass.async_create_task(tracker.async_remove())
        fresh: list[RedRegionalBusTracker] = []
        for position, suffix in _tracker_suffixes(positions).items():
            unique_id = f"{zone_uuid}_{suffix}"
            if unique_id not in known:
                tracker = RedRegionalBusTracker(
                    vehicles,
                    unique_id=unique_id,
                    zone_uuid=zone_uuid,
                    zone_name=zone_name,
                    plate=position.plate,
                    direction=position.direction if suffix != position.plate else None,
                )
                known[unique_id] = tracker
                fresh.append(tracker)
        if fresh:
            async_add_entities(fresh)

    entry.async_on_unload(vehicles.async_add_listener(_sync_trackers))
    _sync_trackers()


class RedRegionalBusTracker(CoordinatorEntity[VehicleCoordinator], TrackerEntity):
    """GPS tracker for one bus, named after its plate."""

    _attr_has_entity_name = True
    _attr_source_type = SourceType.GPS

    def __init__(
        self,
        coordinator: VehicleCoordinator,
        *,
        unique_id: str,
        zone_uuid: str,
        zone_name: str | None,
        plate: str,
        direction: str | None,
    ) -> None:
        """Bind the tracker to its vehicle coordinator and plate."""
        super().__init__(coordinator)
        self._attr_unique_id = unique_id
        self._plate = plate
        self._direction = direction
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            name=f"Bus {plate}",
            manufacturer="DTPR / Red Regional",
            model=zone_name or "Red Regional",
        )

    def _position(self) -> VehiclePosition | None:
        """Return the current position for this plate and direction."""
        for position in self.coordinator.data or ():
            if position.plate != self._plate:
                continue
            if self._direction is not None and position.direction != self._direction:
                continue
            return position
        return None

    @property
    def latitude(self) -> float | None:
        """Return the latest reported latitude."""
        position = self._position()
        return position.latitude if position else None

    @property
    def longitude(self) -> float | None:
        """Return the latest reported longitude."""
        position = self._position()
        return position.longitude if position else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return telemetry backing map cards and templates."""
        position = self._position()
        return {
            "plate": self._plate,
            "route": position.route if position else None,
            "direction": position.direction if position else None,
            "speed_kmh": position.speed_kmh if position else None,
            "last_update": position.last_update.isoformat()
            if position and position.last_update
            else None,
        }
