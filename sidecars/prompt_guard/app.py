"""Prompt Guard HTTP sidecar — screens text for injection/jailbreak.

Frozen contract (Core API ↔ guard):
    POST /guard   {"text": "..."}  -> {"label", "score", "blocked"}
    GET  /health                   -> {"status": "ok"}

Classify-only: this service does NOT decide product behavior (refuse / 4xx /
safe message) — that's the Core API's call based on ``blocked``. Run:
    python -m sidecars.prompt_guard.app
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from .classifier import Classifier
from .config import config

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


class GuardRequest(BaseModel):
    text: str = Field(min_length=1)


class GuardResponse(BaseModel):
    label: str       # "benign" | "malicious"
    score: float     # P(malicious)
    blocked: bool    # score >= GUARD_THRESHOLD


_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    clf = Classifier()
    clf.warmup()  # first request isn't slow
    _state["clf"] = clf
    _state["executor"] = ThreadPoolExecutor(max_workers=config.max_concurrency)
    _state["sem"] = asyncio.Semaphore(config.max_concurrency)
    logger.info("Prompt Guard ready on :%d (threshold=%.2f)", config.http_port, config.threshold)
    try:
        yield
    finally:
        _state["executor"].shutdown(wait=True)


app = FastAPI(title="Prompt Guard Sidecar", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/guard", response_model=GuardResponse)
async def guard(req: GuardRequest) -> GuardResponse:
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty text")
    loop = asyncio.get_running_loop()
    async with _state["sem"]:  # CPU-bound inference released the GIL; bound the pool
        label, score = await loop.run_in_executor(
            _state["executor"], _state["clf"].classify, text,
        )
    return GuardResponse(label=label, score=score, blocked=label == "malicious")


if __name__ == "__main__":
    import uvicorn

    # workers=1: shared in-process model + thread pool; scale with replicas, not workers.
    uvicorn.run("sidecars.prompt_guard.app:app", host="0.0.0.0", port=config.http_port, workers=1)
