"""Small JSON stores that survive server restarts:

  Profiles - per-browser stats (rounds, wins, tiles, bosses, ...) that unlock cosmetic hats
  Daily    - the daily dungeon leaderboard (best scores and fastest clears, per day)

Files live in data/ next to this file, or in $MF3D_DATA. A profile is keyed by a random token the
browser makes and keeps in localStorage; the token works like a password for that profile, so the
server never broadcasts it. Nothing here is otherwise private: names and scores are public anyway.
"""
import json
import os
import re
import time
from pathlib import Path

DATA = Path(os.environ.get("MF3D_DATA") or Path(__file__).parent / "data")
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_PROFILES = 20000

# hat id -> (name, stat, amount needed, how to unlock). Ids must match HATS in static/hats.js.
HATS = {
    "party":  ("Party hat", "rounds",    3,   "Play 3 rounds"),
    "beanie": ("Beanie",    "tiles",     500, "Reveal 500 tiles"),
    "flower": ("Flower",    "daily",     1,   "Finish a daily dungeon"),
    "horns":  ("Horns",     "bosses",    1,   "Land the killing blow on a boss"),
    "tophat": ("Top hat",   "flags",     100, "Flag 100 mines correctly"),
    "crown":  ("Crown",     "wins",      3,   "Win 3 rounds against other players"),
    "halo":   ("Halo",      "coop_wins", 2,   "Clear 2 co-op dungeons"),
    "lantern": ("Lantern",  "deepest",   5,   "Reach floor 5 in a descent"),
}
STATS = ["rounds", "wins", "coop_wins", "tiles", "flags", "mines", "bosses", "kos", "daily", "best",
         "deepest", "descents"]


def unlocked(prof):
    return [h for h, (_, stat, need, _) in HATS.items() if prof and prof.get(stat, 0) >= need]


def public(prof):
    """What the owner of a profile may see about it (sent only to them)."""
    return {"stats": {k: (prof or {}).get(k, 0) for k in STATS}, "unlocked": unlocked(prof),
            "hats": [{"id": h, "name": n, "stat": s, "need": need, "how": how} for h, (n, s, need, how) in HATS.items()]}


class JsonFile:
    def __init__(self, path):
        self.path = Path(path)
        self.dirty = False
        try:
            self.data = json.loads(self.path.read_text("utf-8"))
            if not isinstance(self.data, dict):
                self.data = {}
        except (OSError, ValueError):
            self.data = {}

    def save(self, force=False):
        if not (self.dirty or force):
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, separators=(",", ":")), "utf-8")
        os.replace(tmp, self.path)   # atomic: a crash mid-save never leaves a half-written file
        self.dirty = False


class Profiles(JsonFile):
    def peek(self, token):
        return self.data.get(token) if isinstance(token, str) and TOKEN_RE.match(token) else None

    def get(self, token, name=None):
        """The profile for a token, created on first use. None for a malformed token (or when full)."""
        if not isinstance(token, str) or not TOKEN_RE.match(token):
            return None
        prof = self.data.get(token)
        if prof is None:
            if len(self.data) >= MAX_PROFILES:
                return None
            prof = self.data[token] = {}
        for k in STATS:
            prof.setdefault(k, 0)
        if name:
            prof["name"] = name
        prof["seen"] = int(time.time())
        self.dirty = True
        return prof

    def bump(self, prof, best=None, deepest=None, **inc):
        """Add to a profile's stats (best score and deepest floor keep their maximum); returns the
        hats this unlocked."""
        before = set(unlocked(prof))
        for k, v in inc.items():
            prof[k] = prof.get(k, 0) + v
        if best is not None:
            prof["best"] = max(prof.get("best", 0), best)
        if deepest is not None:
            prof["deepest"] = max(prof.get("deepest", 0), deepest)
        self.dirty = True
        return [h for h in unlocked(prof) if h not in before]


class Descents(JsonFile):
    """Records of descent runs: how deep each team got. Keeps the best MAX_ROWS runs ever."""
    MAX_ROWS = 300

    def record(self, team, depth, score, secs, date=None):
        rows = self.data.setdefault("runs", [])
        rows.append({"team": team[:12], "depth": depth, "score": score, "secs": secs,
                     "date": date or time.strftime("%Y-%m-%d"), "at": int(time.time())})
        rows.sort(key=lambda r: (-r["depth"], -r["score"], r["secs"]))
        del rows[self.MAX_ROWS:]
        self.dirty = True

    def board(self, n=10, date=None):
        rows = self.data.get("runs", [])
        today = [r for r in rows if r["date"] == (date or time.strftime("%Y-%m-%d"))]
        return {"all": rows[:n], "today": today[:n]}


class Daily(JsonFile):
    KEEP_DAYS = 14
    MAX_ROWS = 500

    def record(self, date, name, score, secs, char="", color="", players=1):
        rows = self.data.setdefault(date, [])
        rows.append({"name": name, "score": score, "secs": secs, "char": char, "color": color,
                     "players": players, "at": int(time.time())})
        if len(rows) > self.MAX_ROWS:
            rows.sort(key=lambda r: -r["score"])
            del rows[self.MAX_ROWS:]
        for old in sorted(self.data)[:-self.KEEP_DAYS]:
            del self.data[old]
        self.dirty = True

    def board(self, date, n=10):
        """Best score and fastest clear per name for one day."""
        best, fast = {}, {}
        for r in self.data.get(date, []):
            k = r["name"].lower()
            if k not in best or r["score"] > best[k]["score"]:
                best[k] = r
            if k not in fast or r["secs"] < fast[k]["secs"]:
                fast[k] = r
        pick = lambda r: {"name": r["name"], "score": r["score"], "secs": r["secs"], "color": r.get("color", "")}
        return {"scores": [pick(r) for r in sorted(best.values(), key=lambda r: (-r["score"], r["secs"]))[:n]],
                "times": [pick(r) for r in sorted(fast.values(), key=lambda r: (r["secs"], -r["score"]))[:n]]}
