{
  pkgs,
  username,
  ...
}:
{
  # Determinate Nix owns the daemon and /etc/nix/nix.conf. nix-darwin must not
  # try to manage the installation or the two fight over the same files.
  nix.enable = false;

  nixpkgs.hostPlatform = "aarch64-darwin";
  nixpkgs.config.allowUnfree = true;

  system.primaryUser = username;
  system.stateVersion = 6;

  users.users.${username} = {
    name = username;
    home = "/Users/${username}";
  };

  programs.zsh.enable = true;

  #### macOS settings ########################################################
  # Everything here replaces a click-through in System Settings.

  system.defaults = {
    NSGlobalDomain = {
      AppleInterfaceStyle = "Dark";
      ApplePressAndHoldEnabled = false; # key repeat instead of accent popup
      KeyRepeat = 2;
      InitialKeyRepeat = 15;
      AppleShowAllExtensions = true;
      _HIHideMenuBar = true;
      "com.apple.trackpad.scaling" = 3.0;
    };

    dock = {
      autohide = true;
      show-recents = false;
      mru-spaces = false;
      # Keep the desktop empty; files live in the filesystem, not on a backdrop.
      static-only = false;
    };

    finder = {
      FXPreferredViewStyle = "Nlsv"; # list view
      AppleShowAllExtensions = true;
      ShowPathbar = true;
      FXEnableExtensionChangeWarning = false;
      CreateDesktop = false; # clean desktop
    };

    trackpad = {
      Clicking = true; # tap to click
      TrackpadThreeFingerDrag = true;
    };

    screencapture.location = "/Users/${username}/Downloads";
  };

  #### Homebrew ##############################################################
  # Full inventory is declared here, and cleanup = "zap" deletes anything that
  # is not. Installing by hand no longer sticks: the next rebuild removes it.
  # Add the package to brews or casks below, then run `rebuild --zap-dry` to
  # see what a change would add or remove before applying it.

  homebrew = {
    enable = true;
    onActivation = {
      autoUpdate = true;
      upgrade = true;
      cleanup = "zap";
    };

    brews = [
      "actionlint"
      "ast-grep"
      "awscli"
      "bat"
      "biome"
      "entr"
      "eza"
      "fd"
      "fzf"
      "gh"
      "git-delta"
      "gron"
      "hcloud"
      "herdr" # agent multiplexer; replaces tmux + zellij
      "hyperfine"
      "jj"
      "jq"
      "just"
      "mise" # retained: per-repo runtime switching Nix does not do
      "pandoc"
      "ripgrep"
      "ruff"
      "scc"
      "sd"
      # Currently pulled in as an actionlint dependency. Declared explicitly
      # because the shell workflow depends on it directly.
      "shellcheck"
      "shfmt"
      "starship"
      "tree"
      "ttyd"
      "uv"
      "watchexec"
      "xh"
      "yq"
    ];

    casks = [
      "1password-cli"
      "font-jetbrains-mono-nerd-font"
      "gcloud-cli"
      # Ghostty was installed by hand before this config existed. It was handed
      # to Homebrew once with `brew install --cask --adopt ghostty`, so the
      # cask now owns the existing app rather than refusing to overwrite it.
      "ghostty"
      "orbstack"
      "zed"
    ];
  };
}
