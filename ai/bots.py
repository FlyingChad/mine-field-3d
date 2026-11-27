"""Bot brains: run a trained network against a live game room (server.Room) to choose actions."""
import torch

from .env import ATTACK, DIG0, FLAG0, HELD, MODES, MOVES, NEAR, USE, action_mask, encode
from .models import load_model
from .policy import choose

# seconds between decisions (walking to a neighbouring tile also takes ~0.3 s)
DIFFICULTY = {"easy": 0.9, "normal": 0.5, "hard": 0.28, "insane": 0.12}


class Brain:
    def __init__(self, model_name):
        d = load_model(model_name)
        self.name = d["name"]
        self.spec = d["spec_obj"]
        self.w = d["weights"].unsqueeze(0)

    @property
    def version(self):
        return self.spec.version

    @torch.no_grad()
    def decide(self, W, H, revealed, counts, booms, flags, me_id, me_xy, others_xy, floor=None, extra=None):
        """Room state -> ('move'|'dig'|'flag'|'attack', dx, dy) relative to the bot's tile.
        floor: optional bytearray (1 = floor); walls are seen as "out of bounds", like in training.
        extra (v2 models): {"hp": 0..1, "mode": "race"|"pvp"|"coop", "allies": [(x, y)],
        "boss": (x, y, hp 0..1, winding_up) or None, "attack_ok": bool}. others_xy are then rivals only.
        v3 models also read "traps": [(x, y, up)], "items": [(x, y)] and "goal": (x, y) or None, and
        mode may be "descent". v4 models also read "held" (an id from HELD, "" for none), "shield" and
        "use_ok" (the game found a target for the held item), and may answer ('use', 0, 0)."""
        rev = torch.frombuffer(bytearray(revealed), dtype=torch.uint8).view(1, H, W).bool()
        fl = torch.frombuffer(bytearray(floor), dtype=torch.uint8).view(1, H, W).bool() if floor is not None else None
        cnt = torch.tensor(counts, dtype=torch.long).view(1, H, W) if counts else torch.zeros(1, H, W, dtype=torch.long)
        exp = torch.zeros(1, H * W, dtype=torch.bool)
        for i in booms:
            exp[0, i] = True
        # this bot is agent 0; anyone else's flag is "flagged" but may still be dug (as in the server)
        fo = torch.full((1, H * W), -1, dtype=torch.int8)
        for i, pid in flags.items():
            fo[0, i] = 0 if pid == me_id else 1
        oth = torch.zeros(1, H, W, dtype=torch.bool)
        for x, y in others_xy:
            if 0 <= x < W and 0 <= y < H:
                oth[0, y, x] = True
        pos = torch.tensor([[me_xy[1], me_xy[0]]])
        exp, fo = exp.view(1, H, W), fo.view(1, H, W)
        if self.version >= 2:
            extra = extra or {}
            allies = torch.zeros(1, H, W, dtype=torch.bool)
            for x, y in extra.get("allies", []):
                if 0 <= x < W and 0 <= y < H:
                    allies[0, y, x] = True
            boss = torch.zeros(1, H, W, dtype=torch.bool)
            danger = torch.zeros(1, H, W, dtype=torch.bool)
            b = extra.get("boss")
            bpos, bon, bhp, wind = torch.zeros(1, 2, dtype=torch.long), torch.tensor([False]), torch.zeros(1), torch.tensor([False])
            if b and 0 <= b[0] < W and 0 <= b[1] < H:
                boss[0, b[1], b[0]] = True
                bpos = torch.tensor([[b[1], b[0]]])
                bon, bhp, wind = torch.tensor([True]), torch.tensor([float(b[2])]), torch.tensor([bool(b[3])])
                if b[3]:
                    danger[0, max(0, b[1] - 1):b[1] + 2, max(0, b[0] - 1):b[0] + 2] = True
            mode = extra.get("mode", "race")
            mode = mode if mode in MODES else "race"
            if self.version < 3 and mode == "descent":
                mode = "coop"
            ex = {"boss": boss, "danger": danger, "allies": allies, "hp": torch.tensor([float(extra.get("hp", 1.0))]),
                  "mode": torch.tensor([MODES.index(mode)]),
                  "boss_pos": bpos, "boss_on": bon, "boss_hp": bhp, "windup": wind}
            if self.version >= 3:
                trap = torch.zeros(1, H, W, dtype=torch.bool)
                spikes = torch.zeros(1, H, W, dtype=torch.bool)
                items = torch.zeros(1, H, W, dtype=torch.bool)
                goal = torch.zeros(1, H, W, dtype=torch.bool)
                for x, y, up in extra.get("traps", []):
                    if 0 <= x < W and 0 <= y < H:
                        trap[0, y, x] = True
                        spikes[0, y, x] = bool(up)
                for x, y in extra.get("items", []):
                    if 0 <= x < W and 0 <= y < H:
                        items[0, y, x] = True
                g = extra.get("goal")
                gpos, gon = torch.zeros(1, 2, dtype=torch.long), torch.tensor([False])
                if g and 0 <= g[0] < W and 0 <= g[1] < H:
                    goal[0, g[1], g[0]] = True
                    gpos, gon = torch.tensor([[g[1], g[0]]]), torch.tensor([True])
                ex.update(trap=trap, spikes=spikes, items=items, goal=goal, goal_pos=gpos, goal_on=gon)
            use_ok = None
            if self.version >= 4:
                h = extra.get("held") or ""
                ex.update(held=torch.tensor([HELD.index(h) if h in HELD else 0]),
                          shield=torch.tensor([bool(extra.get("shield"))]))
                use_ok = torch.tensor([bool(extra.get("use_ok")) and bool(h)])
            obs = encode(rev, cnt, exp, fo, pos, oth, self.spec.radius, fl, ex)
            mask = action_mask(rev, fo, pos, 0, fl, torch.tensor([bool(extra.get("attack_ok", False))]), use_ok)
        else:
            obs = encode(rev, cnt, exp, fo, pos, oth, self.spec.radius, fl)
            mask = action_mask(rev, fo, pos, 0, fl)
        a = int(choose(self.spec.forward(self.w, obs.unsqueeze(0))[0], mask)[0])
        if a == USE:
            return "use", 0, 0
        if a == ATTACK:
            return "attack", 0, 0
        if a < DIG0:
            dy, dx = MOVES[a]
            return "move", dx, dy
        dy, dx = NEAR[(a - DIG0) if a < FLAG0 else (a - FLAG0)]
        return ("dig" if a < FLAG0 else "flag"), dx, dy
