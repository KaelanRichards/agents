{
  description = "Kaelan's macOS configuration (nix-darwin + home-manager)";

  inputs = {
    # Pinned to stable 26.05 across all inputs. Bump all four together.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

    nix-darwin = {
      url = "github:nix-darwin/nix-darwin/nix-darwin-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nix-homebrew.url = "github:zhaofengli/nix-homebrew";
  };

  outputs =
    inputs@{
      self,
      nixpkgs,
      nix-darwin,
      home-manager,
      nix-homebrew,
    }:
    let
      username = "kaelan";
      system = "aarch64-darwin";
    in
    {
      # Named "mac" rather than the hostname so a rename doesn't break rebuild.
      darwinConfigurations."mac" = nix-darwin.lib.darwinSystem {
        inherit system;
        specialArgs = { inherit inputs username; };
        modules = [
          ./darwin.nix

          nix-homebrew.darwinModules.nix-homebrew
          {
            nix-homebrew = {
              enable = true;
              user = username;
              # Takes ownership of the existing /opt/homebrew install.
              autoMigrate = true;
              enableRosetta = false;
            };
          }

          home-manager.darwinModules.home-manager
          {
            home-manager = {
              useGlobalPkgs = true;
              useUserPackages = true;
              # ~/.claude/CLAUDE.md and ~/.codex/AGENTS.md already exist as
              # hand-made symlinks; without this the first switch aborts.
              backupFileExtension = "hm-bak";
              extraSpecialArgs = { inherit username; };
              users.${username} = import ./home.nix;
            };
          }
        ];
      };

      darwinPackages = self.darwinConfigurations."mac".pkgs;
    };
}
