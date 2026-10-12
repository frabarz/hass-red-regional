# AGENTS.md

## Project Overview

Unofficial Home Assistant custom integration for Chilean Red Regional public
transport (DTPR / TransApp backend): real-time arrival predictions, service
alerts, live bus GPS. HACS-installable repo **and** Nix flake (`packages`,
`nixosModules`, `devShells`) for NixOS deployment.

- Integration code: `custom_components/red_regional/` (domain `red_regional`,
  config-flow-only, `cloud_polling`, currently zero runtime `requirements`:
  stdlib + HA-bundled `aiohttp` only).
- Nix package: `pkgs/red-regional-ha/package.nix` (via
  `buildHomeAssistantComponent`).
- NixOS module: `nixos-modules/red-regional.nix`
  (`services.hass-red-regional.{enable, package}` → appends to
  `services.home-assistant.customComponents`).
- Behavior spec: `.design/spec/spec-design-red-regional-ha.md` (source of
  truth for entities, polling, filters). API research: `findings.md`.
- Toolchain: Nix flake, HA 2026.9.x + Python 3.14 in dev shell; minimum
  supported runtime is HA 2026.1 (Python >= 3.13) per `manifest.json` /
  `hacs.json`. Keep code `py313`-compatible (`ruff target-version = py313`).
  `pytest` +
  `pytest-homeassistant-custom-component`.

## Setup Commands

- Enter dev env: `nix develop` (provides Python 3.14.7, HA 2026.9.x,
  `pytest`, `ruff`; all commands below assume this shell).
- Inspect outputs: `nix flake show`
- Check everything: `nix flake check`

## Development Workflow

- Integration scaffold: `__init__.py`, `const.py` (API base, `App-Version`,
  zone/stop keys), `config_flow.py`, `translations/en.json` + `es.json`.
- Full entity design (sensor/binary_sensor/device_tracker, coordinator,
  GTFS cache) lives in `.design/spec/spec-design-red-regional-ha.md` —
  follow it; do not invent entity names.
- NixOS consumer wiring:
  ```nix
  imports = [ hass-red-regional.nixosModules.default ];
  services.hass-red-regional = {
    enable = true;
    package = hass-red-regional.packages.${pkgs.system}.red-regional-ha;
  };
  ```
  Requires `services.home-assistant.enable = true`. Zone/stop setup stays in
  the HA UI (no declarative YAML for this integration).
- Keep `custom_components/red_regional/manifest.json` (`domain`, `version`,
  `requirements`) in sync with `pkgs/red-regional-ha/package.nix`
  (`domain`, `version`, `dependencies`) and `requirements.txt`.
- Bump `manifest.json → version` on every release (HACS compares it).

## Testing Instructions

- Run all tests: `pytest tests/ -q` (from repo root, inside `nix develop`).
- Smoke test only asserts manifest/domain layout (`tests/test_manifest.py`);
  extend with coordinator/API mocks per spec §6 (fixtures: Talca `PA151`,
  Concepción `P45068`, route `44B/I`, empty-services off-hours case).
- Build Nix package: `nix build .#red-regional-ha` (runs manifest check
  hook; output `result/custom_components/red_regional/`).
- CI parity: `.github/workflows/validate.yml` (hassfest + HACS action),
  `.github/workflows/test.yml` (pytest + ruff).

## Code Style

- `ruff check .` and `ruff format --check .` must pass (line-length 88,
  `py314`, rules `E,F,I,UP,B,ASYNC` per `pyproject.toml`). Fix with
  `ruff check . --fix` / `ruff format .`.
- Fully typed, async-only code (`aiohttp` via HA session); never add sync
  `requests` calls to the integration (reference SDK uses `requests` —
  port logic, not transport).
- Translations: full literal text in `translations/en.json` (+ `es.json`);
  do NOT use core `strings.json` / `[%key:...%]` placeholders (unsupported
  in custom integrations).

## Build and Deployment

- `nix build .#red-regional-ha` → component derivation.
- HACS install: repo must keep `custom_components/red_regional/` at root,
  `hacs.json` (`country: CL`), `README.md`; ship via GitHub Release.
- Format Nix files: `nix fmt` (uses `nixfmt`).

## Additional Notes

- Gotchas:
  - `haPy.python.withPackages` resolves `ps` against the interpreter's
    default set, NOT the HA scope — reference HA packages absolutely
    (`haPy.pytest`, `haPy.homeassistant`, …) in `flake.nix`.
  - `pytest` binary needs explicit listing in `devShells`; transitive deps
    don't expose it.
  - Package `src` is fileset-filtered to `custom_components/` only, so the
    `*.apk` reverse-engineering artifacts (git-ignored, ~31 MB) never enter
    the Nix store.
  - HA version skew: shell reports its own HA (currently 2026.9.4) vs system
    channel (2026.9.3) — use one nixpkgs input for system + flake.
  - Backend is unofficial (`Os-type: Android`, `App-Version: 2.5.1`,
    `mode=3`, directions `I|R`); centralize in `const.py`, never hardcode
    zone UUIDs except as fallback cache (prefer live `GET /zones`).
- No `git` repo here yet; do not run commit/push unless asked.
