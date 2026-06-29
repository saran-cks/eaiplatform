# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Backend for an enterprise AI platform: permission-scoped RAG (chat), agents, MCP, and A2A, built on a
hexagonal (ports-and-adapters) core. There are **four independent deployables** that share **no code** —
they are coupled only by data at rest (Qdrant + Postgres + Valkey + Phoenix):

| Deployable | Path | Role |
|---|---|---|
| Core API | `src/` | Always-on FastAPI app: auth, chat (RAG), agents, MCP, observability. |
| Embedding sidecar | `sidecars/model_server/` | bge-m3 dense+sparse embeddings + reranker over **gRPC** (:50051). |
| Prompt Guard sidecar | `sidecars/prompt_guard/` | Llama Prompt Guard 2 (86M) injection/jailbreak screening over **HTTP** (:8001). |
| Ingestion worker | `ingestion_worker/` | Standalone pipeline: acquire → gate → parse → guard → chunk → embed → dual-write to Qdrant+Postgres. |

The Core API only **reads** from Qdrant; the ingestion worker is the only **writer**. The shared schema is
pinned in `contracts/` and cross-enforced by a contract test on each side (`test_contract_qdrant.py`).

## Commands

Dependencies are managed with **`uv`, not pip**. Each of the four deployables is its own uv project
(`src/` uses the root `pyproject.toml`; `sidecars/model_server`, `sidecars/prompt_guard` have their own).

```bash
# Core API (root project)
uv run pytest src/tests                       # all core-api tests
uv run pytest src/tests/test_mcp.py           # one test file
uv run pytest src/tests/test_mcp.py::test_name -x   # one test, stop on first failure
uv run ruff check src ingestion_worker        # lint
uv run ruff format src ingestion_worker       # format
uv run mypy src                               # type-check (strict mode)

# Ingestion worker (decoupled; shares root deps)
uv run python -m pytest ingestion_worker/tests

# Sidecars (separate uv projects — cd in first)
cd sidecars/model_server  && uv run pytest tests
cd sidecars/prompt_guard  && uv run pytest tests

# Full stack (Postgres, Valkey, Qdrant, Phoenix, Core API; sidecars are external images)
docker compose up           # override file adds live-reload uvicorn for local dev
```

pytest is configured (root `pyproject.toml`) with `asyncio_mode = "auto"` and `pythonpath = ["src"]`,
so tests import as `core.*`, `adapters.*`, `api.*`, `config.*` with no `src.` prefix.

## Architecture: hexagonal (ports & adapters) — non-negotiable

Dependencies point **inward**. The domain knows nothing about FastAPI, Qdrant, Bedrock, etc.

```
api/routes ─▶ core/use_cases ─▶ core/ports (Protocols) ◀─ adapters/* (concrete I/O)
                   │                  ▲
                   └────────▶ core/domain (entities + value objects)
config/di.py wires adapters → ports.   config/settings.py = all env.
```

**Invariants (a change that breaks one is wrong — enforced by `src/tests/test_architecture.py`):**
- `core/use_cases/` imports only `core/ports/` + `core/domain/`. No adapters, no FastAPI, no vendor SDKs.
- `api/routes/` imports only `core/use_cases/` + `api/schemas/`.
- `adapters/` import `core/ports/` + external libs only. **Adapters never import each other.**
- `config/di.py` (`Container`) is the **only** file that binds a concrete adapter to a port (one each).
- `core/` may not import OpenInference/OTel/Phoenix symbols — only `observability/` + the Phoenix adapter may.

`core/ports/` are `@runtime_checkable typing.Protocol`, all **async**. Adding any external dependency
means: add/extend a port → write an adapter → bind it in `di.py`. Never call I/O from a use-case.

### PermissionScope is the security spine
`PermissionScope(tenant_id, permissions, subject_id)` is a frozen value object **created by the JWT auth
middleware** and flows **top-down as an argument** into every use case. **Never construct or derive it
inside an adapter or use-case** — adapters receive it and obey it (Qdrant payload filter, MCP tool gating,
agent tool registration). `/search` enforces the identical scope as `/chat`.

### Async everywhere
asyncio-only: asyncpg (not sync SQLAlchemy), redis.asyncio for Valkey, async gRPC for the model server,
httpx async, Bedrock SSE streaming. **Zero blocking calls on the event loop.**

## The agent security model (DD-7 … DD-17) — read `docs/design-decisions.md` before touching agent/policy/mcp code

This is the most load-bearing and subtle part of the codebase. The thesis: **prompt filtering is only the
outer perimeter; security is enforced at the action/authorization layer, assuming the agent's context is
already poisoned.** The LLM *proposes*; deterministic code *decides*. Key pieces, all implemented in core:

- **PDP — Policy Decision Point** (`core/use_cases/policy/policy_decision_point.py`): default-deny chokepoint
  every external effect routes through. Gates **flows** (read-source × write-sink pairs), not just actions;
  bounded typed parameters; canonical target resolution (never trusts a model-supplied target label);
  delegation may only *narrow* scope. Must be correct assuming the agent is the attacker.
