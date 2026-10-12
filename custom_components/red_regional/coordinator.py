"""Shared polling coordinators for stop boards and vehicle positions."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TransAppClient
from .const import (
    CONF_DESTINATIONS,
    CONF_LOOK_AHEAD_MIN,
    CONF_MAX_DEPARTURES,
    CONF_ROUTES_WHITELIST,
    CONF_SCAN_INTERVAL_S,
    CONF_TRACKED_ROUTES,
    CONF_WALK_OFFSET_MIN,
    DEFAULT_LOOK_AHEAD_MIN,
    DEFAULT_MAX_DEPARTURES,
    DEFAULT_SCAN_INTERVAL_S,
    DEFAULT_WALK_OFFSET_MIN,
    DOMAIN,
)
from .exceptions import (
    TransAppAuthError,
    TransAppConnectionError,
    TransAppRateLimitError,
)
from .filters import apply_departure_filters
from .gtfs import GtfsIndex, async_ensure_gtfs
from .models import StopBoard, VehiclePosition
from .parse import default_now, is_unknown_stop, parse_machines, parse_stop_board

_LOGGER = logging.getLogger(__name__)

_RATE_LIMIT_RETRY_AFTER_S = 120
_UNREACHABLE_AFTER_FAILURES = 3


def _option(entry: ConfigEntry, key: str, default: Any) -> Any:
    """Prefer options over setup data, falling back to a default."""
    if key in entry.options:
        return entry.options[key]
    return entry.data.get(key, default)


def normalize_tracked_routes(raw: Any) -> tuple[tuple[str, str], ...]:
    """Normalize tracked-route config to (route, direction) pairs.

    Accepts ``"44B"`` (defaults to ``I``) and ``{"route", "direction"}``
    mappings; anything else is dropped.
    """
    if not isinstance(raw, list):
        return ()
    tracked: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            tracked.append((item.strip(), "I"))
            continue
        if not isinstance(item, dict):
            continue
        route = item.get("route")
        if not isinstance(route, str) or not route.strip():
            continue
        direction = item.get("direction", "I")
        if direction not in ("I", "R"):
            direction = "I"
        tracked.append((route.strip(), direction))
    return tuple(tracked)


class RedRegionalCoordinator(DataUpdateCoordinator[StopBoard]):
    """Poll one stopInfo board and expose the filtered departures."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TransAppClient,
        *,
        zone_uuid: str,
        zone_name: str | None,
        stop_code: str,
    ) -> None:
        """Create a board coordinator for one stop."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}-{zone_uuid}-{stop_code}",
            update_interval=timedelta(
                seconds=_option(entry, CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S)
            ),
            always_update=False,
        )
        self._entry = entry
        self._client = client
        self.zone_uuid = zone_uuid
        self.zone_name = zone_name
        self.stop_code = stop_code
        self.gtfs: GtfsIndex = GtfsIndex.empty()
        self._transport_failures = 0
        self.refresh_options()

    async def _async_setup(self) -> None:
        """Load the GTFS index once; enrichment stays best-effort."""
        self.gtfs = await async_ensure_gtfs(self.hass, self._client, self.zone_uuid)

    def refresh_options(self) -> None:
        """Re-read interval and filters after an options change."""
        entry = self._entry
        self.update_interval = timedelta(
            seconds=_option(entry, CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S)
        )
        self.routes_whitelist: tuple[str, ...] = tuple(
            _option(entry, CONF_ROUTES_WHITELIST, ())
        )
        self.destinations: tuple[str, ...] = tuple(
            _option(entry, CONF_DESTINATIONS, ())
        )
        self.max_departures: int = _option(
            entry, CONF_MAX_DEPARTURES, DEFAULT_MAX_DEPARTURES
        )
        self.look_ahead_min: int = _option(
            entry, CONF_LOOK_AHEAD_MIN, DEFAULT_LOOK_AHEAD_MIN
        )
        self.walk_offset_min: int = _option(
            entry, CONF_WALK_OFFSET_MIN, DEFAULT_WALK_OFFSET_MIN
        )

    async def _async_update_data(self) -> StopBoard:
        """Fetch one stopInfo snapshot and return the filtered board."""
        try:
            raw = await self._client.async_get_stop_info(self.zone_uuid, self.stop_code)
        except TransAppAuthError as err:
            raise ConfigEntryAuthFailed(f"TransApp rejected request: {err}") from err
        except TransAppRateLimitError as err:
            raise UpdateFailed(
                f"TransApp rate limit: {err}",
                retry_after=_RATE_LIMIT_RETRY_AFTER_S,
            ) from err
        except TransAppConnectionError as err:
            self._transport_failures += 1
            if self._transport_failures >= _UNREACHABLE_AFTER_FAILURES:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    f"backend_unreachable_{self._entry.entry_id}",
                    is_fixable=True,
                    is_persistent=True,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="backend_unreachable",
                    translation_placeholders={"stop_code": self.stop_code},
                    data={"entry_id": self._entry.entry_id},
                )
            raise UpdateFailed(f"TransApp request failed: {err}") from err
        self._transport_failures = 0
        ir.async_delete_issue(
            self.hass, DOMAIN, f"backend_unreachable_{self._entry.entry_id}"
        )
        if is_unknown_stop(raw):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                f"invalid_stop_{self._entry.entry_id}",
                is_fixable=True,
                is_persistent=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="invalid_stop",
                translation_placeholders={"stop_code": self.stop_code},
                data={"entry_id": self._entry.entry_id},
            )
        else:
            ir.async_delete_issue(
                self.hass, DOMAIN, f"invalid_stop_{self._entry.entry_id}"
            )
        board = parse_stop_board(
            raw,
            stop_code=self.stop_code,
            zone_uuid=self.zone_uuid,
            now=default_now(),
            zone_name=self.zone_name,
            route_colors={
                short: route.color
                for short, route in self.gtfs.routes.items()
                if route.color
            },
            route_names={
                short: route.long_name
                for short, route in self.gtfs.routes.items()
                if route.long_name
            },
        )
        stop_name = board.stop_name
        if stop_name is None:
            stop = self.gtfs.stops.get(self.stop_code)
            if stop is not None:
                stop_name = stop.name
        return replace(
            board,
            stop_name=stop_name,
            departures=tuple(
                apply_departure_filters(
                    board.departures,
                    routes_whitelist=self.routes_whitelist,
                    destinations=self.destinations,
                    look_ahead_min=self.look_ahead_min,
                    walk_offset_min=self.walk_offset_min,
                    max_departures=self.max_departures,
                )
            ),
        )


class VehicleCoordinator(DataUpdateCoordinator[tuple[VehiclePosition, ...]]):
    """Poll live GPS telemetry for the watched routes of one zone."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TransAppClient,
        *,
        zone_uuid: str,
    ) -> None:
        """Create a vehicle coordinator for the tracked routes."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}-{zone_uuid}-vehicles",
            update_interval=timedelta(
                seconds=_option(entry, CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S)
            ),
            always_update=False,
        )
        self._entry = entry
        self._client = client
        self.zone_uuid = zone_uuid
        self.refresh_options()

    def refresh_options(self) -> None:
        """Re-read interval and tracked routes after an options change."""
        self.update_interval = timedelta(
            seconds=_option(self._entry, CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S)
        )
        self.tracked: tuple[tuple[str, str], ...] = normalize_tracked_routes(
            _option(self._entry, CONF_TRACKED_ROUTES, ())
        )

    async def _async_update_data(self) -> tuple[VehiclePosition, ...]:
        """Fetch machines for every watched route and aggregate them."""
        positions: list[VehiclePosition] = []
        try:
            for route, direction in self.tracked:
                raw = await self._client.async_get_machines(
                    self.zone_uuid, route, direction
                )
                positions.extend(parse_machines(raw, now=default_now()))
        except TransAppAuthError as err:
            raise ConfigEntryAuthFailed(f"TransApp rejected request: {err}") from err
        except TransAppRateLimitError as err:
            raise UpdateFailed(
                f"TransApp rate limit: {err}",
                retry_after=_RATE_LIMIT_RETRY_AFTER_S,
            ) from err
        except TransAppConnectionError as err:
            raise UpdateFailed(f"TransApp request failed: {err}") from err
        return tuple(positions)
