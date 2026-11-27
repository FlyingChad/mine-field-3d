"""Vectorised Mine Field simulator for training and evaluating AI bots.

Many boards are simulated at once as tensors of shape (N, H, W), with A agents per board, on CPU or
GPU. It follows the rules in server.py on a tile grid. An agent stands on a tile and each step it can
  * move one tile (8 directions),
  * dig one of the 9 tiles within reach (its own tile + the 8 neighbours), or
  * flag/unflag one of those 9 tiles,
  * (v2 / rich) attack: hit the boss, or in PvP a rival, standing within one tile.
Mines are laid on the first dig of a board, with a safe 3x3 around the dug tile. Digging a mine costs
`mine` reward and stuns the agent for `stun` steps. Safe digs flood-fill. A flag removed by a dig
costs its owner `flag_wrong`. When the episode ends, flags on mines earn `flag_correct` and flags
left on safe tiles cost `flag_wrong`. In the real game a round only ends once every safe tile has
been dug, so every wrong flag is eventually penalised there too.

rich=True adds the game's newer layers so "v2" models can learn them:
  * health: mines and boss smashes take HP; at 0 the agent is knocked out (`ko` reward), sits out
    `respawn` steps and comes back on a random floor tile at full health;
  * a boss per board (bosses=True) that wanders, chases the nearest agent, winds up for `windup`
    steps (shown as a danger zone) and then smashes everyone within one tile;
  * modes per board: race, pvp (attacks hit rivals; KOs pay `pvp_ko`), coop (no friendly fire;
    fitness() gives every agent the team's average). mode="mixed" draws one per board.
extras=True (v3 models) adds the dungeon's newer pieces on top of rich:
  * spike traps on safe tiles: once revealed they cycle up/down (`spike_cycle`, `spike_up` steps, each
    with its own phase) and hurt + stun anyone standing on them while up (`spike_grace` between hits);
  * pickups on safe tiles, collected by walking onto them once revealed (`item` reward); food heals and
    is only taken when hurt, like in the game;
  * a fourth mode, descent (co-op rules; `descent_practice` pre-digs a share of those boards): clearing the board opens stairs a few tiles from an agent and
    pays `floor` to everyone; the board ends when someone reaches the stairs (`stairs` to everyone) or
    after `stairs_auto` steps. The stairs are the "goal" the v3 observation points at (in the game the
    goal is also the vault door while carrying the key).
powers=True (v4 models) also simulates the power-ups (server.py ITEM_WEIGHTS): pickups are generic
(boots / radar / gold: just the `item` reward), food, a shield (absorbs the next hit) or one of the
held items (scatter, freeze, shockwave, blink), which take the single item slot. Action USE fires the
held item. Aiming is a fixed rule, the same as the game's: the nearest foe (a rival, or the boss) in
range for scatter and freeze, everyone around you for the shockwave, and for blink the dug-up tile
within reach with the most hidden ground around it. So v4 learns *when* to use an item, not where.
Version-1/2/3 observations/actions are still produced for older models, so they keep working.

`encode()` and `action_mask()` are standalone so the in-game bots (ai/bots.py) build exactly the same
observations as training does.
"""
import random
import sys
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import layouts  # noqa: E402  (shared with server.py so bots train on the same dungeons they play)

MOVES = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]   # (dy, dx)
NEAR = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]                      # reachable tiles
DIG0, FLAG0, ATTACK, USE = 8, 17, 26, 27
N_ACTIONS = 26                 # v1
N_CHANNELS = 10                # v1: hidden, flagged, exploded, n0, n1, n2, n3, n4+, other agent, out of bounds
N_GLOBAL = 3                   # v1: direction (dy, dx) and distance to the nearest diggable tile
# v2 adds channels boss, danger (boss wind-up zone), ally; out of bounds stays last
N_CHANNELS_V2 = 13
# v2 globals: v1's 3, own hp, mode one-hot (race, pvp, coop), boss dy, dx, distance, present, hp, winding up
N_GLOBAL_V2 = 13
MODES = ["race", "pvp", "coop", "descent"]   # v2 sees descent as coop (it only knows the first three)
# v3 adds channels trap (revealed), spikes up now, pickup, goal (stairs / vault door); out of bounds stays last
N_CHANNELS_V3 = 17
# v3 globals: v2's with a 4-way mode one-hot (14), then goal dy, dx, distance, present
N_GLOBAL_V3 = 18
# v4 (powers): v3's channels; globals v3's 18 + held item one-hot (scatter, freeze, shockwave, blink) + shield
N_GLOBAL_V4 = 23
HELD = ["", "scatter", "freeze", "shockwave", "blink"]   # held item ids, as in server.HELD
# item codes on the board when powers=True: 1 generic, 2 food, 3 shield, 4.. held items (4 + HELD index - 1)
ITEM_CODES = {"radar": 1, "boots": 1, "gold": 1, "apple": 2, "potion": 2, "shield": 3,
              "scatter": 4, "freeze": 5, "shockwave": 6, "blink": 7}
ITEM_WEIGHTS = {"scatter": 4, "shield": 3, "radar": 3, "boots": 3, "freeze": 3, "gold": 3, "shockwave": 2, "blink": 3,
                "apple": 5, "potion": 2}   # as in server.py

# unflag: charged when an agent removes its own flag. Training-only shaping that stops bots from
# toggling a flag on and off as a "safe" way to pass a turn (the lab's default is -0.5).
DEFAULT_REWARDS = dict(reveal=1.0, dig=0.0, mine=-10.0, flag_correct=3.0, flag_wrong=-3.0, step=0.0, clear=0.0, unflag=0.0,
                       ko=-15.0, pvp_ko=20.0, boss_hit=1.0, boss_kill=40.0, item=2.0, floor=10.0, stairs=20.0)
# rich-mode rules, in tiles and steps (one step is roughly one bot decision in the game)
RICH = dict(max_hp=100, mine_damage=35, smash_damage=30, pvp_damage=15, attack_damage=12, boss_hp=300,
            respawn=10, boss_delay=15, boss_respawn=100, windup=2, cooldown=4, aggro=8, boss_speed=0.7, smash_stun=2,
            # extras (v3), from server.py's TRAP_*, SPIKE_*, ITEM_*, FOOD, STAIRS_AUTO at ~0.5 s per step
            trap_density=10 / 1024, spike_cycle=6, spike_up=2, spike_damage=15, spike_grace=2,
            item_density=28 / 1024, food_share=7 / 31, food_heal=35, stairs_auto=60,
            # curriculum: this share of descent boards start with everything dug except a square of
            # radius 1..practice_radius around the first dig, so finishing a floor and finding the
            # stairs comes up often (radius 1 = the safe first dig clears it at once)
            descent_practice=0.0, practice_radius=3,
            # powers (v4), from server.py's THROW_RANGE, SCATTER_*, FREEZE_*, SHOCK_*, BLINK_RANGE, BOSS_POWER_DAMAGE
            throw_range=6, scatter_radius=2, scatter_mines=6, scatter_damage=25, scatter_stun=3, scatter_boss=60,
            freeze_range=9, freeze_steps=8, freeze_boss=20, shock_radius=3, shock_damage=10, shock_stun=3,
            shock_boss=40, boss_stagger=2, blink_range=8)


