"""Unit tests for the departure filtering pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.red_regional.filters import apply_departure_filters
from custom_components.red_regional.models import Departure

TZ = ZoneInfo("America/Santiago")
NOW = datetime(2026, 3, 15, 11, 0, tzinfo=TZ)


def _dep(route: str, due: int, destination: str | None = None) -> Departure:
    return Departure(
        route=route,
        expected_at=NOW + timedelta(minutes=due),
        due_in_min=due,
        destination=destination,
    )


def test_empty_whitelist_passes_all() -> None:
    """No whitelist keeps every departure."""
    deps = (_dep("44B", 4), _dep("63B", 9))
    assert apply_departure_filters(deps) == list(deps)


def test_whitelist_matches_case_insensitive_stripped() -> None:
    """Whitelist matching ignores case and surrounding spaces."""
    deps = [_dep("44B", 4), _dep("63B", 9)]
    result = apply_departure_filters(deps, routes_whitelist=[" 44b "])
    assert [d.route for d in result] == ["44B"]


def test_destinations_substring_match() -> None:
    """Destination filter is a case-insensitive substring match."""
    deps = [
        _dep("44B", 4, "Hualpencillo Centro"),
        _dep("63B", 9, "Chiguayante"),
        _dep("60Z", 12, None),
    ]
    result = apply_departure_filters(deps, destinations=["hualpen"])
    assert [d.route for d in result] == ["44B"]


def test_empty_destinations_passes_all() -> None:
    """No destination filter keeps departures without destination."""
    deps = [_dep("44B", 4, None)]
    assert apply_departure_filters(deps) == deps


def test_walk_offset_hides_sooner_departures() -> None:
    """Departures sooner than the walk offset are hidden; boundary kept."""
    deps = [_dep("44B", 3), _dep("63B", 5), _dep("60Z", 9)]
    result = apply_departure_filters(deps, walk_offset_min=5)
    assert [d.route for d in result] == ["63B", "60Z"]


def test_look_ahead_drops_later_departures() -> None:
    """Departures beyond the window drop; boundary kept."""
    deps = [_dep("44B", 4), _dep("63B", 120), _dep("60Z", 121)]
    result = apply_departure_filters(deps, look_ahead_min=120)
    assert [d.route for d in result] == ["44B", "63B"]


def test_sorts_and_truncates() -> None:
    """Output is ordered by expected_at and capped at max_departures."""
    deps = [_dep("60Z", 20), _dep("44B", 4), _dep("63B", 9)]
    result = apply_departure_filters(deps, max_departures=2)
    assert [d.route for d in result] == ["44B", "63B"]


def test_zero_max_departures_yields_empty() -> None:
    """Zero cap yields no departures instead of slicing from the end."""
    deps = [_dep("44B", 4)]
    assert apply_departure_filters(deps, max_departures=0) == []


def test_input_not_mutated() -> None:
    """Filtering never reorders or trims the caller's sequence."""
    deps = (_dep("60Z", 20), _dep("44B", 4))
    apply_departure_filters(deps, max_departures=1)
    assert [d.route for d in deps] == ["60Z", "44B"]
