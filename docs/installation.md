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
hass-red-regional.url = "github:frabarz/hass-red-regional";

# NixOS configuration
imports = [ hass-red-regional.nixosModules.default ];

services.home-assistant.enable = true;
services.hass-red-regional = {
  enable = true;
  package = hass-red-regional.packages.${pkgs.system}.red-regional-ha;
};
```

Notes:

- Requires `services.home-assistant.enable = true`; the module appends the
  component to `services.home-assistant.customComponents`.
- Use the **same nixpkgs input** for your system and this flake to avoid Home
  Assistant version skew. See `nixos-modules/red-regional.nix`.

Next: [Configuration](configuration.md).