def obs_dim(radius, version=1):
    K2 = (2 * radius + 1) ** 2
    if version >= 4:
        return K2 * N_CHANNELS_V3 + N_GLOBAL_V4
    if version >= 3:
        return K2 * N_CHANNELS_V3 + N_GLOBAL_V3
    return K2 * N_CHANNELS + N_GLOBAL if version < 2 else K2 * N_CHANNELS_V2 + N_GLOBAL_V2


def n_channels(version=1):
    return N_CHANNELS_V3 if version >= 3 else N_CHANNELS_V2 if version >= 2 else N_CHANNELS


def n_actions(version=1):
    return N_ACTIONS if version < 2 else N_ACTIONS + 1 if version < 4 else N_ACTIONS + 2


def _gather(t, flat):
    """t (N,H,W), flat (N,) or (N,K) flat tile indices -> values at those tiles."""
    N = t.shape[0]
    if flat.dim() == 1:
        return t.reshape(N, -1).gather(1, flat[:, None]).squeeze(1)
    return t.reshape(N, -1).gather(1, flat)


def encode(revealed, counts, exploded, flag_owner, pos, others, radius, floor=None, extra=None):
    """Observation for one agent per board.

    revealed, exploded, others: (N,H,W) bool. counts: (N,H,W) long. flag_owner: (N,H,W) int (-1 = none).
    pos: (N,2) long (y, x) of the observing agent. floor: optional (N,H,W) bool; walls (False) are
    encoded exactly like the area outside the board, in the "out of bounds" channel.
    extra (v2 only): dict with boss, danger, allies (N,H,W) bool; hp (N,) in 0..1; mode (N,) long;
    boss_pos (N,2) long; boss_on (N,) bool; boss_hp (N,) in 0..1; windup (N,) bool.
    v3 when extra also has "goal": trap, spikes, items, goal (N,H,W) bool; goal_pos (N,2); goal_on (N,).
    v4 when extra also has "held": held (N,) long (index in HELD), shield (N,) bool.
    Returns (N, obs_dim(radius, version)) float32.
    """
    N, H, W = revealed.shape
    r, K = radius, 2 * radius + 1
    dev = revealed.device
    flagged = (flag_owner >= 0) & ~revealed
    hidden = ~revealed & ~flagged
    if floor is not None:
        hidden = hidden & floor
    shown = revealed & ~exploded
    n = counts.clamp(max=4)
    planes = [hidden, flagged, exploded,
              shown & (n == 0), shown & (n == 1), shown & (n == 2), shown & (n == 3), shown & (n == 4), others]
    v3 = extra is not None and "goal" in extra
    if extra is not None:
        planes += [extra["boss"], extra["danger"], extra["allies"]]
    if v3:
        planes += [extra["trap"], extra["spikes"], extra["items"], extra["goal"]]
    C = len(planes) + 1
    chans = F.pad(torch.stack(planes, 1).float(), (r, r, r, r))
    inner = torch.zeros(N, 1, H, W, device=dev) if floor is None else (~floor).float().unsqueeze(1)
    oob = F.pad(inner, (r, r, r, r), value=1.0)
    full = torch.cat([chans, oob], 1)                                      # (N, C, H+2r, W+2r)
    Wp = W + 2 * r
    ks = torch.arange(K, device=dev)
    rows = pos[:, 0:1] + ks                                                # padded coords: y - r + r + k
    cols = pos[:, 1:2] + ks
    idx = (rows[:, :, None] * Wp + cols[:, None, :]).reshape(N, 1, K * K).expand(N, C, K * K)
    win = full.reshape(N, C, -1).gather(2, idx).reshape(N, -1)

    # direction and distance to the nearest diggable tile (helps when the window is empty)
    gy = torch.arange(H, device=dev).view(1, H, 1)
    gx = torch.arange(W, device=dev).view(1, 1, W)
    py, px = pos[:, 0].view(N, 1, 1), pos[:, 1].view(N, 1, 1)
    d = torch.maximum((gy - py).abs(), (gx - px).abs()).float()
    d = torch.where(hidden, d, torch.full_like(d, 1e9)).reshape(N, -1)
    dmin, arg = d.min(1)
    has = dmin < 1e8
    ty, tx = arg // W, arg % W
    den = dmin.clamp(min=1.0)
    g = [
        torch.where(has, (ty - pos[:, 0]).float() / den, torch.zeros_like(den)),
        torch.where(has, (tx - pos[:, 1]).float() / den, torch.zeros_like(den)),
        torch.where(has, dmin.clamp(max=16.0) / 16.0, torch.ones_like(den)),
    ]
    if extra is not None:
        on = extra["boss_on"]
        bdy = (extra["boss_pos"][:, 0] - pos[:, 0]).float()
        bdx = (extra["boss_pos"][:, 1] - pos[:, 1]).float()
        bd = torch.maximum(bdy.abs(), bdx.abs())
        bden = bd.clamp(min=1.0)
        zero = torch.zeros(N, device=dev)
        mode = extra["mode"]
        modes = [(mode == 0), (mode == 1), (mode == 2), (mode == 3)] if v3 else [(mode == 0), (mode == 1), (mode >= 2)]
        g += [extra["hp"].float(), *[m.float() for m in modes],
              torch.where(on, bdy / bden, zero), torch.where(on, bdx / bden, zero),
              torch.where(on, bd.clamp(max=16.0) / 16.0, torch.ones(N, device=dev)),
              on.float(), torch.where(on, extra["boss_hp"].float(), zero), (on & extra["windup"]).float()]
    if v3:
        gon = extra["goal_on"]
        gdy = (extra["goal_pos"][:, 0] - pos[:, 0]).float()
        gdx = (extra["goal_pos"][:, 1] - pos[:, 1]).float()
        gd = torch.maximum(gdy.abs(), gdx.abs())
        gden = gd.clamp(min=1.0)
        zero = torch.zeros(N, device=dev)
        g += [torch.where(gon, gdy / gden, zero), torch.where(gon, gdx / gden, zero),
              torch.where(gon, gd.clamp(max=16.0) / 16.0, torch.ones(N, device=dev)), gon.float()]
    if extra is not None and "held" in extra:
        held = extra["held"]
        g += [(held == k).float() for k in range(1, len(HELD))] + [extra["shield"].float()]
    return torch.cat([win, torch.stack(g, 1)], 1)


