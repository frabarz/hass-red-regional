---
title: Red Regional Home Assistant Integration
version: 1.0
date_created: 2026-10-11
last_updated: 2026-10-12
owner: Red Regional HA Contributors
tags: [design, home-assistant, public-transport, chile, red-regional, gtfs, sensor]
---

# Introduction

This specification defines a Home Assistant (HA) custom integration (HACS-distributable, core-track quality) that exposes Chilean Red Regional public-transport data (DTPR / TransApp backend) as HA entities. Data access reuses the concepts of the unofficial Python library `red-regional-api` (reverse-engineered from APK `cl.gob.mtt.dtpr.redregional` v2.7.0, Flutter). The goal is feature parity with best-in-class HA public-transport integrations (Swiss, HSL/Digitransit, SL/Trafiklab, Entur, Rejseplanen, NMBS/iRail, GTFS-RT forks, `openpublictransport`).

# 1. Purpose & Scope

## Purpose

Define requirements, constraints, interfaces, and acceptance criteria for a `red_regional` HA integration that provides:

1. Real-time arrival predictions per bus stop (`stopInfo`).
2. Service alerts / disruptions per stop.
3. Live bus GPS positions per route (`synoptic/machines`) on the HA map.
4. Static stop/route metadata from GTFS for friendly names, autocomplete, and diagnostics.
5. Multi-city (multi-zone) support via `GET /zones`.

## Scope

- **In scope:** Config flow (UI), options/reconfigure flow, `sensor` + `binary_sensor` + `device_tracker` platforms, `DataUpdateCoordinator`-based polling, GTFS-static cache, Spanish + English translations, diagnostics, repairs, Lovelace examples, HACS distribution, quality-scale Bronze minimum (target Silver/Gold).
- **Out of scope (see OOS):** A-to-B trip planning (backend does not expose it), ticket payment, push/FCM, map tile rendering.
- **Audience:** Implementers (Python/HA developers) and AI code generators. Assumes HA Core 2024.6+ (config entries, subentries if used, `DataUpdateCoordinator`, `device_tracker`, quality-scale rules) and familiarity with async Python.
- **Assumptions:** Backend base URL `https://phone.dtpr.transapp.cl/v7/phone` remains reachable; required headers `Os-type: Android`, `App-Version: 2.5.1`, `Accept: application/json` remain valid (bump version if rejected); zone UUIDs are stable; users know their stop code (e.g. `P45068`) or can pick from GTFS/autocomplete.

# 2. Definitions

| Term | Definition |
|---|---|
| Red Regional | Chilean Ministry of Transport (MTT/DTPR) regional bus system outside Santiago. Mobile app package `cl.gob.mtt.dtpr.redregional`. |
| TransApp backend | Unofficial name for `phone.dtpr.transapp.cl` HTTP API used by the app. No public docs. |
| Zone | A city/operating area identified by a UUID (`public_id`). Example: Concepcion `f083f24e-7fee-4fdc-9520-dbbdae877f07`, Talca `50cde66c-2b67-4702-afa8-1f190249d9b8`, Temuco `c28e2682-b083-41ba-8827-5caac8b86181`. All operational endpoints are scoped `/{zone_uuid}/...` except `GET /zones`. |
| Stop code | User-facing stop identifier (e.g. `P45068`, `PA151`). Query param `stopCode`. Not the same as GTFS `stop_id` numeric key; mapping lives in GTFS `stop.csv` (`stop_code` column). |
| stopInfo | `GET /{zone}/stopInfo?stopCode=&mode=3&phoneId=` — arrival predictions + alerts for one stop. |
| Synoptic machines | `GET /{zone}/synoptic/machines?route=&direction=I|R[&stopCode=]` — live GPS telemetry for buses in service on one route/direction. `I` = Ida (outbound), `R` = Retorno (return). |
| GTFS-static | `GET /{zone}/gtfs/version/3` + `GET /{zone}/gtfs/download/3` — ZIP containing `stop.csv`, `route.csv`, `shape.csv`, `calendar.csv` (singular names, non-standard vs `stops.txt`). |
| Payment points | `GET /{zone}/payment-points/` — card recharge locations/totems. `GET /{zone}/payment-points/hash` = cache-validation hash (not in current SDK). |
| Board | Stop-centric departure list (all routes at one stop). Contrast with Connection (A-to-B trip). V1 of this integration is board-only. |
| Coordinator | HA `DataUpdateCoordinator[T]` — shared async poller per config/subentry. |
| HACS | Home Assistant Community Store — distribution channel for custom integrations. |

