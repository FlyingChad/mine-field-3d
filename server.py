"""Mine Field 3D - multiplayer competitive minesweeper server.

Run:  .venv\\Scripts\\python server.py   (then open http://localhost:8080)
Players on your network can join via http://<your-ip>:8080
"""
import asyncio
import json
import math
import random
import secrets
import time
from collections import deque
from pathlib import Path

from aiohttp import WSMsgType, web

import layouts
import store

ROOT = Path(__file__).parent
STATIC = ROOT / "static"

W, H = 48, 48          # grid size in tiles; the layout decides which of them are floor
FIELD_SIZE = 32        # the "field" layout is a FIELD_SIZE x FIELD_SIZE square in the middle of the grid
MINE_DENSITY = 150 / 1024   # mines per floor tile (~15%, the classic 150 on 32x32)
MINES = 150            # only used before a room exists; rooms use Room.n_mines
TILE = 2.0             # world units per tile
REACH = 1              # tiles (Chebyshev) from the player's tile they can dig/flag: 1 = own tile + 8 neighbours
REACH_SLACK = 0.3      # extra tolerance (in tiles) for network lag when checking the player's position
STUN_SECONDS = 3.0
MINE_PENALTY = -10
FLAG_CORRECT = 3       # awarded at round end for each flag on a mine
FLAG_WRONG = -3        # charged when your flag is dug up and it was safe
NEXT_ROUND_DELAY = 12
TICK_HZ = 15
ACTION_COOLDOWN = 0.08

# power-ups: buried under random safe tiles, exposed when dug up, collected by walking onto them.
# Their effects are NOT simulated in ai/env.py (v3 only sees pickups as items; bots use held ones by heuristic).
ITEM_DENSITY = 28 / 1024    # power-ups per floor tile
ITEM_WEIGHTS = {"scatter": 4, "shield": 3, "radar": 3, "boots": 3,
                "freeze": 3, "gold": 3, "shockwave": 2, "blink": 3,
                "apple": 5, "potion": 2}
FOOD = {"apple": 25, "potion": 60}   # HP healed; food is only picked up when you are hurt
HELD = ["", "scatter", "freeze", "shockwave", "blink"]  # held items (used with G); the rest act on pickup
THROW_RANGE = 6        # tiles (Chebyshev) a scatter bomb can be thrown
SCATTER_RADIUS = 2     # 2 -> a 5x5 area is re-covered
SCATTER_MINES = 6      # fresh mines scattered into that area
SCATTER_FUSE = 1.6     # seconds between the throw and the blast
SCATTER_STUN = 1.5
RADAR_RADIUS = 4
RADAR_SECONDS = 8
BOOTS_SECONDS = 10
BOOTS_SPEED = 1.6      # movement multiplier (client movement; bots use it server-side)
FREEZE_RANGE = 10      # tiles the freeze beam travels
FREEZE_WIDTH = 0.9     # tiles: how close to the beam a player must be to get hit
FREEZE_SECONDS = 4.0
SHOCK_RADIUS = 3       # tiles (Euclidean) around the user
SHOCK_STUN = 1.5
BLINK_RANGE = 8        # tiles (Chebyshev) you can teleport
GOLD_SECONDS = 12
GOLD_MULT = 2          # reveal points multiplier while gold rush is active

# health: damage knocks you out at 0 HP; you lose points, sit out RESPAWN_SECONDS and respawn
# somewhere else at full health. Health is game-layer only and is not simulated in ai/env.py.
MAX_HP = 100
MINE_DAMAGE = 35
SCATTER_DAMAGE = 25
SHOCK_DAMAGE = 10
KO_PENALTY = -15
RESPAWN_SECONDS = 5.0

# boss monsters roam dungeon layouts (game-layer only; not in ai/env.py). They wander, chase players
# they can see, and wind up a telegraphed ground smash. Players hurt them with a melee attack and
# with power-ups; the killer gets a reward, everyone who helped gets points for their damage, and the
# boss drops loot. A new boss appears BOSS_RESPAWN seconds after one dies.
BOSS_KINDS = {
    "ogre":   {"name": "Ogre",   "hp": 300, "speed": 3.6, "damage": 30, "aggro": 7},
    "wraith": {"name": "Wraith", "hp": 180, "speed": 5.6, "damage": 20, "aggro": 9},
    "golem":  {"name": "Golem",  "hp": 450, "speed": 2.6, "damage": 40, "aggro": 6},
}
BOSS_FIRST_DELAY = 8.0     # seconds into a round before the first boss appears
BOSS_RESPAWN = 40.0
BOSS_REACH = 1.3           # tiles: starts its wind-up when a target is this close
BOSS_HIT_RANGE = 1.9       # tiles: the smash hits everyone this close when it lands
BOSS_WINDUP = 0.75
BOSS_COOLDOWN = 1.6
BOSS_SMASH_STUN = 0.8
ATTACK_DAMAGE = 12         # player melee
ATTACK_RANGE = 1.7         # tiles
ATTACK_COOLDOWN = 0.45
BOSS_KILL_REWARD = 40      # points to whoever lands the killing blow
BOSS_DAMAGE_POINTS = 10    # +1 point per this much damage dealt to a boss
BOSS_POWER_DAMAGE = {"scatter": 60, "shockwave": 40, "freeze": 20}

# game modes, chosen by whoever creates the room:
#   race - everyone for themselves, points decide (the original game)
#   pvp  - race, plus your melee hits other players and knocking someone out earns KO_REWARD
#   coop - one team against the dungeon: no friendly fire, no scatter bombs (they only undo the
#          team's progress), bosses scale with the team, and a shared pool of lives; run out and the
#          round is lost
MODES = ["race", "pvp", "coop", "descent"]
PVP_MELEE_DAMAGE = 15
PVP_MELEE_STUN = 0.35
KO_REWARD = 20
COOP_LIVES_BASE = 3           # team lives = this + 1 per player at round start (KOs cost one)
COOP_BOSS_HP_PER_PLAYER = 0.5 # boss HP x (1 + this * (players - 1))

# descent: co-op rules (one team, shared lives, no friendly fire, no scatter bombs) across a run of
# floors. Clearing a floor opens a staircase near whoever finished it; stepping on it (or waiting
# STAIRS_AUTO seconds) takes the whole team down to a bigger, deadlier floor in the next realm. Scores,
# held items and lives carry over; the run ends when the lives run out and goes on the records board.
DESCENT_REALMS = ["meadow", "jungle", "desert", "tundra", "reef", "spooky", "volcano", "candy", "neon", "moon"]
DESCENT_MINES_PER_FLOOR = 0.07   # mine density x (1 + this * (depth - 1)), capped at DESCENT_MAX_DENSITY
DESCENT_MAX_DENSITY = 0.21
DESCENT_BOSS_HP_PER_FLOOR = 0.2  # boss HP x (1 + this * (depth - 1)) on top of the team scaling
DESCENT_FLOORS_PER_BOSS = 3      # one more boss at once every this many floors (max 3)
FLOOR_BONUS = 10                 # every player gets this x the floor number for clearing it
DESCENT_LIFE_PER_FLOOR = 1       # lives gained for each floor cleared
STAIRS_AUTO = 30.0               # seconds before the team descends anyway
DESCEND_DELAY = 2.5              # seconds between stepping on the stairs and arriving below

# the stairs shop: while the stairs are open, each player may buy each of the floor's SHOP_OFFERS once,
# paying with their own points. Prices go up SHOP_PRICE_PER_FLOOR per floor.
SHOP = {
    "vitality": {"name": "Vitality", "cost": 40, "desc": "+20 max health for the rest of the run"},
    "shield":   {"name": "Shield",   "cost": 25, "desc": "Start the next floor with a shield"},
    "boots":    {"name": "Boots",    "cost": 20, "desc": "Start the next floor with 20 s of boots"},
    "radar":    {"name": "Radar",    "cost": 30, "desc": "A radar sweep where you land on the next floor"},
    "life":     {"name": "Spare life", "cost": 60, "desc": "+1 team life (one per floor, for the team)"},
    "supply":   {"name": "Supply drop", "cost": 30, "desc": "A random held power-up, right now"},
}
SHOP_OFFERS = 3
SHOP_PRICE_PER_FLOOR = 0.15      # cost x (1 + this * (depth - 1))
VITALITY_HP = 20
PERK_BOOTS = 20.0                # seconds of boots from the Boots perk

# floor modifiers: from floor 2 on, each descent floor rolls one twist (never the same twice in a row)
VOLATILE_DAMAGE = 50
MODIFIERS = {
    "dark":     {"name": "Darkness",        "desc": "You can only see what's close. Bring a light."},
    "unstable": {"name": "Unstable ground", "desc": "Every few seconds a patch of dug ground caves back in."},
    "rich":     {"name": "Rich veins",      "desc": "Every tile you dig is worth double points."},
    "swarm":    {"name": "Swarm",           "desc": "One more boss, but every boss is weaker."},
    "trove":    {"name": "Treasure trove",  "desc": "Twice as many power-ups buried."},
    "volatile": {"name": "Volatile",        "desc": f"Mines hit much harder ({VOLATILE_DAMAGE} damage)."},
}
SWARM_HP = 0.6
UNSTABLE_EVERY = 10.0            # seconds between cave-ins
UNSTABLE_RADIUS = 1              # 3x3 patches

# the dungeon vault: a side room sealed by a locked door (two door tiles across a corridor). A key is
# buried somewhere else in the dungeon; whoever carries it to the door opens it for everyone and earns
# VAULT_OPEN_REWARD. Inside wait a treasure chest (CHEST_POINTS) and extra loot. Door tiles are walls
# until opened, so bosses, bots and flood fill all treat them as walls. Game-layer only (not ai/env.py).
VAULT_MIN, VAULT_MAX = 24, 170   # floor tiles a vault may have
VAULT_LOOT = 4                   # extra power-ups buried in the vault
VAULT_OPEN_REWARD = 15
CHEST_POINTS = 30
KEY_BIT = 1 << 10                # fx bit: this player carries the key

# spike traps: buried under safe tiles like power-ups. Once dug up they cycle up and down and hurt
# anyone standing on them while they're up (shields absorb). Game-layer only (not ai/env.py).
TRAP_DENSITY = 10 / 1024         # traps per floor tile
SPIKE_CYCLE = 3.0                # seconds per up/down cycle
SPIKE_UP = 1.1                   # seconds of each cycle the spikes are up
SPIKE_DAMAGE = 15
SPIKE_STUN = 0.4
SPIKE_GRACE = 1.2                # seconds before the same player can be spiked again

# the daily dungeon: room "daily-YYYY-MM-DD" (today, server time) has the same layout, mines, loot and
# realm for everyone that day, and its results go on a leaderboard (store.Daily)
DAILY_PREFIX = "daily-"

# quick chat (the client holds the text for each id) and map pings
QUICK_CHAT = ["help", "boss", "nice", "follow", "gg", "oops"]
CHAT_COOLDOWN = 1.0

# connection safety, for playing over the internet
MAX_MSG_BYTES = 4096             # bigger WebSocket messages close the connection
RATE_PER_SEC = 40                # messages per second per connection (moves are ~15/s)
RATE_BURST = 80
RATE_KICK = 400                  # messages dropped by the rate limit before the connection is closed
RESUME_SECONDS = 45              # a dropped player can reconnect this long and keep their place
MAX_SPECTATORS = 24

