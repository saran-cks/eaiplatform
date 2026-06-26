"""Llama Prompt Guard 2 (86M) — benign vs malicious (prompt-injection / jailbreak).

A small sequence-classification model. ``classify`` is CPU-bound and releases
the GIL, so the app calls it from a thread pool; a single shared instance is safe.
"""
from __future__ import annotations

import logging

from .config import config  # noqa: F401 — sets HF cache + CPU on import

import torch
import torch.nn.functional as F
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)

# Prompt Guard 2 is binary; class index 1 = malicious (matches Meta's reference usage:
# score = softmax(logits)[1]). Threshold turns the score into a label.
MALICIOUS_INDEX = 1


class Classifier:
    def __init__(self) -> None:
        torch.set_num_threads(config.intra_op_threads)
        logger.info("Loading %s (cache=%s)", config.model_name, config.models_dir)
        self._tok = AutoTokenizer.from_pretrained(config.model_name)
        self._model = AutoModelForSequenceClassification.from_pretrained(config.model_name)
        self._model.eval()
        logger.info("Prompt Guard model loaded.")

    @torch.no_grad()
    def classify(self, text: str) -> tuple[str, float]:
        """Return (label, score) where score = P(malicious) in [0, 1]."""
        enc = self._tok(
            text, return_tensors="pt", truncation=True, max_length=config.max_seq_len,
        )
        logits = self._model(**enc).logits
        score = F.softmax(logits, dim=-1)[0, MALICIOUS_INDEX].item()
        label = "malicious" if score >= config.threshold else "benign"
        return label, score

    def warmup(self) -> None:
        self.classify("warmup")