# 3. Requirements, Constraints & Guidelines

## Functional requirements

- **REQ-001**: The integration SHALL support UI setup via `ConfigFlow` (no YAML for new installs). First step selects zone (city) from live `GET /zones` list with names + UUIDs, cached for offline fallback.
- **REQ-002**: The integration SHALL support adding one or more stops per zone. Pattern: single config entry per zone (hub) + stop subentries (HA 2025.2+ `Subentries`) OR multiple config entries (one per stop). Preferred: hub + subentries to share polling. At minimum multiple entries MUST be supported.
- **REQ-003**: Each stop device SHALL expose a `sensor.next_departure` whose state is a timezone-aware `timestamp` (`device_class: timestamp`) of the soonest predicted arrival. Attributes SHALL include full departures list (see §4).
- **REQ-004**: Each departure entry SHALL include where available: `route` (short name, e.g. `44B`), `destination/headsign`, `scheduled_at`, `expected_at`, `due_in_min`, `delay_min`, `realtime` (bool), `direction` (I/R), `vehicle_id/plate`, `cancelled` (bool), `occupancy` (if backend provides, else `null`).
- **REQ-005**: Each stop device SHALL expose a `binary_sensor.service_alert` (`True` = active alert/disruption reported by `stopInfo` for that stop). Attributes: `alerts[]` with `title`, `description`, `route` (if scoped), `valid_from/until`.
- **REQ-006**: Each tracked route (optional, opt-in per stop or per zone) SHALL expose live bus positions as `device_tracker` entities (one per vehicle `plate`). Attributes: `latitude`, `longitude`, `speed_kmh`, `route`, `direction`, `stop_code` (if filtered), `last_update`. Entities MUST support `Show on map` and HA map card.
- **REQ-007**: The integration SHALL support per-stop filters in OptionsFlow: `routes_whitelist[]` (e.g. only `44B`), `destinations[]`, `max_departures` (1–15, default 5), `look_ahead_min` (default 120), `walk_offset_min` (hide departures sooner than walk time; default 0).
- **REQ-008**: The integration SHALL provide a `sensor.departures_count` OR include `departure_count` attribute (decide one; recommended: attribute on next_departure + optional disabled-by-default count sensor) and a human-friendly `departures_text` attribute (e.g. `44B in 4 min, 63B in 9 min`) for TTS/templates.
- **REQ-009**: The integration SHALL cache GTFS-static ZIP per zone on disk (`config/.storage/red_regional/gtfs_{zone}.zip` + unpacked SQLite or parsed CSV) and use it for stop-name lookup, route color/long name, and config-flow autocomplete. MUST check `GET /{zone}/gtfs/version/3` before re-downloading.
- **REQ-010**: The integration SHALL expose services/actions: `red_regional.refresh` (force coordinator refresh for a device/entry), `red_regional.lookup_stop` (name/code -> candidates with zone, code, name, lat/lon), and optionally `red_regional.get_vehicles` (return synoptic machines for a route). Services MUST be typed with `voluptuous` schemas and translated.
- **REQ-011**: The integration SHALL set `unique_id` stably: stop sensor `f"{zone_uuid}_{stop_code}_next"`, alert `f"{zone_uuid}_{stop_code}_alert"`, vehicle tracker `f"{zone_uuid}_{plate}"`. `DeviceInfo.identifiers = {(DOMAIN, f"{zone_uuid}_{stop_code}")}`, with `manufacturer: "DTPR / Red Regional"`, `model: zone city name`, `sw_version: App-Version in use`.
- **REQ-012**: The integration SHALL handle off-hours gracefully: when `services == []` (no buses, e.g. Route 44B outside 06:30–23:00 weekdays), sensors state = `unknown` (not `unavailable`, not exception), `departure_count = 0`, alert sensor retains last known or `off`.
- **REQ-013**: OptionsFlow SHALL allow changing `scan_interval` (see CON-002), filters, and enabling/disabling vehicle tracking without re-creating the entry. ReconfigureFlow SHALL allow changing zone/stop code.
- **REQ-014**: Payment-points data MAY be exposed in V2 as a `sensor` (nearest recharge points) or via `lookup` service only. V1 MAY omit; if omitted, document as roadmap.