COLORS = ["#ff5d5d", "#4fa3ff", "#ffd23f", "#4fd67a", "#c77dff", "#ff9f43",
          "#3ee6d6", "#ff6fb5", "#a3e635", "#f8fafc", "#94a3b8", "#fb7185"]
# must match REALMS in static/realms.js; a room's realm is chosen by whoever creates it
REALM_IDS = ["meadow", "desert", "tundra", "volcano", "moon", "candy", "jungle", "reef", "spooky", "neon"]
# must match the ids in static/characters.js
CHARACTER_IDS = {"miner", "robot", "knight", "wizard", "astronaut", "ninja",
                 "cat", "dino", "pirate", "ghost", "mushroom", "penguin",
                 "dragon", "mech", "alien", "viking", "skeleton", "bee"}


def idx(x, y):
    return y * W + x


def neighbors(x, y):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx or dy:
                nx, ny = x + dx, y + dy
                if 0 <= nx < W and 0 <= ny < H:
                    yield nx, ny


def tile_center(x, y):
    return (x - W / 2 + 0.5) * TILE, (y - H / 2 + 0.5) * TILE


class RateLimit:
    """Token bucket: `rate` messages per second on average, bursts up to `burst`."""

    def __init__(self, rate=RATE_PER_SEC, burst=RATE_BURST):
        self.rate, self.burst, self.tokens, self.t = rate, burst, float(burst), time.monotonic()
        self.dropped = 0

    def allow(self):
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.t) * self.rate)
        self.t = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        self.dropped += 1
        return False


class Player:
    is_bot = False

    def __init__(self, ws, name, color, char="miner", hat=""):
        self.id = secrets.token_hex(4)
        self.token = secrets.token_urlsafe(18)   # lets this player reconnect (resume) after a drop
        self.ws = ws
        self.name = name
        self.color = color
        self.char = char
        self.hat = hat
        self.profile = None       # store.Profiles entry (humans with a profile token only)
        self.round_id = 0
        self.last_chat = 0.0
        self.score = 0
        self.x = random.uniform(-W * TILE / 2 + 2, W * TILE / 2 - 2)
        self.z = random.uniform(-H * TILE / 2 + 2, H * TILE / 2 - 2)
        self.rot = 0.0
        self.stun_until = 0.0
        self.last_action = 0.0
        self.hp = self.max_hp = MAX_HP   # max_hp grows with the Vitality perk (descent)
        self.perks: set[str] = set()       # descent: perks bought for the next floor
        self.bought: set[str] = set()      # descent: shop offers bought on this floor
        self.ko_until = 0.0       # > 0 while knocked out
        self.reset_items()

    def reset_items(self):
        self.held = None          # one held item at a time: a kind from HELD
        self.shield = False
        self.boots_until = 0.0
        self.gold_until = 0.0
        self.frozen_until = 0.0
        self.throw_at = 0.0       # bots: when to try using the held item
        self.key = False          # carrying the vault key
        self.spike_until = 0.0    # spike traps can't hit again before this

    def fx(self, now):
        """Status bits for the tick message: 1 shield, 2 boots, 4 gold rush, 8 frozen, KEY_BIT key;
        (fx >> 4) & 15 is the index of the held item in HELD (0 = nothing)."""
        return ((1 if self.shield else 0) | (2 if now < self.boots_until else 0)
                | (4 if now < self.gold_until else 0) | (8 if now < self.frozen_until else 0)
                | (HELD.index(self.held) << 4 if self.held else 0) | (KEY_BIT if self.key else 0))

    def tile(self):
        return (int((self.x / TILE) + W / 2), int((self.z / TILE) + H / 2))

    def roster(self):
        return {"id": self.id, "name": self.name, "color": self.color, "char": self.char, "hat": self.hat}


class Spectator:
    """Watches a room: receives every broadcast, can't act, isn't on the roster."""
    is_bot = False

    def __init__(self, ws, name):
        self.id = "s" + secrets.token_hex(4)
        self.ws, self.name = ws, name


class NullWS:
    async def send_str(self, _):
        pass


BOT_SPEED = 7.0  # world units / second, same as a walking player
BOT_STEP_SECONDS = TILE / BOT_SPEED   # time a bot takes to walk one tile
GOAL_NEAR = 4    # v3 bots walk to a goal this close themselves (training puts the stairs 2-4 tiles away)


class Boss:
    STATES = {"wander": 0, "chase": 1, "windup": 2, "frozen": 3, "stunned": 4}

    def __init__(self, kind, x, z):
        self.id = "b" + secrets.token_hex(3)
        self.kind = kind
        s = BOSS_KINDS[kind]
        self.name, self.max_hp, self.speed, self.damage, self.aggro = s["name"], s["hp"], s["speed"], s["damage"], s["aggro"]
        self.hp = self.max_hp
        self.x, self.z, self.rot = x, z, 0.0
        self.state = "wander"
        self.path: list[tuple[int, int]] = []
        self.target = None
        self.next_path = 0.0
        self.windup_until = self.cooldown_until = self.frozen_until = self.stun_until = 0.0
        self.dmg_by: dict[str, int] = {}

    def tile(self):
        return (int((self.x / TILE) + W / 2), int((self.z / TILE) + H / 2))

    def row(self, now):
        st = "frozen" if now < self.frozen_until else "stunned" if now < self.stun_until else self.state
        return [self.id, self.kind, round(self.x, 2), round(self.z, 2), round(self.rot, 2), self.hp, self.max_hp,
                self.STATES[st]]


class BotPlayer(Player):
    """A server-side player driven by a trained network (ai/bots.py). Walks tile to tile and obeys
    exactly the same reach / cooldown / stun rules as humans because it calls the same Room methods."""
    is_bot = True

    def __init__(self, brain, name, color, char, difficulty, interval):
        super().__init__(NullWS(), name, color, char)
        self.brain, self.difficulty, self.interval = brain, difficulty, interval
        self.tx, self.tz = self.x, self.z   # Room.place() puts the bot on a floor tile
        self.next_think = 0.0

    def roster(self):
        return {**super().roster(), "bot": True, "model": self.brain.name, "difficulty": self.difficulty}


def today():
    return time.strftime("%Y-%m-%d")


def daily_name(date=None):
    return DAILY_PREFIX + (date or today())


def daily_realm(date):
    return random.Random("realm-" + date).choice(REALM_IDS)


