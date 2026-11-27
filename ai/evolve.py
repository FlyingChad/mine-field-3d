"""Neuroevolution trainer (genetic algorithm over flat weight vectors).

Each generation:
  1. every individual plays `episodes` boards (all boards run in parallel on the GPU),
  2. fitness = mean score with the game's scoring rules (weights adjustable),
  3. the top `elites` survive unchanged and the rest of the population is refilled with children of
     tournament-selected parents (optional uniform crossover) plus Gaussian mutation.

train_process() runs in its own process (started by ai/lab.py). It takes commands on `cmd_q` and
reports progress on `evt_q`.
"""
import math
import time
import traceback

import torch

from .env import MineEnv
from .models import load_model, save_model, safe_name
from .policy import Spec, choose, upgrade

# Every hyperparameter the lab exposes. The lab UI builds its form from this list.
# live=True means it can be changed while a run is in progress.
SCHEMA = [
    {"group": "Run", "fields": [
        {"key": "run_name", "label": "Run name", "type": "text", "default": "", "help": "Name used for auto-saved models. Blank = timestamp."},
        {"key": "generations", "label": "Generations", "type": "int", "default": 0, "min": 0, "max": 100000, "help": "Stop after this many generations (0 = run until stopped)."},
        {"key": "save_every", "label": "Auto-save every", "type": "int", "default": 10, "min": 1, "max": 1000, "help": "Save the current best model every N generations."},
        {"key": "seed_model", "label": "Start from model", "type": "model", "default": "", "help": "Continue evolving a saved model (same network shape). An older model (v2, v3) can seed a newer run (v3, v4) with the same radius and layers: it keeps everything it knows."},
        {"key": "device", "label": "Device", "type": "select", "options": ["auto", "cuda", "cpu"], "default": "auto"},
    ]},
    {"group": "Environment", "fields": [
        {"key": "layout", "label": "Map layout", "type": "select", "options": ["field", "dungeon"], "default": "field",
         "help": "dungeon = rooms and corridors like the game's dungeon maps (walls look like the board edge). Mines then sets the density."},
        {"key": "board_w", "label": "Board width", "type": "int", "default": 16, "min": 6, "max": 48},
        {"key": "board_h", "label": "Board height", "type": "int", "default": 16, "min": 6, "max": 48},
        {"key": "mines", "label": "Mines", "type": "int", "default": 40, "min": 1, "max": 2000, "help": "The real game uses ~15% density (150 on 32×32)."},
        {"key": "episode_steps", "label": "Steps per episode", "type": "int", "default": 250, "min": 10, "max": 5000, "help": "Actions each bot gets per board. Fewer steps reward speed."},
        {"key": "stun_steps", "label": "Stun after mine (steps)", "type": "int", "default": 10, "min": 0, "max": 200},
        {"key": "agents_per_board", "label": "Bots per board", "type": "int", "default": 2, "min": 1, "max": 6, "help": ">1 = random population members share a board (needed for PvP and co-op)."},
        {"key": "mode", "label": "Game mode", "type": "select", "options": ["mixed", "race", "pvp", "coop", "descent"], "default": "mixed",
         "help": "v2+ models only. mixed = each board gets a random mode, so one model learns them all (it sees which mode it's in). descent (v3) = co-op, then walk to the stairs."},
        {"key": "descent_practice", "label": "Descent practice", "type": "float", "default": 0.5, "min": 0, "max": 1, "step": 0.05, "live": True,
         "help": "v3 only. Share of descent boards that start almost fully dug, so bots often get to finish a floor and walk to the stairs."},
        {"key": "bosses", "label": "Bosses", "type": "bool", "default": True, "help": "v2 models only. A boss roams every board, winds up and smashes; bots can attack it."},
    ]},
    {"group": "Network", "fields": [
        {"key": "model_version", "label": "Model type", "type": "select", "options": ["4", "3", "2", "1"], "default": "4",
         "help": "4 = also holds power-ups and learns when to use them. 3 = sees spike traps, pickups and the stairs, and learns Descent. 2 = every mode: health, bosses, allies, attack. 1 = classic minesweeper only."},
        {"key": "radius", "label": "Vision radius", "type": "int", "default": 3, "min": 1, "max": 7, "help": "The bot sees a (2r+1)² window of tiles around itself."},
        {"key": "hidden", "label": "Hidden layers", "type": "text", "default": "64", "help": "Comma-separated layer sizes, e.g. 64 or 128,64."},
        {"key": "activation", "label": "Activation", "type": "select", "options": ["tanh", "relu", "elu"], "default": "tanh"},
        {"key": "action_masking", "label": "Mask invalid actions", "type": "bool", "default": True, "help": "Never pick moves off the board or digs on revealed tiles."},
        {"key": "action_noise", "label": "Action noise", "type": "float", "default": 0.0, "min": 0, "max": 5, "step": 0.05, "live": True, "help": "Gumbel noise on action choice (exploration)."},
    ]},
    {"group": "Evolution", "fields": [
        {"key": "population", "label": "Population", "type": "int", "default": 256, "min": 8, "max": 8192},
        {"key": "episodes", "label": "Boards per individual", "type": "int", "default": 4, "min": 1, "max": 64, "help": "More boards = less noisy fitness, slower generations."},
        {"key": "elites", "label": "Elites kept", "type": "int", "default": 8, "min": 1, "max": 512, "live": True},
        {"key": "tournament", "label": "Tournament size", "type": "int", "default": 4, "min": 1, "max": 64, "live": True, "help": "Higher = stronger selection pressure."},
        {"key": "sigma", "label": "Mutation σ", "type": "float", "default": 0.05, "min": 0.0001, "max": 2, "step": 0.005, "live": True},
        {"key": "sigma_decay", "label": "σ decay / gen", "type": "float", "default": 0.995, "min": 0.9, "max": 1, "step": 0.001, "live": True},
        {"key": "sigma_min", "label": "σ floor", "type": "float", "default": 0.01, "min": 0, "max": 1, "step": 0.001, "live": True},
        {"key": "mutation_rate", "label": "Mutation rate", "type": "float", "default": 1.0, "min": 0.001, "max": 1, "step": 0.01, "live": True, "help": "Fraction of weights perturbed per child."},
        {"key": "crossover", "label": "Uniform crossover", "type": "bool", "default": False, "live": True},
    ]},
    {"group": "Rewards", "fields": [
        {"key": "reward_reveal", "label": "Per tile revealed", "type": "float", "default": 1, "min": -100, "max": 100, "step": 0.1},
        {"key": "reward_mine", "label": "Hit a mine", "type": "float", "default": -10, "min": -1000, "max": 100, "step": 0.5},
        {"key": "reward_flag_correct", "label": "Correct flag", "type": "float", "default": 3, "min": -100, "max": 100, "step": 0.5},
        {"key": "reward_flag_wrong", "label": "Wrong flag", "type": "float", "default": -3, "min": -100, "max": 100, "step": 0.5},
        {"key": "reward_step", "label": "Per step", "type": "float", "default": -0.02, "min": -10, "max": 10, "step": 0.01, "live": True,
         "help": "A small cost for every turn, so wasting turns is never free."},
        {"key": "reward_unflag", "label": "Removing own flag", "type": "float", "default": -0.5, "min": -100, "max": 10, "step": 0.1, "live": True,
         "help": "Charged when a bot takes its own flag back off. Stops bots toggling a flag on and off to pass turns."},
        {"key": "reward_clear", "label": "Board cleared bonus", "type": "float", "default": 0, "min": -1000, "max": 1000, "step": 1},
        {"key": "reward_ko", "label": "Knocked out (v2)", "type": "float", "default": -15, "min": -1000, "max": 100, "step": 0.5},
        {"key": "reward_pvp_ko", "label": "KO a rival in PvP (v2)", "type": "float", "default": 20, "min": -100, "max": 1000, "step": 0.5},
        {"key": "reward_boss_hit", "label": "Per 10 boss damage (v2)", "type": "float", "default": 1, "min": -100, "max": 100, "step": 0.1},
        {"key": "reward_boss_kill", "label": "Boss killing blow (v2)", "type": "float", "default": 40, "min": -100, "max": 1000, "step": 1},
        {"key": "reward_item", "label": "Pickup collected (v3)", "type": "float", "default": 2, "min": -100, "max": 100, "step": 0.5},
        {"key": "reward_floor", "label": "Descent floor cleared (v3)", "type": "float", "default": 10, "min": -100, "max": 1000, "step": 1},
        {"key": "reward_stairs", "label": "Reached the stairs (v3)", "type": "float", "default": 20, "min": -100, "max": 1000, "step": 1},
    ]},
]
FIELDS = {f["key"]: f for g in SCHEMA for f in g["fields"]}
DEFAULTS = {k: f["default"] for k, f in FIELDS.items()}


