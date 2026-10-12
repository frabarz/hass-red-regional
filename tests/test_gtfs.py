"""Unit tests for the GTFS-static cache and parser."""

from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant

from custom_components.red_regional import gtfs as gtfs_module
from custom_components.red_regional.exceptions import TransAppConnectionError
from custom_components.red_regional.gtfs import (
    GtfsIndex,
    async_ensure_gtfs,
    find_stops,
    parse_gtfs_zip,
)

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"

FIXTURES = Path("tests/fixtures")


@pytest.fixture(autouse=True)
def _isolate_gtfs(hass: HomeAssistant) -> None:
    """Isolate GTFS memory and disk caches between tests."""
    from custom_components.red_regional.const import STORAGE_DIR

    gtfs_module._MEMORY.clear()
    base = Path(hass.config.path(".storage", STORAGE_DIR))
    if base.exists():
        shutil.rmtree(base)


def _make_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


class _FakeGtfsClient:
    """Stub client replaying GTFS version and payload outcomes."""

    def __init__(
        self,
        version: Any = None,
        payload: bytes | None = None,
        exc: Exception | None = None,
        fetch_exc: Exception | None = None,
    ) -> None:
        """Store canned version, payload, and failures."""
        self.version = version
        self.payload = payload
        self.exc = exc
        self.fetch_exc = fetch_exc if fetch_exc is not None else exc
        self.version_calls = 0
        self.fetch_calls = 0

    async def async_get_gtfs_version(self, zone_uuid: str) -> Any:
        """Replay the canned version or raise."""
        self.version_calls += 1
        if self.exc is not None:
            raise self.exc
        return {"version": self.version}

    async def async_fetch_gtfs(self, zone_uuid: str) -> bytes:
        """Replay the canned payload or raise."""
        self.fetch_calls += 1
        if self.fetch_exc is not None:
            raise self.fetch_exc
        assert self.payload is not None
        return self.payload


COMMA_ZIP = _make_zip(
    {
        "stops.txt": (
            b"stop_id,stop_name,stop_lat,stop_lon,stop_code\n"
            b"1,Parada Uno,-36.8,-73.0,P00001\n"
            b"2,Sin Codigo,-36.8,-73.0,\n"
        ),
        "routes.txt": (
            b"route_id,route_short_name,route_long_name,route_color\n"
            b"r1,44B,Hualpencillo,EC6907\n"
            b"r2,,Sin Nombre,red\n"
        ),
    }
)


def test_real_concepcion_feed() -> None:
    """The live Concepción feed resolves the canonical stop and route."""
    index = parse_gtfs_zip((FIXTURES / "gtfs_concepcion.zip").read_bytes())
    assert len(index.stops) > 2000
    stop = index.stops["P45068"]
    assert stop.name == "Plaza Tribunales De Justicia"
    assert stop.latitude is not None and stop.longitude is not None
    route = index.routes["44B"]
    assert route.long_name == "Hualpencillo"
    assert route.color == "#EC6907"
    assert find_stops(index, "P45068")[0][0] == "P45068"
    codes = [code for code, _ in find_stops(index, "tribunales")]
    assert "P45068" in codes


def test_plural_comma_names_and_color_normalization() -> None:
    """Standard plural filenames and comma dialect parse with enrichment."""
    index = parse_gtfs_zip(COMMA_ZIP)
    assert index.stops["P00001"].name == "Parada Uno"
    assert "2" not in index.stops
    assert index.routes["44B"].color == "#EC6907"
    assert index.routes["44B"].long_name == "Hualpencillo"
    assert "" not in index.routes


def test_semicolon_bom_and_latin1() -> None:
    """BOM-prefixed semicolon files and latin-1 bytes both decode."""
    bom_zip = _make_zip(
        {
            "stop.csv": (
                "﻿stop_code;stop_name;stop_lat;stop_lon\nP1;Uno;-36.8;-73.0"
            ).encode(),
            "route.csv": b"route_short_name;route_long_name;route_color\n44B;;",
        }
    )
    index = parse_gtfs_zip(bom_zip)
    assert index.stops["P1"].name == "Uno"
    assert index.routes["44B"].long_name is None
    latin_zip = _make_zip({"stop.csv": b"stop_code;stop_name\nP2;Cami\xf3n"})
    assert parse_gtfs_zip(latin_zip).stops["P2"].name == "Cami\u00f3n"


