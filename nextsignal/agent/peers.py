"""Peer selection. Screener's own 'peers' block follows its industry tags and returned a contract
manufacturer and a sugar/ethanol company for HUL, which made the peer check meaningless. We use the
Track C peer universe instead, and fall back to Screener peers only if they are inside the universe."""
from __future__ import annotations
import json
import pathlib
import re

_UNIVERSE = json.loads((pathlib.Path(__file__).resolve().parent.parent / "data" / "track_universe.json").read_text(encoding="utf-8"))
_GROUPS = {k: v for k, v in _UNIVERSE.items() if not k.startswith("_")}


def symbol_from_url(url: str) -> str:
    m = re.search(r"/company/([A-Z0-9&-]+)/", url or "")
    return m.group(1) if m else ""


def pick_peers(symbol: str, screener_peers: list[str], limit: int = 5) -> tuple[list[str], str]:
    for name, members in _GROUPS.items():
        if symbol in members:
            return [m for m in members if m != symbol][:limit], f"universe group '{name}'"
    everyone = {m for g in _GROUPS.values() for m in g}
    filt = [p for p in screener_peers if p in everyone and p != symbol]
    if filt:
        return filt[:limit], "screener peers restricted to the track universe"
    return [], "no comparable peers found in the track universe; peer check skipped"