def sanitize(cfg):
    """Coerce and clamp a config dict from the UI into a valid one."""
    out = dict(DEFAULTS)
    for k, f in FIELDS.items():
        if k not in (cfg or {}):
            continue
        v = cfg[k]
        try:
            if f["type"] == "int":
                v = int(float(v))
            elif f["type"] == "float":
                v = float(v)
                if not math.isfinite(v):
                    raise ValueError
            elif f["type"] == "bool":
                v = v in (True, "true", "on", 1, "1")
            elif f["type"] == "select":
                v = v if v in f["options"] else f["default"]
            else:
                v = str(v)[:200]
        except (TypeError, ValueError):
            v = f["default"]
        if "min" in f:
            v = max(f["min"], v)
        if "max" in f:
            v = min(f["max"], v)
        out[k] = v
    try:
        hidden = [max(1, min(2048, int(h))) for h in str(out["hidden"]).replace(" ", "").split(",") if h]
    except ValueError:
        hidden = [64]
    out["hidden"] = ",".join(str(h) for h in (hidden or [64])[:4])
    out["mines"] = min(out["mines"], out["board_w"] * out["board_h"] - 9)
    A = out["agents_per_board"]
    out["population"] = max(A * 2, out["population"] // A * A)
    out["elites"] = min(out["elites"], out["population"] - 1)
    out["tournament"] = min(out["tournament"], out["population"])
    out["run_name"] = safe_name(out["run_name"], time.strftime("run-%Y%m%d-%H%M%S"))
    out["seed_model"] = safe_name(out["seed_model"], "") if out["seed_model"] else ""
    return out


def spec_from(cfg):
    return Spec(cfg["radius"], [int(h) for h in cfg["hidden"].split(",")], cfg["activation"], int(cfg.get("model_version", 1)))


def rewards_from(cfg):
    return {k[7:]: float(cfg[k]) for k in cfg if k.startswith("reward_")}


def pick_device(name):
    if name in ("auto", "cuda") and torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def make_env(cfg, n, agents, device, version=None, mode=None):
    """version: the newest model version on the board (default: the config's). v2+ runs the
    health/boss/mode rules, v3+ also traps, pickups and descent; older models still observe their own
    view. mode overrides cfg['mode'] (matches use 'race' so wins mean something)."""
    if version is None:
        version = int(cfg.get("model_version", 1))
    return MineEnv(n, agents, cfg["board_h"], cfg["board_w"], cfg["mines"], cfg["episode_steps"],
                   cfg["stun_steps"], rewards_from(cfg), device, cfg.get("layout", "field"),
                   rich=version >= 2, mode=mode or cfg.get("mode", "race"), bosses=cfg.get("bosses", False),
                   extras=version >= 3, powers=version >= 4,
                   params={"descent_practice": float(cfg.get("descent_practice", 0))})


@torch.no_grad()
def evaluate(spec, pop, cfg, device):
    """Play every individual on cfg['episodes'] boards. Returns per-individual fitness and stats (P,)."""
    P, M, A = pop.shape[0], cfg["episodes"], cfg["agents_per_board"]
    S = P * M
    N = S // A
    env = make_env(cfg, N, A, device)
    # which individual controls each (board, agent) slot: every individual appears exactly M times
    ind = torch.cat([torch.randperm(P, device=device).view(P // A, A) for _ in range(M)]).view(-1)
    order = torch.argsort(ind, stable=True)       # slots grouped by individual -> (P, M) layout
    inv = torch.argsort(order)
    masking, noise = cfg["action_masking"], cfg["action_noise"]
    v = spec.version
    while not bool(env.done.all()):
        obs = torch.stack([env.observe(a, spec.radius, v) for a in range(A)], 1).view(S, -1)
        logits = spec.forward(pop, obs[order].view(P, M, -1)).view(S, -1)[inv]
        mask = torch.stack([env.mask(a, v) for a in range(A)], 1).view(S, -1) if masking else None
        env.step(choose(logits, mask, noise).view(N, A))
    per = lambda t: torch.zeros(P, device=device).index_add_(0, ind, t.reshape(-1).float()) / M
    stats = {k: per(v) for k, v in env.stats.items()}
    fitness = per(env.fitness())          # co-op boards share the team average
    cleared = env.cleared.float().mean().item()
    return fitness, stats, cleared


def _put(q, msg):
    try:
        q.put(msg)
    except Exception:
        pass


def train_process(cfg, cmd_q, evt_q):
    try:
        _train(cfg, cmd_q, evt_q)
    except Exception:
        _put(evt_q, {"t": "error", "message": traceback.format_exc()})
    finally:
        _put(evt_q, {"t": "status", "state": "stopped"})


def _train(cfg, cmd_q, evt_q):
    import queue as _queue
    device = pick_device(cfg["device"])
    torch.backends.cuda.matmul.allow_tf32 = True
    spec = spec_from(cfg)
    P, E = cfg["population"], cfg["elites"]
    dev_name = torch.cuda.get_device_name(0) if device.type == "cuda" else "CPU"

    pop = spec.init(P, device)
    if cfg["seed_model"]:
        m = load_model(cfg["seed_model"])
        old = m["spec_obj"]
        if 2 <= old.version < spec.version and (old.radius, old.hidden, old.activation) == (
                spec.radius, spec.hidden, spec.activation):
            m["weights"] = upgrade(old, m["weights"], spec)     # warm-start a newer model from an older one
            m["spec_obj"] = spec
        if not m["spec_obj"].same_shape(spec):
            raise ValueError(f"Model {cfg['seed_model']} has network {m['spec_obj'].describe()}, but this run uses "
                             f"{spec.describe()}. Match the model type / vision radius / hidden layers / activation.")
        w = m["weights"].to(device)
        pop = w.unsqueeze(0) + torch.randn(P, spec.n_params, device=device) * cfg["sigma"]
        pop[0] = w

    _put(evt_q, {"t": "status", "state": "running", "device": dev_name, "params": spec.n_params,
                 "arch": spec.describe(), "cfg": cfg})
    sigma = cfg["sigma"]
    best_vec, best_fit, gen, paused = pop[0].clone(), float("-inf"), 0, False

    def save(name, why):
        n = save_model(name, spec, best_vec, {"run": cfg["run_name"], "generation": gen, "fitness": best_fit,
                                              "cfg": cfg, "why": why})
        _put(evt_q, {"t": "saved", "name": n, "why": why})

    while True:
        # ---- commands (block while paused)
        while True:
            try:
                cmd = cmd_q.get(block=paused, timeout=0.5 if paused else None) if paused else cmd_q.get_nowait()
            except _queue.Empty:
                if paused:
                    continue
                break
            c = cmd.get("t")
            if c == "pause":
                paused = True
                _put(evt_q, {"t": "status", "state": "paused"})
            elif c == "resume":
                paused = False
                _put(evt_q, {"t": "status", "state": "running"})
            elif c == "stop":
                if gen:
                    save(cfg["run_name"], "final")
                return
            elif c == "save" and gen:
                save(cmd.get("name") or f"{cfg['run_name']}-g{gen}", "manual")
            elif c == "tweak":
                for k, v in sanitize({**cfg, **cmd.get("cfg", {})}).items():
                    if FIELDS.get(k, {}).get("live"):
                        cfg[k] = v
                if "sigma" in cmd.get("cfg", {}):
                    sigma = cfg["sigma"]
                E = cfg["elites"]
                _put(evt_q, {"t": "tweaked", "cfg": cfg})

        # ---- evaluate
        t0 = time.time()
        fitness, stats, cleared = evaluate(spec, pop, cfg, device)
        order = torch.argsort(fitness, descending=True)
        pop, fitness = pop[order], fitness[order]
        stats = {k: v[order] for k, v in stats.items()}
        best_vec, best_fit = pop[0].clone(), fitness[0].item()
        gen += 1

        _put(evt_q, {
            "t": "gen", "gen": gen, "seconds": round(time.time() - t0, 3), "sigma": sigma,
            "best": best_fit, "mean": fitness.mean().item(), "median": fitness.median().item(),
            "elite": fitness[:E].mean().item(), "worst": fitness[-1].item(),
            "tiles": stats["tiles"].mean().item(), "mines_hit": stats["mines_hit"].mean().item(),
            "flags_correct": stats["flags_correct"].mean().item(), "flags_wrong": stats["flags_wrong"].mean().item(),
            "unflags": stats["unflags"].mean().item(),
            "best_tiles": stats["tiles"][0].item(), "best_mines_hit": stats["mines_hit"][0].item(),
            "clear_rate": cleared,
            **{k: stats[k].mean().item() for k in ("kos", "boss_damage", "boss_kills", "pvp_kos", "items", "spikes", "stairs", "uses") if k in stats},
            "weights": best_vec.float().cpu().numpy(), "spec": spec.to_dict(),
        })
        if gen % cfg["save_every"] == 0:
            save(cfg["run_name"], "auto")
        if cfg["generations"] and gen >= cfg["generations"]:
            save(cfg["run_name"], "final")
            _put(evt_q, {"t": "finished", "gen": gen})
            return

        # ---- next generation
        T = max(1, cfg["tournament"])
        n_child = P - E

        def select(n):
            cand = torch.randint(0, P, (n, T), device=device)
            return cand.gather(1, fitness[cand].argmax(1, keepdim=True)).squeeze(1)

        children = pop[select(n_child)].clone()
        if cfg["crossover"]:
            other = pop[select(n_child)]
            children = torch.where(torch.rand_like(children) < 0.5, children, other)
        noise = torch.randn_like(children) * sigma
        if cfg["mutation_rate"] < 1:
            noise *= torch.rand_like(children) < cfg["mutation_rate"]
        pop = torch.cat([pop[:E], children + noise])
        sigma = max(cfg["sigma_min"], sigma * cfg["sigma_decay"])


@torch.no_grad()
def run_match(models, games, cfg, device="cpu"):
    """Head-to-head: every game puts all `models` (loaded dicts) on one board.
    Returns per-model results in the same order."""
    A = len(models)
    device = pick_device(device)
    specs = [m["spec_obj"] for m in models]
    # v1 and v2 models can meet: the rich rules run if any model is v2; each sees its own view
    env = make_env(cfg, games, A, device, version=max(s.version for s in specs), mode="race")
    ws = [m["weights"].to(device).unsqueeze(0) for m in models]
    while not bool(env.done.all()):
        acts = []
        for a in range(A):
            obs = env.observe(a, specs[a].radius, specs[a].version).unsqueeze(0)
            logits = specs[a].forward(ws[a], obs)[0]
            acts.append(choose(logits, env.mask(a, specs[a].version)))
        env.step(torch.stack(acts, 1))
    score = env.score
    best = score.max(1, keepdim=True).values
    winners = (score == best).float()
    wins = (winners / winners.sum(1, keepdim=True)).sum(0)   # ties share the win
    return [{
        "name": models[a]["name"],
        "wins": wins[a].item(), "win_rate": wins[a].item() / games,
        "score": score[:, a].mean().item(), "tiles": env.stats["tiles"][:, a].mean().item(),
        "mines_hit": env.stats["mines_hit"][:, a].mean().item(),
        "flags_correct": env.stats["flags_correct"][:, a].mean().item(),
        "flags_wrong": env.stats["flags_wrong"][:, a].mean().item(),
    } for a in range(A)]
