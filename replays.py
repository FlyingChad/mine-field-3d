"""Replays and run recaps.

A `Recorder` follows one round (or one whole Descent run) of a room. Every message the room
broadcasts goes through `add()`: it is kept, already serialised, with its time since the start, and
the recap (per-player stats, a score timeline and the key moments) is tallied from it as it goes.
A replay file is just those messages, opening with a spectator `welcome` and a `roster`, so the
browser plays it back by feeding them to the same `handle()` it uses for a live room.

Private messages (`send_to`: radar, profiles, a player's own welcome with its resume token) never
pass through here, so a replay holds only what any spectator could have seen.

`Replays` keeps the newest MAX_REPLAYS files in <data>/replays as gzipped JSON, plus an index.
"""
import gzip
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

MAX_REPLAYS = 60             # files kept on disk (oldest deleted first)
MAX_SECONDS = 60 * 60        # stop recording messages after this long (the recap keeps counting)
MAX_BYTES = 40_000_000       # ... or after this much JSON
TICK_EVERY = 2               # keep every 2nd 15 Hz `players` tick (the client smooths movement)
SAMPLE_SECONDS = 4.0         # score timeline resolution for the recap
MAX_SAMPLES = 150
MAX_MOMENTS = 80
MIN_SECONDS = 10             # shorter rounds aren't worth a replay
ID_RE = re.compile(r"^[0-9a-f]{12}$")


class Recorder:
    def __init__(self, welcome, roster, meta):
        self.t0 = time.time()
        self.id = secrets.token_hex(6)
        self.meta = dict(meta)
        self.parts = []          # "[t,msg]" strings
        self.size = 0
        self.ticks = 0
        self.truncated = False
        self.names = {}          # pid -> {name, color, bot}
        self.stats = {}          # pid -> counters
        self.moments = []        # [t, kind, text, pid|None]
        self.samples = []        # [t, {pid: score}]
        self.next_sample = 0.0
        self.last_scores = {}
        self._keep(0.0, json.dumps(welcome, separators=(",", ":")))
        self.add(roster)

    def now(self):
        return time.time() - self.t0

    def _keep(self, t, data):
        if self.truncated:
            return
        if t > MAX_SECONDS or self.size > MAX_BYTES:
            self.truncated = True
            return
        s = f"[{t:.2f},{data}]"
        self.parts.append(s)
        self.size += len(s) + 1

    def add(self, msg, data=None):
        t = self.now()
        kind = msg.get("t")
        if kind == "players":
            self.ticks += 1
            self._tally_scores(t, msg)
            if self.ticks % TICK_EVERY:
                return
        self._keep(t, data if data is not None else json.dumps(msg, separators=(",", ":")))
        self._tally(t, kind, msg)

    # ---------------------------------------------------------------- recap
    def _st(self, pid):
        return self.stats.setdefault(pid, {"tiles": 0, "mines": 0, "kos": 0, "pvpKos": 0, "bossDmg": 0,
                                           "bossKills": 0, "items": 0, "spikes": 0, "used": 0})

    def _who(self, pid):
        return (self.names.get(pid) or {}).get("name", "Someone")

    def _moment(self, t, kind, text, pid=None):
        if len(self.moments) < MAX_MOMENTS:
            self.moments.append([round(t, 1), kind, text, pid])

    def _tally_scores(self, t, msg):
        self.last_scores = {row[0]: row[4] for row in msg.get("p", [])}
        if t >= self.next_sample:
            self.samples.append([round(t, 1), dict(self.last_scores)])
            self.next_sample = t + SAMPLE_SECONDS
            if len(self.samples) > MAX_SAMPLES:          # long run: halve the resolution
                self.samples = self.samples[::2]
                self.next_sample = t + SAMPLE_SECONDS * 2

    def _tally(self, t, kind, m):
        pid = m.get("pid")
        if kind == "roster":
            for r in m.get("players", []):
                self.names[r["id"]] = {"name": r["name"], "color": r["color"], "bot": bool(r.get("bot"))}
                self._st(r["id"])
        elif kind == "reveal" and pid:
            self._st(pid)["tiles"] += len(m.get("tiles", []))
        elif kind == "boom" and pid:
            self._st(pid)["mines"] += 1
            self._moment(t, "boom", f"{self._who(pid)} hit a mine", pid)
        elif kind == "ko" and pid:
            self._st(pid)["kos"] += 1
            by = m.get("by")
            if by and by != pid:
                self._st(by)["pvpKos"] += 1
                self._moment(t, "ko", f"{self._who(by)} knocked out {self._who(pid)}", by)
            else:
                self._moment(t, "ko", f"{self._who(pid)} was knocked out", pid)
        elif kind == "bossHit" and m.get("by"):
            self._st(m["by"])["bossDmg"] += m.get("dmg", 0)
        elif kind == "bossSpawn":
            self._moment(t, "boss", f"{'An elite' if m.get('elite') else 'A'} {m.get('name', 'boss')} appeared")
        elif kind == "relic" and pid:
            self._moment(t, "relic", f"{self._who(pid)} took the {m.get('name', 'relic')}", pid)
        elif kind == "phoenix" and pid:
            self._moment(t, "phoenix", f"{self._who(pid)}'s Phoenix Feather saved them", pid)
        elif kind == "bossDown":
            k = m.get("killer")
            if k:
                self._st(k)["bossKills"] += 1
            self._moment(t, "bossDown", f"{self._who(k) if k else 'The team'} defeated the {m.get('name', 'boss')}", k)
        elif kind == "pickup" and pid and not m.get("perk"):
            self._st(pid)["items"] += 1
            if m.get("kind") == "key":
                self._moment(t, "key", f"{self._who(pid)} found the vault key", pid)
            elif m.get("kind") == "chest":
                self._moment(t, "chest", f"{self._who(pid)} opened the treasure chest", pid)
        elif kind == "door":
            self._moment(t, "door", f"{self._who(pid)} unlocked the vault", pid)
        elif kind == "spike" and pid and not m.get("shielded"):
            self._st(pid)["spikes"] += 1
        elif kind in ("throw", "zap", "shock", "blink") and pid:
            self._st(pid)["used"] += 1
        elif kind == "stairs":
            self._moment(t, "stairs", f"Floor {m.get('depth')} cleared")
        elif kind == "round" and m.get("depth"):
            self._moment(t, "floor", f"Down to floor {m['depth']}")

    def recap(self):
        """What the results screen shows: who did what, scores over time and the key moments."""
        samples = self.samples + [[round(self.now(), 1), dict(self.last_scores)]]
        players = []
        for pid, info in self.names.items():
            players.append({"id": pid, **info, **self._st(pid),
                            "score": self.last_scores.get(pid, 0)})
        players.sort(key=lambda p: -p["score"])
        return {"id": self.id, "duration": round(self.now(), 1), "players": players,
                "series": {"t": [s[0] for s in samples],
                           "scores": {p["id"]: [s[1].get(p["id"]) for s in samples] for p in players}},
                "moments": self.moments, "truncated": self.truncated}

    def finish(self, extra_meta):
        self.meta.update(extra_meta)
        self.meta.update({"id": self.id, "ended": time.time(), "duration": round(self.now(), 1),
                          "truncated": self.truncated})
        head = json.dumps({"v": 1, "meta": self.meta, "recap": self.recap()}, separators=(",", ":"))
        return head[:-1] + ',"events":[' + ",".join(self.parts) + "]}"


