"""Pure, dependency-free embedding-drift math (numpy-free).

Phoenix's hosted drift view works off embedding vectors attached to spans; this module
provides the *programmatic* drift signal for ``ObservabilityPort.drift_check`` and alerting.
It is intentionally pure (lists of floats in, floats out) so it is trivially unit-testable
and reusable by any observability adapter (Phoenix today, Langfuse tomorrow).

Drift is measured between two embedding distributions — a reference (baseline) and a current
(recent) window — by the distance between their centroids. Centroid distance is the metric
Phoenix documents for embedding drift; we expose both Euclidean and cosine.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def centroid(vectors: Sequence[Sequence[float]]) -> list[float]:
    """Mean vector of a set of equal-length vectors. Empty → empty."""
    if not vectors:
        return []
    dim = len(vectors[0])
    acc = [0.0] * dim
    n = 0
    for v in vectors:
        if len(v) != dim:
            continue
        for i in range(dim):
            acc[i] += v[i]
        n += 1
    if n == 0:
        return []
    return [x / n for x in acc]


def euclidean_distance(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=False)))


def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """1 - cosine similarity. 0 = identical direction, 1 = orthogonal, 2 = opposite."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return 1.0 - (dot / (na * nb))


def population_stability_index(
    expected: Sequence[float], actual: Sequence[float], *, buckets: int = 10
) -> float:
    """PSI between two 1-D samples (e.g. retrieval-score distributions).

    PSI < 0.1 = no significant shift; 0.1-0.25 = moderate; > 0.25 = major shift
    (the conventional thresholds Phoenix/Arize cite for drift).
    """
    if not expected or not actual:
        return 0.0
    lo = min(min(expected), min(actual))
    hi = max(max(expected), max(actual))
    if hi <= lo:
        return 0.0
    width = (hi - lo) / buckets
    eps = 1e-6

    def _dist(sample: Sequence[float]) -> list[float]:
        counts = [0] * buckets
        for x in sample:
            idx = min(int((x - lo) / width), buckets - 1)
            counts[idx] += 1
        total = len(sample)
        return [c / total for c in counts]

    e_dist = _dist(expected)
    a_dist = _dist(actual)
    psi = 0.0
    for e, a in zip(e_dist, a_dist, strict=False):
        e_adj = max(e, eps)
        a_adj = max(a, eps)
        psi += (a_adj - e_adj) * math.log(a_adj / e_adj)
    return psi


# Conventional drift thresholds (Arize/Phoenix guidance) for centroid cosine distance
# and PSI — exported so adapters and routes classify consistently.
PSI_MODERATE = 0.1
PSI_MAJOR = 0.25


def classify_psi(psi: float) -> str:
    if psi >= PSI_MAJOR:
        return "major"
    if psi >= PSI_MODERATE:
        return "moderate"
    return "stable"