def action_mask(revealed, flag_owner, pos, agent, floor=None, attack_ok=None, use_ok=None):
    """(N, N_ACTIONS [+1 [+1]]) bool of actions that would do something for `agent` standing at pos (N,2).
    With a floor mask, moves into walls and digs/flags on walls are masked out. With attack_ok (N,)
    (v2), an attack column is appended; with use_ok (N,) (v4) a use-item column after it."""
    N, H, W = revealed.shape
    dev = revealed.device
    mv = torch.tensor(MOVES, device=dev)
    nr = torch.tensor(NEAR, device=dev)
    my = pos[:, 0:1] + mv[:, 0]
    mx = pos[:, 1:2] + mv[:, 1]
    move_ok = (my >= 0) & (my < H) & (mx >= 0) & (mx < W)
    if floor is not None:
        move_ok &= _gather(floor, my.clamp(0, H - 1) * W + mx.clamp(0, W - 1))
    ty = pos[:, 0:1] + nr[:, 0]
    tx = pos[:, 1:2] + nr[:, 1]
    inb = (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W)
    flat = ty.clamp(0, H - 1) * W + tx.clamp(0, W - 1)
    if floor is not None:
        inb &= _gather(floor, flat)
    rev = _gather(revealed, flat)
    own = _gather(flag_owner, flat) == agent
    dig_ok = inb & ~rev & ~own
    flag_ok = inb & ~rev
    parts = [move_ok, dig_ok, flag_ok]
    if attack_ok is not None:
        parts.append(attack_ok.view(N, 1))
    if use_ok is not None:
        parts.append(use_ok.view(N, 1))
    return torch.cat(parts, 1)


_BANK = {}


def dungeon_bank(h, w, size=96):
    """A cached bank of dungeon layouts (size, h, w) bool; boards sample from it on reset."""
    if (h, w) not in _BANK:
        rng = random.Random(h * 1000 + w)
        _BANK[(h, w)] = torch.stack([torch.tensor(list(layouts.dungeon(w, h, rng)), dtype=torch.bool).view(h, w)
                                     for _ in range(size)])
    return _BANK[(h, w)]