## Non-functional / quality requirements

- **REQ-020**: All I/O SHALL be async via `aiohttp` (HA shared session via `async_get_clientsession`). Blocking `requests` from the reference library SHALL NOT be used in HA code; port logic to async.
- **REQ-021**: All polling SHALL go through `DataUpdateCoordinator` (one per zone-hub, shared by its stops; or one per stop if no hub). Coordinators MUST use `update_interval` from options, handle `ConfigEntryAuthFailed` / `UpdateFailed`, keep-last-known on transient errors, and support disable-polling + `homeassistant.update_entity`.
- **REQ-022**: Code SHALL be fully typed (`mypy`-clean), `ruff`-clean, use `async_forward_entry_setups`, never block the event loop, handle timezones with `zoneinfo` / HA `dt_util` (America/Santiago default, per-zone aware).
- **REQ-023**: Translations SHALL include at minimum `en` + `es` (`strings.json` + `translations/en.json` + `translations/es.json`): config flow, options flow, entity names (`translation_key`), states, services, repairs, options.
- **REQ-024**: Diagnostics SHALL be implemented (`diagnostics.py`, redacting `phoneId`, lat/lon precision optionally, plates optionally) and `quality_scale.yaml` targeting Silver minimum.
- **REQ-025**: Repairs SHALL raise issues for: backend unreachable/auth-rejected (headers outdated), invalid stop code, GTFS download failure, rate-limit (HTTP 429). Provide fix flow (reconfigure / retry / update App-Version constant).

## Constraints

- **CON-001**: No API key/OAuth. Every request MUST send headers `Os-type: Android`, `App-Version: <PINNED>` (initial `2.5.1`, bump to `2.7.0`-compatible if backend rejects), `Accept: application/json`. `stopInfo` MUST include `phoneId=<uuid4>` (generate once per config entry via `uuid.uuid4()`, persist, reuse; do not regenerate per request).
- **CON-002**: Default polling interval 60 s for `stopInfo` boards; 30 s minimum allowed; 30–60 s for vehicle positions. MUST NOT default below 30 s (unofficial backend, unknown rate limits). Shared coordinator MUST batch stops (one HTTP request per stop per tick; do not fan out per route).
- **CON-003**: `mode=3` on `stopInfo` is a hardcoded magic value from reverse engineering; MUST be sent as `mode=3` unless backend analysis proves otherwise. `direction` only accepts `I`/`R`.
- **CON-004**: Backend is unofficial and may change without notice. Code MUST centralize base URL + headers + `App-Version` in `const.py` (`API_BASE`, `APP_VERSION`, `OS_TYPE`) so a single-constant bump fixes rejections. MUST NOT hardcode zone UUIDs except as fallback cache; MUST prefer live `GET /zones`.
- **CON-005**: GTFS filenames are non-standard (`stop.csv`/`route.csv` singular, `utf-8-sig` encoding). Parser MUST handle both singular and standard plural (`stops.txt`/`routes.txt`) names and both encodings.
- **CON-006**: New integrations MUST NOT use YAML setup (HA core rule since 2023+). Legacy YAML patterns (`scan_interval` in YAML, `Throttle`-only) are forbidden as primary mechanism.

## Guidelines

