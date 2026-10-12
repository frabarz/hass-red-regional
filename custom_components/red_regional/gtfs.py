"""Version-gated GTFS-static cache with a tolerant CSV parser."""

from __future__ import annotations

import csv
import io
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from homeassistant.core import HomeAssistant

from .api import TransAppClient
from .const import STORAGE_DIR
from .exceptions import TransAppError

_LOGGER = logging.getLogger(__name__)

_MEMORY: dict[str, tuple[str | None, GtfsIndex]] = {}


@dataclass(frozen=True)
class GtfsStop:
    """Static metadata for one stop, keyed by stop code."""

    name: str | None
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True)
class GtfsRoute:
    """Static metadata for one route, keyed by upper short name."""

    long_name: str | None
    color: str | None = None


@dataclass(frozen=True)
class GtfsIndex:
    """Parsed GTFS-static snapshot for one zone."""

    stops: dict[str, GtfsStop] = field(default_factory=dict)
    routes: dict[str, GtfsRoute] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> GtfsIndex:
        """Return an index with no stops or routes."""
        return cls(stops={}, routes={})


def find_stops(
    index: GtfsIndex, query: str, limit: int = 8
) -> list[tuple[str, GtfsStop]]:
    """Substring-search stop codes and names for the lookup service."""
    needle = query.strip().lower()
    if not needle:
        return []
    matches = [
        (code, stop)
        for code, stop in index.stops.items()
        if needle in code.lower()
        or (stop.name is not None and needle in stop.name.lower())
    ]
    return matches[:limit]


def _decode_member(raw: bytes) -> str:
    """Decode ZIP member bytes, tolerating BOMs and legacy encodings."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _read_table(
    archive: zipfile.ZipFile, names: list[str], candidates: tuple[str, ...]
) -> csv.DictReader[str] | None:
    """Open the first matching CSV member, sniffing `;` and `,` dialects."""
    for candidate in candidates:
        if candidate not in names:
            continue
        text = _decode_member(archive.read(candidate))
        header = text.splitlines()[0] if text.strip() else ""
        delimiter = ";" if header.count(";") > header.count(",") else ","
        return csv.DictReader(text.splitlines(), delimiter=delimiter)
    return None


def _col(row: dict[str, str | None], *names: str) -> str:
    """Return the first non-blank value across column name variants."""
    for name in names:
        value = row.get(name)
        if value and value.strip():
            return value.strip()
    return ""


def _parse_float(value: str | None) -> float | None:
    """Parse a coordinate, degrading garbage to None."""
    if not value or not value.strip():
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def _normalize_color(value: str | None) -> str | None:
    """Normalize GTFS hex colors to #RRGGBB form."""
    if not value or not value.strip():
        return None
    text = value.strip().lstrip("#")
    if len(text) == 6 and all(char in "0123456789abcdefABCDEF" for char in text):
        return f"#{text.upper()}"
    return value.strip()


def _parse_stops(table: csv.DictReader[str] | None) -> dict[str, GtfsStop]:
    """Index stop rows by stop code."""
    stops: dict[str, GtfsStop] = {}
    if table is None:
        return stops
    for row in table:
        code = _col(row, "stop_code")
        if not code:
            continue
        stops[code] = GtfsStop(
            name=_col(row, "stop_name", "name") or None,
            latitude=_parse_float(_col(row, "stop_lat", "stop_latitude", "lat")),
            longitude=_parse_float(_col(row, "stop_lon", "stop_longitude", "lon")),
        )
    return stops


def _parse_routes(table: csv.DictReader[str] | None) -> dict[str, GtfsRoute]:
    """Index route rows by upper short name; first variant wins."""
    routes: dict[str, GtfsRoute] = {}
    if table is None:
        return routes
    for row in table:
        short = _col(row, "route_short_name", "route_name", "short_name").upper()
        if not short or short in routes:
            continue
        routes[short] = GtfsRoute(
            long_name=_col(row, "route_long_name", "headsign", "long_name") or None,
            color=_normalize_color(_col(row, "route_color", "color")),
        )
    return routes


def parse_gtfs_zip(payload: bytes) -> GtfsIndex:
    """Parse GTFS CSVs from ZIP bytes into an index.

    Accepts singular (`stop.csv`) and standard plural (`stops.txt`) member
    names; corrupt archives yield an empty index instead of raising.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile:
        return GtfsIndex.empty()
    names = archive.namelist()
    return GtfsIndex(
        stops=_parse_stops(_read_table(archive, names, ("stop.csv", "stops.txt"))),
        routes=_parse_routes(_read_table(archive, names, ("route.csv", "routes.txt"))),
    )


def _store_and_parse(
    zip_path: Path, version_path: Path, payload: bytes, version: str
) -> GtfsIndex:
    """Write the ZIP and version file, then parse (runs in an executor)."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(payload)
    index = parse_gtfs_zip(payload)
    version_path.write_text(version, encoding="utf-8")
    return index


def _load_zip(zip_path: Path) -> GtfsIndex:
    """Parse the cached ZIP (runs in an executor)."""
    return parse_gtfs_zip(zip_path.read_bytes())


async def async_ensure_gtfs(
    hass: HomeAssistant, client: TransAppClient, zone_uuid: str
) -> GtfsIndex:
    """Return the zone GTFS index, downloading only when the version changed.

    Degrades gracefully: stale disk, then memory, then an empty index. Never
    raises TransAppError or OSError so enrichment never blocks setup.
    """
    base = Path(hass.config.path(".storage", STORAGE_DIR))
    zip_path = base / f"gtfs_{zone_uuid}.zip"
    version_path = base / f"gtfs_{zone_uuid}.version"
    version: str | None = None
    try:
        raw = await client.async_get_gtfs_version(zone_uuid)
        if isinstance(raw, dict) and raw.get("version"):
            version = str(raw["version"])
    except TransAppError as err:
        _LOGGER.debug("GTFS version check failed for %s: %s", zone_uuid, err)
    memory = _MEMORY.get(zone_uuid)
    if version is not None and memory is not None and memory[0] == version:
        return memory[1]
    try:
        disk_version = (
            version_path.read_text(encoding="utf-8").strip()
            if version_path.exists()
            else None
        )
        if zip_path.exists() and (version is None or disk_version == version):
            index = await hass.async_add_executor_job(_load_zip, zip_path)
            _MEMORY[zone_uuid] = (disk_version, index)
            return index
        payload = await client.async_fetch_gtfs(zone_uuid)
        stored_version = version or disk_version or "unknown"
        index = await hass.async_add_executor_job(
            _store_and_parse, zip_path, version_path, payload, stored_version
        )
        _MEMORY[zone_uuid] = (stored_version, index)
        return index
    except (TransAppError, OSError) as err:
        _LOGGER.warning(
            "GTFS refresh failed for %s, using stale data: %s", zone_uuid, err
        )
    if zip_path.exists():
        try:
            index = await hass.async_add_executor_job(_load_zip, zip_path)
            _MEMORY[zone_uuid] = (None, index)
            return index
        except OSError as err:
            _LOGGER.debug("GTFS stale load failed for %s: %s", zone_uuid, err)
    if memory is not None:
        return memory[1]
    return GtfsIndex.empty()
