"""Shared fixtures (full coordinator/API mocks per spec follow)."""

from __future__ import annotations

import pytest

from custom_components.red_regional.gtfs import GtfsIndex


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
