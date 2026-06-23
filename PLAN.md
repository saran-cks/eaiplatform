# Enterprise AI Platform — Core API — Build Plan

Hexagonal (ports & adapters) FastAPI backend: permission-scoped RAG retrieval over
Qdrant, autonomous ticket/agent intelligence (read-only), AI code generation (Monaco
display only), MCP external connectors, A2A interop. Ingestion worker is **out of scope**
(separate fat worker); we only **retrieve** from Qdrant here.

## Locked decisions
- Python **3.12** (`>=3.12,<3.13`) — universal wheel coverage for grpcio/asyncpg/pydantic-core; free-threading buys nothing for an I/O-bound asyncio app. One-line bump later.
- Dependency tooling: **uv** (`pyproject.toml` + `uv.lock`).
- Auth: **HS256 shared-secret** JWT for local dev; `PermissionScope` carried in claims. Swap to RS256/JWKS later by replacing the verifier adapter only.
- Model server is a **prod sidecar** (bge-m3 embeddings) reachable on `localhost` in prod, `model_server:50051` in Compose. Prompt Guard is a **separate small sidecar** (HTTP :8001). Both env-driven targets.
- Reranker (bge-reranker-v2-m3) is **optional / deferred** for phase 1. Hybrid dense+sparse + RRF top-5 is the phase-1 retrieval path. `RetrieverPort.rerank()` contract is defined; adapter + pipeline branch deferred (config flip: `RERANK_ENABLED`).
- Package import root: `src/` on path → `from core...`, `from adapters...`, etc.
- Ports = `typing.Protocol`. Value objects = frozen dataclasses (immutable). Entities = pydantic v2.

## Architecture invariants (never break)
- `core/use_cases/` imports only `core/ports/` + `core/domain/`.
- `api/routes/` imports only `core/use_cases/` + `api/schemas/`.
- `adapters/` import `core/ports/` + external libs only; **adapters never import each other**.
- `config/di.py` is the **only** wiring file (one binding per port).
- `PermissionScope` flows top-down from JWT middleware — **never derived inside an adapter**.

---

## Task checklist

### Session 1 — Steps 1–4 (foundation + contracts)  ← DONE
- [x] `pyproject.toml` (uv, py3.12, pinned deps), tooling config (ruff/mypy/pytest)
- [x] `config/settings.py` — pydantic-settings v2, all env vars grouped
- [x] `config/di.py` — Container skeleton, one provider per port (raises until adapter wired)
- [x] `.env.example` — mirrors settings, safe placeholders
- [x] `docker-compose.yml` — all 8 services + health checks
- [x] `docker-compose.override.yml` — local dev (source mount, reload)
- [x] `docker/Dockerfile` + `docker/entrypoint.sh`
- [x] All 8 `core/ports/` Protocols (llm, retriever, agent, cache, store, queue, observability, mcp_connector)
- [x] All `core/domain/entities/` (session, message, chunk, document, job)
- [x] All `core/domain/value_objects/` (permission_scope, embedding_vector, retrieval_result)

### Session 2 — Step 5: first runnable slice  ✅ DONE
- [x] `api/main.py` app factory + lifespan (start/stop daemon tasks)
- [x] `api/middleware/auth.py` (HS256 decode -> PermissionScope -> request.state)
- [x] `api/middleware/telemetry.py` (OTel span per request)
- [x] `api/routes/health.py` (`/health` liveness, `/ready` readiness)
- [x] `api/schemas/health.py`
- [x] `daemon/` skeleton: process_manager, agent_reaper, session_cleanup, health_watchdog
- [x] `observability/otel.py` minimal tracer/meter init
- [x] Wire DI for whatever the slice needs; `uvicorn api.main:create_app --factory` -> `/health` 200

### Session 3 — Step 6: storage layer  ✅ DONE
- [x] `adapters/store/postgres.py` (asyncpg pool) + all database mapping tables
- [x] `adapters/cache/valkey.py` (response/chunk/session namespaces)
- [x] SQL schema / migrations bootstrap (automatic on pool initialization)
- [x] DI bindings for StorePort + CachePort

