# /// script
# requires-python = ">=3.11"
# dependencies = ["textual>=0.80"]
# ///
"""dash — interactive TUI control center for the agent environment.

Live panels (machines / health / MCP / CI / sessions) + action keys, composing the
existing CLIs (hcloud, agents-doctor, mcp-sync, gh, tmux). Launch: dash
"""

from __future__ import annotations

import os
import subprocess

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Grid
from textual.widgets import Footer, Header, Static

REPO = os.environ.get("AGENTS_REPO_SLUG", "KaelanRichards/agents")

_PATH = ":".join(
    [
        os.path.expanduser("~/.local/bin"),
        os.path.expanduser("~/.local/share/mise/shims"),
        os.path.expanduser("~/.cargo/bin"),
        "/opt/homebrew/bin",
        "/home/linuxbrew/.linuxbrew/bin",
        os.environ.get("PATH", ""),
    ]
)
ENV = {**os.environ, "PATH": _PATH}

# panel id -> (title, shell command)
PANELS: dict[str, tuple[str, str]] = {
    "machines": (
        "Machines (Hetzner)",
        "hcloud server list 2>/dev/null || echo '(set HCLOUD_TOKEN)'",
    ),
    "health": ("Health", "agents-doctor 2>/dev/null | tail -1"),
    "mcp": ("MCP servers", "mcp-sync list 2>/dev/null"),
    "ci": (
        "Repo / CI",
        f"gh run list --repo {REPO} -L 4 2>/dev/null | cut -f1-4; "
        f"echo '--- open PRs ---'; gh pr list --repo {REPO} 2>/dev/null || echo none",
    ),
    "sessions": ("Sessions (tmux)", "tmux ls 2>/dev/null || echo '(none)'"),
}


def sh(cmd: str, timeout: int = 25) -> str:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=ENV
        )
        return (r.stdout or r.stderr or "(no output)").strip()
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


class Panel(Static):
    pass


class Dash(App):
    TITLE = "agents · dash"
    CSS = """
    Grid { grid-size: 2; grid-rows: auto 1fr 1fr; grid-gutter: 1; padding: 1; }
    Panel { border: round $accent; padding: 0 1; }
    #machines { column-span: 2; }
    """
    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("s", "sync", "Sync"),
        ("d", "doctor", "Doctor"),
        ("g", "grafana", "Grafana"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Grid():
            for pid, (title, _cmd) in PANELS.items():
                yield Panel(f"[b]{title}[/b]\n…loading", id=pid)
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_all()
        self.set_interval(15, self.refresh_all)

    def _set_panel(self, pid: str, title: str, out: str) -> None:
        self.query_one(f"#{pid}", Panel).update(f"[b]{title}[/b]\n{out}")

    @work(thread=True, exclusive=True, group="refresh")
    def refresh_all(self) -> None:
        for pid, (title, cmd) in PANELS.items():
            out = sh(cmd)
            self.call_from_thread(self._set_panel, pid, title, out)

    def action_refresh(self) -> None:
        self.notify("refreshing…")
        self.refresh_all()

    @work(thread=True)
    def action_sync(self) -> None:
        sh("mcp-sync && agents-sync")
        self.call_from_thread(self.notify, "mcp-sync + agents-sync done")
        self.call_from_thread(self.refresh_all)

    @work(thread=True)
    def action_doctor(self) -> None:
        out = sh("agents-doctor 2>/dev/null | tail -1")
        self.call_from_thread(self.notify, out)

    def action_grafana(self) -> None:
        sh("obs open >/dev/null 2>&1 || open http://localhost:3000 >/dev/null 2>&1 &")
        self.notify("opening Grafana (localhost:3000)…")


if __name__ == "__main__":
    Dash().run()
