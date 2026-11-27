"""Model library: trained networks saved as small .pt files in models/."""
import re
import time
from pathlib import Path

import torch

from .policy import Spec

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
CONFIGS_DIR = ROOT / "configs"
RUNS_DIR = ROOT / "runs"


def safe_name(s, default="model"):
    s = re.sub(r"[^A-Za-z0-9_\-]+", "-", str(s or "")).strip("-")[:40]
    return s or default


def model_path(name):
    return MODELS_DIR / f"{safe_name(name)}.pt"


def save_model(name, spec, weights, meta):
    MODELS_DIR.mkdir(exist_ok=True)
    name = safe_name(name)
    torch.save({"name": name, "spec": spec.to_dict(), "weights": weights.detach().float().cpu().clone(),
                "meta": {**meta, "saved": time.time()}}, model_path(name))
    return name


def load_model(name):
    d = torch.load(model_path(name), map_location="cpu", weights_only=True)
    d["spec_obj"] = Spec.from_dict(d["spec"])
    return d


def model_info(d):
    spec = Spec.from_dict(d["spec"])
    return {"name": d["name"], "spec": d["spec"], "arch": spec.describe(), "params": spec.n_params, "meta": d.get("meta", {})}


def list_models():
    out = []
    for p in sorted(MODELS_DIR.glob("*.pt")) if MODELS_DIR.exists() else []:
        try:
            out.append(model_info(torch.load(p, map_location="cpu", weights_only=True)))
        except Exception as e:  # unreadable file: still show it so it can be deleted
            out.append({"name": p.stem, "error": str(e), "meta": {}})
    out.sort(key=lambda m: -m["meta"].get("saved", 0))
    return out


def delete_model(name):
    p = model_path(name)
    if p.exists():
        p.unlink()


def rename_model(old, new):
    d = torch.load(model_path(old), map_location="cpu", weights_only=True)
    new = safe_name(new)
    if model_path(new).exists():
        raise ValueError(f"a model named {new} already exists")
    d["name"] = new
    torch.save(d, model_path(new))
    model_path(old).unlink()
    return new
