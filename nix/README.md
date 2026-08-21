# nix — the Mac, declared

Everything installed and configured on the Mac is written down here. Apply it with
`rebuild`. A fresh machine needs Determinate Nix, a clone of this repo, and one command.

| File          | Holds                                                            |
| ------------- | ---------------------------------------------------------------- |
| `flake.nix`   | Pinned inputs: nixpkgs, nix-darwin, home-manager, nix-homebrew    |
| `darwin.nix`  | macOS settings and the full Homebrew list                        |
| `home.nix`    | Config symlinks into this repo                                   |

All four inputs are pinned to stable **26.05**. Bump them together, never one at a time.

## Commands

```bash
rebuild              # build and switch; asks for your sudo password
rebuild --check      # build only, change nothing, no sudo
rebuild --zap-dry    # list packages cleanup would add or remove
```

`rebuild --check` is safe to run any time and is the fastest way to find a syntax or
option error.

## Adding a package

Add it to `brews` or `casks` in `darwin.nix`, then run `rebuild`. Do not `brew install`
by hand — see the cleanup note below.

## Homebrew cleanup is set to "zap"

`darwin.nix` sets `cleanup = "zap"`, so Homebrew deletes every package not declared here
on each rebuild. That is the point: it turns drift into an error instead of a slow mess.
It is also the setting that can delete something you wanted.

Run `rebuild --zap-dry` before applying a change and read the removal list. It reports both
directions — what would be removed, and what would be installed.

`tmux` and `zellij` were removed when this was switched on. Their configs are archived at
`~/.config/_archive/`; `brew install tmux` and a copy back is all it takes to return.

## Deliberate gaps

This repo is **public**, so config holding credentials is not tracked and this machine is
not fully reproducible by design:

- `gh` (OAuth token), `gcloud`, `op`, `agents-secrets`, `gdrive-mcp` — excluded.
- Claude Code installs and updates itself under `~/.local/share/claude`. Declaring it in
  Homebrew would fight its updater.
- Ghostty was installed by hand before this config existed and was handed to Homebrew with
  `brew install --cask --adopt ghostty`. Nothing more to do; noted because the same trick
  is what any other hand-installed app will need.
- The Linux VM is provisioned from the root `Brewfile` via `bootstrap.sh`, not from here.
  nix-darwin's Homebrew module does not run on Linux. A tool wanted on both machines has
  to be added in both places.

## Why mise is still here

Nix pins one version of a runtime per machine. `mise` reads `.nvmrc` and `.node-version`
per repository, which is what moving between projects actually needs. Nix declares mise;
mise picks the runtime. Moving node and python into Nix would trade a working per-repo
setup for a worse one.
