"""Prompt Guard sidecar configuration (env-driven).

Importing this module pins the HuggingFace cache to a local folder and forces
CPU, so it MUST be imported before transformers / torch. ``HF_TOKEN`` is read
automatically by huggingface_hub from the environment — nothing to wire here;
it's only needed for the first (gated) download of Llama Prompt Guard 2.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Config:
    model_name: str = _env("GUARD_MODEL_NAME", "meta-llama/Llama-Prompt-Guard-2-86M")
    # Pin the model to an immutable commit so a retagged/compromised upstream can't be
    # silently pulled (supply-chain hardening; consistent with the assume-poisoned thesis).
    model_revision: str = _env("GUARD_MODEL_REVISION", "a8ded8e697ce7c355e395a0df51f94adb4a2fd27")
    models_dir: Path = Path(_env("GUARD_MODELS_DIR", str(_HERE / "models")))
    http_port: int = int(_env("GUARD_PORT", "8001"))
    threshold: float = float(_env("GUARD_THRESHOLD", "0.5"))      # block if P(malicious) >= this
    max_seq_len: int = int(_env("GUARD_MAX_SEQ_LEN", "512"))      # prompts are short
    intra_op_threads: int = int(_env("GUARD_INTRA_OP_THREADS", "4"))
    max_concurrency: int = int(_env("GUARD_MAX_CONCURRENCY", "8"))  # 86M is fast; bound the pool


config = Config()

# Keep model weights local (never the global venv / ~/.cache) and force CPU,
# before any heavy import pulls them in.
config.models_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(config.models_dir))
os.environ.setdefault("HF_HUB_CACHE", str(config.models_dir))
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
