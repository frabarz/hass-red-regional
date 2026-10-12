"""Tolerant parsers for TransApp payloads.

The backend changed shape without notice: the reference SDK documents a
legacy ``services[]`` list (``name``/``arrival_time`` minutes), while live
captures return ``predictions[]``/``routeInfo[]``/``events[]``/``alerts[]``.
Peak-hour ``predictions[]`` items (observed 2026-10-12) carry ``route``,
``direction``, ``epochTime``, ``realtime``, ``distance``, bus ``latitude`` /
``longitude`` and ``licensePlate``; live ``alerts[]`` carry ``author`` plus
an HTML ``message`` instead of ``title``/``description``. Every field is
probed across all known candidate keys and missing keys degrade to ``None``
instead of raising.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .const import DEFAULT_TIME_ZONE
from .models import Departure, ServiceAlert, StopBoard, VehiclePosition

_EPOCH_KEYS = (
    "expected",
    "expected_at",
    "epochTime",
    "epoch",
    "epoch_time",
    "arrival",
    "arrivalTime",
    "arrival_timestamp",
    "departureTime",
    "timestamp",
    "time",
    "eta_timestamp",
)

_ISO_KEYS = (
    "expected_at_iso",
    "expected_iso",
    "arrival_iso",
    "arrival_time_iso",
    "expected_time",
    "arrival_time_str",
    "hora",
)

_MINUTES_KEYS = (
    "arrival_time",
    "due",
    "due_in_min",
    "minutes",
    "eta",
    "eta_min",
    "arrival_minutes",
    "minutos",
)

_SCHEDULED_KEYS = (
    "scheduled",
    "scheduled_at",
    "scheduled_time",
    "programmed",
)

_ROUTE_KEYS = ("route", "name", "service", "route_short_name", "linea")

_DESTINATION_KEYS = (
    "destination",
    "headsign",
    "trip_headsign",
    "direction_name",
    "destino",
    "long_name",
)

_VEHICLE_KEYS = (
    "plate",
    "licensePlate",
    "license_plate",
    "vehicle_id",
    "patente",
    "bus_id",
)

_DIRECTION_KEYS = ("direction", "sentido")


def _first_str(item: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first non-blank string found under any key."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _first_num(item: Mapping[str, Any], keys: tuple[str, ...]) -> float | None:
    """Return the first real number found under any key."""
    for key in keys:
        value = item.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.strip():
            try:
                return float(value.strip())
            except ValueError:
                continue
    return None


def _as_epoch(value: Any) -> float | None:
    """Interpret a number as epoch seconds, handling millis and strings."""
    if isinstance(value, bool):
        return None
    seconds: float | None = None
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            seconds = float(value.strip())
        except ValueError:
            return None
    if seconds is None:
        return None
    if seconds > 1e11:
        seconds /= 1000.0
    if seconds < 1e8 or seconds > 2e10:
        return None
    return seconds


def _coerce_datetime(value: Any, tz: Any) -> datetime | None:
    """Normalize epoch/ISO payload values to tz-aware datetimes."""
    epoch = _as_epoch(value)
    if epoch is not None:
        return datetime.fromtimestamp(epoch, tz=tz)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed
    return None


def _expected_from_item(item: Mapping[str, Any], now: datetime) -> datetime | None:
    """Probe absolute then relative arrival candidates for one item."""
    for key in _EPOCH_KEYS:
        if key in item:
            expected = _coerce_datetime(item[key], now.tzinfo)
            if expected is not None:
                return expected
    for key in _ISO_KEYS:
        if key in item:
            expected = _coerce_datetime(item[key], now.tzinfo)
            if expected is not None:
                return expected
    minutes: float | None = None
    for key in _MINUTES_KEYS:
        if key not in item:
            continue
        candidate = item[key]
        if isinstance(candidate, bool):
            continue
        try:
            text = candidate.strip() if isinstance(candidate, str) else candidate
            number = float(text)
        except (TypeError, ValueError, AttributeError):
            continue
        if -30 <= number <= 1440:
            minutes = number
            break
    if minutes is not None:
        return now + timedelta(minutes=max(0.0, minutes))
    return None


def _normalize_direction(value: Any) -> str | None:
    """Keep only the backend-accepted I/R direction codes."""
    if isinstance(value, str) and value.strip().upper() in ("I", "R"):
        return value.strip().upper()
    return None


def _scheduled_from_item(item: Mapping[str, Any], tz: Any) -> datetime | None:
    """Probe scheduled-time candidates for one item."""
    for key in _SCHEDULED_KEYS:
        if key in item:
            scheduled = _coerce_datetime(item[key], tz)
            if scheduled is not None:
                return scheduled
    return None


def _departure_from_item(
    item: Mapping[str, Any],
    now: datetime,
    route_colors: Mapping[str, str] | None,
    route_names: Mapping[str, str] | None,
) -> Departure | None:
    """Build one Departure from a legacy service or prediction item."""
    route = _first_str(item, _ROUTE_KEYS)
    expected_at = _expected_from_item(item, now)
    if route is None or expected_at is None:
        return None
    scheduled_at = _scheduled_from_item(item, now.tzinfo)
    delay_min: int | None = None
    if scheduled_at is not None:
        delay_min = round((expected_at - scheduled_at).total_seconds() / 60)
    else:
        raw_delay = _first_num(item, ("delay", "delay_min", "delay_minutes"))
        if raw_delay is not None:
            delay_min = round(raw_delay)
    destination = _first_str(item, _DESTINATION_KEYS)
    if destination is None and route_names is not None:
        destination = route_names.get(route)
    route_color = route_colors.get(route) if route_colors is not None else None
    realtime = item.get("realtime", True)
    cancelled = bool(item.get("cancelled", item.get("canceled", False)))
    occupancy = _first_str(item, ("occupancy",))
    due_in_min = max(0, round((expected_at - now).total_seconds() / 60))
    return Departure(
        route=route,
        expected_at=expected_at,
        due_in_min=due_in_min,
        destination=destination,
        scheduled_at=scheduled_at,
        delay_min=delay_min,
        realtime=bool(realtime),
        direction=_normalize_direction(
            next((item.get(k) for k in _DIRECTION_KEYS if k in item), None)
        ),
        vehicle_id=_first_str(item, _VEHICLE_KEYS),
        route_color=route_color,
        cancelled=cancelled,
        occupancy=occupancy,
    )


def _plain_text(value: str) -> str:
    """Strip HTML markup from backend messages into plain text."""
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _alert_from_item(item: Mapping[str, Any], now: datetime) -> ServiceAlert | None:
    """Build one ServiceAlert from an operator alert or crowdsourced event."""
    title = _first_str(item, ("title", "name", "subject", "titulo"))
    description = _first_str(item, ("description", "descripcion"))
    message = _first_str(item, ("message", "mensaje"))
    if title is None and message is not None:
        title = _plain_text(message)[:120] or None
    if description is None and message is not None:
        description = _plain_text(message) or None
    if title is None:
        return None
    routes_raw = item.get("routes", item.get("affected_routes", item.get("lines", [])))
    routes = (
        tuple(str(r).strip() for r in routes_raw if str(r).strip())
        if isinstance(routes_raw, list)
        else ()
    )
    valid_from = _coerce_datetime(
        item.get("valid_from", item.get("start", item.get("since"))), now.tzinfo
    )
    valid_until = _coerce_datetime(
        item.get(
            "valid_until",
            item.get("until", item.get("end", item.get("expiryTime"))),
        ),
        now.tzinfo,
    )
    if valid_until is not None and valid_until < now:
        return None
    return ServiceAlert(
        title=title,
        description=description,
        routes=routes,
        valid_from=valid_from,
        valid_until=valid_until,
    )


def _legacy_alert(value: Any, route: str, now: datetime) -> ServiceAlert | None:
    """Build an alert from a legacy per-service alert field."""
    if isinstance(value, dict):
        alert = _alert_from_item(value, now)
        if alert is None:
            return None
        if not alert.routes:
            return ServiceAlert(
                title=alert.title,
                description=alert.description,
                routes=(route,),
                valid_from=alert.valid_from,
                valid_until=alert.valid_until,
            )
        return alert
    if isinstance(value, str) and value.strip():
        return ServiceAlert(title=value.strip(), routes=(route,))
    return None


def is_unknown_stop(raw: Any) -> bool:
    """Detect the invalid-stop signature: empty payload without routeInfo.

    Live captures show unknown codes return 200 with empty lists and no
    routeInfo key, while valid off-hours stops still carry routeInfo.
    """
    if not isinstance(raw, dict):
        return False
    if raw.get("predictions") or raw.get("services"):
        return False
    if raw.get("alerts") or raw.get("events"):
        return False
    return "routeInfo" not in raw


def parse_stop_board(
    raw: Any,
    *,
    stop_code: str,
    zone_uuid: str,
    now: datetime,
    zone_name: str | None = None,
    route_colors: Mapping[str, str] | None = None,
    route_names: Mapping[str, str] | None = None,
) -> StopBoard:
    """Normalize any known stopInfo shape into a StopBoard.

    Accepts legacy ``{"services": [...]}`` and current
    ``{"predictions": [...], "alerts": [...], "events": [...]}`` payloads.
    Empty lists (off-hours) yield an empty board; unknown shapes do too.
    The board is stamped with the reference time it was parsed at.
    """
    if not isinstance(raw, dict):
        return StopBoard(stop_code=stop_code, zone_uuid=zone_uuid, fetched_at=now)
    items: list[Any] = []
    for key in ("predictions", "services"):
        value = raw.get(key)
        if isinstance(value, list):
            items.extend(value)
    departures: list[Departure] = []
    alerts: list[ServiceAlert] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        departure = _departure_from_item(item, now, route_colors, route_names)
        if departure is not None:
            departures.append(departure)
        route = _first_str(item, _ROUTE_KEYS)
        if route is not None and item.get("alert") is not None:
            legacy = _legacy_alert(item.get("alert"), route, now)
            if legacy is not None:
                alerts.append(legacy)
    departures.sort(key=lambda d: d.expected_at)
    for key in ("alerts", "events"):
        value = raw.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            alert = _alert_from_item(item, now)
            if alert is not None:
                alerts.append(alert)
    stop_name: str | None = None
    stop_raw = raw.get("stop")
    if isinstance(stop_raw, dict):
        stop_name = _first_str(stop_raw, ("name", "stop_name"))
    return StopBoard(
        stop_code=stop_code,
        zone_uuid=zone_uuid,
        departures=tuple(departures),
        alerts=tuple(alerts),
        stop_name=stop_name,
        zone_name=zone_name,
        fetched_at=now,
    )


def parse_machines(raw: Any, *, now: datetime) -> tuple[VehiclePosition, ...]:
    """Normalize a synoptic/machines payload into vehicle positions.

    Items without a plate or valid coordinates are skipped; unknown extra
    keys are ignored so backend additions never break parsing.
    """
    if not isinstance(raw, dict):
        return ()
    machines = raw.get("machines")
    if not isinstance(machines, list):
        return ()
    positions: list[VehiclePosition] = []
    for item in machines:
        if not isinstance(item, dict):
            continue
        plate = _first_str(item, _VEHICLE_KEYS)
        latitude = _first_num(item, ("latitude", "lat"))
        longitude = _first_num(item, ("longitude", "lon", "lng", "long"))
        if plate is None or latitude is None or longitude is None:
            continue
        speed = _first_num(item, ("speed", "speed_kmh", "velocidad"))
        positions.append(
            VehiclePosition(
                plate=plate,
                latitude=latitude,
                longitude=longitude,
                speed_kmh=speed,
                route=_first_str(
                    item, ("route", "route_short_name", "linea", "service")
                ),
                direction=_normalize_direction(
                    next(
                        (item.get(k) for k in _DIRECTION_KEYS if k in item),
                        None,
                    )
                ),
                last_update=now,
            )
        )
    return tuple(positions)


def default_now() -> datetime:
    """Return the current time in the integration default time zone."""
    return datetime.now(tz=ZoneInfo(DEFAULT_TIME_ZONE))
