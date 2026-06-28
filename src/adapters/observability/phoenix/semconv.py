"""Neutral vocabulary → OpenInference semantic-convention translation.

This is the ONLY place that knows OpenInference's wire keys. ``core`` speaks the neutral
``ObsAttr`` / ``SpanKind`` vocabulary; this module flattens and renames those into the
exact attribute strings the Phoenix UI renders off
(https://github.com/Arize-ai/openinference, spec/semantic_conventions.md).

The keys are intentionally written as literals (mirroring ``openinference-semantic-conventions``)
so the mapper is pure and unit-testable without importing the package; ``test_phoenix_semconv``
asserts they still match the installed constants, catching upstream drift.

OTel attribute values must be primitives or homogeneous lists — nested objects (messages,
documents, embeddings) are therefore flattened with numeric indices, and dict/list metadata
is JSON-encoded.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from core.ports.observability import ObsAttr, SpanKind

# --- OpenInference span-kind values ---
_SPAN_KIND_KEY = "openinference.span.kind"
_KIND_MAP: dict[SpanKind, str] = {
    SpanKind.CHAIN: "CHAIN",
    SpanKind.LLM: "LLM",
    SpanKind.RETRIEVER: "RETRIEVER",
    SpanKind.EMBEDDING: "EMBEDDING",
    SpanKind.TOOL: "TOOL",
    SpanKind.AGENT: "AGENT",
    SpanKind.GUARDRAIL: "GUARDRAIL",
    SpanKind.RERANKER: "RERANKER",
}

# --- OpenInference attribute keys (mirror openinference.semconv.trace) ---
_INPUT_VALUE = "input.value"
_INPUT_MIME = "input.mime_type"
_OUTPUT_VALUE = "output.value"
_OUTPUT_MIME = "output.mime_type"
_SESSION_ID = "session.id"
_USER_ID = "user.id"
_METADATA = "metadata"
_TAGS = "tag.tags"
_MIME_TEXT = "text/plain"
_MIME_JSON = "application/json"

_LLM_MODEL = "llm.model_name"
_LLM_SYSTEM = "llm.system"
_LLM_INVOCATION_PARAMS = "llm.invocation_parameters"
_LLM_TOK_PROMPT = "llm.token_count.prompt"
_LLM_TOK_COMPLETION = "llm.token_count.completion"
_LLM_TOK_TOTAL = "llm.token_count.total"
_MSG_ROLE = "message.role"
_MSG_CONTENT = "message.content"

_RETRIEVAL_DOCS = "retrieval.documents"
_DOC_ID = "document.id"
_DOC_CONTENT = "document.content"
_DOC_SCORE = "document.score"
_DOC_METADATA = "document.metadata"

_EMBEDDING_MODEL = "embedding.model_name"
_EMBEDDINGS = "embedding.embeddings"
_EMB_VECTOR = "embedding.vector"
_EMB_TEXT = "embedding.text"

_TOOL_NAME = "tool.name"
_TOOL_PARAMS = "tool.parameters"


def span_kind_value(kind: SpanKind) -> str:
    return _KIND_MAP.get(kind, "CHAIN")


def _jsonable(value: Any) -> Any:
    """Coerce a value to something OTel can carry; JSON-encode containers."""
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Sequence) and all(
        isinstance(v, (str, bool, int, float)) for v in value
    ):
        return list(value)
    return json.dumps(value, default=str)


def translate_attrs(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a neutral attribute dict into flat OpenInference attributes (no span kind).

    Unknown neutral keys are passed through verbatim (they still render in the Phoenix
    span attribute panel — useful for the policy/risk forensic keys).
    """
    out: dict[str, Any] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        _translate_one(out, key, value)
    return out


