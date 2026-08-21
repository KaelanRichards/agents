# agents

A small, portable development environment for macOS, Linux, Windows, and WSL.

The repository deliberately does not implement an agent runtime. Claude Code, Codex, and future clients keep responsibility for reasoning, sandboxing, approvals, OAuth, MCP, plugins, and session state.

## What is here

- [chezmoi](https://www.chezmoi.io/) deploys the same dotfiles on every host.
- [mise](https://mise.jdx.dev/) installs pinned runtimes, agent CLIs, and developer tools from a cross-platform checksum lockfile.
- Native Codex and Claude instruction files contain a small shared policy.
- A standard [Development Container](https://containers.dev/) provides an optional isolated Linux environment.
- nix/ is an optional macOS host layer for system settings and GUI applications. Nix is not required on Linux, Windows, or WSL.

There are no custom MCP servers, permission brokers, shell guards, OAuth bridges, workflow engines, VM controllers, or memory services.

## Install

Install mise first using its [official platform instructions](https://mise.jdx.dev/installing-mise.html):

~~~sh
# macOS
brew install mise

# Ubuntu 26.04+
sudo add-apt-repository -y ppa:jdxcode/mise
sudo apt update && sudo apt install -y mise
~~~

~~~powershell
# Windows
winget install jdx.mise
~~~

Then install chezmoi through mise and apply this repository:

~~~sh
mise use --global chezmoi@2.70.5
chezmoi init --apply KaelanRichards/agents
mise install
~~~

The same three commands work in PowerShell. Restart the shell after the first apply so mise activation is loaded.

Authenticate clients separately with their native login commands. Add MCP servers or connectors directly in the client that uses them; only enable integrations needed for the current workflow.

## Daily use

~~~sh
chezmoi diff       # preview dotfile changes
chezmoi apply      # apply them
chezmoi update     # pull this repo and apply
mise install       # install pinned tools
mise outdated      # inspect available updates
mise doctor        # diagnose environment problems
~~~

## Platform model

| Layer | macOS | Linux | Windows | WSL |
|---|---|---|---|---|
| Dotfiles | chezmoi | chezmoi | chezmoi | chezmoi |
| CLI tools | mise | mise | mise | mise |
| Shell | zsh | zsh | PowerShell | zsh |
| Agent isolation | native client sandbox | native client sandbox/container | native Windows sandbox | Linux sandbox/container |
| Host configuration | optional nix-darwin | system package manager | winget/system settings | Linux adapter |

The home/ directory is the chezmoi source root. Platform-specific files are selected in home/.chezmoiignore; no installation script edits files imperatively.

## macOS host configuration

The Nix layer only owns macOS settings, Homebrew itself, the two bootstrap tools (mise and chezmoi), and GUI applications. Command-line tools come from mise on every platform.

~~~sh
nix build ./nix#darwinConfigurations.mac.system --no-link
sudo darwin-rebuild switch --flake ./nix#mac
~~~

Apply chezmoi and run mise install before the first Nix switch; Homebrew cleanup removes undeclared command-line packages.

## Updating the environment

- Change tool versions in home/dot_config/mise/config.toml and refresh the adjacent mise.lock for all supported platforms.
- Change portable dotfiles under home/.
- Change macOS settings or GUI applications under nix/.
- Keep service credentials, OAuth tokens, client caches, and machine-local integration config outside the repository.

CI renders the chezmoi source on macOS, Linux, and Windows and validates the mise tool manifest without installing the full toolchain.