- **Trajectory monitor** (`core/use_cases/policy/trajectory_monitor.py`): stateful **cumulative session
  risk** across tool calls (the answer to slow, gradual poisoning that a stateless PDP can't catch).
  Escalates OK→THROTTLE→REQUIRE_APPROVAL→KILL. Risk persists to Valkey (`adapters/policy/session_risk_store.py`)
  so it survives horizontal scale; **fail-soft** to in-process accumulation on backend outage.
- **The MCP connector IS the only PDP caller** (`adapters/mcp/connector.py`): every `call_tool` runs
  `PDP.decide()` → `TrajectoryMonitor.observe()` → enforce **KILL > deny > require-approval > proceed**,
  *before* the transport is touched. A `ToolSpec` produces both the `list_tools` view and the PDP policy so
  they can't drift; a tool with no spec is default-denied. The agent runtime (`langgraph_runner.py`) drives
  the connector — a PDP deny degrades one worker; a `TrajectoryKill` tears down the whole session (reaped by
  the `agent_reaper` daemon).
- **Taint/provenance is a SIGNAL, not a gate** (DD-9): you can't trace influence through an LLM, so no hard
  deny may depend on taint. It feeds the monitor + raises friction; the PDP must be correct with taint unknown.
- **RAG context is untrusted data, never instructions** (DD-13, `core/use_cases/chat/send_message.py`):
  retrieved chunks are injected in a delimited, **datamarked** block (sentinel-prefixed lines); chunk text
  forging the delimiters is neutralized before rendering. Deep screening is done **once at ingestion**
  (`ingestion_worker`), persisted as `screened`/`injection_risk` fields on the chunk; chat reads the flag and
  **neutralizes/down-ranks, never hard-drops** (hard-drop is a DoS-on-knowledge weapon).
- **Observability is a vendor-neutral port** (DD-17, `core/ports/observability.py`): Phoenix is one adapter
  (`adapters/observability/phoenix/`); a `noop.py` adapter exists. **Fail-soft is absolute** — an exporter
  outage degrades to no-op spans, never an error on the request path.

The static guard `src/tests/test_pdp_chokepoint.py` keeps a two-file allowlist (`connector.py` +
`langgraph_runner.py`) — **any new `.call_tool(` site outside it fails the build.** Each DD carries an
"Enforcement check" describing the test that holds it.

## Key request flows (implement to this exact logic — see `docs/core-api-architecture.md`)

**Chat `/chat/{session_id}/message`** (order matters): Prompt Guard screened upstream → check Valkey
`response:{hash(normalized_query+tenant_id+perm_scope)}` → load `session:{id}` (miss → hydrate from Postgres)
→ gRPC embed (bge-m3 dense+sparse) → Qdrant hybrid + RRF with `{tenant_id, permissions}` payload filter
(pre-LLM) → optional rerank (only if `RERANK_ENABLED` + low score spread) → assemble context (datamarked) →
Bedrock SSE to client → persist turn idempotently by `message_id` → update session (2h sliding) → cache
chunks (24h) → emit OTel spans per step.

**Agent `/agent/{session_id}/run`:** create AgentSession (running) → register in lifecycle manager → ReAct
loop (LangGraph; tools via MCP registry, scope-checked, each routed through the PDP) → SSE per step → on done
deregister. `agent_reaper` daemon kills TTL-exceeded/orphaned/KILLED agents. All agents expose A2A even solo.

**Valkey namespaces (never mixed):** `response:{hash}` 1h (disabled for `/agent`), `chunk:{id}` 24h,
`session:{id}` 2h sliding, `risk:{session_id}` agent-session window.

## Conventions

- Python 3.12, **mypy strict**, ruff-clean (line length 100; rules `E,F,I,UP,B,ASYNC,RUF`). Everything typed,
  async, independently testable.
- pydantic v2 entities (`core/domain/entities/`); frozen dataclass value objects (`core/domain/value_objects/`).
- All config via `config/settings.py` (pydantic-settings); env keys mirror `.env.example`. Logs to stdout
  (CloudWatch) by default; `LOG_TO_FILE` switches to files for local dev.
- No placeholder comments. Mark deferred code with `# FUTURE EXTENSION` (e.g. vllm llm, sqs queue,
  llamaindex/swarm runners, E2B sandbox, MCP write actions, DD-10 credential broker, DD-12 approval backend).
- **Commit messages are single-line**; detailed rationale goes in `docs/*-dev-log.md`, design rationale in
  `docs/design-decisions.md` (append new DDs at the bottom), and the task list in `PLAN.md` / per-deployable
  `docs/*-build-plan.md`. Update these after a session rather than padding the commit.

## Docs map

- `PLAN.md` — top-level project index + task order.
- `docs/core-api-architecture.md` — Core API hexagonal architecture, flows, invariants (read before coding).
- `docs/design-decisions.md` — cross-cutting **why** log (DD-1…DD-17), incl. the full agent security model.
- `docs/*-build-plan.md` / `docs/*-dev-log.md` — per-deployable plans and chronological build logs.
- `contracts/README.md` — the frozen Qdrant/Postgres schema between core-api (reader) and ingestion (writer).
- `docs/smoke-tests.md` — deferred live/E2E checks (ST-N), written here as PENDING rather than run inline.
