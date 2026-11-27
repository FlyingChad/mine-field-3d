"""Small fully-connected policy networks whose weights live in flat vectors, so a whole population of
P networks can be evaluated in one batched matmul: params (P, n_params), inputs (P, K, in_dim)."""
import math

import torch
import torch.nn.functional as F

from .env import n_actions, obs_dim

ACTIVATIONS = {"tanh": torch.tanh, "relu": torch.relu, "elu": F.elu}


class Spec:
    """version 1: classic minesweeper bot (26 actions). version 2: also sees health, the boss and its
    danger zone, allies and the game mode, and has an attack action (27 actions)."""

    def __init__(self, radius=3, hidden=(64,), activation="tanh", version=1):
        self.radius = int(radius)
        self.hidden = [int(h) for h in hidden]
        self.activation = activation if activation in ACTIVATIONS else "tanh"
        self.version = 2 if int(version) >= 2 else 1
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


def choose(logits, mask=None, noise=0.0):
    """Greedy action choice, optionally restricted to valid actions and perturbed with Gumbel noise."""
    if noise > 0:
        u = torch.rand_like(logits).clamp(1e-9, 1 - 1e-9)
        logits = logits - noise * torch.log(-torch.log(u))
    if mask is not None:
        logits = logits.masked_fill(~mask, float("-inf"))
    return logits.argmax(-1)
