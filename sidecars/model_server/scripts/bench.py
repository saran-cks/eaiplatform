"""Local CPU latency/throughput check.

Run from repo root:  python -m sidecars.model_server.scripts.bench
"""
from __future__ import annotations

import statistics
import time

from sidecars.model_server.embedder import Embedder

QUERIES = [
    "How do I reset a failed deployment?",
    "Why is the ingestion job stuck in the queue?",
    "Show recent errors for the billing service.",
] * 20


def main() -> None:
    emb = Embedder()
    emb.warmup()

    latencies_ms = []
    for q in QUERIES:
        start = time.perf_counter()
        emb.encode(q)
        latencies_ms.append((time.perf_counter() - start) * 1000)

    latencies_ms.sort()
    p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
    print(
        f"n={len(latencies_ms)}  "
        f"p50={statistics.median(latencies_ms):.1f}ms  "
        f"p95={p95:.1f}ms  "
        f"max={latencies_ms[-1]:.1f}ms"
    )


if __name__ == "__main__":
    main()
