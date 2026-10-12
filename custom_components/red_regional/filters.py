"""Departure filtering pipeline per spec section 4.2."""

from __future__ import annotations

from collections.abc import Sequence

from .const import (
    DEFAULT_LOOK_AHEAD_MIN,
    DEFAULT_MAX_DEPARTURES,
    DEFAULT_WALK_OFFSET_MIN,
)
from .models import Departure


def apply_departure_filters(
    departures: Sequence[Departure],
    *,
    routes_whitelist: Sequence[str] = (),
    destinations: Sequence[str] = (),
    look_ahead_min: int = DEFAULT_LOOK_AHEAD_MIN,
    walk_offset_min: int = DEFAULT_WALK_OFFSET_MIN,
    max_departures: int = DEFAULT_MAX_DEPARTURES,
) -> list[Departure]:
    """Filter, sort, and truncate departures without mutating the input."""
    whitelist = {r.strip().upper() for r in routes_whitelist if r.strip()}
    result = [
        d for d in departures if not whitelist or d.route.strip().upper() in whitelist
    ]
    wanted = [s.strip().lower() for s in destinations if s.strip()]
    if wanted:
        result = [
            d
            for d in result
            if d.destination is not None
            and any(s in d.destination.lower() for s in wanted)
        ]
    result = [
        d
        for d in result
        if d.due_in_min >= walk_offset_min and d.due_in_min <= look_ahead_min
    ]
    result.sort(key=lambda d: d.expected_at)
    return result[: max(0, max_departures)]
