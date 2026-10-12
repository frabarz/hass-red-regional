"""Unit tests for the TransApp async client."""

from __future__ import annotations

from typing import Any, cast

import pytest
from aiohttp import ClientConnectionError, ClientSession

from custom_components.red_regional.api import TransAppClient
from custom_components.red_regional.exceptions import (
    TransAppAuthError,
    TransAppConnectionError,
    TransAppRateLimitError,
)
from custom_components.red_regional.models import Zone

ZONE = "f083f24e-7fee-4fdc-9520-dbbdae877f07"
PHONE = "00000000-0000-4000-8000-000000000000"


class _FakeResponse:
    """Minimal async context manager mimicking aiohttp responses."""

    def __init__(self, status: int, payload: Any) -> None:
        """Store the canned status and JSON payload."""
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> _FakeResponse:
        """Enter the response context."""
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        """Exit the response context without suppressing errors."""
        return False

    async def json(self) -> Any:
        """Return the canned JSON payload."""
        return self._payload

    async def read(self) -> bytes:
        """Return the canned raw payload."""
        assert isinstance(self._payload, bytes)
        return self._payload


class _FakeSession:
    """Canned aiohttp session recording requests."""

    def __init__(
        self,
        status: int = 200,
        payload: Any = None,
        exc: Exception | None = None,
    ) -> None:
        """Store the canned outcome for the next request."""
        self._status = status
        self._payload = payload
        self._exc = exc
        self.calls: list[tuple[str, dict[str, str], Any]] = []

    def get(
        self, url: str, *, headers: dict[str, str], params: Any = None
    ) -> _FakeResponse:
        """Record the call and return the canned response or raise."""
        self.calls.append((url, headers, params))
        if self._exc is not None:
            raise self._exc
        return _FakeResponse(self._status, self._payload)


def _client(session: _FakeSession) -> tuple[TransAppClient, _FakeSession]:
    return TransAppClient(cast(ClientSession, session), PHONE), session


async def test_zones_parses_and_skips_invalid() -> None:
    """Zone list maps known fields and drops malformed entries."""
    session = _FakeSession(
        payload=[
            {
                "public_id": "uuid-1",
                "name": "concepcion",
                "public_name": "Gran Concepción",
            },
            {"name": "sin-uuid"},
            "junk",
        ]
    )
    client, _ = _client(session)
    zones = await client.async_get_zones()
    assert zones == [
        Zone(uuid="uuid-1", name="concepcion", public_name="Gran Concepción")
    ]
    url, headers, _ = session.calls[0]
    assert url.endswith("/zones")
    assert headers["Os-type"] == "Android"
    assert headers["App-Version"] == "2.5.1"
    assert headers["Accept"] == "application/json"


async def test_stop_info_sends_required_params() -> None:
    """stopInfo carries stopCode, mode=3, and the stable phoneId."""
    session = _FakeSession(payload={"predictions": []})
    client, _ = _client(session)
    await client.async_get_stop_info(ZONE, "P45068")
    url, _, params = session.calls[0]
    assert url.endswith(f"/{ZONE}/stopInfo")
    assert params == {"stopCode": "P45068", "mode": 3, "phoneId": PHONE}


async def test_machines_params_with_and_without_stop() -> None:
    """Machines scope by route/direction, optionally by stop."""
    session = _FakeSession(payload={"machines": []})
    client, _ = _client(session)
    await client.async_get_machines(ZONE, "44B", "I")
    await client.async_get_machines(ZONE, "44B", "I", stop_code="P45068")
    assert session.calls[0][2] == {"route": "44B", "direction": "I"}
    assert session.calls[1][2] == {
        "route": "44B",
        "direction": "I",
        "stopCode": "P45068",
    }


async def test_gtfs_version_path() -> None:
    """GTFS version hits the versioned feed endpoint."""
    session = _FakeSession(payload={"version": "abc"})
    client, _ = _client(session)
    assert await client.async_get_gtfs_version(ZONE) == {"version": "abc"}
    assert session.calls[0][0].endswith(f"/{ZONE}/gtfs/version/3")


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_rejection(status: int) -> None:
    """401/403 surfaces as an auth error for reauth handling."""
    client, _ = _client(_FakeSession(status=status))
    with pytest.raises(TransAppAuthError):
        await client.async_get_zones()


async def test_rate_limit() -> None:
    """429 surfaces as a rate-limit error for backoff handling."""
    client, _ = _client(_FakeSession(status=429))
    with pytest.raises(TransAppRateLimitError):
        await client.async_get_zones()


async def test_server_error() -> None:
    """Unexpected statuses surface as connection errors."""
    client, _ = _client(_FakeSession(status=500))
    with pytest.raises(TransAppConnectionError):
        await client.async_get_zones()


async def test_network_failure() -> None:
    """Transport failures surface as connection errors."""
    client, _ = _client(_FakeSession(exc=ClientConnectionError("down")))
    with pytest.raises(TransAppConnectionError):
        await client.async_get_zones()


async def test_fetch_gtfs_returns_bytes() -> None:
    """GTFS downloads return raw ZIP bytes."""
    client, session = _client(_FakeSession(payload=b"PK fake"))
    assert await client.async_fetch_gtfs(ZONE) == b"PK fake"
    url, _, _ = session.calls[0]
    assert url.endswith(f"/{ZONE}/gtfs/download/3")


async def test_fetch_gtfs_rejection() -> None:
    """GTFS download rejections map to typed errors."""
    client, _ = _client(_FakeSession(status=401))
    with pytest.raises(TransAppAuthError):
        await client.async_fetch_gtfs(ZONE)


async def test_fetch_gtfs_transport_failure() -> None:
    """GTFS transport failures surface as connection errors."""
    client, _ = _client(_FakeSession(exc=ClientConnectionError("down")))
    with pytest.raises(TransAppConnectionError):
        await client.async_fetch_gtfs(ZONE)