- **GUD-001**: Follow modern reference UX: `ha_swiss_transport` (board + connection duality, occupancy, alerts banner), `trollp/SL` (3-sensor split: next/count/status), `rejseplanen` (6-sensor HA-standard, no extra attrs), `openpublictransport` (disabled-by-default calendar/event/camera/stats). For V1 prefer: enabled `sensor.next_departure` + `binary_sensor.alert`; disabled-by-default `sensor.count`, `sensor.next_N_text`, `device_tracker.*`.
- **GUD-002**: State choice: use `timestamp` for next departure (HA-native, history graphs, templates via `relative_time`). Provide `due_in_min` per departure in attributes for countdown cards. Do not use human strings (`"Nu/8 min"`) as state.
- **GUD-003**: Distinguish `scheduled` vs `realtime` explicitly (`realtime: true/false`, `delay_min`). If backend returns only one time field, set `realtime=true` and document assumption; add `attribution: "Datos: DTPR Red Regional (no oficial)"`.
- **GUD-004**: Provide bundled Lovelace examples in README: entities card, markdown/__departures_text__, map card for trackers, `auto-entities` + `button-card` for cancelled/delayed styling.
- **GUD-005**: Log sparingly (no per-poll info logs); debug-log raw payload shapes once per version for reverse-engineering; include payload-shape assertion with graceful degradation (missing keys -> `None`, not crash).

## Patterns to follow

- **PAT-001**: Hub + `DataUpdateCoordinator[List[StopData]]` per zone; `CoordinatorEntity` subclasses; `async_setup_entry` forwards `["sensor", "binary_sensor", "device_tracker"]`.
- **PAT-002**: Config flow: `zone select (async zones fetch w/ fallback) -> stop search (text + autocomplete from GTFS cache + live validation via stopInfo) -> filters -> create`. Validate stop by calling `stopInfo`; reject empty `services` with warning (allow creation, surface `unknown` + repair hint, since off-hours also yield empty).
- **PAT-003**: GTFS cache: `version check -> conditional download (stream, 8192 chunks) -> parse stop.csv/route.csv (+ shape/calendar if present) -> SQLite or JSON index -> stop-code -> name/latlon/route-color lookup`.

## Out of scope

- **OOS-001**: A-to-B trip planning / routing (backend exposes no endpoint; do not fake with GTFS-static alone in V1).
- **OOS-002**: Fare payment, SUBE/bip! card balance, recharge transactions (only static recharge-point locations MAY be listed).
- **OOS-003**: Push notifications via Firebase Cloud Messaging; V1 is poll-only.
- **OOS-004**: Custom map tiles / Mapbox rendering; use HA native map.
- **OOS-005**: Multi-modal (metro/train/ferry) — Red Regional zones are bus-only; `transport_mode` fixed to `bus` unless GTFS proves otherwise.

# 4. Interfaces & Data Contracts

## 4.1 Upstream API (TransApp, unofficial)

Base: `https://phone.dtpr.transapp.cl/v7/phone`

| Method | Endpoint | HA usage |
|---|---|---|
| `GET /zones` | list cities | config flow zone picker; `[{public_id/uuid, name, ...}]` |
| `GET /{zone}/stopInfo?stopCode={CODE}&mode=3&phoneId={UUID}` | predictions + alerts | coordinator poll per stop |
| `GET /{zone}/synoptic/machines?route={R}&direction={I\|R}[&stopCode={C}]` | live GPS | vehicle tracker poll per watched route |
| `GET /{zone}/gtfs/version/3` | version meta | cache invalidation |
| `GET /{zone}/gtfs/download/3` | ZIP | static metadata |
| `GET /{zone}/payment-points/` | recharge sites | V2 / service |
| `GET /zones/search?lat=&lon=` (documented, not in SDK) | nearby zones | optional V2 nearby-stop |

Headers (all requests): `Os-type: Android`, `App-Version: 2.5.1`, `Accept: application/json`.

### stopInfo (inferred shape — MUST validate live and adapt)

```json
{
  "services": [
    {"name": "44B", "arrival_time": 5, "distance": 1200, "plate": "ABCD12", "direction": "I", "alert": null}
  ],
  "alerts": [{"title": "...", "description": "...", "routes": ["44B"]}],
  "stop": {"code": "P45068", "name": "Plaza Tribunales de Justicia"}
}
```

