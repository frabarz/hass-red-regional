"""Immutable data models shared by the API client, parsers, and entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Departure:
    """One predicted bus arrival at a stop."""

    route: str
    expected_at: datetime
    due_in_min: int
    destination: str | None = None
    scheduled_at: datetime | None = None
    delay_min: int | None = None
    realtime: bool = True
    direction: str | None = None
    vehicle_id: str | None = None
    route_color: str | None = None
    cancelled: bool = False
    occupancy: str | None = None


@dataclass(frozen=True)
class ServiceAlert:
    """One service disruption affecting a stop."""

    title: str
    description: str | None = None
    routes: tuple[str, ...] = ()
    valid_from: datetime | None = None
    valid_until: datetime | None = None


@dataclass(frozen=True)
class StopBoard:
    """Full prediction + alert snapshot for one stop."""

    stop_code: str
    zone_uuid: str
    departures: tuple[Departure, ...] = ()
    alerts: tuple[ServiceAlert, ...] = ()
    stop_name: str | None = None
    zone_name: str | None = None
    fetched_at: datetime | None = None

    @property
    def departure_count(self) -> int:
        """Return the number of departures on this board."""
        return len(self.departures)


@dataclass(frozen=True)
class VehiclePosition:
    """Live GPS snapshot for one bus in service."""

    plate: str
    latitude: float
    longitude: float
    speed_kmh: float | None = None
    route: str | None = None
    direction: str | None = None
    last_update: datetime | None = None


@dataclass(frozen=True)
class Zone:
    """One city/operating area from GET /zones."""

    uuid: str
    name: str
    public_name: str | None = None
