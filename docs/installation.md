# Installation

## Via HACS (recommended)

1. HACS → Integrations → ⋮ → Custom repositories → add this repository URL
   with category *Integration*.
2. Find “Red Regional” in HACS and install it.
3. Restart Home Assistant.
4. Settings → Devices & Services → Add Integration → Red Regional.

Once accepted into the HACS default store, step 1 becomes a plain search.

## Manual install

Copy `custom_components/red_regional/` into your Home Assistant
`config/custom_components/` directory and restart. Requires Home Assistant
2026.1+ (Python ≥ 3.13); the integration needs no extra packages beyond what
Home Assistant already ships.

## Via the NixOS flake

```nix
# flake.nix inputs
hass-red-regional = {
  url = "github:frabarz/hass-red-regional";
  inputs.nixpkgs.follows = "nixpkgs";
};

# NixOS configuration (`inputs` is available via specialArgs)
services.home-assistant = {
  enable = true;
  customComponents = [
    inputs.hass-red-regional.packages.${pkgs.stdenv.hostPlatform.system}.default
  ];
};
```

Notes:

- The stock Home Assistant module installs the component through
  `services.home-assistant.customComponents`; no custom NixOS module is needed.
- Keep `inputs.nixpkgs.follows = "nixpkgs"` so the component is built against
  the same Home Assistant version you run.
- Zone/stop setup stays in the Home Assistant UI (there is no declarative YAML
  for this integration).

Next: [Configuration](configuration.md).
