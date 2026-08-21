{
  description = "Optional macOS host configuration";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

    nix-darwin = {
      url = "github:nix-darwin/nix-darwin/nix-darwin-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    nix-homebrew.url = "github:zhaofengli/nix-homebrew";
  };

  outputs =
    inputs@{
      nixpkgs,
      nix-darwin,
      nix-homebrew,
      ...
    }:
    let
      username = "kaelan";
      system = "aarch64-darwin";
    in
    {
      darwinConfigurations.mac = nix-darwin.lib.darwinSystem {
        inherit system;
        specialArgs = { inherit inputs username; };
        modules = [
          ./darwin.nix

          nix-homebrew.darwinModules.nix-homebrew
          {
            nix-homebrew = {
              enable = true;
              user = username;
              autoMigrate = true;
              enableRosetta = false;
            };
          }
        ];
      };
    };
}
