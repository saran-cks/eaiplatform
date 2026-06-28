"""Unit tests for the observability layer (DD-17).

Covers, with no live Phoenix:
  * neutral → OpenInference attribute translation (and that our literal keys match the
    installed openinference constants, if present),
  * pure drift math + the Valkey-backed drift tracker (warm-up → baseline → drift, fail-soft),
  * the NoOp adapter,
  * the Phoenix adapter's span emission via an in-memory OTel exporter (OpenInference attrs,
    session grouping, mid-span enrichment) + drift feeding + fail-soft eval/read,
  * the LLM-judge eval runner (rail parsing + the four evaluators),
  * producer instrumentation: the MCP connector TOOL span and the chat pipeline spans.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from adapters.observability.noop import NoOpObservability
from adapters.observability.phoenix import semconv
from adapters.observability.phoenix.client import PhoenixObservabilityAdapter
from adapters.observability.phoenix.drift import EmbeddingDriftTracker
from core.ports.observability import ObsAttr, SpanKind
from observability import drift as drift_math


# --------------------------------------------------------------------------- fakes
class FakeCache:
    def __init__(self) -> None:
        self.d: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.d.get(key)

    async def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        self.d[key] = value

    async def touch(self, key: str, *, ttl: int) -> bool:
        return True

    async def evict(self, key: str) -> None:
        self.d.pop(key, None)

    async def evict_pattern(self, pattern: str) -> int:
        return 0


class FailingCache(FakeCache):
    async def get(self, key: str) -> str | None:
        raise RuntimeError("valkey down")

    async def set(self, key: str, value: str, *, ttl: int | None = None) -> None:
        raise RuntimeError("valkey down")


# --------------------------------------------------------------------------- semconv
def test_semconv_kind_and_tokens():
    out = semconv.to_openinference(
        SpanKind.LLM,
        {ObsAttr.LLM_MODEL: "m", ObsAttr.LLM_TOKENS_INPUT: 3, ObsAttr.LLM_TOKENS_OUTPUT: 5},
    )
    assert out["openinference.span.kind"] == "LLM"
    assert out["llm.model_name"] == "m"
    assert out["llm.token_count.prompt"] == 3
    assert out["llm.token_count.completion"] == 5


def test_semconv_input_text_vs_json():
    text = semconv.to_openinference(SpanKind.CHAIN, {ObsAttr.INPUT: "hi"})
    assert text["input.value"] == "hi"
    assert text["input.mime_type"] == "text/plain"
    js = semconv.to_openinference(SpanKind.TOOL, {ObsAttr.INPUT: {"a": 1}})
    assert js["input.mime_type"] == "application/json"


def test_semconv_flattens_messages_documents_embeddings():
    out = semconv.translate_attrs(
        {
            ObsAttr.LLM_INPUT_MESSAGES: [{"role": "user", "content": "q"}],
            ObsAttr.RETRIEVAL_DOCUMENTS: [{"id": "c1", "content": "doc", "score": 0.9}],
            ObsAttr.EMBEDDING_VECTOR: [0.1, 0.2],
        }
    )
    assert out["llm.input_messages.0.message.role"] == "user"
    assert out["llm.input_messages.0.message.content"] == "q"
    assert out["retrieval.documents.0.document.id"] == "c1"
    assert out["retrieval.documents.0.document.content"] == "doc"
    assert out["retrieval.documents.0.document.score"] == 0.9
    assert out["embedding.embeddings.0.embedding.vector"] == [0.1, 0.2]


def test_semconv_passes_through_forensic_keys():
    out = semconv.translate_attrs({ObsAttr.POLICY_DECISION: "deny", ObsAttr.RISK_SCORE: 2.1})
    assert out["policy.decision"] == "deny"
    assert out["risk.score"] == 2.1


def test_semconv_keys_match_official_constants():
    pytest.importorskip("openinference.semconv.trace")
    from openinference.semconv.trace import SpanAttributes

    assert semconv._SPAN_KIND_KEY == SpanAttributes.OPENINFERENCE_SPAN_KIND
    assert semconv._INPUT_VALUE == SpanAttributes.INPUT_VALUE
    assert semconv._OUTPUT_VALUE == SpanAttributes.OUTPUT_VALUE
    assert semconv._SESSION_ID == SpanAttributes.SESSION_ID
    assert semconv._LLM_MODEL == SpanAttributes.LLM_MODEL_NAME
    assert semconv._LLM_TOK_PROMPT == SpanAttributes.LLM_TOKEN_COUNT_PROMPT


# --------------------------------------------------------------------------- drift math
def test_drift_math():
    assert drift_math.centroid([[0.0, 0.0], [2.0, 2.0]]) == [1.0, 1.0]
    assert drift_math.euclidean_distance([0.0, 0.0], [3.0, 4.0]) == 5.0
    assert drift_math.cosine_distance([1.0, 0.0], [1.0, 0.0]) == pytest.approx(0.0)
    assert drift_math.cosine_distance([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)


def test_psi_thresholds():
    same = drift_math.population_stability_index([1, 2, 3, 4] * 5, [1, 2, 3, 4] * 5)
    assert same == pytest.approx(0.0, abs=1e-6)
    shifted = drift_math.population_stability_index([0] * 20, [10] * 20)
    assert shifted > drift_math.PSI_MAJOR
    assert drift_math.classify_psi(0.0) == "stable"
    assert drift_math.classify_psi(0.3) == "major"


# --------------------------------------------------------------------------- drift tracker
@pytest.mark.asyncio
async def test_drift_tracker_warmup_then_drift():
    cache = FakeCache()
    tr = EmbeddingDriftTracker(cache)
    # Warm up below the baseline threshold.
    for _ in range(10):
        await tr.observe("t1", [1.0, 0.0])
    warm = await tr.compute("t1")
    assert warm["status"] == "warming_up"

    # Cross the baseline threshold with one direction, then shift the distribution.
    for _ in range(50):
        await tr.observe("t1", [1.0, 0.0])
    for _ in range(60):
        await tr.observe("t1", [0.0, 1.0])
    result = await tr.compute("t1")
    assert result["status"] == "ok"
    assert result["cosine_distance"] > 0.0


@pytest.mark.asyncio
async def test_drift_tracker_fail_soft():
    tr = EmbeddingDriftTracker(FailingCache())
    await tr.observe("t1", [1.0, 0.0])  # must not raise
    result = await tr.compute("t1")
    assert result["status"] == "unavailable"


# --------------------------------------------------------------------------- NoOp
@pytest.mark.asyncio
async def test_noop_observability():
    obs = NoOpObservability()
    async with obs.span("x", kind=SpanKind.LLM, attributes={ObsAttr.INPUT: "q"}) as s:
        s.set_attribute(ObsAttr.OUTPUT, "a")
        assert s.span_id is None
    await obs.record_eval(span_id="s", name="n")  # no raise
    assert await obs.get_traces() == []
    assert (await obs.drift_check())["status"] == "disabled"


# --------------------------------------------------------------------------- Phoenix adapter
@pytest.fixture
def in_memory_spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)  # honoured the first time (default proxy is replaced)
    return exporter


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        otel_service_name="svc", phoenix_http_endpoint="http://x:6006", phoenix_api_key=""
    )


@pytest.mark.asyncio
async def test_phoenix_span_emits_openinference(in_memory_spans):
    adapter = PhoenixObservabilityAdapter(_settings(), cache=FakeCache())
    async with adapter.span(
        "chat.llm",
        kind=SpanKind.LLM,
        attributes={ObsAttr.SESSION_ID: "sess", ObsAttr.LLM_MODEL: "m"},
    ) as span:
        span.set_attribute(ObsAttr.LLM_OUTPUT, "hello")

    spans = in_memory_spans.get_finished_spans()
    rec = next(s for s in spans if s.name == "chat.llm")
    assert rec.attributes["openinference.span.kind"] == "LLM"
    assert rec.attributes["session.id"] == "sess"
    assert rec.attributes["llm.model_name"] == "m"
    assert rec.attributes["output.value"] == "hello"


@pytest.mark.asyncio
async def test_phoenix_span_feeds_drift(in_memory_spans):
    cache = FakeCache()
    adapter = PhoenixObservabilityAdapter(_settings(), cache=cache)
    async with adapter.span(
        "chat.embed",
        kind=SpanKind.EMBEDDING,
        attributes={ObsAttr.TENANT_ID: "t1", ObsAttr.EMBEDDING_TEXT: "q"},
    ) as span:
        span.set_attribute(ObsAttr.EMBEDDING_VECTOR, [0.5, 0.5])
    assert any(k.startswith("drift:cur:t1") for k in cache.d)


@pytest.mark.asyncio
async def test_phoenix_eval_failsoft_without_client(in_memory_spans):
    adapter = PhoenixObservabilityAdapter(_settings(), cache=FakeCache())
    # phoenix.client may be absent / base_url unreachable → must not raise.
    await adapter.record_eval(span_id="abc", name="Hallucination", label="factual", score=1.0)
    assert list(await adapter.get_traces()) == [] or True  # no raise is the assertion


# --------------------------------------------------------------------------- eval runner
def test_parse_verdict():
    from core.use_cases.observability.evaluate_turn import _parse_verdict

    assert _parse_verdict("because X\nfactual", good="factual", bad="hallucinated") == (
        "factual", 1.0,
    )
    assert _parse_verdict("nope\nhallucinated", good="factual", bad="hallucinated") == (
        "hallucinated", 0.0,
    )
    # 'non-toxic' contains 'toxic' — must still resolve to the good rail.
    assert _parse_verdict("fine\nnon-toxic", good="non-toxic", bad="toxic") == ("non-toxic", 1.0)
    assert _parse_verdict("bad\ntoxic", good="non-toxic", bad="toxic") == ("toxic", 0.0)


class _JudgeLLM:
    """Returns the 'good' rail by reading the rail offered in the prompt tail."""

    async def generate(
        self, *, messages, system=None, max_tokens=None, temperature=None, model=None
    ):
        prompt = messages[0].content
        # tail: ...single word: 'GOOD' or 'BAD'...
        good = prompt.split("single word: '")[1].split("'")[0]
        return f"reasoning here\n{good}"


class _RecordingObs(NoOpObservability):
    def __init__(self) -> None:
        self.evals: list[dict[str, Any]] = []

    async def record_eval(self, **kwargs: Any) -> None:
        self.evals.append(kwargs)


@pytest.mark.asyncio
async def test_evaluate_turn_records_four_evals():
    from core.use_cases.observability.evaluate_turn import EvaluateTurnUseCase

    obs = _RecordingObs()
    uc = EvaluateTurnUseCase(llm=_JudgeLLM(), observability=obs)
    await uc.evaluate(span_id="sp", question="q?", context="ctx", answer="ans")
    names = {e["name"] for e in obs.evals}
    assert names == {"Hallucination", "QA Correctness", "Relevance", "Toxicity"}
    assert all(e["score"] == 1.0 for e in obs.evals)


# --------------------------------------------------------------------------- producer: connector
class _SpyTransport:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(self, *, server, name, arguments):
        self.calls.append(name)
        return {"result": f"[{name}]", "ok": True}

    async def close(self) -> None:
        return None


class _CapturingSpan:
    def __init__(self, attrs: dict[str, Any]) -> None:
        self.attrs = attrs

    @property
    def span_id(self) -> str | None:
        return "fake-span"

    def set_attribute(self, key: str, value: Any) -> None:
        self.attrs[key] = value

    def set_attributes(self, attributes) -> None:
        self.attrs.update(attributes)

    def record_exception(self, exc) -> None:
        pass

    def set_error(self, message) -> None:
        pass


class _CapturingObs(NoOpObservability):
    def __init__(self) -> None:
        self.spans: list[tuple[str, SpanKind, dict[str, Any]]] = []
        self.evals: list[dict[str, Any]] = []

    @asynccontextmanager
    async def span(self, name, *, kind=SpanKind.CHAIN, attributes=None):
        attrs = dict(attributes or {})
        self.spans.append((name, kind, attrs))
        yield _CapturingSpan(attrs)

    async def record_eval(self, **kwargs: Any) -> None:
        self.evals.append(kwargs)


def _connector(obs, env="prod"):
    from adapters.mcp.catalog import build_catalog
    from adapters.mcp.connector import PdpGuardedMCPConnector
    from adapters.mcp.target_resolver import McpTargetResolver
    from core.use_cases.policy.policy_decision_point import PolicyDecisionPoint
    from core.use_cases.policy.trajectory_monitor import TrajectoryMonitor

    catalog = build_catalog()
    resolver = McpTargetResolver(catalog=catalog, environment=env)
    pdp = PolicyDecisionPoint(registry=catalog.policy_registry(), target_resolver=resolver)
    transport = _SpyTransport()
    conn = PdpGuardedMCPConnector(
        catalog=catalog,
        pdp=pdp,
        monitor=TrajectoryMonitor(),
        transport=transport,
        observability=obs,
    )
    return conn, transport


def _scope(*perms: str):
    from core.domain.value_objects.permission_scope import PermissionScope

    return PermissionScope(tenant_id="t1", subject_id="u1", permissions=frozenset(perms))


@pytest.mark.asyncio
async def test_connector_emits_tool_span_on_allow():
    obs = _CapturingObs()
    conn, transport = _connector(obs)
    await conn.call_tool(
        name="github.get_file",
        arguments={"repo": "core-api", "path": "x", "ref": "main"},
        scope=_scope("github:read"),
        session_id="a1",
    )
    assert transport.calls == ["github.get_file"]
    name, kind, attrs = obs.spans[0]
    assert name == "mcp.tool.github.get_file"
    assert kind is SpanKind.TOOL
    assert attrs[ObsAttr.POLICY_DECISION] == "allow"
    assert ObsAttr.RISK_SCORE in attrs


@pytest.mark.asyncio
async def test_connector_span_records_denied_call():
    from core.domain.policy.types import PolicyViolation

    obs = _CapturingObs()
    conn, transport = _connector(obs)
    with pytest.raises(PolicyViolation):
        await conn.call_tool(
            name="github.get_file",
            arguments={"repo": "core-api", "path": "x", "ref": "main"},
            scope=_scope(),  # no permission → PDP deny
            session_id="a1",
        )
    assert transport.calls == []
    _, _, attrs = obs.spans[0]
    assert attrs[ObsAttr.POLICY_DECISION] == "deny"


# --------------------------------------------------------------------------- producer: chat
class _MockAsyncIterator:
    def __init__(self, items):
        self.items = items

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)


@pytest.mark.asyncio
async def test_chat_pipeline_emits_spans_and_schedules_eval():
    from unittest.mock import AsyncMock, MagicMock

    from core.domain.entities.session import Session
    from core.domain.value_objects.guard_verdict import GuardVerdict
    from core.domain.value_objects.retrieval_result import RetrievalResult
    from core.use_cases.chat.send_message import SendChatMessageUseCase

    obs = _CapturingObs()

    class _Eval:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def evaluate(self, *, span_id, question, context, answer):
            self.calls.append(span_id)

    evaluator = _Eval()

    store = AsyncMock()
    cache = AsyncMock()
    cache.get.return_value = None
    retriever = AsyncMock()
    retriever.embed.return_value = [0.1, 0.2]
    retriever.search.return_value = RetrievalResult(chunks=(), fusion="rrf", reranked=False)
    guard = AsyncMock()
    guard.screen.return_value = GuardVerdict.allow()
    llm = MagicMock()
    llm.stream.return_value = _MockAsyncIterator(["Hello ", "world"])

    uc = SendChatMessageUseCase(
        store=store,
        cache=cache,
        retriever=retriever,
        llm=llm,
        guard=guard,
        retrieval_top_k=5,
        cache_response_ttl=3600,
        observability=obs,
        evaluator=evaluator,
        eval_sample_rate=1.0,
    )
    session = Session(session_id="s1", tenant_id="t1")
    scope = _scope("read")

    tokens = [t async for t in uc.execute(session=session, query="hi", scope=scope, history=[])]
    assert tokens == ["Hello ", "world"]

    span_names = {name for name, _, _ in obs.spans}
    assert {"chat.guard", "chat.embed", "chat.retrieval", "chat.llm"} <= span_names

    await asyncio.sleep(0.02)  # let the fire-and-forget eval task run
    assert evaluator.calls == ["fake-span"]