def to_openinference(kind: SpanKind, attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Full span attribute dict: the OpenInference span kind plus translated attributes."""
    out = translate_attrs(attributes)
    out[_SPAN_KIND_KEY] = span_kind_value(kind)
    return out


def _translate_one(out: dict[str, Any], key: str, value: Any) -> None:
    if key == ObsAttr.SESSION_ID:
        out[_SESSION_ID] = str(value)
    elif key == ObsAttr.USER_ID:
        out[_USER_ID] = str(value)
    elif key == ObsAttr.TENANT_ID:
        out["tenant.id"] = str(value)
    elif key == ObsAttr.INPUT:
        out[_INPUT_VALUE] = _jsonable(value)
        out[_INPUT_MIME] = _MIME_JSON if not isinstance(value, str) else _MIME_TEXT
    elif key == ObsAttr.OUTPUT:
        out[_OUTPUT_VALUE] = _jsonable(value)
        out[_OUTPUT_MIME] = _MIME_JSON if not isinstance(value, str) else _MIME_TEXT
    elif key == ObsAttr.METADATA:
        out[_METADATA] = json.dumps(value, default=str) if not isinstance(value, str) else value
    elif key == ObsAttr.TAGS:
        out[_TAGS] = [str(v) for v in value] if isinstance(value, Sequence) else [str(value)]
    elif key == ObsAttr.LLM_MODEL:
        out[_LLM_MODEL] = str(value)
    elif key == ObsAttr.LLM_SYSTEM:
        out[_LLM_SYSTEM] = str(value)
    elif key == ObsAttr.LLM_TEMPERATURE:
        out[_LLM_INVOCATION_PARAMS] = json.dumps({"temperature": value})
    elif key == ObsAttr.LLM_INPUT_MESSAGES:
        _flatten_messages(out, "llm.input_messages", value)
    elif key == ObsAttr.LLM_OUTPUT:
        out[_OUTPUT_VALUE] = str(value)
        out["llm.output_messages.0." + _MSG_ROLE] = "assistant"
        out["llm.output_messages.0." + _MSG_CONTENT] = str(value)
    elif key == ObsAttr.LLM_TOKENS_INPUT:
        out[_LLM_TOK_PROMPT] = int(value)
    elif key == ObsAttr.LLM_TOKENS_OUTPUT:
        out[_LLM_TOK_COMPLETION] = int(value)
    elif key == ObsAttr.LLM_TOKENS_TOTAL:
        out[_LLM_TOK_TOTAL] = int(value)
    elif key == ObsAttr.RETRIEVAL_QUERY:
        out[_INPUT_VALUE] = str(value)
        out[_INPUT_MIME] = _MIME_TEXT
    elif key == ObsAttr.RETRIEVAL_TOP_K:
        out["retrieval.top_k"] = int(value)
    elif key == ObsAttr.RETRIEVAL_DOCUMENTS:
        _flatten_documents(out, value)
    elif key == ObsAttr.EMBEDDING_MODEL:
        out[_EMBEDDING_MODEL] = str(value)
    elif key == ObsAttr.EMBEDDING_TEXT:
        out[f"{_EMBEDDINGS}.0.{_EMB_TEXT}"] = str(value)
    elif key == ObsAttr.EMBEDDING_VECTOR:
        out[f"{_EMBEDDINGS}.0.{_EMB_VECTOR}"] = [float(v) for v in value]
    elif key == ObsAttr.TOOL_NAME:
        out[_TOOL_NAME] = str(value)
    elif key == ObsAttr.TOOL_ARGUMENTS:
        out[_TOOL_PARAMS] = json.dumps(value, default=str)
        out[_INPUT_VALUE] = json.dumps(value, default=str)
        out[_INPUT_MIME] = _MIME_JSON
    else:
        # Pass-through (policy.*, risk.*, guard.*, tool.server, …) — render as-is.
        out[key] = _jsonable(value)


def _flatten_messages(out: dict[str, Any], prefix: str, messages: Any) -> None:
    if not isinstance(messages, Sequence):
        return
    for i, msg in enumerate(messages):
        if isinstance(msg, Mapping):
            role = msg.get("role", "user")
            content = msg.get("content", "")
        else:
            role, content = "user", str(msg)
        out[f"{prefix}.{i}.{_MSG_ROLE}"] = str(role)
        out[f"{prefix}.{i}.{_MSG_CONTENT}"] = str(content)


def _flatten_documents(out: dict[str, Any], documents: Any) -> None:
    if not isinstance(documents, Sequence):
        return
    for i, doc in enumerate(documents):
        if not isinstance(doc, Mapping):
            out[f"{_RETRIEVAL_DOCS}.{i}.{_DOC_CONTENT}"] = str(doc)
            continue
        base = f"{_RETRIEVAL_DOCS}.{i}."
        if doc.get("id") is not None:
            out[base + _DOC_ID] = str(doc["id"])
        if doc.get("content") is not None:
            out[base + _DOC_CONTENT] = str(doc["content"])
        if doc.get("score") is not None:
            out[base + _DOC_SCORE] = float(doc["score"])
        if doc.get("metadata") is not None:
            out[base + _DOC_METADATA] = json.dumps(doc["metadata"], default=str)
