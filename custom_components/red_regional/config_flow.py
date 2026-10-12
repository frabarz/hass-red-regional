"""Config flow for Red Regional: zone, stop, filters, reauth, reconfigure."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TransAppClient
from .const import (
    CONF_DESTINATIONS,
    CONF_LOOK_AHEAD_MIN,
    CONF_MAX_DEPARTURES,
    CONF_ROUTES_WHITELIST,
    CONF_SCAN_INTERVAL_S,
    CONF_STOP_CODE,
    CONF_TRACK_VEHICLES,
    CONF_TRACKED_ROUTES,
    CONF_WALK_OFFSET_MIN,
    CONF_ZONE_NAME,
    CONF_ZONE_UUID,
    DEFAULT_LOOK_AHEAD_MIN,
    DEFAULT_MAX_DEPARTURES,
    DEFAULT_SCAN_INTERVAL_S,
    DEFAULT_WALK_OFFSET_MIN,
    DOMAIN,
    FALLBACK_ZONES,
    MAX_LOOK_AHEAD_MIN,
    MAX_MAX_DEPARTURES,
    MAX_SCAN_INTERVAL_S,
    MAX_WALK_OFFSET_MIN,
    MIN_LOOK_AHEAD_MIN,
    MIN_MAX_DEPARTURES,
    MIN_SCAN_INTERVAL_S,
    MIN_WALK_OFFSET_MIN,
)
from .exceptions import TransAppError
from .gtfs import GtfsIndex, async_ensure_gtfs
from .models import StopBoard
from .parse import default_now, parse_stop_board


def _parse_csv(text: str) -> list[str]:
    """Split comma-separated input into cleaned tokens."""
    return [part.strip() for part in text.split(",") if part.strip()]


def _parse_tracked_routes(text: str) -> list[dict[str, str]]:
    """Parse tracked routes from ROUTE or ROUTE:I|R comma-separated text."""
    tracked: list[dict[str, str]] = []
    for part in _parse_csv(text):
        route, _, direction = part.partition(":")
        route = route.strip()
        if not route:
            continue
        direction = direction.strip().upper() or "I"
        if direction not in ("I", "R"):
            direction = "I"
        tracked.append({"route": route, "direction": direction})
    return tracked


async def _load_zone_names(client: TransAppClient) -> dict[str, str]:
    """Return zone uuid to display name, falling back to pinned zones."""
    try:
        zones = await client.async_get_zones()
    except TransAppError:
        return dict(FALLBACK_ZONES)
    if not zones:
        return dict(FALLBACK_ZONES)
    return {zone.uuid: zone.public_name or zone.name for zone in zones}


async def _validate_stop(
    client: TransAppClient,
    zone_uuid: str,
    stop_code: str,
    gtfs: GtfsIndex | None = None,
) -> tuple[StopBoard | None, str | None]:
    """Validate a stop via live stopInfo.

    Returns the board, or (None, error_key). A response carrying routeInfo
    proves the stop exists even off-hours; without it, empty boards mean
    an unknown stop code. GTFS fills the stop name when the backend omits it.
    """
    try:
        raw = await client.async_get_stop_info(zone_uuid, stop_code)
    except TransAppError:
        return None, "cannot_connect"
    board = parse_stop_board(
        raw, stop_code=stop_code, zone_uuid=zone_uuid, now=default_now()
    )
    has_route_info = isinstance(raw, dict) and "routeInfo" in raw
    if not board.departures and not board.alerts and not has_route_info:
        return None, "invalid_stop"
    if board.stop_name is None and gtfs is not None:
        stop = gtfs.stops.get(stop_code)
        if stop is not None and stop.name:
            board = replace(board, stop_name=stop.name)
    return board, None


def _filters_schema(
    routes: str = "",
    destinations: str = "",
    max_departures: int = DEFAULT_MAX_DEPARTURES,
    look_ahead_min: int = DEFAULT_LOOK_AHEAD_MIN,
    walk_offset_min: int = DEFAULT_WALK_OFFSET_MIN,
    track_vehicles: bool = False,
    tracked_routes: str = "",
    scan_interval_s: int = DEFAULT_SCAN_INTERVAL_S,
) -> vol.Schema:
    """Build the shared filters schema for setup and options flows."""
    return vol.Schema(
        {
            vol.Optional(CONF_ROUTES_WHITELIST, default=routes): str,
            vol.Optional(CONF_DESTINATIONS, default=destinations): str,
            vol.Optional(CONF_MAX_DEPARTURES, default=max_departures): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_MAX_DEPARTURES, max=MAX_MAX_DEPARTURES),
            ),
            vol.Optional(CONF_LOOK_AHEAD_MIN, default=look_ahead_min): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_LOOK_AHEAD_MIN, max=MAX_LOOK_AHEAD_MIN),
            ),
            vol.Optional(CONF_WALK_OFFSET_MIN, default=walk_offset_min): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_WALK_OFFSET_MIN, max=MAX_WALK_OFFSET_MIN),
            ),
            vol.Optional(CONF_TRACK_VEHICLES, default=track_vehicles): bool,
            vol.Optional(CONF_TRACKED_ROUTES, default=tracked_routes): str,
            vol.Optional(CONF_SCAN_INTERVAL_S, default=scan_interval_s): vol.All(
                vol.Coerce(int),
                vol.Range(min=MIN_SCAN_INTERVAL_S, max=MAX_SCAN_INTERVAL_S),
            ),
        }
    )


def _filters_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw filters input into entry data."""
    return {
        CONF_ROUTES_WHITELIST: _parse_csv(user_input.get(CONF_ROUTES_WHITELIST, "")),
        CONF_DESTINATIONS: _parse_csv(user_input.get(CONF_DESTINATIONS, "")),
        CONF_MAX_DEPARTURES: user_input.get(
            CONF_MAX_DEPARTURES, DEFAULT_MAX_DEPARTURES
        ),
        CONF_LOOK_AHEAD_MIN: user_input.get(
            CONF_LOOK_AHEAD_MIN, DEFAULT_LOOK_AHEAD_MIN
        ),
        CONF_WALK_OFFSET_MIN: user_input.get(
            CONF_WALK_OFFSET_MIN, DEFAULT_WALK_OFFSET_MIN
        ),
        CONF_TRACK_VEHICLES: user_input.get(CONF_TRACK_VEHICLES, False),
        CONF_TRACKED_ROUTES: _parse_tracked_routes(
            user_input.get(CONF_TRACKED_ROUTES, "")
        ),
        CONF_SCAN_INTERVAL_S: user_input.get(
            CONF_SCAN_INTERVAL_S, DEFAULT_SCAN_INTERVAL_S
        ),
    }


class RedRegionalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup, reauth, and reconfiguration for Red Regional."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._zone_uuid: str | None = None
        self._zone_name: str | None = None
        self._zone_names: dict[str, str] = {}
        self._stop_code: str | None = None
        self._stop_name: str | None = None

    def _client(self, hass: HomeAssistant) -> TransAppClient:
        """Build an ephemeral validation client."""
        return TransAppClient(async_get_clientsession(hass), str(uuid4()))

    def _zone_schema(self) -> vol.Schema:
        """Build the zone select schema from the loaded zones."""
        return vol.Schema(
            {
                vol.Required(CONF_ZONE_UUID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=uuid, label=name)
                            for uuid, name in sorted(
                                self._zone_names.items(), key=lambda kv: kv[1]
                            )
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the zone (city) from the live list with offline fallback."""
        if user_input is not None:
            self._zone_uuid = user_input[CONF_ZONE_UUID]
            self._zone_name = self._zone_names.get(self._zone_uuid)
            return await self.async_step_stop()
        self._zone_names = await _load_zone_names(self._client(self.hass))
        return self.async_show_form(step_id="user", data_schema=self._zone_schema())

    async def async_step_stop(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Enter the stop code and validate it against live stopInfo."""
        errors: dict[str, str] = {}
        if user_input is not None:
            stop_code = user_input[CONF_STOP_CODE].strip().upper()
            assert self._zone_uuid is not None
            client = self._client(self.hass)
            gtfs = await async_ensure_gtfs(self.hass, client, self._zone_uuid)
            board, error = await _validate_stop(
                client, self._zone_uuid, stop_code, gtfs
            )
            if error is not None:
                errors["base"] = error
            else:
                assert board is not None
                await self.async_set_unique_id(f"{self._zone_uuid}_{stop_code}")
                self._abort_if_unique_id_configured()
                self._stop_code = stop_code
                self._stop_name = board.stop_name
                return await self.async_step_filters()
        return self.async_show_form(
            step_id="stop",
            data_schema=vol.Schema({vol.Required(CONF_STOP_CODE): str}),
            errors=errors,
        )

    async def async_step_filters(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect optional departure filters and create the entry."""
        if user_input is not None:
            assert self._zone_uuid is not None
            assert self._stop_code is not None
            title = self._stop_code
            if self._stop_name:
                title = f"{self._stop_name} ({self._stop_code})"
            return self.async_create_entry(
                title=title,
                data={
                    CONF_ZONE_UUID: self._zone_uuid,
                    CONF_ZONE_NAME: self._zone_name,
                    CONF_STOP_CODE: self._stop_code,
                    **_filters_data(user_input),
                },
            )
        return self.async_show_form(step_id="filters", data_schema=_filters_schema())

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Confirm a backend-auth retry after rejected requests."""
        return self.async_show_form(
            step_id="reauth_confirm", data_schema=vol.Schema({})
        )

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Retry the rejected entry after user confirmation."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=vol.Schema({})
            )
        return self.async_update_reload_and_abort(
            self._get_reauth_entry(), data_updates={}
        )

    @staticmethod
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler for a Red Regional entry."""
        from .options_flow import RedRegionalOptionsFlow

        return RedRegionalOptionsFlow(entry)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the zone or stop code of the existing entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            zone_uuid: str = user_input[CONF_ZONE_UUID]
            stop_code: str = user_input[CONF_STOP_CODE].strip().upper()
            client = self._client(self.hass)
            gtfs = await async_ensure_gtfs(self.hass, client, zone_uuid)
            board, error = await _validate_stop(client, zone_uuid, stop_code, gtfs)
            if error is not None:
                errors["base"] = error
            else:
                assert board is not None
                new_unique_id = f"{zone_uuid}_{stop_code}"
                existing = self.hass.config_entries.async_entry_for_domain_unique_id(
                    DOMAIN, new_unique_id
                )
                if existing is not None and existing.entry_id != entry.entry_id:
                    return self.async_abort(reason="already_configured")
                zone_name = self._zone_names.get(zone_uuid)
                title = stop_code
                if board.stop_name:
                    title = f"{board.stop_name} ({stop_code})"
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=new_unique_id,
                    data_updates={
                        CONF_ZONE_UUID: zone_uuid,
                        CONF_ZONE_NAME: zone_name,
                        CONF_STOP_CODE: stop_code,
                    },
                    title=title,
                )
        self._zone_names = await _load_zone_names(self._client(self.hass))
        schema = vol.Schema(
            {
                **self._zone_schema().schema,
                vol.Required(
                    CONF_STOP_CODE, default=entry.data.get(CONF_STOP_CODE, "")
                ): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )
