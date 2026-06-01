# /// script
# requires-python = ">=3.11"
# dependencies = ["textual>=0.80"]
# ///
"""Headless smoke test for dash.py — validates it composes and all panels exist (no TTY)."""

import asyncio
import importlib.util
import pathlib

# Resolve dash.py relative to this checkout, not ~/.config/agents — the repo isn't at the canonical
# path on a CI runner.
path = pathlib.Path(__file__).resolve().parents[1] / "tui" / "dash.py"
spec = importlib.util.spec_from_file_location("dashmod", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


async def main() -> None:
    app = mod.Dash()
    async with app.run_test() as pilot:
        await pilot.pause()
        for pid in mod.PANELS:
            app.query_one(f"#{pid}", mod.Panel)
        print(f"compose OK — {len(mod.PANELS)} panels present")


asyncio.run(main())