class Room:
    def __init__(self, name, realm="meadow", layout="dungeon", mode="race", daily=None):
        self.name = name
        self.daily = daily            # a date string for the daily dungeon, else None
        if daily:                     # everyone gets the same race through the same dungeon today
            realm, layout, mode = daily_realm(daily), "dungeon", "race"
        self.realm = realm if realm in REALM_IDS else random.choice(REALM_IDS)
        self.layout_kind = layout if layout in layouts.LAYOUTS else "dungeon"
        self.mode = mode if mode in MODES else "race"
        self.players: dict[str, Player] = {}
        self.spectators: dict[str, Spectator] = {}
        self.away: dict[str, tuple] = {}   # resume token -> (player, expires): dropped players who may reconnect
        self.hold_until = time.time() + 60 # a new room (e.g. one the lab put bots in) waits for its first human
        self.round_task = None
        self.kos: list[str] = []
        self.depth = 1                     # descent: the floor the team is on
        if self.mode == "descent":
            self.layout_kind = "dungeon"
        self.new_round()

    # ---------- round lifecycle ----------
    def new_round(self, next_floor=False):
        """A fresh board. `next_floor` (descent) keeps the run going: same run, scores and lives."""
        if not next_floor:
            self.run_id = getattr(self, "run_id", 0) + 1   # resumes within a run keep their score
            self.depth = 1
            self.run_started = time.time()
        if self.mode == "descent":
            self.realm = DESCENT_REALMS[(self.depth - 1) % len(DESCENT_REALMS)]
        self.stairs = None                 # descent: the staircase tile once the floor is cleared
        self.stairs_auto = self.descend_at = 0.0
        # the daily dungeon replays one seeded layout all day; other dungeons are new every round
        self.rng = random.Random("mf3d-" + self.daily) if self.daily else random.Random()
        self.floor = layouts.make(self.layout_kind, W, H, rng=self.rng, field_size=(FIELD_SIZE, FIELD_SIZE))
        self.floor_tiles = [i for i in range(W * H) if self.floor[i]]
        self.vault: set[int] = set()       # floor tiles behind the locked door
        self.doors: list[int] = []         # the door tiles (walls while locked)
        self.vault_open = True
        if self.layout_kind == "dungeon":
            self.setup_vault()
        self.spawn_tiles = [i for i in self.floor_tiles if i not in self.vault]
        self.traps: dict[int, float] = {}  # tile index -> spike phase offset (seconds)
        density = MINE_DENSITY
        if self.mode == "descent":
            density = min(DESCENT_MAX_DENSITY, MINE_DENSITY * (1 + DESCENT_MINES_PER_FLOOR * (self.depth - 1)))
        self.n_mines = round(density * len(self.floor_tiles))
        self.mines = None            # set of tile indices, generated on first dig
        self.counts = None
        self.revealed = bytearray(W * H)
        self.flags: dict[int, str] = {}  # tile index -> player id
        self.booms: set[int] = set()
        self.safe_left = len(self.floor_tiles) - self.n_mines
        self.state = "playing"
        self.round_ends_at = None
        self.started_at = time.time()
        self.round_id = getattr(self, "round_id", 0) + 1
        self.buried: dict[int, str] = {}   # tile index -> item kind, still under a cover
        self.items: dict[int, str] = {}    # tile index -> item kind, lying on a revealed tile
        self.bomb_seq = 0
        self.bosses: dict[str, Boss] = {}
        self.next_boss_at = time.time() + BOSS_FIRST_DELAY
        if not next_floor:   # lives carry over from floor to floor in a descent
            self.lives = COOP_LIVES_BASE + len(getattr(self, "players", {}) or {})
        self.failed = False
        # descent: this floor's twist (none on floor 1, never the same twice running) and the shop
        prev = getattr(self, "modifier", None) if next_floor else None
        self.modifier = (random.choice([m for m in MODIFIERS if m != prev])
                         if self.mode == "descent" and self.depth >= 2 else None)
        self.next_crumble = 0.0
        self.shop: list[str] = []          # offer ids, set when the stairs open
        self.life_bought = False

    # ---------- descent ----------
    async def floor_cleared(self, p):
        """Every safe tile is dug up. Descent: open the stairs down; other modes: the round ends."""
        if self.mode != "descent":
            await self.end_round()
            return
        if self.stairs is not None:
            return
        x, y = p.tile() if self.is_floor(*p.tile()) else divmod(self.spawn_tiles[0], W)[::-1]
        spots = [t for t in self.bfs((x, y), max_depth=4)
                 if idx(*t) not in self.booms and idx(*t) not in self.traps and idx(*t) not in self.items]
        sx, sy = min(spots, key=lambda t: (max(abs(t[0] - x), abs(t[1] - y)) != 2, random.random())) if spots else (x, y)
        self.stairs = idx(sx, sy)
        self.stairs_auto = time.time() + STAIRS_AUTO
        bonus = FLOOR_BONUS * self.depth
        flagged = {}   # correct flags pay out here, since a descent round only "ends" when the run fails
        for i, pid in list(self.flags.items()):
            if i in self.mines and pid in self.players:
                flagged[pid] = flagged.get(pid, 0) + FLAG_CORRECT
                del self.flags[i]
        for q in self.players.values():
            q.score += bonus + flagged.get(q.id, 0)
            await self.stat(q, flags=flagged.get(q.id, 0) // FLAG_CORRECT)
        self.lives += DESCENT_LIFE_PER_FLOOR
        self.bosses.clear()                 # the floor's monsters flee
        self.next_boss_at = float("inf")
        self.shop = random.sample(list(SHOP), SHOP_OFFERS)
        for q in self.players.values():
            q.bought.clear()
        await self.broadcast({"t": "stairs", "x": sx, "y": sy, "depth": self.depth, "bonus": bonus,
                              "flags": flagged, "lives": self.lives, "auto": STAIRS_AUTO, "by": p.id,
                              "shop": [{"id": k, **SHOP[k], "cost": self.price(k)} for k in self.shop]})

    async def perk_tick(self):
        """Radar perks fire as soon as the new floor has mines to show."""
        if self.mines is None:
            return
        for p in self.players.values():
            if getattr(p, "radar_pending", False):
                p.radar_pending = False
                x, y = p.tile()
                near = [[m % W, m // W] for m in self.mines
                        if max(abs(m % W - x), abs(m // W - y)) <= RADAR_RADIUS + 2 and not self.revealed[m]]
                await self.send_to(p, {"t": "radar", "mines": near, "dur": RADAR_SECONDS})

    def price(self, k):
        return round(SHOP[k]["cost"] * (1 + SHOP_PRICE_PER_FLOOR * (self.depth - 1)))

    async def buy(self, p, k):
        """A shop purchase: only while the stairs are open, once per offer per player, paid in points."""
        if (self.stairs is None or self.descend_at or k not in self.shop or k in p.bought
                or (k == "life" and self.life_bought)):
            return
        cost = self.price(k)
        if p.score < cost or (k == "supply" and p.held):
            return
        p.score -= cost
        p.bought.add(k)
        if k == "vitality":
            p.max_hp += VITALITY_HP
            p.hp += VITALITY_HP
        elif k == "life":
            self.life_bought = True
            self.lives += 1
        elif k == "supply":
            p.held = random.choice([h for h in HELD if h and h != "scatter"])
        else:
            p.perks.add(k)            # shield / boots / radar: applied on the next floor
        await self.broadcast({"t": "bought", "pid": p.id, "id": k, "cost": cost, "lives": self.lives if k == "life" else None,
                              "held": p.held if k == "supply" else None})

    async def crumble(self, now):
        """Unstable ground: a 3x3 patch of dug-up ground away from everyone caves back in (no new mines)."""
        if self.modifier != "unstable" or self.mines is None or self.stairs is not None or now < self.next_crumble:
            return
        self.next_crumble = now + UNSTABLE_EVERY
        cand = [i for i in self.floor_tiles if self.revealed[i] and i not in self.booms]
        random.shuffle(cand)
        r = UNSTABLE_RADIUS
        for c in cand[:40]:
            cx, cy = c % W, c // W
            if any(max(abs(q.tile()[0] - cx), abs(q.tile()[1] - cy)) <= r + 1 for q in self.players.values()):
                continue
            area = [idx(x, y) for y in range(cy - r, cy + r + 1) for x in range(cx - r, cx + r + 1)
                    if self.is_floor(x, y) and self.revealed[idx(x, y)] and idx(x, y) not in self.booms
                    and idx(x, y) not in self.items and idx(x, y) not in self.traps and idx(x, y) != self.stairs]
            if len(area) < 3:
                continue
            for i in area:
                self.revealed[i] = 0
            self.safe_left += len(area)
            await self.broadcast({"t": "crumble", "tiles": [[i % W, i // W] for i in area], "safeLeft": self.safe_left,
                                  "x": cx, "y": cy})
            return

    async def check_stairs(self, now):
        if self.stairs is None or self.state != "playing":
            return
        if self.descend_at:
            if now >= self.descend_at:
                await self.next_floor()
            return
        by = next((q for q in self.players.values() if not q.ko_until and idx(*q.tile()) == self.stairs
                   and 0 <= q.tile()[0] < W), None)
        if by or now >= self.stairs_auto:
            self.descend_at = now + DESCEND_DELAY
            await self.broadcast({"t": "descending", "by": by.id if by else None, "depth": self.depth + 1,
                                  "in": DESCEND_DELAY})

    async def next_floor(self):
        self.depth += 1
        self.new_round(next_floor=True)
        spawns = {}
        now = time.time()
        for q in self.players.values():
            q.hp, q.ko_until, q.stun_until, q.frozen_until = q.max_hp, 0.0, 0.0, 0.0
            q.key, q.boots_until, q.gold_until = False, 0.0, 0.0   # held items and shields come along
            self.place(q)
            spawns[q.id] = [round(q.x, 2), round(q.z, 2)]
            # perks bought in the shop upstairs
            if "shield" in q.perks:
                q.shield = True
            if "boots" in q.perks:
                q.boots_until = now + PERK_BOOTS
            q.radar_pending = "radar" in q.perks    # sent once the floor's mines exist (first dig)
        for q in self.players.values():
            await self.stat(q, deepest=self.depth)
        await self.broadcast({"t": "round", "snapshot": self.snapshot(), "spawns": spawns, "depth": self.depth})
        for q in self.players.values():
            if "boots" in q.perks:
                await self.send_to(q, {"t": "pickup", "pid": q.id, "x": -1, "y": -1, "kind": "boots", "dur": PERK_BOOTS, "perk": True})
            q.perks.clear()

    # ---------- the vault ----------
    def setup_vault(self):
        """Seal off a side room: find a straight cross-section of a 2-wide corridor whose removal cuts
        a VAULT_MIN..VAULT_MAX tile region off from the rest of the dungeon (8-way, the way flood fill
        spreads), and turn those two tiles into a locked door."""
        cands = []
        for i in self.floor_tiles:
            x, y = i % W, i // W
            if self.is_floor(x, y + 1) and not self.is_floor(x, y - 1) and not self.is_floor(x, y + 2):
                cands.append((i, idx(x, y + 1)))        # across a horizontal corridor
            if self.is_floor(x + 1, y) and not self.is_floor(x - 1, y) and not self.is_floor(x + 2, y):
                cands.append((i, idx(x + 1, y)))        # across a vertical corridor
        self.rng.shuffle(cands)
        best = None
        for cut in cands[:120]:
            side = self._small_side(set(cut))
            if side and (best is None or abs(len(side) - 70) < abs(len(best[1]) - 70)):
                best = (cut, side)
        if not best:
            return
        self.doors, self.vault = list(best[0]), best[1]
        for d in self.doors:
            self.floor[d] = 0
        self.floor_tiles = [i for i in self.floor_tiles if i not in best[0]]
        self.vault_open = False

    def _small_side(self, cut):
        """The region on one side of `cut`, if it is vault-sized and the cut really separates it."""
        seeds = {j for c in cut for nx, ny in neighbors(c % W, c // W)
                 if self.floor[j := idx(nx, ny)] and j not in cut}
        for s in sorted(seeds):
            seen, stack = {s}, [s]
            while stack and len(seen) <= VAULT_MAX:
                i = stack.pop()
                for nx, ny in neighbors(i % W, i // W):
                    j = idx(nx, ny)
                    if self.floor[j] and j not in cut and j not in seen:
                        seen.add(j)
                        stack.append(j)
            if VAULT_MIN <= len(seen) <= VAULT_MAX and not stack and not seeds <= seen:
                return seen
        return None

    def locked_out(self, p, i):
        """True if tile i is inside the locked vault and p is outside it."""
        if self.vault_open or i not in self.vault:
            return False
        px, py = p.tile()
        return not (0 <= px < W and 0 <= py < H) or idx(px, py) not in self.vault

    async def check_doors(self):
        """Open the vault when the key carrier reaches the door; re-bury a lost key."""
        if self.vault_open or self.state != "playing" or self.mines is None:
            return
        holder = next((p for p in self.players.values() if p.key), None)
        if holder:
            hx, hy = holder.tile()
            if not holder.ko_until and any(max(abs(d % W - hx), abs(d // W - hy)) <= 1 for d in self.doors):
                await self.open_vault(holder)
        elif "key" not in self.buried.values() and "key" not in self.items.values():
            await self.bury_key()

    async def bury_key(self):
        spots = [i for i in self.spawn_tiles if i not in self.mines and not self.revealed[i]
                 and i not in self.buried and i not in self.traps and i not in self.items]
        if spots:
            self.buried[self.rng.choice(spots)] = "key"
            return
        spots = [i for i in self.spawn_tiles if i not in self.mines and i not in self.items and i not in self.booms]
        if spots:   # everything outside the vault is dug up: leave the key lying in the open
            i = random.choice(spots)
            self.items[i] = "key"
            await self.broadcast({"t": "drop", "pid": None, "x": i % W, "y": i // W, "kind": "key"})

    async def drop_key(self, q):
        """q (knocked out or gone) drops the key where they stand, or on the nearest free floor tile."""
        if not q.key:
            return
        q.key = False
        x, y = q.tile()
        spots = [(x, y)] if self.is_floor(x, y) else []
        spots += [t for t in self.bfs((x, y), max_depth=3)] if self.is_floor(x, y) else []
        spot = next((t for t in spots if idx(*t) not in self.items), None)
        if spot is None:
            await self.bury_key()
            return
        self.items[idx(*spot)] = "key"
        await self.broadcast({"t": "drop", "pid": q.id, "x": spot[0], "y": spot[1], "kind": "key"})

    async def open_vault(self, p):
        self.vault_open = True
        p.key = False
        for d in self.doors:
            self.floor[d] = 1
        self.floor_tiles = sorted(self.floor_tiles + self.doors)
        self.spawn_tiles = self.floor_tiles
        self.safe_left += len(self.doors)       # door tiles are never mines
        p.score += VAULT_OPEN_REWARD
        await self.broadcast({"t": "door", "pid": p.id, "tiles": [[d % W, d // W] for d in self.doors],
                              "reward": VAULT_OPEN_REWARD})
        await self.open_tiles(p, [(d % W, d // W) for d in self.doors])

    # ---------- spike traps ----------
    def spikes_up(self, i, now):
        return (now + self.traps[i]) % SPIKE_CYCLE < SPIKE_UP

    async def spikes(self, now):
        if self.state != "playing" or not self.traps:
            return
        for p in list(self.players.values()):
            if p.ko_until or now < p.spike_until:
                continue
            x, y = p.tile()
            i = y * W + x
            if not (0 <= x < W and 0 <= y < H) or i not in self.traps or not self.revealed[i] or not self.spikes_up(i, now):
                continue
            p.spike_until = now + SPIKE_GRACE
            shielded = self._absorb(p)
            if not shielded:
                p.stun_until = max(p.stun_until, now + SPIKE_STUN)
                self.hurt(p, SPIKE_DAMAGE, now)
            await self.broadcast({"t": "spike", "pid": p.id, "x": x, "y": y, "shielded": shielded,
                                  "dmg": 0 if shielded else SPIKE_DAMAGE, "stun": 0 if shielded else SPIKE_STUN})
            await self.flush_kos()

    # ---------- profiles (stats that unlock hats) ----------
    async def stat(self, p, best=None, deepest=None, **inc):
        if p is None or not p.profile:
            return
        new = profiles.bump(p.profile, best=best, deepest=deepest, **inc)
        if new:
            await self.send_to(p, {"t": "profile", **store.public(p.profile), "new": new})

    async def send_to(self, p, msg):
        try:
            await p.ws.send_str(json.dumps(msg, separators=(",", ":")))
        except Exception:
            pass

    @property
    def coop(self):
        """Team modes: co-op and descent share the rules (no friendly fire, shared lives, ...)."""
        return self.mode in ("coop", "descent")

    def hits_players(self):
        """Do player-made attacks (power-ups, melee) affect other players? Not in co-op."""
        return not self.coop

    # ---------- bosses ----------
    def boss_target_count(self):
        if self.layout_kind != "dungeon" or self.state != "playing" or self.stairs is not None:
            return 0
        n = 2 if len(self.players) >= 4 else 1
        if self.mode == "descent":   # deeper floors are more crowded
            n += min(2, (self.depth - 1) // DESCENT_FLOORS_PER_BOSS) + (self.modifier == "swarm")
        return n

    def walkable_step(self, x, y, dx, dy):
        """8-way step on floor that doesn't cut through a wall corner."""
        if not self.is_floor(x + dx, y + dy):
            return False
        return not (dx and dy) or (self.is_floor(x + dx, y) and self.is_floor(x, y + dy))

    def bfs(self, start, goal=None, max_depth=None):
        """Breadth-first search over floor tiles. With a goal: the path to it (excluding start).
        Without: every reachable tile within max_depth steps."""
        sx, sy = start
        prev = {start: None}
        q = deque([(start, 0)])
        while q:
            (x, y), d = q.popleft()
            if goal is not None and (x, y) == goal:
                path = []
                node = goal
                while node != start:
                    path.append(node)
                    node = prev[node]
                return path[::-1]
            if max_depth is not None and d >= max_depth:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if (dx or dy) and (x + dx, y + dy) not in prev and self.walkable_step(x, y, dx, dy):
                        prev[(x + dx, y + dy)] = (x, y)
                        q.append(((x + dx, y + dy), d + 1))
        return [] if goal is not None else list(prev)

    def line_of_sight(self, ax, az, bx, bz):
        d = math.hypot(bx - ax, bz - az)
        steps = max(1, int(d / (TILE / 3)))
        for k in range(1, steps):
            t = k / steps
            if not self.is_floor(int((ax + (bx - ax) * t) / TILE + W / 2), int((az + (bz - az) * t) / TILE + H / 2)):
                return False
        return True

    async def update_bosses(self, now, dt):
        if self.state != "playing":
            return
        want = self.boss_target_count()
        if len(self.bosses) < want and now >= self.next_boss_at:
            kind = random.choice(list(BOSS_KINDS))
            x, z = self.spawn_point(list(self.players.values()))
            b = Boss(kind, x, z)
            if self.coop:   # a bigger team faces a tougher boss
                b.max_hp = b.hp = round(b.max_hp * (1 + COOP_BOSS_HP_PER_PLAYER * max(0, len(self.players) - 1)))
            if self.mode == "descent":   # and so does a deeper floor
                b.max_hp = b.hp = round(b.max_hp * (1 + DESCENT_BOSS_HP_PER_FLOOR * (self.depth - 1))
                                        * (SWARM_HP if self.modifier == "swarm" else 1))
            self.bosses[b.id] = b
            self.next_boss_at = now + 6.0     # stagger a second spawn
            await self.broadcast({"t": "bossSpawn", "id": b.id, "kind": kind, "name": b.name, "x": round(x, 2), "z": round(z, 2)})
        for b in list(self.bosses.values()):
            if now < b.frozen_until or now < b.stun_until:
                continue
            if b.state == "windup":
                if now >= b.windup_until:
                    await self.boss_smash(b, now)
                continue
            # pick a target: the nearest visible, conscious player within aggro range
            best = None
            for q in self.players.values():
                if q.ko_until:
                    continue
                d = math.hypot(q.x - b.x, q.z - b.z)
                limit = b.aggro * TILE * (1.5 if q.id == b.target else 1.0)
                if d <= limit and (best is None or d < best[0]) and self.line_of_sight(b.x, b.z, q.x, q.z):
                    best = (d, q)
            if best:
                d, q = best
                b.target, b.state = q.id, "chase"
                if d <= BOSS_REACH * TILE and now >= b.cooldown_until:
                    b.state, b.windup_until, b.path = "windup", now + BOSS_WINDUP, []
                    b.rot = math.atan2(q.x - b.x, q.z - b.z)
                    await self.broadcast({"t": "bossAtk", "id": b.id, "x": round(b.x, 2), "z": round(b.z, 2),
                                          "r": BOSS_HIT_RANGE, "t0": BOSS_WINDUP})
                    continue
                if now >= b.next_path or not b.path:
                    b.path = self.bfs(b.tile(), q.tile())[:12]
                    b.next_path = now + 0.6
                speed = b.speed
            else:
                b.target = None
                if b.state != "wander":
                    b.state, b.path = "wander", []
                if not b.path and now >= b.next_path:
                    options = self.bfs(b.tile(), max_depth=10)
                    goal = random.choice(options) if options else None
                    b.path = self.bfs(b.tile(), goal) if goal else []
                    b.next_path = now + random.uniform(1.0, 3.0)
                speed = b.speed * 0.55
            # walk along the path
            if b.path:
                tx, tz = tile_center(*b.path[0])
                dx, dz = tx - b.x, tz - b.z
                d = math.hypot(dx, dz)
                step = speed * dt
                if d <= step:
                    b.x, b.z = tx, tz
                    b.path.pop(0)
                else:
                    b.x += dx / d * step
                    b.z += dz / d * step
                    b.rot = math.atan2(dx, dz)

    async def boss_smash(self, b, now):
        b.state, b.cooldown_until = "chase", now + BOSS_COOLDOWN
        hit, shielded = [], []
        for q in self.players.values():
            if q.ko_until or math.hypot(q.x - b.x, q.z - b.z) > BOSS_HIT_RANGE * TILE:
                continue
            if self._absorb(q):
                shielded.append(q.id)
            else:
                q.stun_until = max(q.stun_until, now + BOSS_SMASH_STUN)
                self.hurt(q, b.damage, now)
                hit.append(q.id)
        await self.broadcast({"t": "bossSmash", "id": b.id, "x": round(b.x, 2), "z": round(b.z, 2), "r": BOSS_HIT_RANGE,
                              "hit": hit, "shielded": shielded, "damage": b.damage, "stun": BOSS_SMASH_STUN})
        await self.flush_kos()

    async def damage_boss(self, b, dmg, by, stagger=0.0):
        if b.id not in self.bosses or dmg <= 0:
            return
        dmg = min(dmg, b.hp)
        b.hp -= dmg
        if by:
            b.dmg_by[by] = b.dmg_by.get(by, 0) + dmg
            b.target = by if by in self.players else b.target
        if stagger:
            b.stun_until = max(b.stun_until, time.time() + stagger)
            if b.state == "windup":
                b.state = "chase"          # a stagger interrupts the wind-up
        await self.broadcast({"t": "bossHit", "id": b.id, "by": by, "dmg": dmg, "hp": b.hp,
                              "x": round(b.x, 2), "z": round(b.z, 2)})
        if b.hp <= 0:
            await self.boss_down(b, by)

    async def boss_down(self, b, killer):
        self.bosses.pop(b.id, None)
        self.next_boss_at = time.time() + BOSS_RESPAWN
        rewards = {pid: d // BOSS_DAMAGE_POINTS for pid, d in b.dmg_by.items() if pid in self.players}
        if killer in self.players:
            rewards[killer] = rewards.get(killer, 0) + BOSS_KILL_REWARD
        for pid, pts in rewards.items():
            self.players[pid].score += pts
        await self.stat(self.players.get(killer), bosses=1)
        # loot: a potion plus two random power-ups on floor tiles around the boss
        bx, by_ = b.tile()
        spots = [(x, y) for x, y in self.bfs((bx, by_), max_depth=2)
                 if idx(x, y) not in self.items and idx(x, y) not in self.buried and idx(x, y) not in (self.mines or ())]
        random.shuffle(spots)
        kinds = ["potion"] + random.choices([k for k in ITEM_WEIGHTS if k not in FOOD and not (self.coop and k == "scatter")], k=2)
        loot = []
        for (x, y), k in zip(spots, kinds):
            self.items[idx(x, y)] = k
            loot.append([x, y, k])
        await self.broadcast({"t": "bossDown", "id": b.id, "name": b.name, "killer": killer,
                              "x": round(b.x, 2), "z": round(b.z, 2), "loot": loot, "rewards": rewards})

    async def attack(self, p):
        """Player melee swing: hits the nearest boss in range."""
        now = time.time()
        if self.state != "playing" or now < p.stun_until or now - getattr(p, "last_attack", 0) < ATTACK_COOLDOWN:
            return
        p.last_attack = now
        await self.broadcast({"t": "swing", "pid": p.id})
        near = [(math.hypot(b.x - p.x, b.z - p.z), b) for b in self.bosses.values()]
        if self.mode == "pvp":   # in PvP your sword also hits other players
            near += [(math.hypot(q.x - p.x, q.z - p.z), q) for q in self.players.values() if q is not p and not q.ko_until]
        near = [nb for nb in near if nb[0] <= ATTACK_RANGE * TILE]
        if not near:
            return
        target = min(near, key=lambda nb: nb[0])[1]
        if isinstance(target, Boss):
            await self.damage_boss(target, ATTACK_DAMAGE, p.id)
            return
        shielded = self._absorb(target)
        if not shielded:
            target.stun_until = max(target.stun_until, now + PVP_MELEE_STUN)
            self.hurt(target, PVP_MELEE_DAMAGE, now, by=p.id)
        await self.broadcast({"t": "hitPlayer", "pid": p.id, "target": target.id, "shielded": shielded,
                              "dmg": 0 if shielded else PVP_MELEE_DAMAGE, "x": round(p.x, 2), "z": round(p.z, 2)})
        await self.flush_kos()

    def is_floor(self, x, y):
        return 0 <= x < W and 0 <= y < H and self.floor[y * W + x] == 1

    def nb(self, x, y):
        """Neighbouring floor tiles (walls are never revealed, flagged or mined)."""
        return [(nx, ny) for nx, ny in neighbors(x, y) if self.floor[ny * W + nx]]

    def spawn_point(self, avoid=()):
        """A random floor tile centre, preferring ones away from other players."""
        best = None
        for _ in range(12):
            i = random.choice(self.spawn_tiles)   # never inside the locked vault
            x, z = tile_center(i % W, i // W)
            d = min((math.hypot(x - q.x, z - q.z) for q in avoid), default=99)
            if best is None or d > best[0]:
                best = (d, x, z)
            if d > 8 * TILE:
                break
        return best[1], best[2]

    def place(self, p):
        p.x, p.z = self.spawn_point([q for q in self.players.values() if q is not p])
        p.move_lock = time.time() + 0.4
        if p.is_bot:
            p.tx, p.tz = p.x, p.z

    def generate(self, sx, sy):
        rng = self.rng
        forbidden = {idx(sx, sy)} | {idx(nx, ny) for nx, ny in neighbors(sx, sy)}
        if self.daily:
            # the same mines for everyone today: lay them from the day's seed, then move any that fall
            # in the first dig's 3x3 (the first dig is always safe) to other seeded spots
            mines = set(rng.sample(self.floor_tiles, min(self.n_mines, len(self.floor_tiles))))
            spare = [i for i in self.floor_tiles if i not in mines and i not in forbidden]
            for m in sorted(mines & forbidden):
                mines.discard(m)
                mines.add(spare.pop(rng.randrange(len(spare))))
            self.mines = mines
        else:
            candidates = [i for i in self.floor_tiles if i not in forbidden]
            self.mines = set(rng.sample(candidates, min(self.n_mines, len(candidates))))
        self.recount()
        safe = [i for i in self.floor_tiles if i not in self.mines and i not in forbidden]
        n_items = min(len(safe), round(ITEM_DENSITY * len(self.floor_tiles) * (2 if self.modifier == "trove" else 1)))
        pool = {k: w for k, w in ITEM_WEIGHTS.items() if not (self.coop and k == "scatter")}
        kinds = rng.choices(list(pool), weights=list(pool.values()), k=n_items)
        self.buried = dict(zip(rng.sample(safe, n_items), kinds))
        free = [i for i in safe if i not in self.buried]
        n_traps = min(len(free), round(TRAP_DENSITY * len(self.floor_tiles)))
        self.traps = {i: round(rng.uniform(0, SPIKE_CYCLE), 2) for i in rng.sample(free, n_traps)}
        if not self.vault_open:
            # the treasure: a chest and extra loot inside the vault, and the key somewhere outside it
            inside = [i for i in free if i in self.vault and i not in self.traps]
            rng.shuffle(inside)
            loot = ["chest"] + rng.choices([k for k in pool if k not in FOOD], k=VAULT_LOOT)
            for i, k in zip(inside, loot):
                self.buried[i] = k
            outside = [i for i in free if i not in self.vault and i not in self.traps and i not in self.buried]
            if outside:
                self.buried[rng.choice(outside)] = "key"

    def recount(self):
        self.counts = [0] * (W * H)
        for m in self.mines:
            mx, my = m % W, m // W
            for nx, ny in neighbors(mx, my):
                self.counts[idx(nx, ny)] += 1

    def mines_left(self):
        total = self.n_mines if self.mines is None else len(self.mines)
        return total - len(self.flags) - len(self.booms)

    def snapshot(self):
        tiles = []
        for i in range(W * H):
            if self.revealed[i]:
                tiles.append([i % W, i // W, -1 if i in self.booms else self.counts[i]])
        return {
            "state": self.state,
            "layout": "".join("1" if v else "0" for v in self.floor),
            "layoutKind": self.layout_kind,
            "mode": self.mode,
            "lives": self.lives if self.coop else None,
            "tiles": tiles,
            "flags": [[i % W, i // W, pid] for i, pid in self.flags.items()],
            "items": [[i % W, i // W, k] for i, k in self.items.items()],
            "traps": [[i % W, i // W, ph] for i, ph in self.traps.items() if self.revealed[i]],
            "doors": [] if self.vault_open else [[d % W, d // W] for d in self.doors],
            "daily": self.daily,
            "realm": self.realm,
            "depth": self.depth if self.mode == "descent" else None,
            "stairs": None if self.stairs is None else [self.stairs % W, self.stairs // W],
            "modifier": None if not self.modifier else {"id": self.modifier, **MODIFIERS[self.modifier]},
            "shop": [{"id": k, **SHOP[k], "cost": self.price(k)} for k in self.shop],
            "minesLeft": self.mines_left(),
            "safeLeft": self.safe_left,
            "next": max(0, (self.round_ends_at or 0) - time.time()),
            "mines": self.all_mines() if self.state == "over" else [],
        }

    def all_mines(self):
        return [[m % W, m // W] for m in (self.mines or [])]

    # ---------- messaging ----------
    async def broadcast(self, msg):
        data = json.dumps(msg, separators=(",", ":"))
        for p in list(self.players.values()):
            try:
                await p.ws.send_str(data)
            except Exception:
                pass    # a dead socket: its handler's cleanup moves the player to `away` for a resume
        for s in list(self.spectators.values()):
            try:
                await s.ws.send_str(data)
            except Exception:
                self.spectators.pop(s.id, None)

    async def send_roster(self):
        await self.broadcast({"t": "roster", "players": [p.roster() for p in self.players.values()]})

    # ---------- actions ----------
    def can_act(self, p, x, y):
        now = time.time()
        if self.state != "playing" or now < p.stun_until:
            return False
        if now - p.last_action < ACTION_COOLDOWN:
            return False
        if not self.is_floor(x, y) or self.locked_out(p, idx(x, y)):
            return False
        # distance (in tiles) from the player's actual position to the target tile's centre;
        # a neighbouring tile's centre is at most REACH + 0.5 away from anywhere on the player's tile
        cx, cz = (x - W / 2 + 0.5) * TILE, (y - H / 2 + 0.5) * TILE
        if max(abs(p.x - cx), abs(p.z - cz)) / TILE > REACH + 0.5 + REACH_SLACK:
            return False
        p.last_action = now
        return True

    async def dig(self, p, x, y):
        if not self.can_act(p, x, y):
            return
        i = idx(x, y)
        if self.mines is None:
            self.generate(x, y)

        if self.revealed[i]:
            await self.chord(p, x, y)
            return
        if self.flags.get(i) == p.id:
            return  # can't dig your own flag; remove it first
        await self.open_tiles(p, [(x, y)])

    async def chord(self, p, x, y):
        i = idx(x, y)
        if i in self.booms or self.counts[i] == 0:
            return
        marked = [(nx, ny) for nx, ny in self.nb(x, y)
                  if idx(nx, ny) in self.flags or idx(nx, ny) in self.booms]
        if len(marked) != self.counts[i]:
            return
        targets = [(nx, ny) for nx, ny in self.nb(x, y)
                   if not self.revealed[idx(nx, ny)] and idx(nx, ny) not in self.flags]
        if targets:
            await self.open_tiles(p, targets)

    async def open_tiles(self, p, starts):
        # a mine among the starts explodes first (only the first one)
        for x, y in starts:
            if idx(x, y) in self.mines:
                await self.explode(p, x, y)
                return

        opened, penalties, exposed, traps = [], {}, [], []
        queue = deque(starts)
        while queue:
            x, y = queue.popleft()
            i = idx(x, y)
            if self.revealed[i] or i in self.mines:
                continue
            self.revealed[i] = 1
            self.safe_left -= 1
            opened.append([x, y, self.counts[i]])
            kind = self.buried.pop(i, None)
            if kind:
                self.items[i] = kind
                exposed.append([x, y, kind])
            if i in self.traps:
                traps.append([x, y, self.traps[i]])
            owner = self.flags.pop(i, None)
            if owner:
                penalties[owner] = penalties.get(owner, 0) + FLAG_WRONG
            if self.counts[i] == 0:
                for nx, ny in self.nb(x, y):
                    if not self.revealed[idx(nx, ny)]:
                        queue.append((nx, ny))
        if not opened:
            return
        gain = len(opened) * (GOLD_MULT if time.time() < p.gold_until else 1) * (2 if self.modifier == "rich" else 1)
        p.score += gain
        for pid, amt in penalties.items():
            if pid in self.players:
                self.players[pid].score += amt
        await self.broadcast({
            "t": "reveal", "pid": p.id, "tiles": opened,
            "gain": gain, "penalties": penalties, "items": exposed, "traps": traps,
            "minesLeft": self.mines_left(), "safeLeft": self.safe_left,
        })
        await self.stat(p, tiles=len(opened))
        if self.safe_left == 0:
            await self.floor_cleared(p)

    async def explode(self, p, x, y):
        i = idx(x, y)
        self.revealed[i] = 1
        self.booms.add(i)
        owner = self.flags.pop(i, None)
        shielded = p.shield
        now = time.time()
        if shielded:  # the shield soaks the whole hit
            p.shield = False
            penalty, stun, damage = 0, 0, 0
        else:
            penalty, stun, damage = MINE_PENALTY, STUN_SECONDS, VOLATILE_DAMAGE if self.modifier == "volatile" else MINE_DAMAGE
            p.score += penalty
            p.stun_until = now + stun
            self.hurt(p, damage, now)
        await self.broadcast({
            "t": "boom", "pid": p.id, "x": x, "y": y, "penalty": penalty, "shielded": shielded,
            "stun": stun, "damage": damage, "flagOwner": owner, "minesLeft": self.mines_left(),
        })
        if not shielded:
            await self.stat(p, mines=1)
        await self.flush_kos()

    # ---------- health ----------
    def hurt(self, q, amount, now, by=None):
        """Take `amount` HP from q. At 0 HP q is knocked out: KO_PENALTY points, drops its held
        item, sits out RESPAWN_SECONDS and then respawns elsewhere (Room.respawns).
        In PvP, `by` (another player) earns KO_REWARD; in co-op every KO costs the team a life."""
        if q.ko_until or amount <= 0:
            return False
        q.hp = max(0, q.hp - amount)
        if q.hp > 0:
            return False
        q.ko_until = now + RESPAWN_SECONDS
        q.stun_until = max(q.stun_until, q.ko_until)
        q.score += KO_PENALTY
        q.held = None
        reward = 0
        if self.mode == "pvp" and by and by != q.id and by in self.players:
            self.players[by].score += KO_REWARD
            reward = KO_REWARD
        if self.coop:
            self.lives = max(0, self.lives - 1)
        self.kos.append((q.id, by if reward else None, reward))
        return True

    async def flush_kos(self):
        while self.kos:
            pid, by, reward = self.kos.pop(0)
            await self.broadcast({"t": "ko", "pid": pid, "penalty": KO_PENALTY, "respawn": RESPAWN_SECONDS,
                                  "by": by, "reward": reward, "lives": self.lives if self.coop else None})
            q = self.players.get(pid)
            if q and q.key:
                await self.drop_key(q)
            if by:
                await self.stat(self.players.get(by), kos=1)
        if self.coop and self.lives <= 0 and self.state == "playing":
            self.failed = True
            await self.end_round()

    async def respawns(self, now):
        for q in list(self.players.values()):
            if q.ko_until and now >= q.ko_until:
                q.ko_until, q.hp, q.stun_until = 0.0, q.max_hp, 0.0
                q.frozen_until = 0.0
                self.place(q)
                await self.broadcast({"t": "respawn", "pid": q.id, "x": round(q.x, 2), "z": round(q.z, 2), "hp": q.hp})

    # ---------- power-ups ----------
    async def pickups(self, now):
        if self.state != "playing" or not self.items:
            return
        for p in list(self.players.values()):
            if now < p.stun_until:
                continue
            x, y = p.tile()
            if not (0 <= x < W and 0 <= y < H):
                continue
            i = idx(x, y)
            kind = self.items.get(i)
            if (not kind or (kind in HELD and p.held) or (kind == "shield" and p.shield)
                    or (kind in FOOD and p.hp >= p.max_hp)):
                continue
            del self.items[i]
            dur = 0
            if kind == "key":
                p.key = True
                await self.broadcast({"t": "pickup", "pid": p.id, "x": x, "y": y, "kind": kind, "dur": 0})
                continue
            if kind == "chest":
                p.score += CHEST_POINTS
                await self.broadcast({"t": "pickup", "pid": p.id, "x": x, "y": y, "kind": kind, "dur": 0,
                                      "points": CHEST_POINTS})
                continue
            if kind in FOOD:
                heal = min(FOOD[kind], p.max_hp - p.hp)
                p.hp += heal
                await self.broadcast({"t": "pickup", "pid": p.id, "x": x, "y": y, "kind": kind, "dur": 0,
                                      "heal": heal, "hp": p.hp})
                continue
            if kind in HELD:
                p.held = kind
                p.throw_at = now + random.uniform(1.5, 4.0)
            elif kind == "shield":
                p.shield = True
            elif kind == "boots":
                p.boots_until, dur = now + BOOTS_SECONDS, BOOTS_SECONDS
            elif kind == "gold":
                p.gold_until, dur = now + GOLD_SECONDS, GOLD_SECONDS
            await self.broadcast({"t": "pickup", "pid": p.id, "x": x, "y": y, "kind": kind, "dur": dur})
            if kind == "radar":
                near = [[m % W, m // W] for m in self.mines
                        if max(abs(m % W - x), abs(m // W - y)) <= RADAR_RADIUS
                        and not self.revealed[m] and m not in self.flags]
                try:
                    await p.ws.send_str(json.dumps({"t": "radar", "mines": near, "dur": RADAR_SECONDS}))
                except Exception:
                    pass

    async def use(self, p, x, y):
        """Use the held item, aimed at tile (x, y) where it needs aiming."""
        now = time.time()
        if self.state != "playing" or now < p.stun_until or not p.held or self.mines is None:
            return
        if p.held == "shockwave":
            return await self.shockwave(p)
        if not (0 <= x < W and 0 <= y < H):
            return
        cx, cz = tile_center(x, y)
        dist = max(abs(p.x - cx), abs(p.z - cz)) / TILE - 0.5 - REACH_SLACK
        if p.held == "scatter" and dist <= THROW_RANGE:
            await self.throw(p, x, y)
        elif p.held == "freeze" and dist <= FREEZE_RANGE:
            await self.freeze(p, cx, cz)
        elif p.held == "blink" and dist <= BLINK_RANGE and self.is_floor(x, y) and not self.locked_out(p, idx(x, y)):
            await self.blink(p, x, y)

    def _absorb(self, q):
        if q.shield:
            q.shield = False
            return True
        return False

    async def freeze(self, p, tx, tz):
        """Fire an ice beam from p toward (tx, tz); the first other player near the beam is frozen."""
        p.held = None
        dx, dz = tx - p.x, tz - p.z
        d = math.hypot(dx, dz) or 1.0
        ux, uz = dx / d, dz / d
        length = FREEZE_RANGE * TILE
        # dungeon walls stop the beam
        step = TILE / 4
        for k in range(1, int(length / step) + 1):
            bx, bz = p.x + ux * step * k, p.z + uz * step * k
            if not self.is_floor(int(bx / TILE + W / 2), int(bz / TILE + H / 2)):
                length = step * (k - 1)
                break
        best = None
        targets = (list(self.players.values()) if self.hits_players() else []) + list(self.bosses.values())
        for q in targets:
            if q is p:
                continue
            rx, rz = q.x - p.x, q.z - p.z
            along = rx * ux + rz * uz
            width = FREEZE_WIDTH * TILE * (1.6 if isinstance(q, Boss) else 1.0)   # bosses are big
            if 0 < along <= length and abs(rx * uz - rz * ux) <= width and (best is None or along < best[0]):
                best = (along, q)
        end = best[0] if best else length
        target, shielded, boss_hit = None, False, None
        now = time.time()
        if best and isinstance(best[1], Boss):
            boss_hit = best[1]
            target = boss_hit.id
            boss_hit.frozen_until = now + FREEZE_SECONDS
            if boss_hit.state == "windup":
                boss_hit.state = "chase"
        elif best:
            q = best[1]
            target = q.id
            shielded = self._absorb(q)
            if not shielded:
                q.frozen_until = now + FREEZE_SECONDS
                q.stun_until = max(q.stun_until, q.frozen_until)
        await self.broadcast({"t": "zap", "pid": p.id, "from": [round(p.x, 2), round(p.z, 2)],
                              "to": [round(p.x + ux * end, 2), round(p.z + uz * end, 2)],
                              "target": target, "boss": boss_hit is not None, "shielded": shielded, "dur": FREEZE_SECONDS})
        if boss_hit:
            await self.damage_boss(boss_hit, BOSS_POWER_DAMAGE["freeze"], p.id)

    async def shockwave(self, p):
        p.held = None
        now = time.time()
        hit, shielded = [], []
        for q in (self.players.values() if self.hits_players() else ()):
            if q is p or math.hypot(q.x - p.x, q.z - p.z) > SHOCK_RADIUS * TILE:
                continue
            if self._absorb(q):
                shielded.append(q.id)
            else:
                q.stun_until = max(q.stun_until, now + SHOCK_STUN)
                self.hurt(q, SHOCK_DAMAGE, now, by=p.id)
                hit.append(q.id)
        await self.broadcast({"t": "shock", "pid": p.id, "x": round(p.x, 2), "z": round(p.z, 2),
                              "r": SHOCK_RADIUS, "hit": hit, "shielded": shielded, "stun": SHOCK_STUN,
                              "damage": SHOCK_DAMAGE})
        await self.flush_kos()
        for b in list(self.bosses.values()):
            if math.hypot(b.x - p.x, b.z - p.z) <= SHOCK_RADIUS * TILE:
                await self.damage_boss(b, BOSS_POWER_DAMAGE["shockwave"], p.id, stagger=1.0)

    async def blink(self, p, x, y):
        p.held = None
        fx, fz = p.x, p.z
        p.x, p.z = tile_center(x, y)
        p.move_lock = time.time() + 0.4  # ignore client moves sent before it saw the blink
        if p.is_bot:
            p.tx, p.tz = p.x, p.z
        await self.broadcast({"t": "blink", "pid": p.id, "from": [round(fx, 2), round(fz, 2)],
                              "to": [p.x, p.z]})

    async def throw(self, p, x, y):
        p.held = None
        self.bomb_seq += 1
        bid = self.bomb_seq
        await self.broadcast({"t": "throw", "id": bid, "pid": p.id, "x": x, "y": y,
                              "fuse": SCATTER_FUSE, "r": SCATTER_RADIUS})
        asyncio.create_task(self.detonate_later(bid, p.id, x, y, self.round_id))

    async def detonate_later(self, bid, pid, x, y, rid):
        await asyncio.sleep(SCATTER_FUSE)
        if self.round_id != rid or self.state != "playing":
            return
        await self.scatter(bid, pid, x, y)

    async def scatter(self, bid, pid, x, y):
        """Re-cover a (2R+1)^2 area: wipe its revealed tiles, flags, craters, items and mines,
        then scatter SCATTER_MINES fresh mines into it. Players caught inside are knocked out."""
        r = SCATTER_RADIUS
        area = [idx(ax, ay) for ay in range(y - r, y + r + 1) for ax in range(x - r, x + r + 1)
                if self.is_floor(ax, ay)]
        if len(area) < 2:
            return
        for i in area:
            self.revealed[i] = 0
            self.booms.discard(i)
            self.mines.discard(i)
            self.flags.pop(i, None)
            self.items.pop(i, None)
            self.buried.pop(i, None)
            self.traps.pop(i, None)
        added = random.sample(area, min(SCATTER_MINES, len(area) - 1))
        self.mines.update(added)
        self.recount()
        self.safe_left = sum(1 for i in self.floor_tiles if not self.revealed[i] and i not in self.mines)

        # area tiles go back to hidden; revealed tiles on the rim get their new counts
        changed = [[i % W, i // W, -2] for i in area]
        rim = set()
        for i in area:
            for nx, ny in self.nb(i % W, i // W):
                j = idx(nx, ny)
                if self.revealed[j] and j not in self.booms and j not in area:
                    rim.add(j)
        changed += [[j % W, j // W, self.counts[j]] for j in rim]

        now, hit, shielded = time.time(), [], []
        cx, cz = tile_center(x, y)
        for q in (self.players.values() if self.hits_players() else ()):
            if max(abs(q.x - cx), abs(q.z - cz)) <= (r + 0.5) * TILE:
                if self._absorb(q):
                    shielded.append(q.id)
                else:
                    q.stun_until = max(q.stun_until, now + SCATTER_STUN)
                    self.hurt(q, SCATTER_DAMAGE, now, by=pid)
                    hit.append(q.id)
        await self.broadcast({
            "t": "scatter", "id": bid, "pid": pid, "x": x, "y": y, "r": r, "added": len(added),
            "tiles": changed, "hit": hit, "shielded": shielded, "stun": SCATTER_STUN, "damage": SCATTER_DAMAGE,
            "minesLeft": self.mines_left(), "safeLeft": self.safe_left,
        })
        await self.flush_kos()
        await self.check_doors()    # a key caught in the blast is buried again somewhere else
        for b in list(self.bosses.values()):
            if max(abs(b.x - cx), abs(b.z - cz)) <= (r + 0.5) * TILE:
                await self.damage_boss(b, BOSS_POWER_DAMAGE["scatter"], pid, stagger=1.2)

    async def flag(self, p, x, y):
        if not self.can_act(p, x, y):
            return
        i = idx(x, y)
        if self.revealed[i]:
            return
        owner = self.flags.get(i)
        if owner is None:
            self.flags[i] = p.id
            new = p.id
        elif owner == p.id:
            del self.flags[i]
            new = None
        else:
            return  # someone else's flag; you may dig it at your own risk
        await self.broadcast({"t": "flag", "x": x, "y": y, "pid": new, "minesLeft": self.mines_left()})

    async def update_bots(self, now, dt):
        for p in list(self.players.values()):
            if not p.is_bot:
                continue
            dx, dz = p.tx - p.x, p.tz - p.z
            d = math.hypot(dx, dz)
            if p.held and now >= p.throw_at and self.state == "playing" and now >= p.stun_until:
                await self.bot_use(p, now)
            if d > 1e-3:
                step = BOT_SPEED * dt * (BOOTS_SPEED if now < p.boots_until else 1)
                if d <= step:
                    p.x, p.z = p.tx, p.tz
                else:
                    p.x += dx / d * step
                    p.z += dz / d * step
                p.rot = math.atan2(dx, dz)
                continue
            if self.state != "playing" or now < p.next_think or now < p.stun_until:
                continue
            p.next_think = now + p.interval
            x, y = p.tile()
            version = getattr(p.brain, "version", 1)
            v2, v3 = version >= 2, version >= 3
            prey = list(self.bosses.values()) + ([q for q in self.players.values() if q is not p and not q.ko_until]
                                                 if self.mode == "pvp" else [])
            can_hit = any(math.hypot(b.x - p.x, b.z - p.z) <= ATTACK_RANGE * TILE for b in prey)
            # v1 models know nothing about combat, so a heuristic swings for them; v2 models decide themselves
            if not v2 and can_hit:
                await self.attack(p)
                continue
            # heuristic (not learned, v1/v2 only; v3 sees pickups): when hurt, walk toward visible food nearby
            if not v3 and p.hp <= p.max_hp - 40:
                food = [(max(abs(i % W - x), abs(i // W - y)), i) for i, k in self.items.items() if k in FOOD]
                food = [f for f in food if f[0] <= 8]
                if food:
                    _, i = min(food)
                    sx, sy = (i % W > x) - (i % W < x), (i // W > y) - (i // W < y)
                    for cx, cy in ((x + sx, y + sy), (x + sx, y), (x, y + sy)):
                        if (cx, cy) != (x, y) and self.is_floor(cx, cy):
                            p.tx, p.tz = tile_center(cx, cy)
                            break
                    else:
                        cx = None
                    if cx is not None:
                        continue
            # the goal: the vault door while carrying the key, else the stairs once the floor is cleared.
            # v1/v2 always BFS-walk there (heuristic); v3 models learned to reach a nearby goal themselves,
            # so the walk only takes over when it's further than training ever put it (GOAL_NEAR).
            goal = None
            if p.key and not self.vault_open:
                fronts = [t for d in self.doors for t in self.nb(d % W, d // W) if idx(*t) not in self.vault]
                if fronts:
                    goal = min(fronts, key=lambda t: max(abs(t[0] - x), abs(t[1] - y)))
            elif self.stairs is not None:
                goal = (self.stairs % W, self.stairs // W)
            if goal and (not v3 or max(abs(goal[0] - x), abs(goal[1] - y)) > GOAL_NEAR):
                path = self.bfs((x, y), goal)
                if path:
                    p.tx, p.tz = tile_center(*path[0])
                    continue
                if self.stairs is not None and not v3:
                    continue
            mates = [q for q in self.players.values() if q is not p and not q.ko_until]
            extra = None
            if v2:   # what a v2 model also sees: its health, the mode, teammates and the nearest boss
                boss = min(self.bosses.values(), key=lambda b: math.hypot(b.x - p.x, b.z - p.z), default=None)
                # models know race / pvp / coop; descent plays by co-op rules
                extra = {"hp": p.hp / p.max_hp, "mode": self.mode if v3 else ("coop" if self.coop else self.mode),
                         "attack_ok": can_hit, "allies": [q.tile() for q in mates] if self.coop else [],
                         "boss": (*boss.tile(), boss.hp / boss.max_hp, boss.state == "windup") if boss else None}
                if v3:   # traps (up by the time a step lands), pickups and the goal, all within its view
                    soon = now + BOT_STEP_SECONDS
                    extra.update(traps=[(i % W, i // W, self.spikes_up(i, soon)) for i in self.traps if self.revealed[i]],
                                 items=[(i % W, i // W) for i in self.items], goal=goal)
                others = [] if self.coop else [q.tile() for q in mates]
            else:
                others = [q.tile() for q in self.players.values() if q is not p]
            kind, ox, oy = p.brain.decide(W, H, self.revealed, self.counts, self.booms, self.flags, p.id, (x, y), others,
                                          floor=self.floor, extra=extra)
            if kind == "attack":
                await self.attack(p)
                continue
            tx, ty = x + ox, y + oy
            if not self.is_floor(tx, ty):
                continue
            if kind == "move":
                if not v3 and idx(tx, ty) in self.traps and self.revealed[idx(tx, ty)]:
                    continue    # heuristic (v1/v2): bots keep off spike traps they can see
                p.tx, p.tz = tile_center(tx, ty)
            elif kind == "dig":
                await self.dig(p, tx, ty)
            else:
                await self.flag(p, tx, ty)

    async def bot_use(self, p, now):
        """Heuristics for held items (not learned): aim at the nearest opponent in range,
        shockwave when someone is close, blink toward unexplored ground. Otherwise retry later."""
        px, py = p.tile()
        foes = []
        for q in (self.players.values() if self.hits_players() else ()):   # teammates aren't targets in co-op
            if q is not p and now >= q.stun_until:
                qx, qy = q.tile()
                if 0 <= qx < W and 0 <= qy < H:
                    foes.append((max(abs(qx - px), abs(qy - py)), qx, qy))
        for b in self.bosses.values():   # bosses are fair game too
            bx, by = b.tile()
            foes.append((max(abs(bx - px), abs(by - py)), bx, by))
        foes.sort()
        rng = {"scatter": THROW_RANGE, "freeze": FREEZE_RANGE - 1, "shockwave": SHOCK_RADIUS - 1}.get(p.held)
        if rng is not None:
            if foes and foes[0][0] <= rng:
                return await self.use(p, foes[0][1], foes[0][2])
        elif p.held == "blink":
            # the reachable tile with the most hidden tiles around it
            best, best_n = None, 2
            for _ in range(40):
                x = min(max(px + random.randint(-BLINK_RANGE, BLINK_RANGE), 0), W - 1)
                y = min(max(py + random.randint(-BLINK_RANGE, BLINK_RANGE), 0), H - 1)
                if not self.revealed[idx(x, y)] or idx(x, y) in self.booms:
                    continue
                n = sum(1 for nx, ny in self.nb(x, y) if not self.revealed[idx(nx, ny)])
                if n > best_n:
                    best, best_n = (x, y), n
            if best:
                return await self.use(p, *best)
        p.throw_at = now + 1.0

    async def end_round(self):
        self.state = "over"
        bonuses = {}
        for i, pid in self.flags.items():
            if i in self.mines and pid in self.players:
                bonuses[pid] = bonuses.get(pid, 0) + FLAG_CORRECT
        for pid, b in bonuses.items():
            self.players[pid].score += b
        self.round_ends_at = time.time() + NEXT_ROUND_DELAY
        standings = sorted(self.players.values(), key=lambda q: -q.score)
        duration = round(time.time() - self.started_at)
        # stats for profiles (humans only) and the daily leaderboard
        top = standings[0] if standings else None
        for q in standings:
            if q.is_bot:
                continue
            # a win: first place outright, against at least one other player (bots count)
            won = not self.coop and len(standings) >= 2 and q is top and q.score > standings[1].score
            if self.daily and not self.failed:
                daily_board.record(self.daily, q.name, q.score, duration, q.char, q.color, len(standings))
            if self.mode == "descent":
                await self.stat(q, deepest=self.depth, descents=1)
            await self.stat(q, best=q.score, rounds=1, flags=bonuses.get(q.id, 0) // FLAG_CORRECT,
                            wins=int(won), coop_wins=int(self.mode == "coop" and not self.failed),
                            daily=int(bool(self.daily) and not self.failed))
        if self.mode == "descent" and any(not q.is_bot for q in standings):
            descent_board.record([{"name": q.name, "color": q.color, "bot": q.is_bot} for q in standings],
                                 self.depth, sum(q.score for q in standings), round(time.time() - self.run_started))
        await self.broadcast({
            "t": "over",
            "mode": self.mode, "failed": self.failed,
            "depth": self.depth if self.mode == "descent" else None,
            "runSecs": round(time.time() - self.run_started),
            "team": sum(q.score for q in standings) if self.coop else None,
            "results": [{"id": q.id, "name": q.name, "color": q.color, "score": q.score,
                         "flagBonus": bonuses.get(q.id, 0)} for q in standings],
            "mines": self.all_mines(),
            "next": NEXT_ROUND_DELAY,
            "duration": duration,
            "daily": self.daily,
        })
        for q in standings:
            if q.profile:   # the round's stats, so the hat picker is up to date
                await self.send_to(q, {"t": "profile", **store.public(q.profile)})
        self.round_task = asyncio.create_task(self.restart_later())

    async def restart_later(self):
        await asyncio.sleep(NEXT_ROUND_DELAY)
        self.new_round()
        spawns = {}
        for q in self.players.values():
            q.score = 0
            q.stun_until = 0
            q.hp = q.max_hp = MAX_HP
            q.ko_until = 0.0
            q.perks.clear(); q.bought.clear()
            q.reset_items()
            q.round_id = self.run_id
            self.place(q)   # the new layout has different floor, so everyone gets a fresh spawn
            spawns[q.id] = [round(q.x, 2), round(q.z, 2)]
        await self.broadcast({"t": "round", "snapshot": self.snapshot(), "spawns": spawns})


rooms: dict[str, Room] = {}


def clean(s, n, default):
    s = "".join(ch for ch in str(s or "") if ch.isprintable()).strip()[:n]
    return s or default


def pick_char(c):
    return c if c in CHARACTER_IDS else "miner"


def pick_color(room, wanted, me=None):
    """Honour the requested colour if nobody else in the room has it, else the first free one."""
    used = {p.color for p in room.players.values() if p is not me}
    if wanted in COLORS and wanted not in used:
        return wanted
    if me is not None:
        return me.color
    return next((c for c in COLORS if c not in used), random.choice(COLORS))


def pick_hat(prof, hat):
    return hat if isinstance(hat, str) and hat in store.unlocked(prof) else ""


def welcome_msg(room, who, spectator=False):
    return {
        "t": "welcome", "id": who.id, "room": room.name, "spectator": spectator,
        "token": None if spectator else who.token, "serverTime": time.time(),
        "cfg": {"w": W, "h": H, "mines": room.n_mines, "tile": TILE, "reach": REACH, "realm": room.realm,
                "mode": room.mode, "daily": room.daily,
                "throwRange": THROW_RANGE, "scatterRadius": SCATTER_RADIUS, "bootsSpeed": BOOTS_SPEED,
                "freezeRange": FREEZE_RANGE, "blinkRange": BLINK_RANGE, "shockRadius": SHOCK_RADIUS,
                "held": HELD, "maxHp": MAX_HP, "keyBit": KEY_BIT, "spikeCycle": SPIKE_CYCLE, "spikeUp": SPIKE_UP,
                "quick": QUICK_CHAT, "resumeSeconds": RESUME_SECONDS},
        "spawn": [0, 0] if spectator else [who.x, who.z],
        "snapshot": room.snapshot(),
    }


def make_room(room_name, data):
    if room_name == daily_name():
        return Room(room_name, daily=today())
    return Room(room_name, data.get("realm"), data.get("layout"), data.get("mode"))


async def close_room(room):
    """Close a room: its round timer, its bots, and anyone still watching it."""
    if room.round_task:
        room.round_task.cancel()
    if rooms.get(room.name) is room:
        rooms.pop(room.name, None)
    for s in list(room.spectators.values()):
        await room.send_to(s, {"t": "error", "message": "That room has closed: everyone left."})
        try:
            await s.ws.close()
        except Exception:
            pass
    room.spectators.clear()


def has_humans(room):
    """Should the room stay open? Yes while a human is in it, one may still reconnect, or it's brand new."""
    return any(not p.is_bot for p in room.players.values()) or bool(room.away) or time.time() < room.hold_until


async def resume(room, token, ws):
    """Give a reconnecting player their place back: same id, score, health and items.
    Works whether the old connection is already gone (`away`) or not yet noticed as dead."""
    entry = room.away.pop(token, None)
    p = entry[0] if entry else next((q for q in room.players.values() if not q.is_bot and q.token == token), None)
    if p is None:
        return None
    old, p.ws = p.ws, ws
    if old is not ws and entry is None:
        asyncio.create_task(old.close())     # the stale connection: its cleanup sees it was replaced
    if p.color in {q.color for q in room.players.values() if q is not p}:
        p.color = pick_color(room, None)
    if p.round_id != room.run_id:            # a new round (or descent run) started while they were away
        p.score, p.hp, p.max_hp, p.ko_until, p.stun_until = 0, MAX_HP, MAX_HP, 0.0, 0.0
        p.reset_items()
        p.round_id = room.run_id
        room.place(p)
    elif not room.is_floor(*p.tile()):       # same descent run, but the team went down a floor
        p.key = False
        room.place(p)
    room.players[p.id] = p
    return p


async def ws_handler(request):
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=MAX_MSG_BYTES)
    await ws.prepare(request)
    room = player = watcher = None
    bucket = RateLimit()
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            if not bucket.allow():
                if bucket.dropped > RATE_KICK:   # flooding: disconnect
                    await ws.close(code=1008, message=b"too many messages")
                    break
                continue
            try:
                data = json.loads(msg.data)
                t = data.get("t")
            except Exception:
                continue

            if t == "join" and player is None and watcher is None:
                room_name = clean(data.get("room"), 24, "lobby").lower()
                existing = rooms.get(room_name)
                if data.get("spectate"):
                    if not existing:
                        await ws.send_str(json.dumps({"t": "error", "message": f"There's no open room called “{room_name}” to watch."}))
                        continue
                    if len(existing.spectators) >= MAX_SPECTATORS:
                        await ws.send_str(json.dumps({"t": "error", "message": f"Room “{room_name}” already has {MAX_SPECTATORS} spectators."}))
                        continue
                    room, watcher = existing, Spectator(ws, clean(data.get("name"), 16, "Spectator"))
                    room.spectators[watcher.id] = watcher
                    await ws.send_str(json.dumps(welcome_msg(room, watcher, spectator=True)))
                    await room.send_to(watcher, {"t": "roster", "players": [p.roster() for p in room.players.values()]})
                    continue
                if existing and isinstance(data.get("resume"), str):
                    player = await resume(existing, data["resume"], ws)
                    if player:
                        room = existing
                        await ws.send_str(json.dumps({**welcome_msg(room, player), "resumed": True}))
                        if player.profile:
                            await room.send_to(player, {"t": "profile", **store.public(player.profile)})
                        await room.send_roster()
                        continue
                if existing and len(existing.players) >= MAX_PLAYERS:
                    await ws.send_str(json.dumps({"t": "error", "full": True, "message": f"Room “{room_name}” is full ({MAX_PLAYERS} players). You can watch it instead."}))
                    continue
                room = existing or rooms.setdefault(room_name, make_room(room_name, data))
                color = pick_color(room, data.get("color"))
                name = clean(data.get("name"), 16, "Sweeper")
                prof = profiles.get(data.get("profile"), name)
                player = Player(ws, name, color, pick_char(data.get("char")), pick_hat(prof, data.get("hat")))
                player.profile, player.round_id = prof, room.run_id
                room.place(player)
                room.players[player.id] = player
                if room.coop and room.state == "playing":
                    room.lives += 1          # every teammate brings a life to the shared pool
                await ws.send_str(json.dumps(welcome_msg(room, player)))
                if prof:
                    await room.send_to(player, {"t": "profile", **store.public(prof)})
                await room.send_roster()
            elif player is None:
                continue                     # spectators (and not-yet-joined sockets) can't act
            elif t == "look":  # change name / character / colour / hat mid-game
                player.name = clean(data.get("name"), 16, player.name)
                player.char = pick_char(data.get("char"))
                player.color = pick_color(room, data.get("color"), me=player)
                player.hat = pick_hat(player.profile, data.get("hat"))
                if player.profile:
                    player.profile["name"] = player.name
                await room.send_roster()
            elif t in ("emote", "ping"):
                now = time.time()
                if now - player.last_chat < CHAT_COOLDOWN:
                    continue
                if t == "emote":
                    if data.get("id") not in QUICK_CHAT:
                        continue
                    out = {"t": "emote", "pid": player.id, "id": data["id"]}
                else:
                    try:
                        x, y = int(data["x"]), int(data["y"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if not (0 <= x < W and 0 <= y < H):
                        continue
                    out = {"t": "ping", "pid": player.id, "x": x, "y": y}
                player.last_chat = now
                await room.broadcast(out)
            elif t == "move":
                if time.time() < getattr(player, "move_lock", 0):
                    continue
                try:
                    lim_x, lim_z = W * TILE / 2 + 6, H * TILE / 2 + 6
                    nx = max(-lim_x, min(lim_x, float(data["x"])))
                    nz = max(-lim_z, min(lim_z, float(data["z"])))
                    # in a dungeon you can't stand inside a wall (the client collides with them too)
                    if room.layout_kind == "dungeon" and not room.is_floor(int(nx / TILE + W / 2), int(nz / TILE + H / 2)):
                        continue
                    player.x, player.z = nx, nz
                    player.rot = float(data.get("r", 0))
                except (KeyError, TypeError, ValueError):
                    pass
            elif t in ("dig", "flag"):
                try:
                    x, y = int(data["x"]), int(data["y"])
                except (KeyError, TypeError, ValueError):
                    continue
                await (room.dig if t == "dig" else room.flag)(player, x, y)
            elif t == "attack":
                await room.attack(player)
            elif t == "buy":
                await room.buy(player, data.get("id") if isinstance(data.get("id"), str) else "")
            elif t in ("use", "throw"):
                try:
                    x, y = int(data.get("x", -1)), int(data.get("y", -1))
                except (TypeError, ValueError):
                    continue
                await room.use(player, x, y)
    finally:
        if room and watcher:
            room.spectators.pop(watcher.id, None)
        # skip if this connection was replaced by a resume (the player now lives on the new one)
        if room and player and player.ws is ws and room.players.get(player.id) is player:
            room.players.pop(player.id, None)
            await room.drop_key(player)
            # keep their place for a while in case they reconnect; the room closes (with its bots) once
            # no humans are left and nobody can still come back (see tick_loop)
            room.away[player.token] = (player, time.time() + RESUME_SECONDS)
            await room.send_roster()
    return ws


# ---------------------------------------------------------------- lobby
MAX_PLAYERS = len(COLORS)


def lobby_summary():
    """Public list of open rooms for the join screen (no ids or anything private)."""
    out = []
    for r in rooms.values():
        humans = [p for p in r.players.values() if not p.is_bot]
        bots = [p for p in r.players.values() if p.is_bot]
        total = len(r.floor_tiles) - (len(r.mines) if r.mines else r.n_mines)
        done = max(0, total - r.safe_left) if r.mines else 0
        out.append({
            "name": r.name, "mode": r.mode, "layout": r.layout_kind, "realm": r.realm, "state": r.state,
            "humans": len(humans), "bots": len(bots), "max": MAX_PLAYERS,
            "players": [{"name": p.name, "color": p.color, "char": p.char, "bot": p.is_bot, "score": p.score}
                        for p in sorted(r.players.values(), key=lambda q: -q.score)][:8],
            "progress": round(done / total, 3) if total else 0,
            "bosses": len(r.bosses), "lives": r.lives if r.coop else None,
            "age": round(time.time() - r.started_at),
            "spectators": len(r.spectators), "away": len(r.away), "daily": bool(r.daily),
            "depth": r.depth if r.mode == "descent" else None,
            "vault": None if not r.doors else ("open" if r.vault_open else "locked"),
        })
    out.sort(key=lambda d: (-d["humans"], d["name"]))
    return out


NO_STORE = {"Cache-Control": "no-store"}


async def api_rooms(_):
    return web.json_response({"rooms": lobby_summary()}, headers=NO_STORE)


async def api_daily(_):
    d = today()
    return web.json_response({"date": d, "room": daily_name(d), "realm": daily_realm(d), **daily_board.board(d)},
                             headers=NO_STORE)


async def api_profile(request):
    """A profile's stats and hat unlocks, for its owner's join screen (the token is the key)."""
    return web.json_response(store.public(profiles.peek(request.query.get("token"))), headers=NO_STORE)


async def api_descents(_):
    return web.json_response(descent_board.board(), headers=NO_STORE)


profiles = store.Profiles(store.DATA / "profiles.json")
daily_board = store.Daily(store.DATA / "daily.json")
descent_board = store.Descents(store.DATA / "descents.json")


# ---------------------------------------------------------------- bots (used by the lab)
def rooms_summary():
    return [{"name": r.name, "realm": r.realm, "layout": r.layout_kind, "mode": r.mode, "state": r.state, "safeLeft": r.safe_left,
             "players": [{**p.roster(), "score": p.score} for p in r.players.values()]}
            for r in rooms.values()]


async def add_bot(room_name, model, difficulty="normal", char=None):
    from ai.bots import DIFFICULTY, Brain
    if not model:
        raise ValueError("Pick a model for the bot.")
    room_name = clean(room_name, 24, "lobby").lower()
    room = rooms.get(room_name) or rooms.setdefault(room_name, Room(room_name))
    if len(room.players) >= len(COLORS):
        raise ValueError("That room is full.")
    brain = Brain(model)
    difficulty = difficulty if difficulty in DIFFICULTY else "normal"
    char = char if char in CHARACTER_IDS else random.choice(sorted(CHARACTER_IDS))
    taken = {p.name for p in room.players.values()}
    base = clean(brain.name, 13, "Bot")
    name = next(n for n in [base] + [f"{base} {k}" for k in range(2, 20)] if n not in taken)
    bot = BotPlayer(brain, name, pick_color(room, None), char, difficulty, DIFFICULTY[difficulty])
    room.place(bot)
    room.players[bot.id] = bot
    if room.coop and room.state == "playing":
        room.lives += 1
    await room.send_roster()


async def remove_bot(room_name, bot_id):
    room = rooms.get(str(room_name or ""))
    p = room and room.players.get(str(bot_id or ""))
    if p and p.is_bot:
        room.players.pop(p.id, None)
        if room.players:
            await room.send_roster()
        else:
            rooms.pop(room.name, None)


async def tick_loop(app):
    async def loop():
        last = saved = time.time()
        while True:
            await asyncio.sleep(1 / TICK_HZ)
            now = time.time()
            dt, last = now - last, now
            if now - saved > 10:
                saved = now
                profiles.save()
                daily_board.save()
                descent_board.save()
            for room in list(rooms.values()):
                for token, (_, until) in list(room.away.items()):
                    if now >= until:
                        del room.away[token]
                if not has_humans(room):   # last human gone for good: close it (its bots go with it)
                    await close_room(room)
                    continue
                if not room.players:
                    continue
                try:
                    await room.update_bots(now, dt)
                except Exception as e:  # a broken model must not take the game down
                    print("bot error:", repr(e))
                await room.update_bosses(now, dt)
                await room.pickups(now)
                await room.check_doors()
                await room.check_stairs(now)
                await room.crumble(now)
                await room.perk_tick()
                await room.spikes(now)
                await room.respawns(now)
                await room.broadcast({"t": "players", "p": [
                    [p.id, round(p.x, 2), round(p.z, 2), round(p.rot, 2), p.score,
                     round(max(0.0, p.stun_until - now), 2), p.fx(now), p.hp, p.max_hp]
                    for p in room.players.values()],
                    "b": [b.row(now) for b in room.bosses.values()]})
    task = asyncio.create_task(loop())
    yield
    task.cancel()
    profiles.save()
    daily_board.save()
    descent_board.save()


async def index(_):
    return web.FileResponse(STATIC / "index.html")


def make_app(lab=True):
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/rooms", api_rooms)
    app.router.add_get("/api/daily", api_daily)
    app.router.add_get("/api/profile", api_profile)
    app.router.add_get("/api/descents", api_descents)
    app.router.add_static("/static", STATIC)
    app.cleanup_ctx.append(tick_loop)
    if lab:
        try:
            from ai.lab import Lab
            Lab(STATIC, rooms_summary, add_bot, remove_bot, sorted(CHARACTER_IDS)).setup(app)
        except ImportError as e:
            print(f"AI lab disabled ({e}). Install it with: .venv\\Scripts\\pip install -r requirements-ai.txt")
    return app


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    print(f"Mine Field 3D running on http://localhost:{args.port}  (AI lab: http://localhost:{args.port}/lab)")
    web.run_app(make_app(), host=args.host, port=args.port, print=None)
