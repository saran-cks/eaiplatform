<!-- SCOPE BANNER — read first -->
> **SCOPE — CORE API ONLY.** This document describes ONLY the always-on FastAPI **Core API** (`src/`) — its hexagonal architecture, flow logic, and invariants. It does **NOT** cover the embedding sidecar (`sidecars/model_server/`), the Prompt Guard sidecar (`sidecars/prompt_guard/`), or the separately-deployed **Ingestion Worker** (`ingestion_worker/`). Those are independent deployables, each documented separately. The **only** surface shared across all of them is **Qdrant, Postgres, Valkey, and Phoenix** — and the Qdrant collection + payload schema is the frozen contract between this app (reader) and the Ingestion Worker (writer).

# INSTRUCTIONS — Core API architecture & logic (for AI code agents working on this repo)

Read this before touching code. It explains *why* the project is shaped the way it is.
For the task list and session log, see `PLAN.md`. This file is the architecture + logic.

## What this is
Backend for an enterprise AI platform structured around four core use cases across two categories:

### 1. Chat Interface
*   **1a. Real-Time Project Check (Current)**: Spawns a dedicated agent to connect to systems and check logs/status in real time via MCP. Bypasses Qdrant retrieval.
*   **1b. Incident Resolution (Current/Future)**: Uses Qdrant RAG (with permissions) to understand context, spawns specialized subagents to query logs/APIs/GitHub, and returns a step-by-step resolution. Live action execution is a FUTURE extension requiring human-in-the-loop approval.

### 2. Code Assist
*   **2a. Monaco UI Editor (Current)**: Suggests and highlights code fixes in a Monaco-based UI.
*   **2b. Typer CLI (Current/Future)**: Integrated live to the app for developer CLI utilities. Sandbox execution of generated code is a FUTURE extension.

The ingestion worker is a separate fat service (we only retrieve from Qdrant). External connections use MCP. A2A-compatible.

## Non-negotiable architecture: hexagonal (ports & adapters)
Dependencies point inward. The domain knows nothing about FastAPI, Qdrant, Bedrock, etc.

```
api/routes ─▶ core/use_cases ─▶ core/ports (Protocols) ◀─ adapters/* (concrete I/O)
                    │                  ▲
                    └────────▶ core/domain (entities + value objects)
config/di.py wires adapters → ports.   config/settings.py = all env.
```

**Invariants — a change that breaks one of these is wrong:**
- `core/use_cases/` imports only `core/ports/` + `core/domain/`. No adapters, no FastAPI.
- `api/routes/` imports only `core/use_cases/` + `api/schemas/`.
- `adapters/` import `core/ports/` + external libs only. **Adapters never import each other.**
- `config/di.py` is the ONLY file that binds a concrete adapter to a port (one provider each).
- `PermissionScope` is created by JWT middleware and flows top-down as an argument.
  **Never construct/derive it inside an adapter or use-case.** Adapters receive it and obey it.

## Layout (src/ is on PYTHONPATH → import as `core.*`, `adapters.*`, `api.*`, `config.*`)
- `core/domain/entities/` — pydantic v2 models (Session/AgentSession, Message/Turn, Chunk/RetrievedChunk, Document, IngestionJob).
- `core/domain/value_objects/` — frozen dataclasses (PermissionScope, EmbeddingVector, RetrievalResult). Immutable, hashable.
- `core/ports/` — `typing.Protocol`, `@runtime_checkable`, async. 8 ports: llm, retriever, agent, cache, store, queue, observability, mcp_connector.
- `core/use_cases/` — orchestration only; depends on ports.
- `adapters/` — bedrock (llm), qdrant + model_server gRPC (retriever), langgraph_runner + a2a (agent), valkey (cache), postgres (store), arq (queue), phoenix (observability), mcp/.
- `api/` — middleware (auth, telemetry), routes, schemas.
- `observability/` — otel init, typed span builders, metrics, drift logic.
- `daemon/` — background asyncio tasks (process_manager, agent_reaper, session_cleanup, health_watchdog).
- `config/` — settings.py (pydantic-settings), di.py (Container).

