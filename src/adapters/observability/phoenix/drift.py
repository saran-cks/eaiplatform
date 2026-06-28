"""Valkey-backed embedding-drift tracker.

Feeds the programmatic drift signal for ``ObservabilityPort.drift_check``. As query
embeddings flow through retrieval, the Phoenix adapter pushes each vector here; we keep,
per tenant, an incremental **running centroid** plus a frozen **baseline** centroid
captured once enough samples have accrued. Drift = distance(baseline, current centroid).

State lives in Valkey (shared across workers, restart-safe) via ``CachePort``. Fail-soft:
any backend error degrades drift to ``status=unavailable`` — it never breaks retrieval.

This is the deployed-server analogue of Phoenix's notebook ``Inferences`` drift: the rich
UMAP point-cloud lives in the Phoenix UI (fed by the embedding vectors we attach to spans);
this gives an always-on numeric signal suitable for metrics/alerts.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence

from core.ports.cache import CachePort
from observability import drift as drift_math

logger = logging.getLogger(__name__)

# Samples to accumulate before freezing the baseline centroid.
_BASELINE_MIN_SAMPLES = 50


class EmbeddingDriftTracker:
    def __init__(self, cache: CachePort, *, prefix: str = "drift:", ttl: int = 604_800) -> None:
        self._cache = cache
        self._prefix = prefix
        self._ttl = ttl  # 7 days: drift baseline is a slow-moving reference

    def _cur_key(self, tenant: str) -> str:
        return f"{self._prefix}cur:{tenant}"

    def _base_key(self, tenant: str) -> str:
        return f"{self._prefix}base:{tenant}"

    async def observe(self, tenant_id: str, vector: Sequence[float]) -> None:
        """Fold a query embedding into the tenant's running centroid (fail-soft)."""
        if not vector:
            return
        tenant = tenant_id or "default"
        try:
            raw = await self._cache.get(self._cur_key(tenant))
            state = json.loads(raw) if raw else {"sum": [0.0] * len(vector), "count": 0}
            acc = state["sum"]
            if len(acc) != len(vector):  # dim change → reset
                acc = [0.0] * len(vector)
                state["count"] = 0
            for i, x in enumerate(vector):
                acc[i] += float(x)
            state["sum"] = acc
            state["count"] += 1
            await self._cache.set(self._cur_key(tenant), json.dumps(state), ttl=self._ttl)

            # Freeze the baseline once we have a stable reference and none exists yet.
            if state["count"] >= _BASELINE_MIN_SAMPLES:
                if await self._cache.get(self._base_key(tenant)) is None:
                    centroid = [s / state["count"] for s in acc]
                    await self._cache.set(
                        self._base_key(tenant), json.dumps(centroid), ttl=self._ttl
                    )
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("drift observe failed for %s: %s", tenant, exc)

    async def compute(self, tenant_id: str | None) -> dict[str, object]:
        """Return the current drift signal for a tenant (or 'default')."""
        tenant = tenant_id or "default"
        try:
            cur_raw = await self._cache.get(self._cur_key(tenant))
            base_raw = await self._cache.get(self._base_key(tenant))
        except Exception as exc:
            logger.warning("drift compute failed for %s: %s", tenant, exc)
            return {"status": "unavailable", "tenant_id": tenant}

        if not cur_raw:
            return {"status": "no_data", "tenant_id": tenant, "samples": 0}
        state = json.loads(cur_raw)
        count = state.get("count", 0)
        current = [s / count for s in state["sum"]] if count else []
        if not base_raw:
            return {
                "status": "warming_up",
                "tenant_id": tenant,
                "samples": count,
                "baseline_at": _BASELINE_MIN_SAMPLES,
            }
        baseline = json.loads(base_raw)
        cosine = drift_math.cosine_distance(baseline, current)
        euclidean = drift_math.euclidean_distance(baseline, current)
        return {
            "status": "ok",
            "tenant_id": tenant,
            "samples": count,
            "cosine_distance": round(cosine, 6),
            "euclidean_distance": round(euclidean, 6),
            "drift": round(cosine, 6),
        }
