"""Async client for the unofficial TransApp backend.

Endpoint and parameter mapping ported from
https://github.com/edwinroket/red-regional-api, which reverse-engineered the
Red Regional app; transport rewritten here on ``aiohttp`` for Home Assistant.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import API_BASE, APP_VERSION, OS_TYPE, REQUEST_TIMEOUT_S
from .exceptions import (
    TransAppAuthError,
    TransAppConnectionError,
    TransAppRateLimitError,
)
from .models import Zone

_LOGGER = logging.getLogger(__name__)


class TransAppClient:
    """Async HTTP client for phone.dtpr.transapp.cl.

    Transport only: every method returns decoded JSON and raises a typed
    error on failure. Payload normalization lives in ``parse.py``.
    """

    def __init__(self, session: ClientSession, phone_id: str) -> None:
        """Store the shared session and the stable per-entry phone id."""
        self._session = session
        self._phone_id = phone_id

    @property
    def _headers(self) -> dict[str, str]:
        """Return the mandatory headers for every request."""
        return {
            "Os-type": OS_TYPE,
            "App-Version": APP_VERSION,
            "Accept": "application/json",
        }

    def _check_status(self, path: str, status: int) -> None:
        """Raise the typed error for a non-200 response status."""
        if status in (401, 403):
            raise TransAppAuthError(f"Backend rejected request to {path}")
        if status == 429:
            raise TransAppRateLimitError(f"Backend rate-limited request to {path}")
        if status != 200:
            raise TransAppConnectionError(f"Unexpected status {status} for {path}")

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET one endpoint and return its decoded JSON body."""
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_S):
                async with self._session.get(
                    f"{API_BASE}{path}", headers=self._headers, params=params
                ) as response:
                    self._check_status(path, response.status)
                    return await response.json()
        except (ClientError, TimeoutError) as err:
            raise TransAppConnectionError(f"Request to {path} failed: {err}") from err

    async def async_get_zones(self) -> list[Zone]:
        """Return all supported cities from GET /zones."""
        raw = await self._get_json("/zones")
        zones: list[Zone] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict):
                continue
            uuid = item.get("public_id")
            name = item.get("name")
            if not uuid or not name:
                continue
            zones.append(
                Zone(uuid=uuid, name=name, public_name=item.get("public_name"))
            )
        return zones

    async def async_get_stop_info(self, zone_uuid: str, stop_code: str) -> Any:
        """Return raw stopInfo predictions + alerts for one stop."""
        return await self._get_json(
            f"/{zone_uuid}/stopInfo",
            {
                "stopCode": stop_code,
                "mode": 3,
                "phoneId": self._phone_id,
            },
        )

    async def async_get_machines(
        self,
        zone_uuid: str,
        route: str,
        direction: str,
        stop_code: str | None = None,
    ) -> Any:
        """Return raw live GPS telemetry for one route/direction."""
        params: dict[str, Any] = {"route": route, "direction": direction}
        if stop_code:
            params["stopCode"] = stop_code
        return await self._get_json(f"/{zone_uuid}/synoptic/machines", params)

    async def async_get_gtfs_version(self, zone_uuid: str) -> Any:
        """Return version metadata for the zone GTFS feed."""
        return await self._get_json(f"/{zone_uuid}/gtfs/version/3")

    async def async_fetch_gtfs(self, zone_uuid: str) -> bytes:
        """Download the zone GTFS ZIP bytes for disk caching elsewhere."""
        path = f"/{zone_uuid}/gtfs/download/3"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_S * 6):
                async with self._session.get(
                    f"{API_BASE}{path}", headers=self._headers
                ) as response:
                    self._check_status(path, response.status)
                    return await response.read()
        except (ClientError, TimeoutError) as err:
            raise TransAppConnectionError(f"Request to {path} failed: {err}") from err