> The reference repo contains no raw JSON sample; field names above are illustrative. Implementer MUST capture real payloads (debug log + diagnostics fixture) and map: service name -> `route`, arrival minutes or epoch -> `expected_at` + `due_in_min`, distance/plate -> `vehicle_id`, alert/event -> `binary_sensor`.

Empty/off-hours: `{"services": []}`.

### synoptic/machines (inferred shape)

```json
{
  "machines": [
    {"license_plate": "ABCD12", "latitude": -36.82, "longitude": -73.05, "speed": 32, "route": "44B", "direction": "I"}
  ]
}
```

### GTFS ZIP contents

`stop.csv` (`stop_id, stop_name, stop_lat, stop_lon, stop_code`), `route.csv` (`route_id, route_short_name, route_long_name, route_color`), `shape.csv`, `calendar.csv`. Encoding `utf-8-sig`.

## 4.2 HA entities

### Device per stop

`identifiers: {(red_regional, "{zone}_{stop_code}")}`, `name: "{stop_name} ({stop_code})"`, `manufacturer: "DTPR / Red Regional"`, `model: "{city}"`.

| Platform | Entity | State | Key attributes |
|---|---|---|---|
| `sensor` | `sensor.{slug}_proxima_llegada` (`translation_key: next_departure`, `device_class: timestamp`) | soonest `expected_at` or `unknown` | `stop_code`, `stop_name`, `zone/city`, `departure_count`, `departures[]` (ordered by `expected_at`, max `max_departures`), `departures_text`, `attribution`, `last_update` |
| `binary_sensor` | `binary_sensor.{slug}_alerta_servicio` (`translation_key: service_alert`) | `on` if `alerts[]` non-empty | `alerts[]: {title, description, routes, valid_from, valid_until}` |
| `sensor` (disabled by default) | `sensor.{slug}_salidas` (count) | `departure_count` int | same source |
| `device_tracker` (per vehicle, only if tracking enabled) | `device_tracker.{plate_lower}` | `home`/`not_home` n/a — use GPS state | `latitude`, `longitude`, `speed_kmh`, `route`, `direction`, `plate` |

`departures[N]` schema:

```python
{
    "route": str,  # "44B"
    "destination": str | None,  # headsign / long name from GTFS
    "scheduled_at": str | None,  # ISO8601 or None
    "expected_at": str,  # ISO8601, timezone-aware
    "due_in_min": int,  # max(0, round((expected-now)/60) - walk_offset clamp)
    "delay_min": int | None,
    "realtime": bool,
    "direction": str | None,  # "I" | "R"
    "vehicle_id": str | None,  # plate
    "route_color": str | None,  # "#EC6907" from GTFS
    "cancelled": bool,
    "occupancy": str | None,
}
```

Filtering semantics: `routes_whitelist` exact match (case-insensitive, strip spaces); `destinations[]` substring match; `walk_offset_min` hides `due_in_min < offset`; `look_ahead_min` drops later; then sort + truncate to `max_departures`.

## 4.3 Config / options schema

```yaml
# Conceptuel (UI only, no YAML)
zone_uuid: uuid-string            # required, from /zones
zone_name: string                 # cached display name
stops:
  - stop_code: "P45068"           # required, validated via stopInfo
    name_override: string | null
    routes_whitelist: [string]    # default []
    destinations: [string]        # default []
    max_departures: 5             # 1..15
    look_ahead_min: 120           # 15..360
    walk_offset_min: 0            # 0..30
track_vehicles: false             # per stop or per zone
tracked_routes: ["44B"]           # required if track_vehicles
scan_interval_s: 60               # 30..600
```

`phoneId`: one UUIDv4 per config entry, generated at setup, stored, reused.

## 4.4 Services

- `red_regional.refresh`: `{config_entry_id | device_id}` -> force coordinator refresh.
- `red_regional.lookup_stop`: `{zone_uuid, query}` -> `{candidates: [{stop_code, stop_name, lat, lon}]}` (GTFS cache first, live fallback).
- `red_regional.get_vehicles` (optional V1): `{zone_uuid, route, direction}` -> machines list.

