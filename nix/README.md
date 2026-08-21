# Optional macOS host layer

The portable environment is chezmoi plus mise. This flake is intentionally smaller: it manages macOS preferences, Homebrew, the two bootstrap tools, and GUI applications.

It does not deploy dotfiles or command-line development tools. That avoids duplicating the portable manifests.

## Apply

Apply chezmoi and run mise install first. Then:

~~~sh
nix build .#darwinConfigurations.mac.system --no-link
sudo darwin-rebuild switch --flake .#mac
~~~

Run these commands from this directory.

Homebrew cleanup is set to zap. The declared formula list is intentionally only chezmoi and mise; other command-line tools live under mise.