class Replays:
    def __init__(self, folder):
        self.dir = Path(folder)
        self.lock = threading.Lock()
        self.index = []
        try:
            self.index = json.loads((self.dir / "index.json").read_text("utf-8"))
        except (OSError, ValueError):
            self.index = []
        self.index = [e for e in self.index if isinstance(e, dict) and ID_RE.match(str(e.get("id", "")))]

    def save(self, rec, extra_meta):
        """Write a finished recording (blocking: run it in a thread). Returns its id, or None."""
        if rec.now() < MIN_SECONDS:
            return None
        body = rec.finish(extra_meta).encode("utf-8")
        with self.lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / f"{rec.id}.json.gz"
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(gzip.compress(body, 6))
            os.replace(tmp, path)
            self.index.insert(0, rec.meta)
            for old in self.index[MAX_REPLAYS:]:
                try:
                    (self.dir / f"{old['id']}.json.gz").unlink()
                except OSError:
                    pass
            self.index = self.index[:MAX_REPLAYS]
            itmp = self.dir / "index.tmp"
            itmp.write_text(json.dumps(self.index, separators=(",", ":")), "utf-8")
            os.replace(itmp, self.dir / "index.json")
        return rec.id

    def path(self, rid):
        if not ID_RE.match(rid or ""):
            return None
        p = self.dir / f"{rid}.json.gz"
        return p if p.is_file() else None

    def list(self, n=20):
        return self.index[:n]