# 5. Acceptance Criteria

- **AC-001**: Given a valid zone + stop code (e.g. Concepción / `P45068`) during service hours, When the entry is set up, Then `sensor.*_proxima_llegada` state is a valid future timestamp and `departures[]` is non-empty with `route`, `expected_at`, `due_in_min` present.
- **AC-002**: Given off-hours (empty `services`), When coordinator updates, Then sensors stay `unknown` (count 0), no exception, no `unavailable` flapping, log at most debug.
- **AC-003**: Given an invalid stop code, When config flow validates, Then user sees a translatable error and entry is not created; existing entry with stop removed upstream becomes `unknown` + repair issue (not crash).
- **AC-004**: Given `routes_whitelist: ["44B"]`, When departures include other routes, Then only `44B` appears in state/attributes.
- **AC-005**: Given backend returns alerts, When coordinator updates, Then `binary_sensor.*_alerta` is `on` with `alerts[]` populated; Given no alerts, Then `off`.
- **AC-006**: Given vehicle tracking enabled for route `44B/I`, When buses are in service, Then one `device_tracker` per plate appears with valid lat/lon and shows on HA map; When none in service, Then zero trackers (no orphans after cleanup).
- **AC-007**: Given `walk_offset_min: 5`, When a bus is due in 3 min, Then it is hidden from state/attributes.
- **AC-008**: Given default options, When running 10 min, Then HTTP request rate is ~1 req/stop/min (coordinator) + ~1 req/route/min (vehicles) and no 429; on 429/5xx, backoff keeps last-known and logs warning once (not per tick).
- **AC-009**: Given HA restart, When entries reload, Then `unique_id`s are stable, GTFS cache is reused (no re-download if version unchanged), `phoneId` is reused.
- **AC-010**: Given `hassfest` + `pytest-homeassistant-custom-component`, When CI runs, Then manifest, translations, diagnostics, and quality-scale Bronze checks pass.
- **AC-011**: Given Spanish locale, When UI is rendered, Then all config/options/entity strings appear in Spanish; English fallback exists.
- **AC-012**: Given diagnostics download, When inspected, Then no `phoneId` / precise home coords leak beyond stop/vehicle data already public, plates optionally masked per option.

# 6. Test Automation Strategy

- **Test Levels**: Unit (parsers: stopInfo -> departures, GTFS CSV variants, filters/offset/window, timestamp/tz math), Integration (coordinator with mocked `aiohttp` fixtures incl. empty/off-hours/429/alert shapes; config flow validation; options flow), End-to-End (real backend smoke test, manual, off-hours + peak; Lovelace cards render).
- **Frameworks**: `pytest`, `pytest-asyncio`, `pytest-homeassistant-custom-component`, `aresponses`/`aioresponses` for HTTP mocks, `ruff`, `mypy`. Fixtures: capture real `stopInfo` + `machines` + `zones` + GTFS ZIP samples (store under `tests/fixtures/`, redact `phoneId`).
- **Test Data Management**: Talca `PA151` + Concepción `P45068` + Route `44B/I` as canonical fixtures; include empty-services, alerts-present, machines-empty, GTFS singular-vs-plural filenames, `utf-8-sig` BOM cases.
- **CI/CD Integration**: GitHub Actions: lint (`ruff`), typecheck, `hassfest`, tests on HA stable + beta; HACS `hacs.json` validation.
- **Coverage Requirements**: Minimum 85% lines for `coordinator.py`, `sensor.py`, parsers; 100% of filter/offset branches.
- **Performance Testing**: Assert request budget (AC-008); soak test 1 h with 3 stops, assert no memory/request blowup; GTFS download streamed (no full-memory ZIP).

# 7. Rationale & Context

- Why board-first (not A-to-B): backend has no trip-planning endpoint (`findings.md` maps it Not available). All comparable integrations offer board mode; A-to-B (Swiss, NMBS, DB) requires connections API we do not have. GTFS-static-only routing is out of scope for V1.
- Why `timestamp` state + rich attributes: matches HA-native history + `relative_time` templates; avoids legacy minutes-state/template-unfriendly flat attrs (Entur) and single-departure limits (Rejseplanen). `departures_text` preserves TTS/simple-card ergonomics.
- Why hub + subentries: shares one coordinator per zone, respects unknown rate limits, mirrors `openpublictransport`/BVG hub pattern; fallback to multi-entry keeps compatibility with HA <2025.2.
- Why async port (not reuse `requests` SDK): HA forbids blocking I/O; reference SDK has no timeouts/retries/typing. Port pure parsing logic; replace transport with `aiohttp` + HA session.
- Why GTFS cache + version check: stop codes are opaque (`P45068`); friendly names, colors, autocomplete require static feed. Non-standard CSV names + BOM require tolerant parser (lesson from `gtfs/import_gtfs_sqlite.py` only handling 2 files).
- Why 30–60 s polling: `findings.md` recommends it; aligns with SL (30 s), Entur (45 s min), Swiss (90 s), BVG (90 s). Under 30 s risks unofficial-backend throttling.
- Why vehicle trackers opt-in: per-route polling multiplies load; default-off avoids quota + entity spam (lesson: NMBS liveboards disabled-by-default).

# 8. Dependencies & External Integrations

## External Systems

- **EXT-001**: TransApp/DTPR backend (`phone.dtpr.transapp.cl`) — REST/JSON over HTTPS; unofficial, no SLA, may break on app update. Centralize version constant + fallback zone cache.

## Third-Party Services

- **SVC-001**: None required. No Mapbox/Firebase keys needed (maps via HA native; analytics/crashlytics not used).

## Infrastructure Dependencies

- **INF-001**: Home Assistant 2024.6+ with HACS (for distribution); file-system cache dir for GTFS ZIP/SQLite; internet egress to backend.

## Data Dependencies

- **DAT-001**: `GET /zones` — JSON list of cities/UUIDs; fetched at setup + weekly refresh; fallback to pinned UUIDs (Concepción/Talca/Temuco) if offline.
- **DAT-002**: `stopInfo` per stop per tick — JSON predictions + alerts; 30–600 s frequency.
- **DAT-003**: `synoptic/machines` per watched route per tick — JSON GPS; only when tracking enabled.
- **DAT-004**: GTFS ZIP per zone — CSV static feed; refreshed only when `version/3` changes.
- **DAT-005**: `payment-points/` — JSON recharge sites; V2 only.

## Technology Platform Dependencies

- **PLT-001**: Python 3.12+ async (`aiohttp` via HA session); HA `DataUpdateCoordinator`, `device_tracker`, `binary_sensor`, `sensor` platforms; `voluptuous` schemas; `zoneinfo`.
- **PLT-002**: Reference library `red-regional-api` (MIT/unknown license — verify) as *logic reference only*, not runtime dependency.

## Compliance Dependencies

- **COM-001**: Unofficial API — MUST disclose in README + attribution ("Integración no oficial, sin afiliación con MTT/DTPR"), respect fair use (default intervals, no scraping bursts), handle backend changes gracefully. Verify reference-repo license before copying code.

# 9. Examples & Edge Cases

```python
# Example: minimal setup (Concepción, stop P45068, only 44B, with walk offset)
# Config entry (conceptual):
{
    "zone_uuid": "f083f24e-7fee-4fdc-9520-dbbdae877f07",
    "zone_name": "Concepción",
    "stop_code": "P45068",
    "routes_whitelist": ["44B"],
    "max_departures": 5,
    "walk_offset_min": 2,
    "track_vehicles": True,
    "tracked_routes": [{"route": "44B", "direction": "I"}],
    "scan_interval_s": 60,
}

# Resulting sensor attributes:
{
    "state": "2026-03-15T08:04:00-03:00",  # device_class timestamp
    "departure_count": 2,
    "departures": [
        {
            "route": "44B",
            "destination": "Hualpencillo",
            "expected_at": "2026-03-15T08:04:00-03:00",
            "due_in_min": 4,
            "delay_min": 1,
            "realtime": True,
            "direction": "I",
            "vehicle_id": "ABCD12",
            "route_color": "#EC6907",
            "cancelled": False,
            "occupancy": None,
        },
        {
            "route": "44B",
            "destination": "Hualpencillo",
            "expected_at": "2026-03-15T08:19:00-03:00",
            "due_in_min": 19,
            "delay_min": 0,
            "realtime": True,
            "direction": "I",
            "vehicle_id": None,
            "route_color": "#EC6907",
            "cancelled": False,
            "occupancy": None,
        },
    ],
    "departures_text": "44B en 4 min, 44B en 19 min",
    "stop_name": "Plaza Tribunales de Justicia",
}
# Lovelace: entities + markdown departures_text + map (device_trackers)
```

