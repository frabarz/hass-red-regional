# NixOS module wiring the Red Regional custom component into
# services.home-assistant. Config-flow-only: the module only installs the
# component (customComponents); stop/zone setup happens in the HA UI, and
# declarative `services.home-assistant.config.red_regional` is NOT used.
{
  config,
  lib,
  ...
}:

let
  cfg = config.services.hass-red-regional;
in
{
  options.services.hass-red-regional = {
    enable = lib.mkEnableOption "Red Regional Home Assistant custom integration";

    package = lib.mkOption {
      type = lib.types.package;
      description = ''
        The red_regional custom component derivation.
        Defaults to this flake's package built against the flake's nixpkgs
        (same input as your system should use to avoid HA version skew).
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.services.home-assistant.enable;
        message = "services.hass-red-regional.enable requires services.home-assistant.enable = true.";
      }
    ];

    services.home-assistant.customComponents = [ cfg.package ];
  };
}