class MineEnv:
    def __init__(self, n, agents=1, h=16, w=16, mines=40, steps=250, stun=10, rewards=None, device="cpu",
                 layout="field", rich=False, mode="race", bosses=False, params=None, extras=False, powers=False):
        """layout: "field" (every tile is floor) or "dungeon" (rooms and corridors from layouts.py).
        For dungeons `mines` is read as a density: each board gets mines/(h*w) of its floor tiles.
        rich / mode / bosses: see the module docstring."""
        assert mines <= h * w - 9, "too many mines for the board"
        self.N, self.A, self.H, self.W = n, agents, h, w
        self.layout = layout if layout in ("field", "dungeon") else "field"
        self.density = mines / (h * w)
        self.n_mines, self.steps, self.stun_steps = mines, steps, stun
        self.rw = {**DEFAULT_REWARDS, **(rewards or {})}
        self.rich = bool(rich)
        self.mode_name = mode if mode in MODES + ["mixed"] else "race"
        self.bosses = bool(bosses) and self.rich
        self.extras = bool(extras or powers) and self.rich
        self.powers = bool(powers) and self.extras
        self.p = {**RICH, **(params or {})}
        self.device = torch.device(device)
        self.kernel = torch.ones(1, 1, 3, 3, device=self.device)
        self.moves = torch.tensor(MOVES, device=self.device)
        self.near = torch.tensor(NEAR, device=self.device)
        self.reset()

    def reset(self):
        N, A, H, W, dev = self.N, self.A, self.H, self.W, self.device
        self.mines = torch.zeros(N, H, W, dtype=torch.bool, device=dev)
        self.counts = torch.zeros(N, H, W, dtype=torch.long, device=dev)
        self.revealed = torch.zeros(N, H, W, dtype=torch.bool, device=dev)
        self.exploded = torch.zeros(N, H, W, dtype=torch.bool, device=dev)
        self.flag_owner = torch.full((N, H, W), -1, dtype=torch.int8, device=dev)
        self.generated = torch.zeros(N, dtype=torch.bool, device=dev)
        if self.layout == "dungeon":
            bank = dungeon_bank(H, W).to(dev)
            self.floor = bank[torch.randint(0, bank.shape[0], (N,), device=dev)]
        else:
            self.floor = torch.ones(N, H, W, dtype=torch.bool, device=dev)
        n_floor = self.floor.reshape(N, -1).sum(1)
        if self.layout == "dungeon":
            self.board_mines = (n_floor.float() * self.density).round().long().clamp(min=1).minimum(n_floor - 9)
        else:
            self.board_mines = torch.full((N,), self.n_mines, dtype=torch.long, device=dev)
        # agents start on random floor tiles
        start = torch.multinomial(self.floor.reshape(N, -1).float(), A, replacement=True)
        self.pos = torch.stack([start // W, start % W], 2)
        self.stun = torch.zeros(N, A, dtype=torch.long, device=dev)
        self.score = torch.zeros(N, A, device=dev)
        self.done = torch.zeros(N, dtype=torch.bool, device=dev)
        self.t = 0
        z = lambda: torch.zeros(N, A, device=dev)
        self.stats = dict(tiles=z(), digs=z(), mines_hit=z(), flags_correct=z(), flags_wrong=z(), unflags=z())
        self.cleared = torch.zeros(N, dtype=torch.bool, device=dev)
        self.safe_total = n_floor - self.board_mines
        # rich-mode state
        mi = MODES.index(self.mode_name) if self.mode_name in MODES else -1
        n_modes = 4 if self.extras else 3
        if mi == 3 and not self.extras:
            mi = 2                      # descent without extras is just co-op
        self.mode = (torch.randint(0, n_modes, (N,), device=dev) if mi < 0 else torch.full((N,), mi, dtype=torch.long, device=dev))
        if not self.rich:
            self.mode.zero_()
        self.hp = torch.full((N, A), float(self.p["max_hp"]), device=dev)
        self.ko = torch.zeros(N, A, dtype=torch.bool, device=dev)
        self.boss_on = torch.zeros(N, dtype=torch.bool, device=dev)
        self.boss_pos = torch.zeros(N, 2, dtype=torch.long, device=dev)
        self.boss_hp = torch.zeros(N, device=dev)
        self.boss_windup = torch.zeros(N, dtype=torch.long, device=dev)
        self.boss_cd = torch.zeros(N, dtype=torch.long, device=dev)
        self.boss_next = torch.full((N,), self.p["boss_delay"], dtype=torch.long, device=dev)
        if self.rich:
            self.stats.update(kos=z(), boss_damage=z(), boss_kills=z(), pvp_kos=z())
        # extras (v3) state: traps with a phase each, pickups (1 power-up, 2 food), descent stairs
        self.traps = torch.zeros(N, H, W, dtype=torch.bool, device=dev)
        self.phase = torch.zeros(N, H, W, dtype=torch.long, device=dev)
        self.items = torch.zeros(N, H, W, dtype=torch.int8, device=dev)
        self.spike_cd = torch.zeros(N, A, dtype=torch.long, device=dev)
        self.stairs_on = torch.zeros(N, dtype=torch.bool, device=dev)
        self.stairs_pos = torch.zeros(N, 2, dtype=torch.long, device=dev)
        self.stairs_t = torch.zeros(N, dtype=torch.long, device=dev)
        if self.extras:
            self.stats.update(items=z(), spikes=z(), stairs=z())
        # powers (v4) state: the held item (index in HELD), a shield, and a boss stagger/freeze timer
        self.held = torch.zeros(N, A, dtype=torch.long, device=dev)
        self.shield = torch.zeros(N, A, dtype=torch.bool, device=dev)
        self.boss_stun = torch.zeros(N, dtype=torch.long, device=dev)
        if self.powers:
            self.stats.update(uses=z(), shielded=z())

    # ---------------------------------------------------------------- observations
    def others_mask(self, a, split=False):
        """Tiles with other (conscious) agents. split=True returns (rivals, allies): in co-op every
        other agent is an ally."""
        N, H, W = self.N, self.H, self.W
        rivals = torch.zeros(N, H, W, dtype=torch.bool, device=self.device)
        allies = torch.zeros(N, H, W, dtype=torch.bool, device=self.device)
        ar = torch.arange(N, device=self.device)
        coop = self.mode >= 2
        for o in range(self.A):
            if o == a:
                continue
            here = ~self.ko[:, o]
            y, x = self.pos[:, o, 0], self.pos[:, o, 1]
            if split:
                rivals[ar, y, x] |= here & ~coop
                allies[ar, y, x] |= here & coop
            else:
                rivals[ar, y, x] |= here
        return (rivals, allies) if split else rivals

    def boss_masks(self):
        N, H, W = self.N, self.H, self.W
        boss = torch.zeros(N, H, W, dtype=torch.bool, device=self.device)
        ar = torch.arange(N, device=self.device)
        boss[ar, self.boss_pos[:, 0], self.boss_pos[:, 1]] = self.boss_on
        winding = self.boss_on & (self.boss_windup > 0)
        danger = F.max_pool2d((boss & winding.view(N, 1, 1)).float().unsqueeze(1), 3, 1, 1).squeeze(1) > 0
        return boss, danger

    def spikes_up(self):
        """(N,H,W) bool: revealed traps whose spikes are up at the current step."""
        p = self.p
        return self.traps & self.revealed & ((self.t + self.phase) % p["spike_cycle"] < p["spike_up"])

    def extra(self, a, version=2):
        rivals, allies = self.others_mask(a, split=True)
        boss, danger = self.boss_masks()
        ex = {"boss": boss, "danger": danger, "allies": allies, "hp": self.hp[:, a] / self.p["max_hp"],
              "mode": self.mode, "boss_pos": self.boss_pos, "boss_on": self.boss_on,
              "boss_hp": self.boss_hp / self.p["boss_hp"], "windup": self.boss_windup > 0}
        if version >= 3:
            N, H, W = self.N, self.H, self.W
            goal = torch.zeros(N, H, W, dtype=torch.bool, device=self.device)
            goal[torch.arange(N, device=self.device), self.stairs_pos[:, 0], self.stairs_pos[:, 1]] = self.stairs_on
            ex.update(trap=self.traps & self.revealed, spikes=self.spikes_up(), items=(self.items > 0) & self.revealed,
                      goal=goal, goal_pos=self.stairs_pos, goal_on=self.stairs_on)
        if version >= 4:
            ex.update(held=self.held[:, a], shield=self.shield[:, a])
        return rivals, ex

    def observe(self, a, radius, version=1):
        if version >= 2:
            rivals, ex = self.extra(a, version)
            return encode(self.revealed, self.counts, self.exploded, self.flag_owner, self.pos[:, a], rivals,
                          radius, self.floor, ex)
        return encode(self.revealed, self.counts, self.exploded, self.flag_owner, self.pos[:, a], self.others_mask(a),
                      radius, self.floor)

    def attack_ok(self, a):
        """Would an attack hit something? A boss within one tile, or in PvP a conscious rival."""
        py, px = self.pos[:, a, 0], self.pos[:, a, 1]
        d_boss = torch.maximum((self.boss_pos[:, 0] - py).abs(), (self.boss_pos[:, 1] - px).abs())
        ok = self.boss_on & (d_boss <= 1)
        if self.A > 1:
            d = torch.maximum((self.pos[:, :, 0] - py[:, None]).abs(), (self.pos[:, :, 1] - px[:, None]).abs())
            d[:, a] = 99
            d[self.ko] = 99
            ok |= (self.mode == 1) & (d.min(1).values <= 1)
        return ok

    def _foe(self, a):
        """The nearest foe of agent a on every board: a conscious rival (not in co-op) or the boss.
        Returns (distance (N,) float (1e9 = none), y, x, is_boss (N,) bool, rival index (N,))."""
        N, A = self.N, self.A
        py, px = self.pos[:, a, 0], self.pos[:, a, 1]
        d = torch.maximum((self.pos[:, :, 0] - py[:, None]).abs(), (self.pos[:, :, 1] - px[:, None]).abs()).float()
        d[:, a] = 1e9
        d[self.ko | (self.stun > 0)] = 1e9       # like the game, skip rivals who are already stunned
        d[self.mode >= 2] = 1e9                  # teammates aren't targets
        dr, ri = d.min(1)
        db = torch.where(self.boss_on, torch.maximum((self.boss_pos[:, 0] - py).abs(),
                                                     (self.boss_pos[:, 1] - px).abs()).float(), torch.full_like(dr, 1e9))
        boss = db < dr                           # rivals first on a tie, like the game's sort
        ar = torch.arange(N, device=self.device)
        y = torch.where(boss, self.boss_pos[:, 0], self.pos[ar, ri, 0])
        x = torch.where(boss, self.boss_pos[:, 1], self.pos[ar, ri, 1])
        return torch.minimum(dr, db), y, x, boss, ri

    def _blink_spot(self, a):
        """Where a blink would take agent a: the dug-up tile within blink_range with the most hidden
        neighbours (more than 2), or none. Returns (ok (N,), y, x)."""
        N, H, W = self.N, self.H, self.W
        hid = (~self.revealed & self.floor).float().unsqueeze(1)
        n = F.conv2d(hid, self.kernel, padding=1).squeeze(1)
        py, px = self.pos[:, a, 0].view(N, 1, 1), self.pos[:, a, 1].view(N, 1, 1)
        yy = torch.arange(H, device=self.device).view(1, H, 1)
        xx = torch.arange(W, device=self.device).view(1, 1, W)
        near = torch.maximum((yy - py).abs(), (xx - px).abs()) <= self.p["blink_range"]
        cand = self.revealed & ~self.exploded & self.floor & near & (n > 2)
        score = torch.where(cand, n + torch.rand(N, H, W, device=self.device) * 0.5, torch.full_like(n, -1.0))
        best = score.reshape(N, -1).argmax(1)
        return cand.reshape(N, -1).any(1), best // W, best % W

    def use_ok(self, a):
        """Would USE do something? The held item has a target (scatter, freeze), always (shockwave), or
        somewhere worth blinking to. Items only work once the board has mines (as in the game)."""
        h = self.held[:, a]
        ok = (h == 3)
        if bool(((h == 1) | (h == 2)).any()):
            d = self._foe(a)[0]
            ok |= (h == 1) & (d <= self.p["throw_range"]) | (h == 2) & (d <= self.p["freeze_range"])
        if bool((h == 4).any()):
            ok |= (h == 4) & self._blink_spot(a)[0]
        return ok & (h > 0) & self.generated & ~self.ko[:, a]

    def mask(self, a, version=1):
        if version >= 4:
            return action_mask(self.revealed, self.flag_owner, self.pos[:, a], a, self.floor, self.attack_ok(a), self.use_ok(a))
        if version >= 2:
            return action_mask(self.revealed, self.flag_owner, self.pos[:, a], a, self.floor, self.attack_ok(a))
        return action_mask(self.revealed, self.flag_owner, self.pos[:, a], a, self.floor)

    def fitness(self):
        """Per-agent fitness: own score, except co-op boards where everyone gets the team average."""
        s = self.score.clone()
        if self.rich:
            coop = self.mode >= 2
            if coop.any():
                s[coop] = s[coop].mean(1, keepdim=True).expand(-1, self.A)
        return s

    # ---------------------------------------------------------------- rules
    def _generate(self, boards, ty, tx):
        idx = boards.nonzero().squeeze(1)
        if idx.numel() == 0:
            return
        n, H, W = idx.numel(), self.H, self.W
        scores = torch.rand(n, H, W, device=self.device)
        yy = torch.arange(H, device=self.device).view(1, H, 1)
        xx = torch.arange(W, device=self.device).view(1, 1, W)
        excl = ((yy - ty[idx].view(n, 1, 1)).abs() <= 1) & ((xx - tx[idx].view(n, 1, 1)).abs() <= 1)
        scores[excl] = 2.0
        scores[~self.floor[idx]] = 3.0          # walls never hold mines
        # the board_mines[b] lowest-scoring tiles of each board become mines
        order = scores.reshape(n, -1).argsort(1)
        ranks = torch.empty_like(order)
        ranks.scatter_(1, order, torch.arange(H * W, device=self.device).expand(n, -1))
        m = (ranks < self.board_mines[idx].view(n, 1)).view(n, H, W)
        self.mines[idx] = m
        c = F.conv2d(m.float().unsqueeze(1), self.kernel, padding=1).squeeze(1).round().long()
        self.counts[idx] = c - m.long()
        self.generated[idx] = True
        if self.extras:
            p = self.p
            free = self.floor[idx] & ~m & ~excl
            tr = free & (torch.rand(n, H, W, device=self.device) < p["trap_density"])
            self.traps[idx] = tr
            self.phase[idx] = torch.randint(0, p["spike_cycle"], (n, H, W), device=self.device)
            it = free & ~tr & (torch.rand(n, H, W, device=self.device) < p["item_density"])
            if self.powers:
                kinds = list(ITEM_WEIGHTS)
                w = torch.tensor([ITEM_WEIGHTS[k] for k in kinds], dtype=torch.float, device=self.device)
                pick = torch.multinomial(w, n * H * W, replacement=True).view(n, H, W)
                code = torch.tensor([ITEM_CODES[k] for k in kinds], dtype=torch.int8, device=self.device)[pick]
                coop = (self.mode[idx] >= 2).view(n, 1, 1)
                code = torch.where(coop & (code == ITEM_CODES["scatter"]), torch.ones_like(code), code)   # no scatter in co-op
                self.items[idx] = torch.where(it, code, torch.zeros_like(code))
            else:
                food = torch.rand(n, H, W, device=self.device) < p["food_share"]
                self.items[idx] = torch.where(it, torch.where(food, 2, 1), 0).to(torch.int8)
            practice = (self.mode[idx] == 3) & (torch.rand(n, device=self.device) < p["descent_practice"])
            if practice.any():
                rad = torch.randint(1, p["practice_radius"] + 1, (n, 1, 1), device=self.device)
                far = torch.maximum((yy - ty[idx].view(n, 1, 1)).abs(), (xx - tx[idx].view(n, 1, 1)).abs()) > rad
                pre = practice.view(n, 1, 1) & far & self.floor[idx] & ~m
                self.revealed[idx] |= pre
                self.items[idx] = torch.where(pre, torch.zeros_like(self.items[idx]), self.items[idx])

    def _flood(self, seed):
        new = seed & ~self.revealed
        frontier = new & (self.counts == 0)
        while frontier.any():
            grown = F.max_pool2d(frontier.float().unsqueeze(1), 3, 1, 1).squeeze(1) > 0
            grown &= ~self.revealed & ~new & ~self.mines & self.floor
            new |= grown
            frontier = grown & (self.counts == 0)
        return new

    def _targets(self, ar, a, act, base):
        off = self.near[(act - base).clamp(0, 8)]
        ty = self.pos[ar, a, 0] + off[:, 0]
        tx = self.pos[ar, a, 1] + off[:, 1]
        inb = (ty >= 0) & (ty < self.H) & (tx >= 0) & (tx < self.W)
        tyc, txc = ty.clamp(0, self.H - 1), tx.clamp(0, self.W - 1)
        flat = tyc * self.W + txc
        return inb & _gather(self.floor, flat), tyc, txc, flat

    def _hurt(self, b, ag, amount, by=None, stun=0):
        """Damage agents ag on boards b (1-D long tensors, unique boards). Handles knockouts."""
        if b.numel() == 0:
            return
        if self.powers:
            sh = self.shield[b, ag]
            if sh.any():          # a shield soaks the whole hit
                self.shield[b[sh], ag[sh]] = False
                self.stats["shielded"][b[sh], ag[sh]] += 1
                b, ag = b[~sh], ag[~sh]
                by = by[~sh] if by is not None else None
                if b.numel() == 0:
                    return
        self.hp[b, ag] -= amount
        if stun:
            self.stun[b, ag] = torch.maximum(self.stun[b, ag], torch.full_like(self.stun[b, ag], stun))
        new_ko = (self.hp[b, ag] <= 0) & ~self.ko[b, ag]
        kb, ka = b[new_ko], ag[new_ko]
        if kb.numel():
            self.ko[kb, ka] = True
            self.hp[kb, ka] = 0
            self.stun[kb, ka] = torch.maximum(self.stun[kb, ka], torch.full_like(ka, self.p["respawn"]))
            self.score[kb, ka] += self.rw["ko"]
            self.stats["kos"][kb, ka] += 1
            if by is not None:
                kby = by[new_ko]
                pvp = self.mode[kb] == 1
                self.score[kb[pvp], kby[pvp]] += self.rw["pvp_ko"]
                self.stats["pvp_kos"][kb[pvp], kby[pvp]] += 1

    def _respawn(self):
        back = self.ko & (self.stun == 0)
        if not back.any():
            return
        b, a = back.nonzero(as_tuple=True)
        spot = torch.multinomial(self.floor[b].reshape(b.numel(), -1).float(), 1).squeeze(1)
        self.pos[b, a, 0], self.pos[b, a, 1] = spot // self.W, spot % self.W
        self.hp[b, a] = float(self.p["max_hp"])
        self.ko[b, a] = False

    def _boss_step(self, live):
        N, H, W, p, dev = self.N, self.H, self.W, self.p, self.device
        spawn = live & ~self.boss_on & (self.t >= self.boss_next)
        if spawn.any():
            s = spawn.nonzero().squeeze(1)
            spot = torch.multinomial(self.floor[s].reshape(s.numel(), -1).float(), 1).squeeze(1)
            self.boss_pos[s, 0], self.boss_pos[s, 1] = spot // W, spot % W
            self.boss_on[s] = True
            self.boss_hp[s] = float(p["boss_hp"])
            self.boss_windup[s] = 0
            self.boss_cd[s] = 0
        held_still = self.boss_stun > 0               # frozen or staggered (power-ups)
        self.boss_stun = (self.boss_stun - 1).clamp(min=0)
        on = live & self.boss_on & ~held_still
        if not on.any():
            return
        d = torch.maximum((self.pos[:, :, 0] - self.boss_pos[:, None, 0]).abs(),
                          (self.pos[:, :, 1] - self.boss_pos[:, None, 1]).abs()).float()
        d[self.ko] = 1e9
        dmin, tgt = d.min(1)
        winding = on & (self.boss_windup > 0)
        self.boss_windup[winding] -= 1
        smash = winding & (self.boss_windup == 0)
        if smash.any():
            hit = smash[:, None] & (d <= 1)
            b, ag = hit.nonzero(as_tuple=True)
            self._hurt(b, ag, p["smash_damage"], stun=p["smash_stun"])
            self.boss_cd[smash] = p["cooldown"]
        start = on & ~winding & (dmin <= 1) & (self.boss_cd == 0)
        self.boss_windup[start] = p["windup"]
        free = on & ~winding & ~start
        chase = free & (dmin <= p["aggro"]) & (dmin > 1) & (torch.rand(N, device=dev) < p["boss_speed"])
        wander = free & (dmin > p["aggro"]) & (torch.rand(N, device=dev) < 0.3)
        ar = torch.arange(N, device=dev)
        ty = torch.where(chase, self.pos[ar, tgt, 0], self.boss_pos[:, 0] + torch.randint(-1, 2, (N,), device=dev))
        tx = torch.where(chase, self.pos[ar, tgt, 1], self.boss_pos[:, 1] + torch.randint(-1, 2, (N,), device=dev))
        sy, sx = (ty - self.boss_pos[:, 0]).sign(), (tx - self.boss_pos[:, 1]).sign()
        by, bx = self.boss_pos[:, 0], self.boss_pos[:, 1]
        fl = lambda y, x: _gather(self.floor, y.clamp(0, H - 1) * W + x.clamp(0, W - 1)) & (y >= 0) & (y < H) & (x >= 0) & (x < W)
        moving = chase | wander
        diag = moving & (sy != 0) & (sx != 0) & fl(by + sy, bx + sx) & fl(by + sy, bx) & fl(by, bx + sx)
        only_y = moving & ~diag & (sy != 0) & fl(by + sy, bx)
        only_x = moving & ~diag & ~only_y & (sx != 0) & fl(by, bx + sx)
        self.boss_pos[:, 0] = torch.where(diag | only_y, by + sy, by)
        self.boss_pos[:, 1] = torch.where(diag | only_x, bx + sx, bx)
        self.boss_cd = (self.boss_cd - 1).clamp(min=0)

    def step(self, actions):
        """actions: (N, A) long. Returns the per-agent reward for this step, shape (N, A)."""
        N, A, H, W = self.N, self.A, self.H, self.W
        rw = self.rw
        before = self.score.clone()
        live = ~self.done
        if self.rich:
            self._respawn()
        stunned = self.stun > 0
        self.stun = (self.stun - 1).clamp(min=0)
        ar = torch.arange(N, device=self.device)
        # each board gets its own random acting order every step, so no agent is systematically first
        # (acting first matters: the first dig of a board is guaranteed safe and opens a big area)
        order = torch.rand(N, A, device=self.device).argsort(1)
        for k in range(A):
            a = order[:, k]               # (N,) which agent acts in this slot on each board
            act = actions[ar, a]
            active = live & ~self.done & ~stunned[ar, a]

            mv = active & (act < DIG0)
            if mv.any():
                d = self.moves[act.clamp(max=7)]
                py, px = self.pos[ar, a, 0], self.pos[ar, a, 1]
                ny, nx = (py + d[:, 0]).clamp(0, H - 1), (px + d[:, 1]).clamp(0, W - 1)
                ok = mv & _gather(self.floor, ny * W + nx)     # walls block movement
                self.pos[ar, a, 0] = torch.where(ok, ny, py)
                self.pos[ar, a, 1] = torch.where(ok, nx, px)

            dg = active & (act >= DIG0) & (act < FLAG0)
            if dg.any():
                inb, ty, tx, flat = self._targets(ar, a, act, DIG0)
                valid = dg & inb & ~_gather(self.revealed, flat) & (_gather(self.flag_owner, flat).long() != a)
                gen = valid & ~self.generated
                if gen.any():
                    self._generate(gen, ty, tx)
                is_mine = _gather(self.mines, flat)
                boom = valid & is_mine
                if boom.any():
                    b = boom.nonzero().squeeze(1)
                    ab = a[b]
                    self.revealed.view(N, -1)[b, flat[b]] = True
                    self.exploded.view(N, -1)[b, flat[b]] = True
                    self.flag_owner.view(N, -1)[b, flat[b]] = -1
                    if self.powers:   # a shield soaks the blast: no penalty, stun or damage
                        sh = self.shield[b, ab]
                        self.shield[b[sh], ab[sh]] = False
                        self.stats["shielded"][b[sh], ab[sh]] += 1
                        b, ab = b[~sh], ab[~sh]
                    self.score[b, ab] += rw["mine"]
                    self.stun[b, ab] = self.stun_steps
                    self.stats["mines_hit"][b, ab] += 1
                    if self.rich:
                        self._hurt(b, ab, self.p["mine_damage"])
                safe = valid & ~is_mine
                if safe.any():
                    s = safe.nonzero().squeeze(1)
                    seed = torch.zeros(N, H * W, dtype=torch.bool, device=self.device)
                    seed[s, flat[s]] = True
                    new = self._flood(seed.view(N, H, W))
                    cnt = new.reshape(N, -1).sum(1).float()
                    opened = (cnt > 0).float()     # one safe dig, however many tiles it floods open
                    self.score[ar, a] += cnt * rw["reveal"] + opened * rw["dig"]
                    self.stats["tiles"][ar, a] += cnt
                    self.stats["digs"][ar, a] += opened
                    for o in range(A):
                        lost = (new & (self.flag_owner == o)).reshape(N, -1).sum(1).float()
                        self.score[:, o] += lost * rw["flag_wrong"]
                        self.stats["flags_wrong"][:, o] += lost
                    self.flag_owner[new] = -1
                    self.revealed |= new

            fl = active & (act >= FLAG0) & (act < ATTACK)
            if fl.any():
                inb, ty, tx, flat = self._targets(ar, a, act, FLAG0)
                valid = fl & inb & ~_gather(self.revealed, flat)
                owner = _gather(self.flag_owner, flat)
                me = a.to(owner.dtype)
                removed = valid & (owner == me)            # taking your own flag back off
                new_owner = torch.where(valid & (owner < 0), me,
                                        torch.where(removed, torch.full_like(owner, -1), owner))
                self.flag_owner.view(N, -1).scatter_(1, flat[:, None], new_owner[:, None])
                if removed.any():
                    rb = removed.nonzero().squeeze(1)
                    self.score[rb, a[rb]] += rw["unflag"]
                    self.stats["unflags"][rb, a[rb]] += 1

            at = active & (act == ATTACK)
            if self.rich and at.any():
                py, px = self.pos[ar, a, 0], self.pos[ar, a, 1]
                d_boss = torch.maximum((self.boss_pos[:, 0] - py).abs(), (self.boss_pos[:, 1] - px).abs())
                hit_boss = at & self.boss_on & (d_boss <= 1)
                if hit_boss.any():
                    hb = hit_boss.nonzero().squeeze(1)
                    self._damage_boss(hb, a[hb], float(self.p["attack_damage"]))
                pvp = at & ~hit_boss & (self.mode == 1)
                if pvp.any() and A > 1:
                    d = torch.maximum((self.pos[:, :, 0] - py[:, None]).abs(), (self.pos[:, :, 1] - px[:, None]).abs()).float()
                    d[ar, a] = 1e9
                    d[self.ko] = 1e9
                    dmin, victim = d.min(1)
                    hit = (pvp & (dmin <= 1)).nonzero().squeeze(1)
                    self._hurt(hit, victim[hit], self.p["pvp_damage"], by=a[hit], stun=1)

            us = active & (act == USE)
            if self.powers and us.any():
                self._use(us & self.use_ok_cached(a), a)

        if self.bosses:
            self._boss_step(live)
        at_stairs = torch.zeros(N, dtype=torch.bool, device=self.device)
        if self.extras:
            at_stairs = self._extras_step(live)
        if rw["step"]:
            self.score[live] += rw["step"]
        safe_rev = (self.revealed & ~self.mines).reshape(N, -1).sum(1)
        just = live & self.generated & (safe_rev >= self.safe_total) & ~self.cleared
        descent = self.mode == 3
        if self.extras and (just & descent).any():
            self._open_stairs(just & descent)
        self.cleared |= just
        self.t += 1
        timeout = self.stairs_on & (self.t - self.stairs_t >= self.p["stairs_auto"])
        finished = live & ((self.cleared & ~descent) | at_stairs | timeout
                           | torch.tensor(self.t >= self.steps, device=self.device))
        if finished.any():
            self._finish(finished, finished & self.cleared)
        return self.score - before

    def use_ok_cached(self, a):
        """use_ok for the acting agents. a: (N,) agent index per board (the acting order differs by board)."""
        out = torch.zeros(self.N, dtype=torch.bool, device=self.device)
        for k in range(self.A):
            sel = a == k
            if sel.any():
                out |= sel & self.use_ok(k)
        return out

    def _damage_boss(self, b, by, dmg, stun=0):
        """Hurt the boss on boards b, credited to agents `by` (boss_hit per 10 damage, boss_kill)."""
        if b.numel() == 0:
            return
        rw = self.rw
        self.boss_hp[b] -= dmg
        self.score[b, by] += rw["boss_hit"] * dmg / 10
        self.stats["boss_damage"][b, by] += dmg
        if stun:
            self.boss_stun[b] = torch.maximum(self.boss_stun[b], torch.full_like(self.boss_stun[b], stun))
            self.boss_windup[b] = 0          # a stagger interrupts the wind-up
        dead = self.boss_hp[b] <= 0
        db, dby = b[dead], by[dead]
        if db.numel():
            self.boss_on[db] = False
            self.boss_next[db] = self.t + self.p["boss_respawn"]
            self.score[db, dby] += rw["boss_kill"]
            self.stats["boss_kills"][db, dby] += 1

    def _use(self, sel, a):
        """Agents a (per board) on boards `sel` use their held item (already checked by use_ok)."""
        N, H, W, p = self.N, self.H, self.W, self.p
        ar = torch.arange(N, device=self.device)
        held = self.held[ar, a]
        yy = torch.arange(H, device=self.device).view(1, H, 1)
        xx = torch.arange(W, device=self.device).view(1, 1, W)
        for b in sel.nonzero().view(-1).tolist():
            u, h = int(a[b]), int(held[b])
            B = torch.tensor([b], device=self.device)
            U = torch.tensor([u], device=self.device)
            uy, ux = int(self.pos[b, u, 0]), int(self.pos[b, u, 1])
            others = [o for o in range(self.A) if o != u and not bool(self.ko[b, o])]
            rivals = [] if int(self.mode[b]) >= 2 else others
            if h in (1, 2):
                d, ty, tx, boss, ri = (t[b] for t in self._foe(u))
                ty, tx = int(ty), int(tx)
            if h == 1:        # scatter: re-cover a 5x5, new mines in it, hurt everyone inside
                r = p["scatter_radius"]
                area = (torch.maximum((yy[0] - ty).abs(), (xx[0] - tx).abs()) <= r) & self.floor[b]
                for t in (self.revealed, self.exploded, self.mines, self.traps):
                    t[b][area] = False
                self.flag_owner[b][area] = -1
                self.items[b][area] = 0
                cells = area.view(-1).nonzero().view(-1)
                k = min(p["scatter_mines"], max(0, cells.numel() - 1))
                if k:
                    self.mines[b].view(-1)[cells[torch.randperm(cells.numel(), device=self.device)[:k]]] = True
                m = self.mines[b].float().view(1, 1, H, W)
                self.counts[b] = (F.conv2d(m, self.kernel, padding=1).view(H, W).round().long() - self.mines[b].long())
                self.safe_total[b] = self.floor[b].sum() - self.mines[b].sum()
                hit = [o for o in rivals + ([u] if int(self.mode[b]) < 2 else [])
                       if max(abs(int(self.pos[b, o, 0]) - ty), abs(int(self.pos[b, o, 1]) - tx)) <= r]
                if hit:
                    self._hurt(B.repeat(len(hit)), torch.tensor(hit, device=self.device), p["scatter_damage"],
                               by=U.repeat(len(hit)), stun=p["scatter_stun"])
                if bool(self.boss_on[b]) and max(abs(int(self.boss_pos[b, 0]) - ty), abs(int(self.boss_pos[b, 1]) - tx)) <= r:
                    self._damage_boss(B, U, float(p["scatter_boss"]), stun=p["boss_stagger"])
            elif h == 2:      # freeze: the nearest foe in range is frozen
                if bool(boss):
                    self.boss_stun[b] = max(int(self.boss_stun[b]), p["freeze_steps"])
                    self.boss_windup[b] = 0
                    self._damage_boss(B, U, float(p["freeze_boss"]))
                else:
                    V = torch.tensor([int(ri)], device=self.device)
                    if self.powers and bool(self.shield[b, int(ri)]):
                        self.shield[b, int(ri)] = False
                        self.stats["shielded"][b, int(ri)] += 1
                    else:
                        self.stun[B, V] = torch.maximum(self.stun[B, V], torch.full_like(V, p["freeze_steps"]))
            elif h == 3:      # shockwave: everyone within shock_radius (Euclidean)
                r2 = p["shock_radius"] ** 2
                hit = [o for o in rivals if (int(self.pos[b, o, 0]) - uy) ** 2 + (int(self.pos[b, o, 1]) - ux) ** 2 <= r2]
                if hit:
                    self._hurt(B.repeat(len(hit)), torch.tensor(hit, device=self.device), p["shock_damage"],
                               by=U.repeat(len(hit)), stun=p["shock_stun"])
                if bool(self.boss_on[b]) and (int(self.boss_pos[b, 0]) - uy) ** 2 + (int(self.boss_pos[b, 1]) - ux) ** 2 <= r2:
                    self._damage_boss(B, U, float(p["shock_boss"]), stun=p["boss_stagger"])
            elif h == 4:      # blink: to the most promising dug-up tile within reach
                ok, by_, bx_ = self._blink_spot(u)
                if bool(ok[b]):
                    self.pos[b, u, 0], self.pos[b, u, 1] = by_[b], bx_[b]
            self.held[b, u] = 0
            self.stats["uses"][b, u] += 1

    def _extras_step(self, live):
        """Pickups, spikes and the stairs, after everyone has acted. Returns boards whose stairs were reached."""
        N, A, p, rw = self.N, self.A, self.p, self.rw
        up = self.spikes_up()
        self.spike_cd = (self.spike_cd - 1).clamp(min=0)
        reached = torch.zeros(N, dtype=torch.bool, device=self.device)
        for a in range(A):
            y, x = self.pos[:, a, 0], self.pos[:, a, 1]
            awake = live & ~self.ko[:, a]
            flat = y * self.W + x
            kind = _gather(self.items, flat)
            rev = _gather(self.revealed, flat)
            hurt = self.hp[:, a] < p["max_hp"]
            wants = (kind == 1) | ((kind == 2) & hurt)
            if self.powers:   # a shield only if you have none; a held item only with empty hands
                wants |= ((kind == 3) & ~self.shield[:, a]) | ((kind >= 4) & (self.held[:, a] == 0))
            take = awake & (self.stun[:, a] == 0) & rev & wants
            if take.any():
                t = take.nonzero().squeeze(1)
                self.items.view(N, -1)[t, flat[t]] = 0
                food = t[kind[t] == 2]
                self.hp[food, a] = (self.hp[food, a] + p["food_heal"]).clamp(max=float(p["max_hp"]))
                if self.powers:
                    k = kind[t].long()
                    self.shield[t[k == 3], a] = True
                    hk = k >= 4
                    self.held[t[hk], a] = k[hk] - 3
                self.score[t, a] += rw["item"]
                self.stats["items"][t, a] += 1
            spiked = awake & (self.spike_cd[:, a] == 0) & _gather(up, flat)
            if spiked.any():
                s = spiked.nonzero().squeeze(1)
                self.spike_cd[s, a] = p["spike_grace"]
                self.stats["spikes"][s, a] += 1
                self._hurt(s, torch.full_like(s, a), p["spike_damage"], stun=1)
            reached |= (live & self.stairs_on & ~self.ko[:, a]
                        & (y == self.stairs_pos[:, 0]) & (x == self.stairs_pos[:, 1]))
        if reached.any():
            self.score[reached] += rw["stairs"]
            self.stats["stairs"][reached] += 1
        return reached

    def _open_stairs(self, boards):
        """Descent floor cleared: stairs 2-4 tiles from a random conscious agent, the floor bonus for
        everyone, and the boss leaves (as in server.floor_cleared)."""
        b = boards.nonzero().squeeze(1)
        n, H, W = b.numel(), self.H, self.W
        who = torch.multinomial((~self.ko[b]).float() + 1e-6, 1).squeeze(1)
        py, px = self.pos[b, who, 0], self.pos[b, who, 1]
        yy = torch.arange(H, device=self.device).view(1, H, 1)
        xx = torch.arange(W, device=self.device).view(1, 1, W)
        d = torch.maximum((yy - py.view(n, 1, 1)).abs(), (xx - px.view(n, 1, 1)).abs())
        ok = self.floor[b] & ~self.traps[b] & ~self.exploded[b] & (d >= 2) & (d <= 4)
        here = torch.zeros_like(ok)
        here[torch.arange(n, device=self.device), py, px] = True
        ok = torch.where(ok.reshape(n, -1).any(1).view(n, 1, 1), ok, here)
        spot = torch.multinomial(ok.reshape(n, -1).float(), 1).squeeze(1)
        self.stairs_pos[b, 0], self.stairs_pos[b, 1] = spot // W, spot % W
        self.stairs_on[b] = True
        self.stairs_t[b] = self.t
        self.score[b] += self.rw["floor"]
        self.boss_on[b] = False
        self.boss_next[b] = 1 << 30

    def _finish(self, fin, cleared):
        for o in range(self.A):
            mine_f = ((self.flag_owner == o) & self.mines).reshape(self.N, -1).sum(1).float()
            wrong_f = ((self.flag_owner == o) & ~self.mines).reshape(self.N, -1).sum(1).float()
            self.score[fin, o] += mine_f[fin] * self.rw["flag_correct"] + wrong_f[fin] * self.rw["flag_wrong"]
            self.score[cleared, o] += self.rw["clear"]
            self.stats["flags_correct"][fin, o] += mine_f[fin]
            self.stats["flags_wrong"][fin, o] += wrong_f[fin]
        self.cleared |= cleared
        self.done |= fin
