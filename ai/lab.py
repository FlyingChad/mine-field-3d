"""The training lab: /lab page + /lab/ws WebSocket.

Runs the trainer in a separate process, streams its progress to every open lab page, runs live
"watch" games and head-to-head matches, manages saved models and configs, and deploys bots into
game rooms (through callbacks provided by server.py).
"""
import asyncio
import json
import multiprocessing as mp
import queue
import time
from pathlib import Path

import torch
from aiohttp import WSMsgType, web

from . import evolve
from .env import MODES
from .models import (CONFIGS_DIR, RUNS_DIR, delete_model, list_models, load_model, rename_model, safe_name)
from .policy import Spec, choose

torch.set_num_threads(2)  # keep the game server responsive; heavy work happens in the trainer process


def _dumps(m):
    return json.dumps(m, separators=(",", ":"))


class Lab:
    def __init__(self, static_dir, rooms_summary, add_bot, remove_bot, characters):
        self.static_dir = Path(static_dir)
        self.rooms_summary, self.add_bot, self.remove_bot = rooms_summary, add_bot, remove_bot
        self.characters = characters
        self.ctx = mp.get_context("spawn")
        self.clients = {}             # ws -> {"watch": task, "speed": float}
        self.proc = self.cmd_q = self.evt_q = None
        self.state, self.info, self.cfg, self.history = "idle", {}, None, []
        self.best = None              # (Spec, weights) of the latest generation's best
        self.last_rooms = ""

    def setup(self, app):
        app.router.add_get("/lab", lambda _: web.FileResponse(self.static_dir / "lab.html"))
        app.router.add_get("/lab/ws", self.ws_handler)
        app.cleanup_ctx.append(self._lifecycle)

    async def _lifecycle(self, app):
        tasks = [asyncio.create_task(self._pump()), asyncio.create_task(self._rooms_loop())]
        yield
        for t in tasks:
            t.cancel()
        if self.proc and self.proc.is_alive():
            self.proc.terminate()

    # ------------------------------------------------------------------ messaging
    async def send(self, ws, msg):
        try:
            await ws.send_str(_dumps(msg))
        except Exception:
            pass

    async def broadcast(self, msg):
        data = _dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except Exception:
                pass

    def configs(self):
        CONFIGS_DIR.mkdir(exist_ok=True)
        out = []
        for p in sorted(CONFIGS_DIR.glob("*.json")):
            try:
                out.append({"name": p.stem, "cfg": json.loads(p.read_text())})
            except Exception:
                pass
        return out

    def runs(self):
        return [p.stem for p in sorted(RUNS_DIR.glob("*.json"), key=lambda p: -p.stat().st_mtime)] if RUNS_DIR.exists() else []

    def hello(self):
        return {"t": "hello", "schema": evolve.SCHEMA, "defaults": evolve.DEFAULTS, "state": self.state,
                "info": self.info, "cfg": self.cfg, "history": self.history, "models": list_models(),
                "configs": self.configs(), "runs": self.runs(), "rooms": self.rooms_summary(),
                "characters": self.characters, "difficulties": ["easy", "normal", "hard", "insane"],
                "cuda": torch.cuda.is_available(),
                "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}

    # ------------------------------------------------------------------ trainer process
    async def _pump(self):
        while True:
            await asyncio.sleep(0.1)
            if not self.evt_q:
                continue
            while True:
                try:
                    evt = self.evt_q.get_nowait()
                except (queue.Empty, OSError, EOFError):
                    break
                await self._on_event(evt)
            if self.proc and not self.proc.is_alive() and self.state in ("running", "paused", "starting"):
                await self._on_event({"t": "status", "state": "stopped"})

    async def _on_event(self, e):
        t = e["t"]
        if t == "gen":
            w = torch.from_numpy(e.pop("weights"))
            self.best = (Spec.from_dict(e.pop("spec")), w)
            self.history.append(e)
            await self.broadcast(e)
            if len(self.history) % 5 == 1:
                self._persist_run()
        elif t == "status":
            self.state = e["state"]
            for k in ("device", "params", "arch", "cfg"):
                if k in e:
                    self.info[k] = e[k]
            if "cfg" in e:
                self.cfg = e["cfg"]
            if self.state == "stopped":
                self._persist_run()
            await self.broadcast({"t": "status", "state": self.state, "info": self.info, "cfg": self.cfg})
        elif t == "saved":
            await self.broadcast({"t": "models", "models": list_models(), "toast": f"Saved model “{e['name']}” ({e['why']})"})
        elif t == "tweaked":
            self.cfg = e["cfg"]
            await self.broadcast({"t": "status", "state": self.state, "info": self.info, "cfg": self.cfg})
        elif t == "finished":
            await self.broadcast({"t": "toast", "text": f"Training finished after {e['gen']} generations"})
        elif t == "error":
            await self.broadcast({"t": "error", "text": e["message"]})

    def _persist_run(self):
        if not self.cfg or not self.history:
            return
        RUNS_DIR.mkdir(exist_ok=True)
        (RUNS_DIR / f"{self.cfg['run_name']}.json").write_text(
            json.dumps({"cfg": self.cfg, "info": self.info, "history": self.history}))

    def _running(self):
        return self.proc is not None and self.proc.is_alive()

    async def start(self, cfg):
        if self._running():
            raise ValueError("A training run is already in progress. Stop it first.")
        cfg = evolve.sanitize(cfg)
        self.cmd_q, self.evt_q = self.ctx.Queue(), self.ctx.Queue()
        self.proc = self.ctx.Process(target=evolve.train_process, args=(cfg, self.cmd_q, self.evt_q), daemon=True)
        self.proc.start()
        self.cfg, self.history, self.best, self.state = cfg, [], None, "starting"
        self.info = {}
        await self.broadcast({"t": "reset", "cfg": cfg})
        await self.broadcast({"t": "status", "state": "starting", "info": {}, "cfg": cfg})

    def command(self, msg):
        if not self._running():
            raise ValueError("No training run is in progress.")
        self.cmd_q.put(msg)

    # ------------------------------------------------------------------ rooms
    async def _rooms_loop(self):
        while True:
            await asyncio.sleep(1)
            rooms = self.rooms_summary()
            s = _dumps(rooms)
            if s != self.last_rooms:
                self.last_rooms = s
                await self.broadcast({"t": "rooms", "rooms": rooms})

    # ------------------------------------------------------------------ watching
    def _watch_sources(self, msg):
        if msg.get("source") == "run":
            if not self.best:
                raise ValueError("No generation has finished yet. Start training first.")
            spec, w = self.best
            return [(spec, w, f"Run best · gen {len(self.history)}")]
        names = [n for n in msg.get("models", []) if n][:6]
        if not names:
            raise ValueError("Pick at least one model to watch.")
        return [(m["spec_obj"], m["weights"], m["name"]) for m in (load_model(n) for n in names)]

    def _board_cfg(self, msg):
        base = dict(self.cfg or evolve.DEFAULTS)
        b = msg.get("board") or {}
        return evolve.sanitize({**base, **{k: b[k] for k in ("board_w", "board_h", "mines", "episode_steps", "layout", "mode", "bosses") if k in b},
                                "agents_per_board": 1})

    async def _watch(self, ws, msg):
        client = self.clients[ws]
        cfg = self._board_cfg(msg)
        episode = 0
        while True:
            sources = self._watch_sources(msg)      # re-read each episode so "run" follows training
            A = len(sources)
            env = evolve.make_env(cfg, 1, A, "cpu", version=max(s[0].version for s in sources))
            episode += 1
            prefs = net = None
            while not bool(env.done.all()):
                acts = []
                with torch.no_grad():
                    for a, (spec, w, _) in enumerate(sources):
                        obs = env.observe(a, spec.radius, spec.version).unsqueeze(0)
                        logits = spec.forward(w.unsqueeze(0), obs)[0]
                        m = env.mask(a, spec.version)
                        acts.append(choose(logits, m))
                        if a == 0:
                            prefs = torch.softmax(logits.masked_fill(~m, float("-inf")), -1)[0]
                            net = self._net(spec, w, obs[0, 0], prefs, int(acts[0][0]))
                    env.step(torch.stack(acts, 1))
                frame = self._frame(env, sources, prefs, acts, episode)
                frame["net"] = net
                await self.send(ws, frame)
                await asyncio.sleep(1 / client["speed"])
            await asyncio.sleep(2.0)

    _shown_cache = {}

    @classmethod
    def _net(cls, spec, w, x, prefs, action, max_nodes=40, max_edges=48):
        """What bot 1's network is doing this step, for the animated view in the Watch tab.

        Input: the (2r+1)^2 vision window as one node per cell (plus the 3 global features).
        Hidden: up to `max_nodes` units per layer (the ones with the strongest outgoing weights,
        so the picture stays stable). Output: the 26 action probabilities.
        Edges: for each pair of layers, the `max_edges` strongest contributions
        (source activation x weight) this step, signed."""
        from .env import n_channels
        layers = spec.weights(w)
        acts = spec.trace(w, x)
        hidden = acts[:-1]
        key = (id(w), spec.describe())
        if key not in cls._shown_cache:
            cls._shown_cache = {key: [layers[l + 1][0].norm(dim=1).topk(min(max_nodes, layers[l + 1][0].shape[0])).indices.sort().values
                                      for l in range(len(hidden))]}
        shown = cls._shown_cache[key]
        K = 2 * spec.radius + 1
        KK, C = K * K, n_channels(spec.version)
        win = x[:C * KK].view(C, KK)
        glob = x[C * KK:]
        # one character per vision cell: o = outside/wall, x = exploded, f = flagged, h = hidden, 0-4 = count
        codes = []
        for cell in range(KK):
            col = win[:, cell]
            codes.append("o" if col[C - 1] > 0 else "x" if col[2] > 0 else "f" if col[1] > 0 else "h" if col[0] > 0
                         else str(int(col[3:8].argmax())) if col[3:8].max() > 0 else "o")
        others = [int(c) for c in (win[8] > 0).nonzero().view(-1).tolist()]
        v2 = {}
        if spec.version >= 2:   # boss, danger zone and allies within the vision window
            named = (("boss", 9), ("danger", 10), ("allies", 11))
            if spec.version >= 3:   # traps, spikes up, pickups, the goal
                named += (("traps", 12), ("spikes", 13), ("items", 14), ("goal", 15))
            v2 = {k: [int(c) for c in (win[i] > 0).nonzero().view(-1).tolist()] for k, i in named}

        def top(contrib):
            flat = contrib.reshape(-1)
            k = min(max_edges, flat.numel())
            idx = flat.abs().topk(k).indices
            n = contrib.shape[1]
            return [[int(i) // n, int(i) % n, round(float(flat[i]), 4)] for i in idx]

        edges = []
        W1 = layers[0][0]
        cells = (win.unsqueeze(2) * W1[:C * KK].view(C, KK, -1)).sum(0)           # (KK, h1)
        g = glob.unsqueeze(1) * W1[C * KK:]                                         # (3, h1)
        edges.append(top(torch.cat([cells, g], 0)[:, shown[0]]))
        for l in range(len(hidden)):
            Wn = layers[l + 1][0]
            src = hidden[l][shown[l]].unsqueeze(1) * Wn[shown[l]]
            edges.append(top(src if l == len(hidden) - 1 else src[:, shown[l + 1]]))
        return {"k": K, "cells": "".join(codes), "others": others, **v2, "version": spec.version,
                "glob": [round(float(v), 3) for v in glob],
                "hidden": [[round(float(v), 3) for v in hidden[l][shown[l]]] for l in range(len(hidden))],
                "sizes": [int(h.numel()) for h in hidden], "act_fn": spec.activation,
                "out": [round(float(p), 4) for p in prefs], "action": action, "edges": edges}

    @staticmethod
    def _frame(env, sources, prefs, acts, episode):
        H, W = env.H, env.W
        rev, cnt, exp, mines = env.revealed[0], env.counts[0], env.exploded[0], env.mines[0]
        done = bool(env.done[0])
        cells = []
        for i, (r, c, x, m, f) in enumerate(zip(rev.view(-1).tolist(), cnt.view(-1).tolist(), exp.view(-1).tolist(),
                                                 mines.view(-1).tolist(), env.floor[0].view(-1).tolist())):
            cells.append("#" if not f else "X" if x else str(c) if r else ("m" if done and m else "."))
        fo = env.flag_owner[0].view(-1)
        flags = [[i, int(fo[i])] for i in (fo >= 0).nonzero().view(-1).tolist()]
        agents = [{"label": s[2], "y": int(env.pos[0, a, 0]), "x": int(env.pos[0, a, 1]),
                   "score": round(env.score[0, a].item(), 1), "stun": int(env.stun[0, a]), "act": int(acts[a][0]),
                   "tiles": int(env.stats["tiles"][0, a]), "mines": int(env.stats["mines_hit"][0, a]),
                   "hp": round(env.hp[0, a].item() / env.p["max_hp"], 3) if env.rich else None,
                   "ko": bool(env.ko[0, a]) if env.rich else False,
                   "kos": int(env.stats["kos"][0, a]) if env.rich else 0,
                   "bossDmg": int(env.stats["boss_damage"][0, a]) if env.rich else 0}
                  for a, s in enumerate(sources)]
        boss = None
        if env.rich and bool(env.boss_on[0]):
            boss = {"y": int(env.boss_pos[0, 0]), "x": int(env.boss_pos[0, 1]), "hp": round(env.boss_hp[0].item() / env.p["boss_hp"], 3),
                    "windup": int(env.boss_windup[0])}
        return {"t": "frame", "w": W, "h": H, "cells": "".join(cells), "flags": flags, "agents": agents, "boss": boss,
                "mode": MODES[int(env.mode[0])] if env.rich else None,
                "traps": [[i, int(up)] for i, up in zip((env.traps[0] & rev).view(-1).nonzero().view(-1).tolist(),
                                                         env.spikes_up()[0].view(-1)[(env.traps[0] & rev).view(-1)].tolist())],
                "items": [[i, int(env.items[0].view(-1)[i])] for i in ((env.items[0] > 0) & rev).view(-1).nonzero().view(-1).tolist()],
                "stairs": int(env.stairs_pos[0, 0]) * W + int(env.stairs_pos[0, 1]) if bool(env.stairs_on[0]) else None,
                "prefs": [round(p, 4) for p in prefs.tolist()] if prefs is not None else None,
                "step": env.t, "steps": env.steps, "done": done, "cleared": bool(env.cleared[0]), "episode": episode}

    def _stop_watch(self, ws):
        task = self.clients.get(ws, {}).get("watch")
        if task:
            task.cancel()
            self.clients[ws]["watch"] = None

    # ------------------------------------------------------------------ websocket
    async def ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=8 * 1024 * 1024)
        await ws.prepare(request)
        self.clients[ws] = {"watch": None, "speed": 8.0}
        await self.send(ws, self.hello())
        try:
            async for raw in ws:
                if raw.type != WSMsgType.TEXT:
                    continue
                try:
                    msg = json.loads(raw.data)
                    await self._handle(ws, msg)
                except Exception as e:
                    await self.send(ws, {"t": "error", "text": str(e)})
        finally:
            self._stop_watch(ws)
            self.clients.pop(ws, None)
        return ws

    async def _handle(self, ws, msg):
        t = msg.get("t")
        if t == "start":
            await self.start(msg.get("cfg") or {})
        elif t in ("pause", "resume", "stop"):
            self.command({"t": t})
        elif t == "save":
            self.command({"t": "save", "name": safe_name(msg.get("name"), "") or None})
        elif t == "tweak":
            self.command({"t": "tweak", "cfg": msg.get("cfg") or {}})
        elif t == "saveConfig":
            CONFIGS_DIR.mkdir(exist_ok=True)
            name = safe_name(msg.get("name"), "config")
            (CONFIGS_DIR / f"{name}.json").write_text(json.dumps(evolve.sanitize(msg.get("cfg") or {}), indent=2))
            await self.broadcast({"t": "configs", "configs": self.configs(), "toast": f"Saved config “{name}”"})
        elif t == "deleteConfig":
            p = CONFIGS_DIR / f"{safe_name(msg.get('name'))}.json"
            if p.exists():
                p.unlink()
            await self.broadcast({"t": "configs", "configs": self.configs()})
        elif t == "deleteModel":
            delete_model(msg.get("name"))
            await self.broadcast({"t": "models", "models": list_models()})
        elif t == "renameModel":
            new = rename_model(msg.get("name"), msg.get("new"))
            await self.broadcast({"t": "models", "models": list_models(), "toast": f"Renamed to “{new}”"})
        elif t == "loadRun":
            p = RUNS_DIR / f"{safe_name(msg.get('name'))}.json"
            await self.send(ws, {"t": "run", "name": p.stem, **json.loads(p.read_text())})
        elif t == "watch":
            self._watch_sources(msg)  # validate before starting
            self._stop_watch(ws)
            self.clients[ws]["speed"] = max(1.0, min(60.0, float(msg.get("speed", 8))))
            task = asyncio.create_task(self._watch(ws, msg))
            task.add_done_callback(lambda tk: None if tk.cancelled() or not tk.exception() else
                                   asyncio.ensure_future(self.send(ws, {"t": "error", "text": str(tk.exception())})))
            self.clients[ws]["watch"] = task
        elif t == "watchSpeed":
            self.clients[ws]["speed"] = max(1.0, min(60.0, float(msg.get("speed", 8))))
        elif t == "stopWatch":
            self._stop_watch(ws)
        elif t == "match":
            names = [n for n in msg.get("models", []) if n]
            if not 2 <= len(names) <= 6:
                raise ValueError("Pick 2 to 6 models for a match.")
            games = max(1, min(2000, int(msg.get("games", 200))))
            models = [load_model(n) for n in names]
            cfg = self._board_cfg(msg)
            await self.send(ws, {"t": "toast", "text": f"Running {games} games…"})
            t0 = time.time()
            res = await asyncio.get_running_loop().run_in_executor(None, evolve.run_match, models, games, cfg, "auto")
            await self.send(ws, {"t": "matchResult", "results": res, "games": games, "seconds": round(time.time() - t0, 2),
                                 "board": {k: cfg[k] for k in ("board_w", "board_h", "mines", "episode_steps", "layout", "mode", "bosses")}})
        elif t == "addBot":
            await self.add_bot(msg.get("room"), msg.get("model"), msg.get("difficulty", "normal"), msg.get("char"))
            await self.broadcast({"t": "rooms", "rooms": self.rooms_summary()})
        elif t == "removeBot":
            await self.remove_bot(msg.get("room"), msg.get("id"))
            await self.broadcast({"t": "rooms", "rooms": self.rooms_summary()})
