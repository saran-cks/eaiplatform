"""ObservabilityPort — the single, vendor-neutral seam for tracing, evals, drift, datasets.

This port is deliberately backend-agnostic. Core and use-cases depend ONLY on this
contract and the neutral vocabulary below (``SpanKind`` / ``ObsAttr`` / ``ObsSpan``);
nothing in ``core`` ever imports OpenInference, OpenTelemetry, or a Phoenix client.

That is the whole point: swapping Phoenix for Langfuse (or anything else) is a matter of
writing a new adapter under ``adapters/observability/<vendor>/`` that maps this neutral
vocabulary onto the vendor's wire format, and rebinding it in ``config/di.py``. No core
or use-case code changes.

Write side: ``span()`` (rich, kind-tagged spans grouped into Phoenix *sessions* via
``ObsAttr.SESSION_ID``), ``record_eval`` (LLM-judge / human annotations), ``curate_dataset``.
Read side: ``get_traces`` / ``get_evals`` / ``get_datasets`` back the ``/observability`` routes.
``drift_check`` answers the embedding-drift query. Every method must be fail-soft — an
observability backend outage must never break the request path.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class SpanKind(StrEnum):
    """Neutral span taxonomy. Adapters map these onto their backend's span kinds
    (e.g. the Phoenix adapter maps them to OpenInference ``openinference.span.kind``)."""

    CHAIN = "chain"
    LLM = "llm"
    RETRIEVER = "retriever"
    EMBEDDING = "embedding"
    TOOL = "tool"
    AGENT = "agent"
    GUARDRAIL = "guardrail"
    RERANKER = "reranker"


class ObsAttr:
    """Neutral, backend-agnostic span-attribute keys (our internal vocabulary).

    The adapter translates these to the backend's semantic conventions. Producers
    (use-cases, the MCP connector, the agent runtime) only ever reference these
    constants, never a vendor's key strings.
    """

    # --- session / identity (drives Phoenix "Sessions" grouping) ---
    SESSION_ID = "session.id"
    USER_ID = "user.id"
    TENANT_ID = "tenant.id"

    # --- generic input/output (rendered as the span's primary content) ---
    INPUT = "input"
    OUTPUT = "output"
    METADATA = "metadata"
    TAGS = "tags"

    # --- LLM ---
    LLM_MODEL = "llm.model"
    LLM_SYSTEM = "llm.system"
    LLM_INPUT_MESSAGES = "llm.input_messages"   # sequence of {role, content}
    LLM_OUTPUT = "llm.output"
    LLM_TOKENS_INPUT = "llm.tokens.input"
    LLM_TOKENS_OUTPUT = "llm.tokens.output"
    LLM_TOKENS_TOTAL = "llm.tokens.total"
    LLM_TEMPERATURE = "llm.temperature"

    # --- retrieval / embedding ---
    RETRIEVAL_QUERY = "retrieval.query"
    RETRIEVAL_TOP_K = "retrieval.top_k"
    RETRIEVAL_DOCUMENTS = "retrieval.documents"  # sequence of {id, content, score, metadata}
    EMBEDDING_MODEL = "embedding.model"
    EMBEDDING_TEXT = "embedding.text"
    EMBEDDING_VECTOR = "embedding.vector"        # list[float] (powers UMAP / drift in Phoenix)

    # --- tool / MCP ---
    TOOL_NAME = "tool.name"
    TOOL_ARGUMENTS = "tool.arguments"
    TOOL_SERVER = "tool.server"

    # --- policy / trajectory (DD-8 / DD-11 forensics) ---
    POLICY_DECISION = "policy.decision"          # allow | deny | require_approval
    POLICY_REASON = "policy.reason"
    POLICY_TARGET = "policy.target"
    POLICY_ENVIRONMENT = "policy.environment"
    RISK_LEVEL = "risk.level"                    # ok | throttle | require_approval | kill
    RISK_SCORE = "risk.score"
    RISK_SIGNALS = "risk.signals"

    # --- guardrail ---
    GUARD_BLOCKED = "guard.blocked"
    GUARD_LABEL = "guard.label"
    GUARD_SCORE = "guard.score"


@runtime_checkable
class ObsSpan(Protocol):
    """Neutral handle to an in-progress span. Lets a producer enrich a span with
    values only known mid-operation (token counts, output) without touching the
    backend's span object directly."""

    @property
    def span_id(self) -> str | None:
        """Backend span id (hex), if the span is recording — used to attach evals."""
        ...

    def set_attribute(self, key: str, value: Any) -> None: ...

    def set_attributes(self, attributes: Mapping[str, Any]) -> None: ...

    def record_exception(self, exc: BaseException) -> None: ...

    def set_error(self, message: str) -> None:
        """Mark the span as failed (status=ERROR) with a message."""
        ...


@runtime_checkable
class ObservabilityPort(Protocol):
    # --- write side -------------------------------------------------------
    def span(
        self,
        name: str,
        *,
        kind: SpanKind = SpanKind.CHAIN,
        attributes: Mapping[str, Any] | None = None,
    ) -> AbstractAsyncContextManager[ObsSpan]:
        """Open a kind-tagged span as an async context manager yielding an ``ObsSpan``.

        Implementations MUST NOT raise on backend failure — a broken exporter degrades
        to a no-op span, never an error on the caller's hot path.
        """
        ...

    async def record_eval(
        self,
        *,
        span_id: str,
        name: str,
        label: str | None = None,
        score: float | None = None,
        explanation: str | None = None,
        annotator_kind: str = "LLM",
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Attach an evaluation/annotation to a span (LLM-judge or human feedback),
        so it renders as an eval in the backend UI. Fail-soft."""
        ...

    async def curate_dataset(
        self, *, tenant_id: str, dataset: str, examples: Sequence[Mapping[str, Any]]
    ) -> None:
        """Append labelled real-traffic examples to a named dataset for offline eval.

        ``tenant_id`` scopes the dataset: the write and the read side (``get_datasets``)
        agree on a tenant-namespaced identity so one tenant never sees another's data."""
        ...

    # --- read side (backs /observability routes) --------------------------
    # ``tenant_id`` is mandatory on every read: the /observability routes carry query text
    # and retrieved-chunk content, so results MUST be filtered to the caller's tenant. It is
    # the PermissionScope's tenant, passed top-down; adapters filter, never derive it.
    async def get_traces(
        self, *, tenant_id: str, limit: int = 50, session_id: str | None = None
    ) -> Sequence[Mapping[str, Any]]:
        ...

    async def get_evals(
        self, *, tenant_id: str, limit: int = 50
    ) -> Sequence[Mapping[str, Any]]:
        ...

    async def get_datasets(self, *, tenant_id: str) -> Sequence[Mapping[str, Any]]:
        ...

    async def drift_check(self, *, tenant_id: str | None = None) -> Mapping[str, Any]:
        """Query/compute embedding drift between query-time and reference vector spaces."""
        ...

    async def close(self) -> None:
        """Release backend clients (called from the app lifespan)."""
        ...
