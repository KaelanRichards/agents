{
  description = "Agent dev environment — reproducible CLI toolbelt (laptop + VM)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          name = "agents";
          packages = with pkgs; [
            # version control
            jujutsu
            git
            delta
            gh
            # search & data
            ripgrep
            fd
            fzf
            jq
            yq-go
            ast-grep
            sd
            gron
            bat
            eza
            tree
            scc
            # code quality
            ruff
            biome
            shellcheck
            shfmt
            gitleaks
            actionlint
            # build / run / misc
            just
            watchexec
            entr
            hyperfine
            xh
            pandoc
            starship
            # language version management (languages stay mise/uv-managed)
            mise
            uv
            # multiplexers & remote
            tmux
            zellij
            mosh
            neovim
            ttyd
            # provisioning
            hcloud
          ];

          shellHook = ''
            echo "agents devShell · $(jj --version 2>/dev/null) · $(rg --version 2>/dev/null | head -1)"
            echo "languages via mise/uv; claude & codex install separately (not in nixpkgs)."
          '';
        };
      }
    );
}
