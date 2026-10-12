"""Unit tests for TransApp payload parsers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from custom_components.red_regional.models import StopBoard
from custom_components.red_regional.parse import (
    is_unknown_stop,
    parse_machines,
    parse_stop_board,
)

TZ = ZoneInfo("America/Santiago")
NOW = datetime(2026, 3, 15, 11, 0, tzinfo=TZ)
ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"

FIXTURES = Path("tests/fixtures")


def _load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def test_empty_off_hours_payload_yields_empty_board() -> None:
    """Empty predictions parse to an empty board."""
    board = parse_stop_board(
        {"events": [], "alerts": [], "predictions": [], "routeInfo": []},
        stop_code="P45068",
        zone_uuid=ZONE,
        now=NOW,
    )
    assert isinstance(board, StopBoard)
    assert board.stop_code == "P45068"
    assert board.departures == ()
    assert board.alerts == ()
    assert board.departure_count == 0


def test_live_full_capture_parses() -> None:
    """The live P45068 capture maps predictions, vehicles, and alerts."""
    raw = _load("stopinfo_P45068_full.json")
    now = datetime.fromtimestamp(1791772400, tz=TZ)
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=now)
    assert [d.route for d in board.departures] == ["10N", "10L"]
    first, second = board.departures
    assert first.direction == "R"
    assert first.realtime is True
    assert first.vehicle_id == "DRFP70"
    assert second.vehicle_id == "BCFZ37"
    assert first.expected_at == datetime.fromtimestamp(1791772534, tz=TZ)
    assert first.due_in_min == 2
    assert len(board.alerts) == 8
    assert "Alerta GPS" in board.alerts[0].title
    assert board.alerts[-1].title == "Paradero en buen estado"


def test_invalid_stop_fixture_yields_empty_board() -> None:
    """Unknown stop codes degrade to an empty board, never an error."""
    board = parse_stop_board(
        _load("stopinfo_invalid.json"),
        stop_code="NOEXISTE99",
        zone_uuid=ZONE,
        now=NOW,
    )
    assert board.departures == ()
    assert board.alerts == ()


def test_legacy_services_shape() -> None:
    """Reference-SDK services shape maps to departures."""
    raw = {
        "services": [
            {
                "name": "44B",
                "arrival_time": 5,
                "distance": 1200,
                "plate": "ABCD12",
                "direction": "I",
                "alert": None,
            }
        ]
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert len(board.departures) == 1
    dep = board.departures[0]
    assert dep.route == "44B"
    assert dep.expected_at == NOW + timedelta(minutes=5)
    assert dep.due_in_min == 5
    assert dep.realtime is True
    assert dep.delay_min is None
    assert dep.direction == "I"
    assert dep.vehicle_id == "ABCD12"
    assert dep.cancelled is False


def test_legacy_service_alert_attaches_route() -> None:
    """Per-service legacy alerts become board alerts scoped to the route."""
    raw = {
        "services": [
            {
                "name": "44B",
                "arrival_time": 5,
                "alert": {"title": "Desvío", "description": "Por obras"},
            }
        ]
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert len(board.alerts) == 1
    assert board.alerts[0].title == "Desvío"
    assert board.alerts[0].routes == ("44B",)


def test_epoch_and_iso_predictions() -> None:
    """Absolute arrival representations normalize to tz-aware datetimes."""
    epoch = int((NOW + timedelta(minutes=9)).timestamp())
    raw = {
        "predictions": [
            {"route": "63B", "expected": epoch, "direction": "R"},
            {
                "route": "60Z",
                "arrival_time_str": (NOW + timedelta(minutes=14)).isoformat(),
            },
        ]
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert [d.route for d in board.departures] == ["63B", "60Z"]
    assert board.departures[0].due_in_min == 9
    assert board.departures[1].due_in_min == 14
    assert board.departures[0].expected_at.tzinfo is not None


def test_scheduled_expected_yields_delay() -> None:
    """Scheduled vs expected difference populates delay_min."""
    raw = {
        "predictions": [
            {
                "route": "44B",
                "expected": int((NOW + timedelta(minutes=6)).timestamp()),
                "scheduled": int((NOW + timedelta(minutes=5)).timestamp()),
            }
        ]
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert board.departures[0].delay_min == 1


def test_items_missing_route_or_time_are_skipped() -> None:
    """Incomplete items never produce departures."""
    raw = {"predictions": [{"route": "44B"}, {"expected": 9999999999}, "junk"]}
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert board.departures == ()


def test_unknown_direction_degrades_to_none() -> None:
    """Direction codes outside I/R do not propagate."""
    raw = {"services": [{"name": "44B", "arrival_time": 3, "direction": "X"}]}
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert board.departures[0].direction is None


def test_non_dict_payload_yields_empty_board() -> None:
    """Garbage payloads degrade to an empty board."""
    payload: Any
    for payload in (None, [], "oops"):
        board = parse_stop_board(payload, stop_code="P45068", zone_uuid=ZONE, now=NOW)
        assert board.departures == ()


def test_operator_alerts_and_unexpired_events() -> None:
    """Operator alerts map fully; unexpired events map; expired drop."""
    raw = {
        "alerts": [
            {
                "title": "Corte",
                "description": "Puente cerrado",
                "routes": ["44B"],
            }
        ],
        "events": [
            {
                "name": "Mala Iluminación",
                "description": "",
                "expiryTime": "2026-12-13T21:16:49.980Z",
            },
            {
                "name": "Viejo",
                "description": "",
                "expiryTime": "2020-01-01T00:00:00Z",
            },
            {"description": "sin título"},
        ],
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert [a.title for a in board.alerts] == ["Corte", "Mala Iluminación"]
    assert board.alerts[0].routes == ("44B",)
    assert board.alerts[1].valid_until is not None


def test_gtfs_enrichment_and_stop_name() -> None:
    """Route colors/names fill gaps; stop block names the board."""
    raw = {
        "services": [{"name": "44B", "arrival_time": 4}],
        "stop": {"code": "P45068", "name": "Plaza Tribunales de Justicia"},
    }
    board = parse_stop_board(
        raw,
        stop_code="P45068",
        zone_uuid=ZONE,
        now=NOW,
        route_colors={"44B": "#EC6907"},
        route_names={"44B": "Hualpencillo"},
    )
    assert board.stop_name == "Plaza Tribunales de Justicia"
    assert board.departures[0].route_color == "#EC6907"
    assert board.departures[0].destination == "Hualpencillo"


def test_machines_empty_fixture() -> None:
    """Real empty machines capture parses to no positions."""
    assert parse_machines(_load("machines_44B_I_empty.json"), now=NOW) == ()


def test_machines_example_shape() -> None:
    """Reference-SDK machine keys map; incomplete machines drop."""
    raw = {
        "machines": [
            {
                "license_plate": "ABCD12",
                "latitude": -36.82,
                "longitude": -73.05,
                "speed": 32,
                "route": "44B",
                "direction": "I",
            },
            {"latitude": -36.82, "longitude": -73.05},
            {"license_plate": "SINCOORD"},
            "junk",
        ]
    }
    positions = parse_machines(raw, now=NOW)
    assert len(positions) == 1
    bus = positions[0]
    assert bus.plate == "ABCD12"
    assert (bus.latitude, bus.longitude) == (-36.82, -73.05)
    assert bus.speed_kmh == 32
    assert bus.route == "44B"
    assert bus.direction == "I"
    assert bus.last_update == NOW


def test_machines_non_dict_yields_empty() -> None:
    """Garbage machines payloads degrade to empty."""
    assert parse_machines(None, now=NOW) == ()
    assert parse_machines({"machines": {}}, now=NOW) == ()


def test_millis_epoch_and_string_minutes() -> None:
    """Millis epochs and numeric-string minutes both resolve."""
    millis = int((NOW + timedelta(minutes=11)).timestamp() * 1000)
    raw = {
        "predictions": [
            {"route": "44B", "expected": millis},
            {"route": "63B", "arrival_time": "7"},
        ]
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert [d.due_in_min for d in board.departures] == [7, 11]


def test_unparseable_arrivals_are_skipped() -> None:
    """Textual or boolean arrivals never produce departures."""
    raw = {
        "predictions": [
            {"route": "44B", "arrival_time": "pronto"},
            {"route": "63B", "arrival_time": True},
        ]
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert board.departures == ()


def test_naive_iso_assumes_local_zone() -> None:
    """Naive ISO strings are interpreted in the reference timezone."""
    raw = {"predictions": [{"route": "44B", "arrival_time_str": "2026-03-15T11:20:00"}]}
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert board.departures[0].due_in_min == 20
    assert board.departures[0].expected_at.tzinfo is not None


def test_string_legacy_alert() -> None:
    """Plain-text legacy alerts become titled alerts for the route."""
    raw = {
        "services": [{"name": "44B", "arrival_time": 5, "alert": "Corte de tránsito"}]
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert len(board.alerts) == 1
    assert board.alerts[0].title == "Corte de tránsito"
    assert board.alerts[0].routes == ("44B",)


def test_dict_legacy_alert_keeps_its_routes() -> None:
    """Legacy alert dicts keep explicit routes instead of the fallback."""
    raw = {
        "services": [
            {
                "name": "44B",
                "arrival_time": 5,
                "alert": {"title": "Desvío", "routes": ["44B", "63B"]},
            }
        ]
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert board.alerts[0].routes == ("44B", "63B")


def test_machines_alternate_keys_and_missing_speed() -> None:
    """Alternate machine keys map; missing speed stays None."""
    raw = {
        "machines": [
            {
                "plate": "XYZ789",
                "lat": -36.8,
                "lng": -73.0,
                "velocidad": "32",
                "linea": "44B",
                "sentido": "R",
            }
        ]
    }
    (bus,) = parse_machines(raw, now=NOW)
    assert bus.plate == "XYZ789"
    assert bus.speed_kmh == 32
    assert bus.route == "44B"
    assert bus.direction == "R"


def test_non_list_predictions_yields_empty() -> None:
    """Non-list prediction containers degrade to an empty board."""
    board = parse_stop_board(
        {"predictions": {"route": "44B"}},
        stop_code="P45068",
        zone_uuid=ZONE,
        now=NOW,
    )
    assert board.departures == ()


def test_epoch_edge_cases_are_skipped() -> None:
    """Boolean and out-of-range epochs never resolve."""
    raw = {
        "predictions": [
            {"route": "44B", "expected": True},
            {"route": "63B", "expected": 12345},
            {"route": "60Z", "arrival_time_str": "mañana"},
        ]
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert board.departures == ()


def test_explicit_delay_without_scheduled() -> None:
    """Raw delay fields populate delay_min when scheduled is absent."""
    raw = {"services": [{"name": "44B", "arrival_time": 5, "delay": 2}]}
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert board.departures[0].delay_min == 2


def test_malformed_legacy_alerts_are_skipped() -> None:
    """Untitled or non-text legacy alerts never produce alerts."""
    raw = {
        "services": [
            {"name": "44B", "arrival_time": 5, "alert": {"foo": 1}},
            {"name": "63B", "arrival_time": 6, "alert": 5},
        ],
        "alerts": ["nota"],
    }
    board = parse_stop_board(raw, stop_code="P45068", zone_uuid=ZONE, now=NOW)
    assert board.alerts == ()


def test_non_numeric_speed_degrades_to_none() -> None:
    """Boolean and textual speeds resolve to unknown speed."""
    raw = {
        "machines": [
            {
                "plate": "T1",
                "latitude": -36.8,
                "longitude": -73.0,
                "velocidad": True,
                "speed": "rapid",
            }
        ]
    }
    (bus,) = parse_machines(raw, now=NOW)
    assert bus.speed_kmh is None


def test_default_now_is_santiago_aware() -> None:
    """Default clock returns a timezone-aware timestamp."""
    from custom_components.red_regional.parse import default_now

    assert default_now().tzinfo is not None


def test_is_unknown_stop_signature() -> None:
    """Only empty payloads without routeInfo read as unknown stops."""
    assert is_unknown_stop({"events": [], "alerts": [], "predictions": []}) is True
    assert is_unknown_stop({"routeInfo": [], "predictions": []}) is False
    assert is_unknown_stop({"predictions": [{"route": "44B"}]}) is False
    assert is_unknown_stop({"alerts": [{"title": "X"}]}) is False
    assert is_unknown_stop(None) is False
    assert is_unknown_stop([]) is False
