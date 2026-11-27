"""Small fully-connected policy networks whose weights live in flat vectors, so a whole population of
P networks can be evaluated in one batched matmul: params (P, n_params), inputs (P, K, in_dim)."""
import math

import torch
import torch.nn.functional as F

from .env import n_actions, obs_dim

ACTIVATIONS = {"tanh": torch.tanh, "relu": torch.relu, "elu": F.elu}


class Spec:
    """version 1: classic minesweeper bot (26 actions). version 2: also sees health, the boss and its
    danger zone, allies and the game mode, and has an attack action (27 actions). version 3: also sees
    spike traps (and whether they're up), pickups, the goal (stairs / vault door) and the descent mode.
    version 4: also sees its held item and shield, and has a "use item" action (28 actions).
    version 5: also sees the logic hint: covered tiles the visible numbers prove safe or mined, and the
    way to the nearest proven-safe tile (env.deduce)."""

    def __init__(self, radius=3, hidden=(64,), activation="tanh", version=1):
        self.radius = int(radius)
        self.hidden = [int(h) for h in hidden]
        self.activation = activation if activation in ACTIVATIONS else "tanh"
        self.version = max(1, min(5, int(version)))
        self.in_dim = obs_dim(self.radius, self.version)
        self.out_dim = n_actions(self.version)
        dims = [self.in_dim] + self.hidden + [self.out_dim]
        self.layers = list(zip(dims[:-1], dims[1:]))
        self.n_params = sum(i * o + o for i, o in self.layers)

    def to_dict(self):
        return {"radius": self.radius, "hidden": self.hidden, "activation": self.activation, "version": self.version}

    @classmethod
    def from_dict(cls, d):
        return cls(d["radius"], d["hidden"], d.get("activation", "tanh"), d.get("version", 1))

    def same_shape(self, other):
        return self.to_dict() == other.to_dict()

    def describe(self):
        return (f"v{self.version} {self.in_dim}→" + "→".join(str(h) for h in self.hidden)
                + f"→{self.out_dim} ({self.activation})")

    def init(self, n, device="cpu"):
        parts = []
        for i, o in self.layers:
            parts.append(torch.randn(n, i * o, device=device) / math.sqrt(i))
            parts.append(torch.zeros(n, o, device=device))
        return torch.cat(parts, 1)

    def forward(self, params, x):
        """params (P, n_params) or (1, n_params); x (P, K, in_dim) -> logits (P, K, out_dim)."""
        act = ACTIVATIONS[self.activation]
        o = 0
        last = len(self.layers) - 1
        for li, (i, out) in enumerate(self.layers):
            Wt = params[:, o:o + i * out].reshape(-1, i, out); o += i * out
            b = params[:, o:o + out]; o += out
            x = torch.baddbmm(b.unsqueeze(1), x, Wt)
            if li < last:
                x = act(x)
        return x


    def weights(self, params):
        """The (W, b) of each layer for one network; params (n_params,) or (1, n_params)."""
        p = params.reshape(-1)
        out, o = [], 0
        for i, n in self.layers:
            Wt = p[o:o + i * n].view(i, n); o += i * n
            b = p[o:o + n]; o += n
            out.append((Wt, b))
        return out

    def trace(self, params, x):
        """Like forward() for one network and one input x (in_dim,), but returns every layer's output:
        [hidden_1, ..., hidden_k, logits] (used by the lab's live network view)."""
        act = ACTIVATIONS[self.activation]
        outs, h = [], x
        layers = self.weights(params)
        for li, (Wt, b) in enumerate(layers):
            h = h @ Wt + b
            if li < len(layers) - 1:
                h = act(h)
            outs.append(h)
        return outs


USE_BIAS = 5.0   # a v3->v4 upgrade starts "use item" here: above nearly every other action's score


def upgrade(old, w, new):
    """Warm start: the weights of an older network `old` (Spec) laid out for a newer one `new` with
    the same radius / hidden layers / activation (any of v2..v4 -> any newer version, one step at a time).

    v2 -> v3: every v2 input keeps its weights, the new inputs (traps, spikes, pickups, goal) start at
    zero and "descent" starts as a copy of "co-op", so the v3 network plays exactly like the v2 one
    until evolution finds a use for what it now sees.
    v3 -> v4: the new inputs (held item, shield) start at zero and the new USE action gets a bias of
    USE_BIAS and no weights: it fires whenever an item would hit something, like the game's built-in
    rule, and evolution learns when holding on is better. Every other action is unchanged.
    v4 -> v5: the logic-hint inputs (safe and mine planes, nearest safe tile) start at zero, so the
    v5 network plays exactly like the v4 one until evolution finds a use for the hint."""
    assert (old.radius, old.hidden, old.activation) == (new.radius, new.hidden, new.activation)
    assert 2 <= old.version < new.version <= 5
    steps = {2: _v2_to_v3, 3: _v3_to_v4, 4: _v4_to_v5}
    v = old.version
    while v < new.version:
        w = steps[v](Spec(old.radius, old.hidden, old.activation, v), w)
        v += 1
    assert w.numel() == new.n_params
    return w


