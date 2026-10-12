"""Options flow for Red Regional: filters and polling without re-setup."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, OptionsFlow

from .config_flow import _filters_data, _filters_schema
from .const import (
    CONF_DESTINATIONS,
    CONF_LOOK_AHEAD_MIN,
    CONF_MAX_DEPARTURES,
    CONF_ROUTES_WHITELIST,
    CONF_SCAN_INTERVAL_S,
    CONF_TRACK_VEHICLES,
    CONF_TRACKED_ROUTES,
    CONF_WALK_OFFSET_MIN,
)


def _csv(values: Any) -> str:
    """Join stored filter lists back into editable text."""
    if isinstance(values, list):
        parts: list[str] = []
        for value in values:
            if isinstance(value, dict):
                route = value.get("route", "")
                direction = value.get("direction", "I")
                parts.append(f"{route}:{direction}" if direction != "I" else route)
            elif value:
                parts.append(str(value))
        return ", ".join(parts)
    return str(values) if values else ""


class RedRegionalOptionsFlow(OptionsFlow):
    """Handle options for a Red Regional stop entry."""

    def __init__(self, entry: ConfigEntry) -> None:
        """Store the entry being configured."""
        self._entry = entry

    def _current(self, key: str, default: Any) -> Any:
        """Prefer saved options over the original setup data."""
        if key in self._entry.options:
            return self._entry.options[key]
        return self._entry.data.get(key, default)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        """Show and save filters, tracking, and polling options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=_filters_data(user_input))
        return self.async_show_form(
            step_id="init",
            data_schema=_filters_schema(
                routes=_csv(self._current(CONF_ROUTES_WHITELIST, "")),
                destinations=_csv(self._current(CONF_DESTINATIONS, "")),
                max_departures=self._current(CONF_MAX_DEPARTURES, 5),
                look_ahead_min=self._current(CONF_LOOK_AHEAD_MIN, 120),
                walk_offset_min=self._current(CONF_WALK_OFFSET_MIN, 0),
                track_vehicles=bool(self._current(CONF_TRACK_VEHICLES, False)),
                tracked_routes=_csv(self._current(CONF_TRACKED_ROUTES, "")),
                scan_interval_s=self._current(CONF_SCAN_INTERVAL_S, 60),
            ),
        )