Edge cases:

1. Off-hours empty `services` -> `unknown`, count 0, no crash (Route 44B Sun before 07:30).
2. Backend bumps `App-Version` enforcement (2.5.1 rejected) -> repair issue "Actualizar versión de app", single-constant bump.
3. Zone UUID missing from pinned list (e.g. Chillán) -> live `/zones` covers; fallback cache prevents setup blockage.
4. `stop.csv` vs `stops.txt`, BOM vs plain UTF-8 -> parser tries both.
5. Arrival field is epoch seconds vs minutes-vs ISO string -> parser probes all three, normalizes to tz-aware ISO.
6. Duplicate plates across directions I/R -> tracker `unique_id` includes direction if needed (`{zone}_{plate}_{direction}`).
7. Stop renamed in GTFS but code stable -> `name_override` option wins; device rename does not change `unique_id`.
8. 429/503 -> exponential backoff (60 s -> 5 min -> 30 min max), keep-last-known, repair on sustained failure.

# 10. Validation Criteria

- [ ] Config flow creates working entry for Talca/Temuco/Concepción with live validation; zone list loads from `/zones` with pinned fallback.
- [ ] `sensor.next_departure` + `binary_sensor.alert` appear with correct `unique_id`/`DeviceInfo`/translations (en+es).
- [ ] Filters (`routes_whitelist`, `walk_offset`, `look_ahead`, `max_departures`) behave per §4.2 (unit-tested).
- [ ] Off-hours/empty, invalid-stop, 429/5xx, GTFS-failure paths produce `unknown` + repairs, never traceback in UI.
- [ ] Vehicle tracking opt-in yields map-plottable trackers; opt-out yields none.
- [ ] GTFS version-gated caching works; parser handles singular/plural + BOM.
- [ ] Polling budget respected (AC-008); `App-Version`/`phoneId`/headers per CON-001/CON-004.
- [ ] `hassfest`, `ruff`, `mypy`, `pytest` green; diagnostics redaction verified; Bronze quality-scale met (Silver targeted).
- [ ] README includes HACS install, zone/stop lookup guide, Lovelace examples, unofficial-disclaimer, troubleshooting (off-hours, version bump, rate limits).

# 11. Related Specifications / Further Reading

- Local: `findings.md` (APK analysis, endpoints, zone UUIDs, test stop P45068 / route 44B).
- Upstream reference: https://github.com/edwinroket/red-regional-api (`client/transapp.py`, `examples/`, `gtfs/import_gtfs_sqlite.py`).
- HA docs: Integration quality scale, Config flow + Options + Reconfigure + Subentries, `DataUpdateCoordinator`, `device_tracker`, `diagnostics`, `repairs`, Lovelace map card.
- Parity references: `swiss_public_transport` + `ha_swiss_transport` (board/connection duality), `rejseplanen` (HA-standard 6-sensor), `nmbs`/`belgiantrain` (connection + liveboard), `entur_public_transport` (quay expansion, whitelist), HSL/Digitransit forks (GTFS-ID + realtime states), SL `trollp/SL` + `Trafiklab` (next/count/status split, travel search), `gtfs` core + `gtfs_rt`/`gtfs2` HACS forks (static+RT, vehicle map), `openpublictransport` (38-provider EFA/HAFAS/OTP/MOTIS, actions + disabled-by-default extras).
- Backend (unofficial): `https://phone.dtpr.transapp.cl/v7/phone/zones` (start live-capture here before coding parsers).