### Session 4 — Step 7: retrieval layer  ✅ DONE
- [x] `adapters/retriever/qdrant.py` (hybrid dense+sparse, RRF, payload permission filter)
- [x] `adapters/retriever/model_server/embed_client.py` (async gRPC → bge-m3)
- [x] `adapters/retriever/model_server/rerank_client.py` (deferred impl, contract only)
- [x] `core/use_cases/retrieval/search_chunks.py`
- [x] `api/routes/search.py` + schema (authenticated, scope-filtered)

### Session 5 — Step 8: chat pipeline
- [ ] `adapters/llm/bedrock.py` (async SSE stream) + `vllm.py` FUTURE stub
- [ ] `core/use_cases/chat/send_message.py` (full RAG order), `manage_session.py`
- [ ] `api/routes/chat.py` (SSE) + schema

### Session 6 — Step 9: agent pipeline + A2A
- [ ] `adapters/agent/langgraph_runner.py`, `lifecycle_manager.py`
- [ ] `adapters/agent/a2a/{protocol,registry}.py`; `swarm_coordinator.py` FUTURE stub
- [ ] `llamaindex_runner.py` (optional), `swarm_runner.py` FUTURE stubs
- [ ] `core/use_cases/agent/{run_agent,manage_artifacts,lifecycle}.py`
- [ ] `api/routes/agent.py` (SSE) + schema

### Session 7 — Step 10: MCP layer
- [ ] `adapters/mcp/{registry,connector}.py`, `tools/base.py`
- [ ] `tools/{servicenow,confluence,github,zendesk}.py` (read-only; write = FUTURE)
- [ ] `api/routes/mcp.py` + schema

### Session 8 — Step 11: observability
- [ ] `observability/{otel,spans,metrics,drift}.py` full
- [ ] `adapters/observability/phoenix/{client,otel_exporter,drift,evals,datasets}.py`
- [ ] `core/use_cases/observability/get_phoenix_data.py`
- [ ] `api/routes/observability.py` + `feedback.py` + schemas

### Session 9 — Step 12: dashboard
- [ ] `api/routes/dashboard.py` (SSE drilldown, rate-limited) + schema

### Session 10 — Steps 13–14: tests + logging
- [ ] `tests/{unit,integration,e2e,profiling}` skeletons
- [ ] File-based logging with stdout flag (`LOG_TO_FILE`) for CloudWatch switch

### Deferred queue/llm backends (any time)
- [ ] `adapters/queue/arq.py` (active) + `sqs.py` FUTURE stub
- [ ] FUTURE: E2B sandbox exec, CLI transport, MCP write actions

---

## What YOU need to do after Session 1
1. Install uv if needed: `pip install uv` (or `winget install astral-sh.uv`).
2. From project root: `uv sync` — creates `.venv` and `uv.lock` from `pyproject.toml`.
3. Copy env: `cp .env.example .env` (PowerShell: `Copy-Item .env.example .env`) and set real `JWT_SECRET`, AWS creds, etc.
4. Provide images for `model_server` and `guard_gateway` (replace the `your-*-image` placeholders in `docker-compose.yml`).
5. Bring up infra only (core_api app code lands in Session 2):
   `docker compose up -d postgres valkey qdrant phoenix`
6. Sanity: Qdrant UI `http://localhost:6333/dashboard`, Phoenix UI `http://localhost:6006`.
7. Review the 8 ports in `src/core/ports/` — these are the contracts everything else implements. Flag any method you want added/changed before adapters get built in Session 3+.

> Note on health checks: `postgres`/`valkey` use real in-image checks. `qdrant`/`phoenix`
> use HTTP checks that assume `curl` in the image — if the pinned image lacks it, switch
> that service to `condition: service_started` (the `health_watchdog` daemon does deep
> readiness in Session 2). `model_server`/`guard_gateway` are your images: expose a
> healthcheck or they default to `service_started`.
