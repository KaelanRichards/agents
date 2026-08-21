{
  config,
  lib,
  username,
  ...
}:
let
  # Stable path. ~/.dotfiles symlinks here, so scripts never care where the
  # clone lives.
  dotfiles = "/Users/${username}/.config/agents";

  # mkOutOfStoreSymlink, not a store copy: a tool that rewrites its own config
  # at runtime writes straight back into the repo, so the change is versioned
  # instead of silently discarded on the next rebuild.
  link = path: config.lib.file.mkOutOfStoreSymlink "${dotfiles}/${path}";
in
{
  home.username = username;
  home.homeDirectory = "/Users/${username}";
  home.stateVersion = "26.05";

  # Packages come from Homebrew (see darwin.nix). Declaring them here too would
  # put two copies on PATH and make which(1) results depend on ordering.
  home.packages = [ ];

  # Shell env is NOT managed here on purpose. ~/.zshenv sources
  # agents/zsh/agents.env.zsh, which is already the single source of truth for
  # PATH and toolchain across interactive and agent-spawned shells. Enabling
  # programs.zsh would rewrite ~/.zshrc and fight it.

  # Individual files, never whole directories. These tools keep state next to
  # their config -- Zed's prompt library, herdr's socket -- and linking the
  # directory would hand that state to the repo, or lose it on the next switch.
  xdg.configFile = {
    "ghostty/config".source = link "config/ghostty/config";
    "zed/settings.json".source = link "config/zed/settings.json";
    "mise/config.toml".source = link "config/mise/config.toml";
    "herdr/config.toml".source = link "config/herdr/config.toml";
    "jj/config.toml".source = link "jj/config.toml";
  };

  # One memory file, every harness. Adding a new agent CLI means adding a line
  # here, not copying the rules again.
  home.file = {
    ".claude/CLAUDE.md".source = link "AGENTS.md";
    ".codex/AGENTS.md".source = link "AGENTS.md";
  };
}
