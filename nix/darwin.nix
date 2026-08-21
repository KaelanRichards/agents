{
  username,
  ...
}:
{
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

  system.defaults = {
    NSGlobalDomain = {
      AppleInterfaceStyle = "Dark";
      ApplePressAndHoldEnabled = false;
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
    };

    finder = {
      FXPreferredViewStyle = "Nlsv";
      AppleShowAllExtensions = true;
      ShowPathbar = true;
      FXEnableExtensionChangeWarning = false;
      CreateDesktop = false;
    };

    trackpad = {
      Clicking = true;
      TrackpadThreeFingerDrag = false;
    };

    screencapture.location = "/Users/${username}/Downloads";
  };

  homebrew = {
    enable = true;
    onActivation = {
      autoUpdate = true;
      upgrade = true;
      cleanup = "zap";
    };

    brews = [
      "chezmoi"
      "mise"
    ];

    casks = [
      "1password-cli"
      "font-jetbrains-mono-nerd-font"
      "gcloud-cli"
      "ghostty"
      "orbstack"
      "zed"
    ];
  };
}
