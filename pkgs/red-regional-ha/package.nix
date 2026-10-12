# Arguments are resolved from home-assistant.python3Packages scope.
# IMPORTANT: call via pkgs.home-assistant.python3Packages.callPackage, NOT
# pkgs.callPackage, so buildHomeAssistantComponent and any future Python
# deps come from HA's pinned interpreter set.
{
  lib,
  buildHomeAssistantComponent,
  src,
}:

buildHomeAssistantComponent rec {
  owner = "frabarz";
  domain = "red_regional";
  version = "0.1.0";

  inherit src;

  # No runtime `dependencies`: the integration uses only stdlib + aiohttp
  # (already bundled with Home Assistant). If a third-party lib is added
  # later, declare it here (from home-assistant.python3Packages) AND pin it
  # in custom_components/red_regional/manifest.json -> requirements.

  meta = {
    description = "Red Regional (TransApp/DTPR) arrival predictions and live bus positions";
    homepage = "https://github.com/frabarz/hass-red-regional";
    license = lib.licenses.mit;
    maintainers = [ ];
  };
}