## Tech + conventions
- Python 3.12, FastAPI, **asyncio everywhere — zero blocking calls on the event loop**.
- asyncpg (not SQLAlchemy sync) · redis.asyncio for Valkey · async gRPC for model server · httpx async.
- Native Qdrant Client (RAG) + LangGraph (ReAct agent & state workflows). AWS Bedrock (Claude) SSE streaming.
- Qdrant hybrid dense+sparse + RRF. pydantic v2 schemas. pydantic-settings v2 config. ARQ on Valkey.
- OpenTelemetry → Phoenix (OTLP gRPC :4317). pytest + pytest-asyncio; locust + py-spy later.
- uv for deps. Everything typed (mypy strict), ruff-clean, async, independently testable.
- No placeholder comments. Mark deferred code with `# FUTURE EXTENSION`. Keep token use low.

## Key flows (implement to this exact logic)
**Chat `/chat/{session_id}/message`** (order matters):
1. Prompt Guard already screened upstream (separate HTTP sidecar). 2. Check Valkey
`response:{hash(normalized_query+tenant_id+perm_scope)}` → hit streams & returns. 3. Load
`session:{id}` from Valkey, miss → hydrate from Postgres. 4. gRPC embed (bge-m3 dense+sparse).
5. Qdrant hybrid + RRF with payload filter `{tenant_id, permissions}` from the scope (pre-LLM).
6. **Optional** rerank only if `RERANK_ENABLED` and score spread < threshold (deferred phase 1).
7. LlamaIndex assembles context+prompt. 8. Bedrock SSE → client (first token < 2s).
9. Persist turn idempotently (`message_id`). 10. Update `session:{id}` (sliding 2h). 11. Cache
chunks `chunk:{id}` (24h). 12. Emit OTel spans for every step.

**Agent `/agent/{session_id}/run`:** create AgentSession (status=running, sandbox_ref=null),
register in lifecycle_manager, run ReAct loop (tools via MCP registry, scope-checked; code →
Monaco; each step SSE). On done → completed + deregister. On interrupt → graceful, interrupted.
`agent_reaper` daemon kills TTL-exceeded/orphaned agents. All agents expose A2A interfaces even solo.

> **Agent retrieval — IMPLEMENT LATER.** If an agent needs **semantic** data from Qdrant, it MUST embed its query through the **same embedding sidecar** the chat path uses (via `RetrieverPort` / the gRPC embed client) — never a second embedding model, never raw vectors. Vector search = embed-then-ANN, so there is no semantic retrieval without embedding. Only **exact/filter lookups** (by `tenant_id`/`permissions`/`ticket_id`/`doc_id`) skip embedding — use Qdrant payload filter or Postgres for those. The agent's ReAct loop should expose retrieval as a scope-checked **tool** that reuses the chat retrieval use-case; this tool is not built yet — wire it when agent tools land. See `docs/design-decisions.md`.

**Valkey namespaces (never mixed):** `response:{hash}` 1h (disabled for /agent), `chunk:{id}` 24h,
`session:{id}` 2h sliding.

**Permissions everywhere:** JWT middleware → `PermissionScope(tenant_id, permissions, subject_id)`
→ passed into Qdrant filter, MCP tool gating, and agent tool registration. `/search` enforces the
identical scope as `/chat/`.

**Observability:** every operation emits OTel spans → Phoenix. drift (query vs ingestion vectors),
evals (retrieval quality + LLM faithfulness/relevance), dataset curation from real traffic. Read
back through `ObservabilityPort` so Phoenix is swappable by adapter only. `/feedback/{turn_id}`
writes Postgres AND emits an eval span.

## FUTURE EXTENSION (stub + mark, don't build): vllm llm, sqs queue, llamaindex_runner, swarm_runner,
a2a swarm_coordinator, E2B sandbox exec, CLI transport, MCP write actions (ServiceNow/GitHub/Zendesk).

## Working rules for agents
- Build in the order in `PLAN.md`; don't collapse layers or build everything at once.
- New external dependency → add to a port + an adapter + a di.py binding. Never call I/O from a use-case.
- After each session: tick `PLAN.md` checkboxes and append next-step notes there.
- Logs go to stdout (CloudWatch) by default; `LOG_TO_FILE` flag switches to files for local dev.
