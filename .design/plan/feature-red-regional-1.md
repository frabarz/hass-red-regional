---
goal: Incremental implementation of Red Regional HA integration to spec v1.0
version: 1.0
date_created: 2026-10-11
last_updated: 2026-10-11
owner: Red Regional HA Contributors
status: 'Completed'
tags: [feature, home-assistant, public-transport, chile, red-regional, plan]
---

# Introduction

![Status: Completed](https://img.shields.io/badge/status-Completed-brightgreen)

Incremental, executable plan to take `custom_components/red_regional/` from the current scaffold (manifest, stub `config_flow.py`, stub `__init__.py`, partial `const.py`, stub `en/es.json`) to a spec-compliant V1: board-only departures (`sensor`), service alerts (`binary_sensor`), opt-in live GPS (`device_tracker`), GTFS-static cache, services, translations, diagnostics, repairs. Each phase is independently buildable, testable, and committable. No code is written by this plan; each TASK names exact files, symbols, and done-criteria.

> Spec source of truth: `.design/spec/spec-design-red-regional-ha.md` v1.0. Inferred upstream JSON shapes in spec §4.1 are illustrative and MUST be re-validated against live payloads before parser freeze (Phase 1).

## 1. Requirements & Constraints

- **REQ-001**: UI-only setup via `ConfigFlow`; first step zone picker from live `GET /zones` with pinned-UUID offline fallback.
- **REQ-002**: One config entry per stop minimum; hub + shared coordinator preferred, subentries optional, never YAML.
- **REQ-003**: `sensor.next_departure` state is tz-aware `timestamp` of soonest arrival; rich `departures[]` attributes per §4.2 schema.
- **REQ-004**: Departure fields: `route`, `destination`, `scheduled_at`, `expected_at`, `due_in_min`, `delay_min`, `realtime`, `direction`, `vehicle_id`, `route_color`, `cancelled`, `occupancy`.
- **REQ-005**: `binary_sensor.service_alert` on iff `alerts[]` non-empty, with `title/description/routes/valid_from/valid_until`.
- **REQ-006**: Opt-in `device_tracker` per vehicle plate, map-capable, orphan cleanup when out of service.
- **REQ-007**: Per-stop options filters: `routes_whitelist`, `destinations`, `max_departures` 1–15 (default 5), `look_ahead_min` (default 120), `walk_offset_min` (default 0).
- **REQ-008**: `departure_count` attribute + disabled-by-default count sensor + `departures_text` for TTS/cards.
- **REQ-009**: GTFS ZIP per-zone disk cache with `version/3` gate; tolerant parser (singular/plural names, `utf-8-sig`/utf-8).
- **REQ-010**: Typed `voluptuous` services `red_regional.refresh`, `red_regional.lookup_stop`, optional `red_regional.get_vehicles`, all translated.
- **REQ-011**: Stable `unique_id`s (`{zone}_{stop}_next`, `{zone}_{stop}_alert`, `{zone}_{plate}`); `DeviceInfo.identifiers={(DOMAIN, f"{zone}_{stop}")}`, manufacturer `DTPR / Red Regional`, model = city name.
- **REQ-012**: Empty `services` → `unknown` + count 0, never `unavailable`/exception.
- **REQ-013**: OptionsFlow (scan_interval 30–600, filters, tracking toggle) without re-creating entry; ReconfigureFlow for zone/stop.
- **REQ-020**: Async-only; `aiohttp` via `async_get_clientsession`; zero `requests` in runtime code.
- **REQ-021**: All polling via `DataUpdateCoordinator` with `update_interval` from options, `UpdateFailed`/`ConfigEntryAuthFailed`, keep-last-known, backoff on 429/5xx.
- **REQ-022**: Fully typed, `ruff`-clean (line-length 88, `E,F,I,UP,B,ASYNC`, target `py313`), `mypy`-clean, `zoneinfo`/`dt_util`, docstrings at module/class/public-function level only, no inline chatter comments.
- **REQ-023**: Full literal text in `translations/en.json` + `translations/es.json`; no `strings.json` / `[%key%]` placeholders (unsupported in custom integrations).
- **REQ-024**: `diagnostics.py` with `phoneId`/precision redaction; `quality_scale.yaml` targeting Silver (Bronze minimum).
- **REQ-025**: Repairs for unreachable/auth-rejected/invalid-stop/GTFS-failure/429 with fix flow.
- **CON-001**: Headers `Os-type: Android`, `App-Version: 2.5.1`, `Accept: application/json`; `stopInfo` carries `mode=3` + persisted per-entry `phoneId` (uuid4 once, stored, reused).
- **CON-002**: Default 60 s boards, 30 s minimum, 30–60 s vehicles; one HTTP request per stop per tick; no fan-out per route.
- **CON-003**: `mode=3` magic preserved; `direction` strictly `I|R`.
- **CON-004**: Base URL + headers + `APP_VERSION` centralized in `const.py`; no hardcoded zone UUIDs except pinned fallback cache.
- **CON-005**: GTFS parser handles `stop.csv`/`stops.txt`, `route.csv`/`routes.txt`, BOM + plain.
- **CON-006**: No YAML setup path; `async_forward_entry_setups`, `ConfigEntry.runtime_data` (HA 2026.1 pattern).
- **GUD-001**: V1 entity split: enabled `sensor.next_departure` + `binary_sensor.alert`; disabled-by-default count sensor + trackers.
- **GUD-002**: `timestamp` state + `due_in_min` attributes; never human strings as state.
- **GUD-003**: Explicit `scheduled` vs `realtime` + `delay_min`; `attribution: "Datos: DTPR Red Regional (no oficial)"`.
- **GUD-004**: README Lovelace examples (entities, markdown `departures_text`, map, auto-entities/cancelled styling).
- **GUD-005**: Sparse logging (no per-poll info); debug payload shape once; missing keys → `None`, never crash.
- **PAT-001**: Hub `DataUpdateCoordinator`; `CoordinatorEntity` subclasses; forward `["sensor", "binary_sensor", "device_tracker"]`.
- **PAT-002**: Config flow zone → stop search (GTFS autocomplete + live `stopInfo` validation) → filters → create; empty-services allowed with warning + repair hint.
- **PAT-003**: GTFS version-check → streamed conditional download (8192 chunks) → parse → JSON/SQLite index.
- **OOS-001**: No A-to-B trip planning. **OOS-002**: No payment/balance (V2 sensor/lookup only). **OOS-003**: No FCM push. **OOS-004**: No custom tiles. **OOS-005**: Bus-only `transport_mode`.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Lock live API contract and land typed async client foundation with zero entities.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-001 | Live-capture `GET /zones`, `GET /{zone}/stopInfo?stopCode=P39704&mode=3&phoneId=<uuid>`, `GET /{zone}/synoptic/machines?route=44B&direction=I`, `GET /{zone}/gtfs/version/3` with headers `Os-type: Android, App-Version: 2.5.1`; save redacted fixtures to `tests/fixtures/{zones,stopinfo_P39704_full,stopinfo_empty,machines_44B_I,machines_empty,alerts_present,http_429}.json` | ✅ | 2026-10-11 |
| TASK-002 | Extend `custom_components/red_regional/const.py` with `API_BASE, APP_VERSION, OS_TYPE, CONF_ZONE_UUID, CONF_ZONE_NAME, CONF_STOP_CODE, CONF_ROUTES_WHITELIST, CONF_DESTINATIONS, CONF_MAX_DEPARTURES, CONF_LOOK_AHEAD_MIN, CONF_WALK_OFFSET_MIN, CONF_TRACK_VEHICLES, CONF_TRACKED_ROUTES, CONF_SCAN_INTERVAL_S, CONF_PHONE_ID, DEFAULT_SCAN_INTERVAL_S=60, MIN_SCAN_INTERVAL_S=30, FALLBACK_ZONES` (Concepcion/Talca/Temuco UUIDs from spec §2) | ✅ | 2026-10-11 |
| TASK-003 | Create `custom_components/red_regional/models.py` with frozen dataclasses `Departure, StopBoard, ServiceAlert, VehiclePosition` exactly per spec §4.2 schema plus `__eq__` for coordinator `always_update=False` | ✅ | 2026-10-11 |
| TASK-004 | Create `custom_components/red_regional/api.py` class `TransAppClient` with `async_get_zones, async_get_stop_info, async_get_machines, async_get_gtfs_version` on injected `aiohttp.ClientSession`, `asyncio.timeout(10)`, centralized headers, raising `TransAppAuthError/TransAppConnectionError/TransAppRateLimitError` from `exceptions.py` | ✅ | 2026-10-11 |
| TASK-005 | Create `custom_components/red_regional/exceptions.py` with `TransAppError, TransAppAuthError, TransAppConnectionError, TransAppRateLimitError, InvalidStopError` | ✅ | 2026-10-11 |
| TASK-006 | Create `custom_components/red_regional/parse.py` with `parse_stop_board(raw, now, gtfs_index) -> StopBoard` and `parse_machines(raw) -> list[VehiclePosition]` probing arrival-as-minutes/epoch/ISO, normalizing to tz-aware `expected_at`, missing keys to `None` | ✅ | 2026-10-11 |
| TASK-007 | Create `custom_components/red_regional/filters.py` with `apply_departure_filters(departures, routes_whitelist, destinations, look_ahead_min, walk_offset_min, max_departures, now) -> list[Departure]` implementing exact/CI-strip match, substring destination, offset-hide, window-drop, sort, truncate | ✅ | 2026-10-11 |
| TASK-008 | Add unit tests `tests/test_parse.py`, `tests/test_filters.py` covering full/empty/alert/429 shapes, BOM/singular-plural deferred to Phase 7, tz math America/Santiago, 100% filter-branch coverage | ✅ | 2026-10-11 |

### Implementation Phase 2

- GOAL-002: Wire shared polling and entry lifecycle; no entities yet but coordinators refresh green under mocks.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-009 | Create `custom_components/red_regional/coordinator.py` class `RedRegionalCoordinator(DataUpdateCoordinator[StopBoard])` with `config_entry` passed explicitly, `name=f"{DOMAIN}-{zone}-{stop}"`, `update_interval` from options, `_async_setup` loading GTFS index handle, `_async_update_data` single `stopInfo` call mapping `TransAppAuthError→ConfigEntryAuthFailed`, others→`UpdateFailed` with `retry_after` on 429, `always_update=False` | ✅ | 2026-10-11 |
| TASK-010 | Create `custom_components/red_regional/vehicle_coordinator.py` class `VehicleCoordinator(DataUpdateCoordinator[list[VehiclePosition]])` polling `synoptic/machines` per watched `(route, direction)` only when tracking enabled, same error mapping | ✅ | 2026-10-11 |
| TASK-011 | Rewrite `custom_components/red_regional/__init__.py` with `RedRegionalRuntimeData` dataclass, `async_setup_entry` (generate+persist `phoneId` uuid4 once, build `TransAppClient` on `async_get_clientsession`, `await coordinator.async_config_entry_first_refresh()`, `async_forward_entry_setups(entry, ["sensor","binary_sensor","device_tracker"])`, options update listener toggling `update_interval`), `async_unload_entry`, `async_migrate_entry`, `async_reload_entry` support | ✅ | 2026-10-11 |
| TASK-012 | Set `PLATFORMS=["sensor","binary_sensor","device_tracker"]`; add `tests/test_coordinator.py` with `aioresponses`/`aresponses` fixtures for success/empty/429/5xx/auth asserting keep-last-known, `unknown`-safe data, single-request-per-tick budget | ✅ | 2026-10-11 |

### Implementation Phase 3

- GOAL-003: Ship full config, options, and reconfigure flows with live validation.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-013 | Rewrite `custom_components/red_regional/config_flow.py` steps `async_step_user` (zone select via live `/zones` + `FALLBACK_ZONES`, `vol.Schema` with `select` selector) → `async_step_stop` (text + GTFS-autocomplete hint, live `stopInfo` validation, `invalid_stop`/`cannot_connect` errors, empty-services warning-allow) → `async_step_filters`; `VERSION=1`, `async_set_unique_id(f"{zone}_{stop}")` + `_abort_if_unique_id_configured`, title `f"{stop_name} ({stop_code})"` | ✅ | 2026-10-11 |
| TASK-014 | Add `async_step_reauth` (confirm → update headers/`APP_VERSION` path) and `async_step_reconfigure` (zone/stop change via `async_update_reload_and_abort`, `async_set_unique_id` + `_abort_if_unique_id_mismatch`) in same file | ✅ | 2026-10-11 |
| TASK-015 | Create `custom_components/red_regional/options_flow.py` (`RedRegionalOptionsFlow`) editing `scan_interval_s` 30–600, all filters, `track_vehicles` + `tracked_routes`, `name_override`; wire `entry.async_on_unload(entry.add_update_listener(...))` | ✅ | 2026-10-11 |
| TASK-016 | Add `tests/test_config_flow.py` + `tests/test_options_flow.py` covering zone-fallback, valid/invalid/off-hours stop, duplicate abort, reauth, reconfigure (no new entry), options interval propagation | ✅ | 2026-10-11 |

### Implementation Phase 4

- GOAL-004: Expose board as HA-native timestamp sensor.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-017 | Create `custom_components/red_regional/entity.py` class `RedRegionalStopEntity(CoordinatorEntity[RedRegionalCoordinator])` with `DeviceInfo(identifiers={(DOMAIN, f"{zone}_{stop}")}, manufacturer="DTPR / Red Regional", model=zone_name, sw_version=APP_VERSION)`, `available=coordinator.last_update_success` | ✅ | 2026-10-11 |
| TASK-018 | Create `custom_components/red_regional/sensor.py` classes `NextDepartureSensor` (`translation_key=next_departure`, `device_class=SensorDeviceClass.TIMESTAMP`, `unique_id=f"{zone}_{stop}_next"`, state soonest `expected_at` else `None`, attrs `stop_code/stop_name/zone/departure_count/departures[]/departures_text/attribution/last_update`) and `DeparturesCountSensor` (`entity_registry_enabled_default=False`, `unique_id=f"{zone}_{stop}_count"`) | ✅ | 2026-10-11 |
| TASK-019 | Add `tests/test_sensor.py` asserting AC-001/AC-002/AC-004/AC-007 (future timestamp, empty→`unknown`+0, whitelist, walk-offset hide, look-ahead truncate, `departures_text` format) | ✅ | 2026-10-11 |

### Implementation Phase 5

- GOAL-005: Expose disruptions as binary sensor.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-020 | Create `custom_components/red_regional/binary_sensor.py` class `ServiceAlertSensor` (`translation_key=service_alert`, `unique_id=f"{zone}_{stop}_alert"`, `is_on=bool(alerts)`, attrs `alerts[]`) reusing `RedRegionalStopEntity` + same `DeviceInfo` | ✅ | 2026-10-11 |
| TASK-021 | Add `tests/test_binary_sensor.py` asserting AC-005 (alerts→`on` with populated attrs, none→`off`) | ✅ | 2026-10-11 |

### Implementation Phase 6

- GOAL-006: Expose opt-in live bus GPS on HA map.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-022 | Create `custom_components/red_regional/device_tracker.py` with `async_setup_entry` creating one `TrackerEntity` per plate from `VehicleCoordinator`, `unique_id=f"{zone}_{plate}"` (append `_{direction}` on I/R collision per edge-case 6), `source_type=SourceType.GPS`, `latitude/longitude`, attrs `speed_kmh/route/direction/plate/last_update`, stale/out-of-service cleanup removing orphans | ✅ | 2026-10-11 |
| TASK-023 | Add `tests/test_device_tracker.py` asserting AC-006 (in-service→trackers with valid lat/lon, empty→zero entities, duplicate-plate-direction split) | ✅ | 2026-10-11 |

### Implementation Phase 7

- GOAL-007: Land version-gated GTFS-static cache backing names, colors, and lookup.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-024 | Create `custom_components/red_regional/gtfs.py` with `async_ensure_gtfs(hass, zone_uuid) -> GtfsIndex` implementing version-check → streamed download (8192 chunks) to `config/.storage/red_regional/gtfs_{zone}.zip` → tolerant parse (`stop.csv`/`stops.txt`, `route.csv`/`routes.txt`, `utf-8-sig`/utf-8) → JSON/SQLite index exposing `stop_name/lat/lon/route_color/route_long_name` | ✅ | 2026-10-11 |
| TASK-025 | Wire `gtfs.py` into coordinator `_async_setup`, config-flow autocomplete, and `parse_stop_board` destination/color enrichment; add `tests/test_gtfs.py` + fixtures for singular-vs-plural, BOM-vs-plain, version-unchanged reuse (AC-009) | ✅ | 2026-10-11 |

### Implementation Phase 8

- GOAL-008: Register typed, translated services.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-026 | Create `custom_components/red_regional/services.py` + `services.yaml` registering `red_regional.refresh` (`config_entry_id|device_id` → `coordinator.async_request_refresh`), `red_regional.lookup_stop` (`zone_uuid+query` → GTFS-first candidates `stop_code/stop_name/lat/lon`), optional `red_regional.get_vehicles` (`zone_uuid+route+direction`) with `voluptuous` schemas; call `async_register_entity_service`/`hass.services.async_register` from `__init__.py` | ✅ | 2026-10-11 |
| TASK-027 | Add `tests/test_services.py` for schema validation, refresh debounce, lookup GTFS-first + live-fallback paths | ✅ | 2026-10-11 |

### Implementation Phase 9

- GOAL-009: Reach Bronze (target Silver) quality gate with i18n, diagnostics, repairs, docs, CI.

| Task | Description | Completed | Date |
| ---- | ----------- | --------- | ---- |
| TASK-028 | Rewrite `translations/en.json` + `translations/es.json` with full literal text for config/options/reconfigure/entity-names/services/repairs/issues; add `tests/test_translations.py` asserting en/es key parity | ✅ | 2026-10-11 |
| TASK-029 | Create `custom_components/red_regional/diagnostics.py` (`async_get_config_entry_diagnostics` redacting `phoneId` via `async_redact_data`, lat/lon truncation + plate masking options) + `tests/test_diagnostics.py` asserting AC-012 | ✅ | 2026-10-11 |
| TASK-030 | Create `custom_components/red_regional/repairs.py` + issue wiring in coordinator (`backend_unreachable`, `app_version_rejected`, `invalid_stop`, `gtfs_failed`, `rate_limited`) with fix flows to reconfigure/retry; add `tests/test_repairs.py` | ✅ | 2026-10-11 |
| TASK-031 | Add `icons.json`, `quality_scale.yaml` (Silver target), extend `manifest.json`/`hacs.json`/`requirements.txt`↔`package.nix` sync check, README HACS install + zone/stop guide + Lovelace (entities/markdown/map/auto-entities) + unofficial disclaimer + troubleshooting, `tests/test_manifest.py` extension for hassfest-relevant keys | ✅ | 2026-10-11 |
| TASK-032 | CI parity pass: `pytest tests/ -q`, `ruff check .`, `ruff format --check .`, `mypy`, `nix build .#red-regional-ha`, hassfest + HACS actions green; soak assertion for AC-008 request budget and backoff single-warning semantics | ✅ | 2026-10-11 |

## 3. Alternatives

- **ALT-001**: Multiple config entries with one coordinator each instead of hub + shared coordinator — rejected: multiplies `stopInfo` request rate against unknown unofficial limits and duplicates `phoneId`/GTFS cache handling; retained only as fallback for HA <2025.2 without subentries.
- **ALT-002**: Reuse reference `red-regional-api` (`requests`, sync) as runtime dependency — rejected: blocks HA event loop, no timeouts/retries/typing; port pure parsing logic to `aiohttp` per REQ-020.
- **ALT-003**: Minutes-until-arrival as sensor state — rejected: breaks HA history/`relative_time` templates andRecorder semantics; `timestamp` + `due_in_min` attributes per GUD-002 preserves both.
- **ALT-004**: YAML-first configuration — rejected: forbidden by CON-006 for new integrations; UI + options/reconfigure only.
- **ALT-005**: Per-route fan-out polling inside stop coordinator — rejected: violates CON-002 request budget; separate opt-in `VehicleCoordinator` only when tracking enabled.
- **ALT-006**: SQLite-full-GTFS import including shapes/calendar day one — rejected: over-engineering; V1 indexes only `stop`/`route` (+ shape/calendar opportunistically if present).

## 4. Dependencies

- **DEP-001**: HA 2026.1+ runtime (`ConfigEntry.runtime_data`, `async_forward_entry_setups`, `DataUpdateCoordinator._async_setup`, `TrackerEntity`); dev shell HA 2026.9.x + Python 3.13-compatible code (`ruff target-version py313`).
- **DEP-002**: `pytest`, `pytest-homeassistant-custom-component`, `pytest-asyncio` (auto mode), `aresponses`/`aioresponses` for HTTP mocks.
- **DEP-003**: Live TransApp backend `https://phone.dtpr.transapp.cl/v7/phone` for fixture capture; pinned `App-Version 2.5.1` + `Os-type Android` headers.
- **DEP-004**: Reference logic only: `github.com/edwinroket/red-regional-api` (`client/transapp.py`, `gtfs/import_gtfs_sqlite.py`) — verify license before porting lines.
- **DEP-005**: Nix flake outputs (`packages.red-regional-ha`, `nixosModules.default`, `devShells`) and `pkgs/red-regional-ha/package.nix` manifest sync.
- **DEP-006**: Parity references consulted: `ha_swiss_transport` (board duality), `trollp/SL` (next/count/status split), `rejseplanen` (HA-standard sensors), `openpublictransport` (disabled-by-default extras), `511_transit` HACS (stop+vehicle device grouping), `gtfs_rt` forks (map pattern).

## 5. Files

- **FILE-001**: `custom_components/red_regional/const.py` — extend with all CONF keys, intervals, fallback zones.
- **FILE-002**: `custom_components/red_regional/api.py` — new async `TransAppClient`.
- **FILE-003**: `custom_components/red_regional/models.py` — new frozen dataclasses.
- **FILE-004**: `custom_components/red_regional/exceptions.py` — new typed errors.
- **FILE-005**: `custom_components/red_regional/parse.py` — new payload parsers.
- **FILE-006**: `custom_components/red_regional/filters.py` — new filter pipeline.
- **FILE-007**: `custom_components/red_regional/coordinator.py` — new stop board coordinator.
- **FILE-008**: `VehicleCoordinator` inside `coordinator.py` (merged; no separate `vehicle_coordinator.py`) — vehicle GPS polling sharing helpers with the board coordinator.
- **FILE-009**: `custom_components/red_regional/gtfs.py` — new version-gated cache.
- **FILE-010**: `custom_components/red_regional/__init__.py` — rewrite entry lifecycle + services registration.
- **FILE-011**: `custom_components/red_regional/config_flow.py` — rewrite zone/stop/filters + reauth + reconfigure.
- **FILE-012**: `custom_components/red_regional/options_flow.py` — new options flow.
- **FILE-013**: `custom_components/red_regional/entity.py` — new shared base entity.
- **FILE-014**: `custom_components/red_regional/sensor.py` — new timestamp + count sensors.
- **FILE-015**: `custom_components/red_regional/binary_sensor.py` — new alert sensor.
- **FILE-016**: `custom_components/red_regional/device_tracker.py` — new GPS trackers.
- **FILE-017**: `custom_components/red_regional/services.py` + `services.yaml` — new services.
- **FILE-018**: `custom_components/red_regional/diagnostics.py` — new redacted diagnostics.
- **FILE-019**: `custom_components/red_regional/repairs.py` — new fix flows.
- **FILE-020**: `custom_components/red_regional/translations/en.json`, `es.json` — full literal text.
- **FILE-021**: `custom_components/red_regional/icons.json`, `quality_scale.yaml`, `manifest.json`, `services.yaml` — quality/HACS metadata.
- **FILE-022**: `tests/fixtures/*.json|.zip` — live-captured redacted fixtures (zones, stopinfo full/empty/alerts, machines full/empty, 429, GTFS singular/plural+BOM).
- **FILE-023**: `tests/test_{parse,filters,coordinator,config_flow,options_flow,sensor,binary_sensor,device_tracker,gtfs,services,translations,diagnostics,repairs}.py` — coverage per §6.
- **FILE-024**: `README.md`, `.github/workflows/{validate,test}.yml`, `pkgs/red-regional-ha/package.nix`, `requirements.txt` — docs/CI/packaging sync.

## 6. Testing

- **TEST-001**: Parser units: full/off-hours-empty/alerts/429/5xx/missing-key shapes → typed boards, tz-aware ISO, `None`-degradation (spec §6, AC-002/AC-005).
- **TEST-002**: Filter units: whitelist CI-strip, destination substring, walk-offset hide (AC-007), look-ahead drop, sort+truncate 1–15 (AC-004).
- **TEST-003**: Coordinator integration with mocked `aiohttp`: success, empty→`unknown`-safe, 429→`retry_after`+keep-last-known+single warning, auth→`ConfigEntryAuthFailed`+reauth (AC-008).
- **TEST-004**: Config flow: live-zones + fallback, valid/invalid/off-hours stop (AC-003), duplicate unique_id abort, reauth, reconfigure updates-without-new-entry.
- **TEST-005**: Sensor: valid timestamp state + `departures[]` completeness (AC-001), count/disabled-default, `departures_text`.
- **TEST-006**: Binary sensor on/off transitions (AC-005).
- **TEST-007**: Device tracker: plate-per-entity, valid lat/lon, map attrs, orphan cleanup, I/R collision split (AC-006).
- **TEST-008**: GTFS: singular/plural + BOM matrix, version-gated no-redownload, restart reuse (AC-009).
- **TEST-009**: Services schema + refresh + lookup candidates shape.
- **TEST-010**: Translation en/es parity (AC-011), diagnostics redaction (`phoneId`, precision, plates) (AC-012), repairs issuance/fix, hassfest + HACS validation (AC-010).
- **TEST-011**: Budget soak: 3 stops × 10 min mocked ticks ≈ 1 req/stop/min + 1 req/route/min, no 429; coverage ≥85% coordinator/sensor/parsers, 100% filter branches.

## 7. Risks & Assumptions

- **RISK-001**: Inferred `stopInfo`/`machines` field names are wrong (no raw sample in reference repo) → mitigate by Phase 1 live capture + tolerant parser + debug shape log + diagnostics fixture; freeze parsers only after capture.
- **RISK-002**: Backend enforces newer `App-Version` (2.7.0 APK in repo vs pinned 2.5.1) → mitigate by single-constant bump (CON-004) + `app_version_rejected` repair + reauth path.
- **RISK-003**: Unknown rate limits on unofficial backend → mitigate by 60 s default / 30 s floor, shared coordinator, opt-in vehicles, exponential backoff, single-warning logs.
- **RISK-004**: Zone UUID drift / new cities → mitigate by live `/zones` primary + pinned fallback, never hardcode beyond fallback.
- **RISK-005**: GTFS non-standard names/encodings and large ZIPs → mitigate by dual-name + dual-encoding parser, streamed 8192-chunk download, disk cache, version gate.
- **RISK-006**: HA API drift (2026.1 min vs 2026.9 dev shell, `runtime_data`/`_async_setup`/subentries) → mitigate by mature patterns from HA docs 2024.8 coordinator-setup post, HA Config Flow docs, `integration_blueprint` reauth/reconfigure/options reference; keep `py313` compat.
- **ASSUMPTION-001**: Base URL `https://phone.dtpr.transapp.cl/v7/phone` + `mode=3` + `I|R` directions remain valid; re-validate in Phase 1.
- **ASSUMPTION-002**: Canonical fixtures Talca `PA151`, Concepcion `P39704`, route `44B/I` obtainable live; off-hours empty case reproducible.
- **ASSUMPTION-003**: Reference `red-regional-api` license permits logic porting; verify before copying beyond concepts.
- **ASSUMPTION-004**: Single stop per config entry acceptable for V1; hub+subentries is optimization, not blocker (REQ-002 minimum).

## 8. Related Specifications / Further Reading

- Local spec: `.design/spec/spec-design-red-regional-ha.md` (requirements, entities, AC-001–AC-012, §6–§11).
- Local research: `findings.md` (APK endpoints, zone UUIDs, P39704/44B fixtures); reference `red-regional-api` `client/transapp.py`, `gtfs/import_gtfs_sqlite.py` — https://github.com/edwinroket/red-regional-api.
- Live backend start point: `https://phone.dtpr.transapp.cl/v7/phone/zones`.
- HA docs: Integration fetching data (`DataUpdateCoordinator`, `always_update`, `_async_setup`, `ConfigEntryAuthFailed`, `retry_after`) — https://developers.home-assistant.io/docs/integration_fetching_data/; Coordinator setup post 2024-08-05 — https://developers.home-assistant.io/blog/2024/08/05/coordinator_async_setup/; Config flow (unique_id, reconfigure, reauth) — https://developers.home-assistant.io/docs/core/integration/config_flow/; Repairs — https://developers.home-assistant.io/docs/core/platform/repairs/; Custom integration localization (no `strings.json`/`[%key%]`) — https://developers.home-assistant.io/docs/internationalization/custom_integration/.
- Reference scaffold: `roquerodrigo/ha-integration-blueprint` / `jpawlowski/hacs.integration_blueprint` (coordinator + reauth/reconfigure/options + diagnostics + repairs + 90% gate); quality/silver guidelines per `christianreiss/ha-silverline GUIDELINES.md`.
- Parity integrations: `swiss_public_transport` + `ha_swiss_transport`, `rejseplanen`, `nmbs`, `entur_public_transport`, HSL/Digitransit, SL `trollp/SL`, `gtfs` core + `gtfs_rt` forks (`bgheneti/ha-gtfs-rt`), `openpublictransport`, `Seabmoby/511_transit_home_assistant` (stop+vehicle device grouping, map card).
