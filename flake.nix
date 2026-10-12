{
  description = "Red Regional Home Assistant integration (HACS + NixOS)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      pkgsFor = system: import nixpkgs { inherit system; };

      # Nix store source for the component derivation: ONLY
      # custom_components/ (excludes APKs, .design, .git, etc.).
      componentSrc = nixpkgs.lib.fileset.toSource {
        root = ./.;
        fileset = nixpkgs.lib.fileset.unions [ ./custom_components ];
      };
    in
    {
      packages = nixpkgs.lib.genAttrs systems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          red-regional-ha =
            pkgs.home-assistant.python3Packages.callPackage ./pkgs/red-regional-ha/package.nix
              {
                src = componentSrc;
              };
          default = self.packages.${system}.red-regional-ha;
        }
      );

      nixosModules.red-regional = import ./nixos-modules/red-regional.nix;
      nixosModules.default = self.nixosModules.red-regional;

      devShells = nixpkgs.lib.genAttrs systems (
        system:
        let
          pkgs = pkgsFor system;
          haPy = pkgs.home-assistant.python3Packages;
          # NOTE: haPy.python.withPackages resolves `ps` against the
          # interpreter's default pkgs, NOT the HA scope, so reference HA
          # packages absolutely (haPy.<attr>). Same interpreter (3.14), so
          # ABI matches.
          pythonEnv = haPy.python.withPackages (_: [
            haPy.homeassistant
            haPy.pytest
            haPy."pytest-homeassistant-custom-component"
            haPy.pytest-asyncio
            haPy.pytest-aiohttp
            haPy.pytest-cov
            haPy.respx
            haPy.syrupy
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              pythonEnv
              pkgs.ruff
              pkgs.uv
              pkgs.git
              pkgs.jq
              pkgs.nix-output-monitor
            ];

            shellHook = ''
              echo "Red Regional HA dev shell"
              echo "  python: $(python --version 2>&1)"
              echo "  HA:     $(python -c 'import homeassistant.const as c; print(c.__version__)' 2>/dev/null || echo 'unavailable')"
              echo "  ruff:   $(ruff --version 2>/dev/null || echo 'unavailable')"
              echo ""
              echo "  pytest tests/          # run integration tests"
              echo "  ruff check . && ruff format --check ."
              echo "  nix build .#red-regional-ha   # build Nix package"
            '';
          };
        }
      );

      formatter = nixpkgs.lib.genAttrs systems (
        system:
        let
          pkgs = pkgsFor system;
        in
        pkgs.nixfmt
      );
    };
}
