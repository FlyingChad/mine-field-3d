"""Shared setup for the tests: import the server with its data files in a throwaway folder."""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = tempfile.mkdtemp(prefix="mf3d-tests-")
os.environ["MF3D_DATA"] = TMP          # profiles / daily leaderboard go here, never into data/
sys.path.insert(0, str(ROOT))

import server as S  # noqa: E402
import store  # noqa: E402

S.profiles = store.Profiles(Path(TMP) / "profiles.json")
S.daily_board = store.Daily(Path(TMP) / "daily.json")


class FakeWS:
    """Stands in for a WebSocket: records every message the server sends."""

    def __init__(self):
        self.msgs = []

    async def send_str(self, s):
        self.msgs.append(json.loads(s))

    async def close(self):
        pass

    def of(self, t):
        return [m for m in self.msgs if m["t"] == t]


def at(p, x, y):
    p.x, p.z = S.tile_center(x, y)


def player(room, name="A", color="#fff", ws=None, **kw):
    p = S.Player(ws or FakeWS(), name, color, **kw)
    p.round_id = room.round_id
    room.players[p.id] = p
    return p


def field_room(mode="race", name="t"):
    """A whole-grid field (every tile is floor), so fixed coordinates are always valid."""
    old = S.FIELD_SIZE
    S.FIELD_SIZE = S.W
    try:
        return S.Room(name, "meadow", "field", mode)
    finally:
        S.FIELD_SIZE = old


def vault_room(**kw):
    for _ in range(50):
        r = S.Room("v", "meadow", "dungeon", **kw)
        if r.doors:
            return r
    raise AssertionError("no dungeon with a vault in 50 tries")
