"""Shared fixtures (full coordinator/API mocks per spec follow)."""

from __future__ import annotations

import pytest
from homeassistant.helpers import device_registry as dr

from custom_components.red_regional.gtfs import GtfsIndex


def device_by_identifier(
    registry: dr.DeviceRegistry, identifier: tuple[str, str], entry_id: str
) -> dr.DeviceEntry | None:
    """Look up a device by identifier across HA versions.

    HA 2026.1 exposes ``DeviceRegistry.async_get_device`` (identifier sets);
    later releases renamed it to ``async_get_device_by_identifier`` (single
    identifier plus owning entry id).
    """
    getter = getattr(registry, "async_get_device_by_identifier", None)
    if getter is not None:
        return getter(identifier, entry_id)
    return registry.async_get_device({identifier})


@pytest.fixture(autouse=True)
def _offline_gtfs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep GTFS enrichment offline unless a test opts in explicitly."""

    async def _empty(hass: object, client: object, zone_uuid: str) -> GtfsIndex:
        return GtfsIndex.empty()

    monkeypatch.setattr(
        "custom_components.red_regional.coordinator.async_ensure_gtfs", _empty
    )
    monkeypatch.setattr(
        "custom_components.red_regional.config_flow.async_ensure_gtfs", _empty
    )