def _v2_to_v3(old, w):
    from .env import N_CHANNELS_V2
    KK = (2 * old.radius + 1) ** 2
    (W1, b1), *rest = old.weights(w)
    h = W1.shape[1]
    win = W1[:N_CHANNELS_V2 * KK].view(N_CHANNELS_V2, KK, h)
    g = W1[N_CHANNELS_V2 * KK:]                    # dir 3, hp, race, pvp, coop, boss 6
    zeros = lambda n: torch.zeros(n, KK, h, dtype=W1.dtype, device=W1.device)
    win3 = torch.cat([win[:12], zeros(4), win[12:13]])           # 12 shared planes, 4 new, out of bounds
    g3 = torch.cat([g[:7], g[6:7], g[7:], torch.zeros(4, h, dtype=W1.dtype, device=W1.device)])
    W1n = torch.cat([win3.reshape(-1, h), g3])
    return torch.cat([W1n.reshape(-1), b1] + [t.reshape(-1) for Wb in rest for t in Wb])


def _v3_to_v4(old, w):
    from .env import N_GLOBAL_V4, N_GLOBAL_V3
    layers = old.weights(w)
    (W1, b1) = layers[0]
    h = W1.shape[1]
    W1n = torch.cat([W1, torch.zeros(N_GLOBAL_V4 - N_GLOBAL_V3, h, dtype=W1.dtype, device=W1.device)])
    if len(layers) == 1:                            # no hidden layers: W1 is also the output layer
        W1n = torch.cat([W1n, torch.zeros(W1n.shape[0], 1, dtype=W1.dtype, device=W1.device)], 1)
        b1 = torch.cat([b1, torch.tensor([USE_BIAS], dtype=b1.dtype, device=b1.device)])
        return torch.cat([W1n.reshape(-1), b1])
    mid = layers[1:-1]
    Wo, bo = layers[-1]
    Won = torch.cat([Wo, torch.zeros(Wo.shape[0], 1, dtype=Wo.dtype, device=Wo.device)], 1)
    bon = torch.cat([bo, torch.tensor([USE_BIAS], dtype=bo.dtype, device=bo.device)])
    return torch.cat([W1n.reshape(-1), b1] + [t.reshape(-1) for Wb in mid for t in Wb] + [Won.reshape(-1), bon])


def _v4_to_v5(old, w):
    from .env import N_CHANNELS_V3, N_CHANNELS_V5, N_GLOBAL_V4, N_GLOBAL_V5
    KK = (2 * old.radius + 1) ** 2
    (W1, b1), *rest = old.weights(w)
    h = W1.shape[1]
    win = W1[:N_CHANNELS_V3 * KK].view(N_CHANNELS_V3, KK, h)
    g = W1[N_CHANNELS_V3 * KK:]
    zw = torch.zeros(N_CHANNELS_V5 - N_CHANNELS_V3, KK, h, dtype=W1.dtype, device=W1.device)
    win5 = torch.cat([win[:-1], zw, win[-1:]])                 # 16 planes, safe, mine, out of bounds
    g5 = torch.cat([g, torch.zeros(N_GLOBAL_V5 - N_GLOBAL_V4, h, dtype=W1.dtype, device=W1.device)])
    W1n = torch.cat([win5.reshape(-1, h), g5])
    return torch.cat([W1n.reshape(-1), b1] + [t.reshape(-1) for Wb in rest for t in Wb])


def choose(logits, mask=None, noise=0.0):
    """Greedy action choice, optionally restricted to valid actions and perturbed with Gumbel noise."""
    if noise > 0:
        u = torch.rand_like(logits).clamp(1e-9, 1 - 1e-9)
        logits = logits - noise * torch.log(-torch.log(u))
    if mask is not None:
        logits = logits.masked_fill(~mask, float("-inf"))
    return logits.argmax(-1)