def test_bad_coords_colors_and_garbage() -> None:
    """Bad numbers degrade to None; odd colors pass through; junk is empty."""
    payload = _make_zip(
        {
            "stop.csv": (b"stop_code,stop_name,stop_lat,stop_lon\nP1,Uno,xx,yy"),
            "route.csv": (b"route_short_name,route_long_name,route_color\n44B,X,red"),
        }
    )
    index = parse_gtfs_zip(payload)
    assert index.stops["P1"].latitude is None
    assert index.routes["44B"].color == "red"
    assert parse_gtfs_zip(b"not a zip") == GtfsIndex.empty()
    assert parse_gtfs_zip(_make_zip({})) == GtfsIndex.empty()


def test_find_stops_guards() -> None:
    """Blank queries match nothing; limits apply."""
    index = parse_gtfs_zip(COMMA_ZIP)
    assert find_stops(index, "   ") == []
    assert len(find_stops(index, "P", limit=1)) == 1


async def test_download_then_stale_reuse(hass: HomeAssistant) -> None:
    """First call downloads; later failures reuse memory or stale disk."""
    client = _FakeGtfsClient(version="v1", payload=COMMA_ZIP)
    index = await async_ensure_gtfs(hass, client, ZONE)  # type: ignore[arg-type]
    assert index.stops["P00001"].name == "Parada Uno"
    assert client.fetch_calls == 1
    client.exc = TransAppConnectionError("down")
    stale = await async_ensure_gtfs(hass, client, ZONE)  # type: ignore[arg-type]
    assert stale.stops["P00001"].name == "Parada Uno"
    assert client.fetch_calls == 1
    gtfs_module._MEMORY.clear()
    redownload = await async_ensure_gtfs(hass, client, ZONE)  # type: ignore[arg-type]
    assert redownload.stops["P00001"].name == "Parada Uno"


async def test_version_change_refetches(hass: HomeAssistant) -> None:
    """A bumped feed version triggers a fresh download."""
    client = _FakeGtfsClient(version="v1", payload=COMMA_ZIP)
    await async_ensure_gtfs(hass, client, ZONE)  # type: ignore[arg-type]
    client.version = "v2"
    await async_ensure_gtfs(hass, client, ZONE)  # type: ignore[arg-type]
    assert client.fetch_calls == 2


async def test_total_failure_is_empty(hass: HomeAssistant) -> None:
    """No network and no cache degrades to an empty index, never raises."""
    client = _FakeGtfsClient(exc=TransAppConnectionError("down"))
    index = await async_ensure_gtfs(hass, client, "zone-without-cache")  # type: ignore[arg-type]
    assert index == GtfsIndex.empty()


async def test_memory_hit_skips_disk_and_network(hass: HomeAssistant) -> None:
    """A matching memory version returns without touching disk or network."""
    client = _FakeGtfsClient(version="v1", payload=COMMA_ZIP)
    first = await async_ensure_gtfs(hass, client, ZONE)  # type: ignore[arg-type]
    quiet = _FakeGtfsClient(version="v1", payload=COMMA_ZIP)
    second = await async_ensure_gtfs(hass, quiet, ZONE)  # type: ignore[arg-type]
    assert second is first
    assert quiet.fetch_calls == 0


async def test_fetch_failure_falls_back_to_stale_disk(
    hass: HomeAssistant,
) -> None:
    """A failed refresh serves the stale disk copy without raising."""
    from custom_components.red_regional.const import STORAGE_DIR

    client = _FakeGtfsClient(version="v1", payload=COMMA_ZIP)
    await async_ensure_gtfs(hass, client, ZONE)  # type: ignore[arg-type]
    gtfs_module._MEMORY.clear()
    failing = _FakeGtfsClient(version="v2", fetch_exc=TransAppConnectionError("down"))
    stale = await async_ensure_gtfs(hass, failing, ZONE)  # type: ignore[arg-type]
    assert stale.stops["P00001"].name == "Parada Uno"
    base = Path(hass.config.path(".storage", STORAGE_DIR))
    assert (base / f"gtfs_{ZONE}.version").read_text() == "v1"


async def test_corrupt_disk_falls_back_to_memory(hass: HomeAssistant) -> None:
    """An unreadable disk copy degrades to the memory index."""
    from custom_components.red_regional.const import STORAGE_DIR

    client = _FakeGtfsClient(version="v1", payload=COMMA_ZIP)
    await async_ensure_gtfs(hass, client, ZONE)  # type: ignore[arg-type]
    base = Path(hass.config.path(".storage", STORAGE_DIR))
    zip_path = base / f"gtfs_{ZONE}.zip"
    zip_path.unlink()
    zip_path.mkdir()
    failing = _FakeGtfsClient(version="v2", fetch_exc=TransAppConnectionError("down"))
    index = await async_ensure_gtfs(hass, failing, ZONE)  # type: ignore[arg-type]
    assert index.stops["P00001"].name == "Parada Uno"
