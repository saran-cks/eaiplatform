"""Embedding sidecar configuration (env-driven).

Importing this module pins the HuggingFace cache to a local folder and forces
CPU, so it MUST be imported before transformers / FlagEmbedding / torch.
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
    model_name: str = _env("EMBED_MODEL_NAME", "BAAI/bge-m3")
    models_dir: Path = Path(_env("EMBED_MODELS_DIR", str(_HERE / "models")))
    grpc_port: int = int(_env("GRPC_PORT", "50051"))
    max_workers: int = int(_env("EMBED_MAX_WORKERS", "4"))        # concurrent inferences
    intra_op_threads: int = int(_env("EMBED_INTRA_OP_THREADS", "4"))  # benched sweet spot; >4 regresses
    max_seq_len: int = int(_env("EMBED_MAX_SEQ_LEN", "512"))      # queries are short
    use_fp16: bool = _env("EMBED_USE_FP16", "false").lower() == "true"


config = Config()

# Keep model weights local (never the global venv / ~/.cache) and force CPU,
# before any heavy import pulls them in.
config.models_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(config.models_dir))
os.environ.setdefault("HF_HUB_CACHE", str(config.models_dir))
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
