# Red Regional — Home Assistant integration

Live departures, service alerts, and bus positions for Chilean
[Red Regional](https://www.dtpr.gob.cl/) public transport (regional cities
outside Santiago), straight from the TransApp backend into Home Assistant.

> **Unofficial integration, no affiliation with MTT/DTPR.** The backend is
> reverse-engineered and may change without notice.

## What it does

Add a bus stop once, get a device with:

- **Next departure** — timestamp sensor with the full departure board
  (`route`, `destination`, `due_in_min`, `delay_min`, `realtime`, …).
- **Service alert** — binary sensor, on while alerts affect the stop.
- **Live buses** (opt-in) — one map-ready GPS tracker per bus in service.

Works in English and Spanish. Requires Home Assistant 2026.1 or newer.

## Install

Via HACS (recommended):

1. HACS → Integrations → ⋮ → Custom repositories → add this repo URL
   (category *Integration*).
2. Install “Red Regional”, restart Home Assistant.
3. Settings → Devices & Services → Add Integration → Red Regional, then pick
   your city and stop code (e.g. `P45068`).

Details and alternatives (manual install, NixOS flake):
[docs/installation.md](docs/installation.md).

## Documentation

- [Configuration](docs/configuration.md) — zones, stops, filters, options.
- [Entities](docs/entities.md) — sensors, attributes, trackers.
- [Dashboards](docs/dashboards.md) — Lovelace cards and TTS examples.
- [Services](docs/services.md) — `refresh`, `lookup_stop`, `get_vehicles`.
- [Troubleshooting](docs/troubleshooting.md) — off-hours, repairs, FAQ.

## Acknowledgments

The hard part — reverse-engineering the Red Regional app and mapping the
TransApp backend — was done by
[edwinroket/red-regional-api](https://github.com/edwinroket/red-regional-api).
This integration ports its API client to async (`aiohttp`) for Home Assistant
and builds the entities, flows, and caching around it.

## Development

```bash
nix develop            # HA 2026.9 / Python 3.14 + pytest + ruff
pytest tests/
ruff check . && ruff format --check .
nix build .#red-regional-ha
nix flake check
```

Implementation notes live in
[AGENTS.md](AGENTS.md); the behavior spec in
[.design/spec/spec-design-red-regional-ha.md](.design/spec/spec-design-red-regional-ha.md).
