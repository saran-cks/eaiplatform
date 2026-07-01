<!-- SCOPE BANNER — read first -->
> **SCOPE — CORE API ONLY.** This is the chronological dev log for ONLY the always-on FastAPI **Core API** (`src/`). It does **NOT** log work on the embedding sidecar (`sidecars/model_server/`), the Prompt Guard sidecar (`sidecars/prompt_guard/`), or the separately-deployed **Ingestion Worker** (`ingestion_worker/`) — those are independent deployables with their own logs. The **only** shared surface is **Qdrant, Postgres, Valkey, and Phoenix**.

# Enterprise AI Platform Core API - Chronological Build & Developer Log

This file tracks the historical sequence of build sessions, architectural additions, developer notes, and resolving errors.

---

## Session 1: Foundation & Contracts
*   **Completed**: Pre-implemented in starter codebase.
*   **Target**: Establish project layout, basic configuration settings, core domain models, and port interfaces (Protocols).
*   **Steps Completed**:
    *   Set up package structures: `src/core`, `src/config`, `src/api`, `src/observability`, `src/daemon`.
    *   Declared type-safe settings in `src/config/settings.py` via `pydantic-settings` to map environment variables.
    *   Defined the 8 core Port Protocols in `src/core/ports/`: `StorePort`, `CachePort`, `RetrieverPort`, `LLMPort`, `AgentPort`, `QueuePort`, `ObservabilityPort`, `MCPConnectorPort`.
    *   Defined Domain Entities (`Session`, `AgentSession`, `Message`, `Turn`, `Document`, `Chunk`) and Value Objects (`PermissionScope`, `EmbeddingVector`, `RetrievalResult`).
    *   Created `docker-compose.yml` defining the stack (Postgres, Valkey, Qdrant, Phoenix, and placeholders for model sidecars).
    *   Wired `build_container` dependency injection skeleton in `src/config/di.py` raising `AdapterNotWired` for incomplete ports.

---

## Session 2: First Runnable Slice
*   **Completed**: 2026-06-22
*   **Target**: Get the FastAPI factory, lifespan handlers, middleware, health endpoints, background daemons, and basic telemetry wired and runnable.
*   **Steps Completed**:
    *   Created the main app factory `src/api/main.py` configuring middleware order and routes.
    *   Added `AuthMiddleware` in `src/api/middleware/auth.py` to parse incoming JWT HS256 tokens and inject the `PermissionScope` into request state.
    *   Added `TelemetryMiddleware` in `src/api/middleware/telemetry.py` to instrument requests.
    *   Created `/health` (liveness) and `/ready` (readiness connection tests) endpoints under `src/api/routes/health.py`.
    *   Implemented background daemons in `src/daemon/tasks.py` (`process_manager`, `agent_reaper`, `session_cleanup`, `health_watchdog`).
    *   Configured OpenTelemetry exporter initialization in `src/observability/otel.py` reporting to local Arize Phoenix.
    *   Verified the API server starts and runs cleanly using `uv run uvicorn`.
*   **Issues Faced & Resolved**:
    *   **Unicode Encoding Error (Windows)**: The `→` character in the OTel initialization logs caused a `UnicodeEncodeError` under Windows cp1252 console encoding. Resolved by replacing `→` with `->` in logging output.
    *   **Readiness Probe Timeout Delay**: Originally, readiness probes timed out at 3s per service. When multiple services were down, this could cause the `/ready` HTTP request to stall for over 9 seconds. Resolved by reducing individual connection timeouts to 1s.

---

## Session 3: Storage Layer
*   **Completed**: 2026-06-23
*   **Target**: Implement durable storage and caching layers using raw, non-blocking drivers, and wire them to the DI container.
*   **Steps Completed**:
    *   Created `ValkeyAdapter` in `src/adapters/cache/valkey.py` using `redis.asyncio` for keys, TTLs, and sliding windows.
    *   Created `PostgresAdapter` in `src/adapters/store/postgres.py` using raw `asyncpg` for high-throughput persistence.
    *   Implemented automatic table bootstrapping on first query inside `PostgresAdapter` to dynamically create:
        *   `sessions`, `messages`, `turns` (with JSONB retrieved chunks/feedback), `agent_sessions`, `documents`, `artifacts`, and `connector_credentials` tables.
    *   Wired `PostgresAdapter` and `ValkeyAdapter` into `src/config/di.py`.
    *   Upgraded `/ready` route to probe health using the DI container's active connection pools.
    *   Verified functionality with an integration script testing full CRUD and serialization roundtrips against live containers.
*   **Issues Faced & Resolved**:
    *   **Pydantic Namespace Conflict**: Pydantic v2 raised a `UserWarning` warning that configuration fields starting with `model_` (like `model_server_host` and `model_server_port`) conflict with internal protected namespaces. Resolved by adding `protected_namespaces = ('settings_')` to the `Settings` model config.
    *   **System Python Import Error (`ModuleNotFoundError`)**: Attempting to run uvicorn globally picked up the Windows Store Python installation instead of the virtual environment (`.venv`) created by `uv sync`, leading to missing dependencies like `opentelemetry`. Resolved by switching execution to `uv run uvicorn` or explicitly activating the `.venv` first.

---

## Session 4: Retrieval Layer
*   **Completed**: 2026-06-23
*   **Target**: Implement Qdrant hybrid search, Reciprocal Rank Fusion (RRF), payload-level PermissionScope filters, and the async gRPC embedding sidecar client.
*   **Steps Completed**:
    *   Defined the gRPC service definition in `src/adapters/retriever/model_server/proto/embedding.proto`.
    *   Compiled the protobuf file to Python stubs using `grpcio-tools`.
    *   Implemented the async gRPC embedding client `embed_client.py` and reranker stub `rerank_client.py`.
    *   Created `QdrantRetrieverAdapter` in `src/adapters/retriever/qdrant.py` implementing hybrid prefetch search (dense + sparse) fused with RRF, payload indexing, and `PermissionScope` gating.
    *   Created `SearchChunksUseCase` in `src/core/use_cases/retrieval/search_chunks.py`.
    *   Exposed the `/search` HTTP GET endpoint in `src/api/routes/search.py` and wired request/response schemas.
    *   Wired `QdrantRetrieverAdapter` in `src/config/di.py` and registered the new route in `src/api/main.py`.
    *   Gracefully closed active database connection pools and gRPC channels during lifespan shutdown in `api/main.py` (following production-grade connection lifecycle standards).
    *   Successfully verified search constraints and security boundaries via a test integration script.
*   **Issues Faced & Resolved**:
    *   **Protobuf Path Import Issue**: Standard protobuf compilation created relative imports (`import embedding_pb2`) which fail when `PYTHONPATH` points to `src`. Resolved by re-compiling with `-Isrc` root parameter to produce absolute module imports.
    *   **TypeError on AsyncQdrantClient**: The client constructor in `qdrant-client` does not accept `grpc=bool` directly; it accepts `grpc_port=int` and `prefer_grpc=bool`. Resolved by updating client instantiation arguments in the adapter and tests.

---

## Session 5: Chat Pipeline (SSE Streaming RAG)
*   **Date**: 2026-06-23
*   **Commit message**: `feat(chat): full RAG chat pipeline — Bedrock SSE streaming, session management, Valkey caching, turn persistence`
*   **Steps Completed**:
    *   Implemented `BedrockAdapter` in `src/adapters/llm/bedrock.py`:
        *   Uses `aioboto3` with Bedrock Converse API (single-shot) and ConverseStream API (token-delta streaming).
        *   **Mock mode**: if `AWS_ACCESS_KEY_ID` is unset, the adapter logs a warning and yields a pre-baked string word-by-word with a 30ms inter-word delay — enables integration tests without live Bedrock credentials.
        *   `aioboto3` is imported lazily inside the method body to prevent import-time failures in mock mode.
    *   Implemented `ManageSessionUseCase` in `src/core/use_cases/chat/manage_session.py`:
        *   `get_or_create_session`: fast-paths via Valkey (`session:{id}`), falls back to Postgres `get_session`, creates on miss.
        *   `hydrate_history`: caches `session:{id}:history` in Valkey with a 2-hour sliding TTL; invalidated after each Turn is appended.
        *   `refresh_session_cache`: updates the session cache with a configurable sliding TTL.
    *   Implemented `SendChatMessageUseCase` in `src/core/use_cases/chat/send_message.py`:
        *   Async generator (`async def execute ... yield`) — the SSE controller iterates it directly.
        *   Pipeline: cache probe → embed (gRPC) → hybrid search (Qdrant) → system prompt construction → `LLMPort.stream()` → yield tokens → `StorePort.append_turn()` → cache response → evict history cache.
        *   Graceful degradation: embedding failures and retrieval failures are caught, logged, and the pipeline continues (embedding failure yields a single error token; retrieval failure yields empty context).
    *   Created Pydantic schemas in `src/api/schemas/chat.py`: `ChatMessageRequest`, `SessionOut`, `MessageOut`, `HistoryOut`.
    *   Implemented chat HTTP routes in `src/api/routes/chat.py`:
        *   `POST /chat` → 201 create session.
        *   `GET /chat` → list sessions for tenant/subject.
        *   `GET /chat/{session_id}/history` → up to 20 messages.
        *   `POST /chat/{session_id}/message` → `StreamingResponse` (text/event-stream). Each token is `data: <token>\n\n`; stream ends with `data: [DONE]\n\n`. Sets `X-Accel-Buffering: no` for nginx compatibility.
    *   Wired `BedrockAdapter` in `src/config/di.py` (replaced `AdapterNotWired` stub).
    *   Registered `chat_router` in `src/api/main.py`.
*   **Verification**:
    *   `uv run python -c "from api.main import create_app; create_app(); print('Import OK')"` → **Import OK**.
    *   Full integration test (`test_chat_mock.py`) with live server:
        *   Session created → Postgres row inserted, Valkey cache populated.
        *   SSE stream: BedrockAdapter detected no AWS key → MOCK mode; gRPC embed unavailable → graceful fallback token streamed → `[DONE]` sentinel sent.
        *   History GET returned 200.
*   **Issues Faced & Resolved**:
    *   **Async generator cannot be returned from coroutine**: Initial design had `execute()` return `self._pipeline(...)` (a second async generator). Python async generators cannot be returned by a regular coroutine and used with `async for`; the indirection caused a type mismatch. Resolved by making `execute()` itself an async generator (removed the `_pipeline` wrapper).
    *   **JWT secret mismatch in test**: Test had a hardcoded `dev-secret-key`; `.env` uses `change-me-dev-only-not-for-prod`. Fixed test to read from `.env` values.
    *   **Windows cp1252 encode error**: Unicode checkmark (`✓`) in `print()` raised `UnicodeEncodeError` on Windows. Fixed with `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")`.
    *   **Support for Temporary AWS Credentials**: Local dev profiles using IAM Roles/SSO generate temporary access keys (starting with `ASIA...`) requiring `AWS_SESSION_TOKEN`. Added `aws_session_token` to `Settings` and forwarded it in `BedrockAdapter._make_boto_kwargs()`.
    *   **Bedrock Model ID ValidationException**: Calling Llama/Claude model IDs on-demand directly yielded a throughput exception. Resolved by switching settings to point to regional Cross-Region Inference Profile IDs (prefixed with `us.`).
    *   **Critical Caching Permission Leak**: Fixed response cache leaking data across permission boundaries by hashing the sorted set of active permissions alongside the query and tenant ID in `_build_cache_key`.
    *   **Multi-Turn Caching & Conversation Context**: Fixed dialogue context risks by restricting response cache lookup and caching only to single-turn chats (`len(history) == 0`).
    *   **Cache Hit History/Turn Gaps**: Ensured that a cache hit still writes the `Turn` to Postgres to avoid missing gaps in conversational history.
    *   **Fail-Closed Retrieval & Embedding Errors**: Replaced silent open degradation (falling back to parametric hallucinated output) with strict exception throwing (fail-closed) when Qdrant search or embedding is offline.
    *   **EventSource Error Streaming**: Modified routes (`chat.py`) to yield formatted SSE `event: error\ndata: <message>\n\n` frames, allowing frontend clients to distinguish errors from regular token outputs.
    *   **Public Documents Gating Lockout**: Fixed the Qdrant retriever's permission matching to automatically append a fallback `"public"` permission, allowing documents tagged as public to be retrieved by all authorized tenant users.
    *   **Pytest Suite Initialization**: Set up `src/tests/__init__.py` and `src/tests/test_chat_security.py` with 4 comprehensive async unit tests for permission hashing, cache hit/miss rules, and fail-closed RAG behavior.

---

## Session 6: Agent Loop & A2A Interop
*   **Completed**: 2026-06-24
*   **Target**: Implement the agentic Map-Reduce execution loop using LangGraph, support SSE streaming of thoughts/deltas, and set up A2A registry stubs.
*   **Steps Completed**:
    *   **LangGraph Agent Loop (`langgraph_runner.py`)**:
        - Created a `StateGraph` running a Map-Reduce flow: parallel log/code/ticket workers fanning out via `Send` calls and fanning in to a LLM-based synthesizer.
        - Used a list reducer (`operator.add` on `sub_agent_results`) to accumulate results across concurrent worker nodes without data loss.
        - Enforced iteration guard `settings.agent_max_iterations` to route directly to synthesizer and flag truncation rather than raising exception or looping infinitely.
        - Isolated worker failures inside try-except blocks, returning a failed `WorkerResult` state rather than failing the entire LangGraph execution.
        - Passed an `asyncio.Queue` inside `RunnableConfig` for node functions to stream thought/status messages during execution.
        - Implemented `interrupt()` and `terminate()` mapping to task cancel and local session interrupt flags for cooperative cancellation.
    *   **A2A Subsystem Stubs**:
        - Defined wire schemas for agent-to-agent protocol in `src/adapters/agent/a2a/protocol.py`.
        - Created a protocol-compatible registry stub in `src/adapters/agent/a2a/registry.py` for future activation.
    *   **Use Cases & HTTP Router**:
        - Added `RunAgentUseCase` to manage the session lifecycle, execute the graph, handle cancellation, and yield SSE-compliant events (`thought`, `worker_start`, `worker_done`, `synthesis`, `output`, `done`).
        - Added `ManageArtifactsUseCase` for artifact CRUD plumbing.
        - Added `/agent/run` and `/agent/{session_id}/interrupt` endpoints in `src/api/routes/agent.py`.
        - Bound adapter in `src/config/di.py` and registered routes in `src/api/main.py`.
    *   **Verification**:
        - Added pytest suite `src/tests/test_agent_mock.py` containing 4 tests validating the iteration cap, state fanning/reducers, worker failure isolation, and session cancellation.
        - Created an integration client `scratch/test_agent_sse_live.py` verifying full token stream parsing and SSE format.
        - Cleaned all Ruff violations (`E501` line length, unused `datetime` imports, sorted imports, and replaced `asyncio.TimeoutError` alias with built-in `TimeoutError`).
*   **Issues Faced & Resolved**:
    *   **LangGraph Node Config Binding**: Config annotation in node functions must be `RunnableConfig` from `langchain_core.runnables` (using `dict[str, Any]` raises `TypeError`).
    *   **LangGraph 1.x Send Import**: Importing `Send` from `langgraph.constants` is deprecated; must import from `langgraph.types`.
    *   **Ruff Line Length E501**: Long text inputs and dictionary items exceeded the 100-character line-length threshold. Resolved by splitting lines, extracting temporary variables, and multi-line wrapping in `langgraph_runner.py`.

---

## Session 7: Security hardening — JWT issuer (`iss`) validation — 2026-06-27
*   **Trigger (review feedback)**: "JWT auth doesn't validate `iss`. The `jwt.decode` call passes `audience` but not `issuer`. The `JWT_ISSUER` setting exists but isn't used in `AuthMiddleware`. Easy fix but a real gap."
*   **Fix**:
    *   `AuthMiddleware.__init__` now takes an `issuer` param; `jwt.decode(...)` passes `issuer=self._issuer` plus `options={"require": ["iss", "aud"]}` so a wrong issuer (`InvalidIssuerError`) and a missing `iss`/`aud` (`MissingRequiredClaimError`) are both rejected — both subclasses of `InvalidTokenError`, already mapped to **401**. Fails closed.
    *   `src/api/main.py` passes `issuer=settings.jwt_issuer` into the middleware (the setting existed and was previously dead).
*   **Regression test (new `src/tests/test_auth.py`)**: spins a minimal Starlette app behind `AuthMiddleware` + `TestClient`, signs tokens with PyJWT. Asserts: valid `iss` -> 200 + scope; wrong `iss` -> 401; missing `iss` -> 401; wrong `aud` -> 401; no Bearer header -> 401. This is the first direct test of `AuthMiddleware` (previously untested).
*   **Verification**: `uv run pytest src/tests/ -q` -> **15 passed**. New file ruff-clean.

---

## Session 8: Wire the Prompt Guard — input screening on both user-facing entry points — 2026-06-27
*   **Trigger**: "wire the prompt guard." The Prompt Guard sidecar was built and validated standalone (frozen contract `POST /guard {text} -> {label, score, blocked}`, `GET /health`), and `GUARD_ENABLED` / `GUARD_GATEWAY_URL` settings existed, but **nothing in `src/` ever called it** — chat and agent sent raw user input straight to retrieval/LLM/agent. This wires the first line of defence.
*   **Decisions (user-confirmed)**:
    *   **Fail-closed.** If the guard blocks *or* screening can't complete (sidecar down/timeout), the request is refused — consistent with how embed/retrieval already fail-closed in the same chat use case. A down guard means no chat, by design.
    *   **"Chat" = both user-facing front doors.** Screen the RAG chat endpoint **and** the agent endpoint. Both are reachable from the UI; both get a preliminary guard on the inbound user text.
    *   **Classify-only stays in the sidecar; the product decision lives in the Core API.** The port returns a verdict; the use case decides refuse/allow. Threshold remains a sidecar concern.
*   **Hexagonal wiring (port → adapter → DI → use case, no boundary violations — `test_architecture.py` still green)**:
    *   **Domain VO** `core/domain/value_objects/guard_verdict.py`: frozen `GuardVerdict(label, score, blocked)` with `.allow()` / `.refuse()` factories.
    *   **Port** `core/ports/guard.py`: `GuardPort` Protocol — `async screen(text) -> GuardVerdict` + `async close()`.
    *   **Adapters** `adapters/guard/`: `HttpGuardAdapter` (httpx `AsyncClient`, tight `Timeout(5.0, connect=2.0)`, maps JSON → verdict, **raises** on transport/HTTP error — does not swallow); `NullGuardAdapter` (always-allow, logged warning) bound when `GUARD_ENABLED=false` so use cases call `screen()` unconditionally.
    *   **DI** `config/di.py`: `Container.guard` returns the HTTP adapter when enabled, else the null adapter. `main.py` closes the httpx client on shutdown (mirrors store/retriever).
    *   **Chat** (`use_cases/chat/send_message.py`): screen `query` as **step 0**, before the cache probe — a malicious query never touches cache, retrieval, or the LLM. Blocked/fail-closed → log + yield a fixed refusal string + `return`. No persistence of blocked turns.
    *   **Agent** (`use_cases/agent/run_agent.py`): screen `prompt` at the top of `execute()`, **before** the `AgentSession` is created or any state is written. Blocked → return a single-event `_refusal_stream()` emitting an `output` event with the refusal (route appends `done`); the agent loop never starts.
*   **Verification**: new `src/tests/test_guard.py` (7 tests): adapter maps malicious response, adapter raises on HTTP 500, null guard allows, chat blocks before pipeline (no cache/embed/llm calls), chat fails closed on guard exception, agent refuses before run (no session/`agent.run`). Updated the 3 chat + 2 agent use-case construction sites in existing tests with a benign-guard mock (a bare `AsyncMock` would return a truthy `.blocked` and wrongly block everything). `uv run pytest src/tests -q` -> **21 passed**; new files ruff-clean (pre-existing lint debt in touched files left out of scope, as before).
*   **Deliberately out of scope (future, per DDs)**: retrieved-content / RAG-corpus scanning is **ingest-time** (DD-13, ingestion worker) — not this input-screening layer. Layer-0 system-prompt hardening, taint/PDP/trajectory monitoring remain design-only. The guard is input screening, not the action-layer control.

---

## Session 9: Layer-0 prompt hardening — frame retrieved context as untrusted data — 2026-06-27
*   **Trigger**: DD-13 Layer 0. The prompt guard (Session 8) screens the *user's query* but does nothing about *indirect* injection via a poisoned corpus — the retrieved chunks. `_SYSTEM_PROMPT_TEMPLATE` injected context under a bare `CONTEXT:` label with no "this is data, not instructions" framing. Cheapest, highest-ROI structural defense against indirect injection.
*   **Change** (`use_cases/chat/send_message.py`): the context block is now wrapped in explicit `BEGIN/END CONTEXT (untrusted data)` markers (datamarking / structural separation) with an instruction to treat anything that looks like a command inside it as data and never act on it. No behavioral/code-path change — prompt text only.
*   **Regression guard** (`test_chat_security.py::test_system_prompt_marks_context_as_untrusted`): asserts the rendered system prompt contains the untrusted framing + begin/end markers, so the hardening can't silently regress. (Input-screening *bypass* is already covered by `test_guard.py`'s blocked-before-pipeline tests.)
*   **Verification**: `uv run pytest src/tests/test_chat_security.py -q` -> **5 passed**. Touched files add no new ruff findings (pre-existing debt left out of scope).

---

## Session 10: Policy Decision Point (DD-8) — the action chokepoint, in core — 2026-06-28
*   **Trigger**: "Plan A" — the highest-leverage, fully non-blocking security build. DD-7's action-layer security was entirely on paper (`MCPConnectorPort` has no adapter/caller). This implements the deterministic, default-deny PDP that converts "we have a security philosophy" into "a poisoned agent physically cannot mutate prod" — pure core logic, no external deps.
*   **Built** (hexagonal — domain + port + use-case, `test_architecture.py` still green):
    *   **`core/domain/policy/types.py`** — `Effect` / `Reversibility` / `DecisionEffect` enums; `ToolPolicy` (per-tool contract: required perms, allowed environments, **bounded params** `max_items`, **flow gating** `allowed_data_sources`, reversibility); `CanonicalTarget`; `ActionRequest` (carries `model_supplied_target` we never trust, `parent_scope` for delegation, `taint_level` as a signal); `Decision`; `PolicyRegistry` (absence ⇒ default-deny).
    *   **`core/ports/target_resolver.py`** — `TargetResolverPort`: resolves the real adapter-bound target so the PDP never trusts a model label.
    *   **`core/use_cases/policy/policy_decision_point.py`** — deterministic `decide()`. Rule order (first failure wins): unknown-tool → scope perms → **delegation attenuation** (scope may only narrow) → canonical target (unresolved / **model-label spoof** / kind / environment) → **flow gating** (read-source × write-sink) → **bounded params** → **reversibility/approval** (DD-12) → **taint friction** (DD-9). Mutating allows carry a `mint_capability` obligation (DD-10 hook).
*   **The two pressure-tested invariants, encoded**: (DD-8) the allow never depends on the model being honest — canonical-target resolution + spoof rejection; (DD-9) taint only ever escalates ALLOW→REQUIRE_APPROVAL and **can never flip a DENY into an ALLOW** — asserted directly by `test_taint_never_turns_a_deny_into_an_allow`.
*   **Enforcement (DD-8 check, now real)**: `src/tests/test_pdp_chokepoint.py` — a static, `test_architecture`-style guard that **no module invokes a write-capable tool (`.call_tool(`) outside a PDP-guarded allowlist** (empty today ⇒ zero bypasses; fails the instant someone wires tool execution without the PDP). Plus a behavioral default-deny check.
*   **Verification**: 17 PDP rule tests + 2 chokepoint tests; `uv run pytest src/tests -q` -> **48 passed**; new files ruff-clean. DD-8 enforcement line in `design-decisions.md` updated to "Implemented (core, no caller yet)".
*   **Deliberately out of scope** (separate components; PDP is correct without them by design): credential broker (DD-10 minting), trajectory monitor (DD-11, stateful session risk — the answer to the *slow* attack), approval workflow backend (DD-12 — PDP only consumes a token), and the PDP-guarded MCP adapter that will be its first caller when agent tools land.

---

## Session 11: Trajectory monitor + cumulative session risk (DD-11) — the slow-attack answer — 2026-06-28
*   **Trigger**: DD-11. The PDP (Session 10) is stateless by construction — it clears each action in isolation, so a *chain* of individually-allowed actions (slow context poisoning, gradual privilege elevation, read-then-exfiltrate) walks straight past it. This is the independent, **stateful** complement.
*   **Built** (pure core — domain + use-case):
    *   **`core/domain/policy/trajectory.py`** — `ActionEvent` (recorded by the runtime after each PDP decision), `RiskLevel` (OK → THROTTLE → REQUIRE_APPROVAL → KILL), `TrajectoryVerdict`, `SessionRiskState` (serializable per-session accumulator), tunable `RiskWeights` / `RiskThresholds`.
    *   **`core/use_cases/policy/trajectory_monitor.py`** — `TrajectoryMonitor.observe(session_id, event)` accumulates **session-level** (not per-message) risk. Signals: **mutating-drift** (recent window mutating-dense), **read-then-exfiltrate** (prior sensitive read + now an external-sourced mutating write), **elevation-gradient** (mutating action in a higher env than seen before), **privilege-growth** (needs a not-seen-before permission), **probing** (PDP returned deny/require-approval). Crossing a threshold → throttle / re-approval / kill (`agent_reaper` hook).
*   **The DD-8 vs DD-11 split, made concrete**: DD-8 stops the single catastrophic action; DD-11 stops the slow accumulation. `test_thousand_small_cuts_trips_monitor_though_each_passes_pdp` runs every action through the **real PDP** (asserting `ALLOW` each time) while the monitor climbs to **KILL** — the enforcement check that proves neither control alone is sufficient.
*   **Design fidelity (DD-9)**: the monitor consumes provenance/taint as a *risk input* (read-then-exfil, external-source writes), never as a hard gate — consistent with "taint is a signal." A bulk read of *sensitive* data is a mild signal by design; reads of non-sensitive data are free.
*   **Verification**: 9 trajectory tests; `uv run pytest src/tests -q` -> **57 passed**; new files ruff-clean. DD-11 enforcement line updated to "Implemented (core, no caller yet)".
*   **Deliberately out of scope**: Redis-backed `SessionRiskStore` (in-memory now; `SessionRiskState` is serializable for the future port), Phoenix spans, and the agent-runtime caller that enforces the verdict.

---

## Session 12: coverage + lint hygiene — 2026-06-28
*   **New unit tests** (targeting load-bearing logic that was only covered indirectly):
    *   `test_permission_scope.py` (8) — the security-boundary VO had **zero** direct tests. Covers `has`/`has_any`/`has_all`/`require` and the critical `from_claims` JWT parsing: happy path, **missing/empty `tenant_id` → `PermissionDenied`** (the tenant-isolation failure mode), malformed `permissions` → empty (no accidental grant), absent subject, frozen immutability.
*   **Lint hygiene** (whole `src`): no critical/bug findings (no F821/F811/F841/syntax). Cleaned 48 — 46 ruff autofixes (unused imports, import order, `datetime.UTC`, deprecated imports) + 2 `B904` by hand (proper `raise … from exc` in the agent-interrupt and search routes, preserving the original traceback). Remaining 29 E501 + 3 RUF are cosmetic, left as-is.
*   **Verification**: `uv run pytest src/tests -q` -> **65 passed** (was 57). (Ingestion-worker coverage logged separately.)

---

## Session 13: MCP layer — PDP-guarded connector, the first real caller of DD-8 + DD-11 — 2026-06-28
*   **Trigger**: the action-layer security (PDP, Session 10; trajectory monitor, Session 11) was *core, no caller* — the chokepoint allowlist was empty and nothing executed a tool. This builds the MCP connector as that first caller, turning the philosophy load-bearing.
*   **Built** (`src/adapters/mcp/`, hexagonal — adapter implements `MCPConnectorPort`, `test_architecture.py` green):
    *   **`tools/{servicenow,confluence,github,zendesk}.py` + `tools/base.py`** — one `ToolSpec` per read-only tool. A spec yields *both* its `list_tools` view (`describe()`) and its PDP `ToolPolicy` (`to_policy()`), so display and policy can't drift. `id_arg` names the argument the resolver reads for the canonical target.
    *   **`catalog.py`** — `ToolCatalog`: `policy_registry()` (PDP registry; a tool absent here is default-denied), scope-filtered `list_for_scope()`, name→server/spec lookup.
    *   **`transport.py`** — `MCPTransportPort` + `MockMCPTransport` (canned results, no live servers — mirrors Bedrock mock mode). The raw, **unguarded** execution seam; the only place a tool is actually invoked.
    *   **`target_resolver.py`** — `McpTargetResolver` (DD-8 canonical targets): builds the real target from the spec's `target_kind` + the id in arguments, bound to the connector's environment; missing id / unknown tool → `None` → PDP default-deny.
    *   **`connector.py`** — `PdpGuardedMCPConnector`, **the chokepoint**. Every `call_tool`: `PDP.decide()` → `TrajectoryMonitor.observe()` (fed on *every* decision, so denies accrue "probing") → enforce **KILL > deny > require-approval > proceed** → only then `transport.call_tool()`. Denied → `PolicyViolation`; KILL trajectory → `TrajectoryKill`. Sole module on the chokepoint allowlist.
*   **Wiring**: `config/di.py` builds the connector (catalog → PDP + monitor + resolver + mock transport; `mcp_enabled=false` ⇒ empty catalog ⇒ default-deny everything, not a hard error). `MCP_ENABLED`/`MCP_MOCK_MODE` settings added. `main.py` closes the connector on shutdown.
*   **Two small, documented decisions**: (1) `MCPConnectorPort.call_tool` gained an optional `session_id` so DD-11 can key per-session risk (falls back to subject/tenant); (2) `+ close()` on the port for lifecycle symmetry. Captured as **DD-14**.
*   **Enforcement made real**: `test_pdp_chokepoint.py` allowlist flipped from `{}` to `{adapters/mcp/connector.py}` — the static guard now protects a *live* path (anyone wiring `.call_tool(` elsewhere without the PDP fails the build).
*   **Verification**: new `src/tests/test_mcp.py` (9) exercises the **real** PDP + monitor + catalog + resolver (only the transport is a spy): scope-filtered listing; in-scope read ALLOW reaches transport; unknown-tool / missing-perm / unresolvable-target denied **before** transport; a denied call accrues probing risk; a **KILL verdict vetoes a PDP-allowed action**; session_id→subject fallback; catalog↔policy lockstep. `uv run pytest src/tests -q` -> **74 passed**; new files ruff-clean.
*   **Deliberately out of scope**: `api/routes/mcp.py` (no HTTP front door yet — keeps the chokepoint allowlist = exactly the connector; the agent runtime becomes the caller when agent tools land), real `ClientSession` transport (smoke-tests **ST-3**), and the still-future DD-10 credential broker / DD-12 approval backend / Redis `SessionRiskStore` / Phoenix spans.

---

## Session 14: Agent runtime is the chokepoint's runtime caller + reaper hook on KILL — 2026-06-28
*   **Trigger**: Session 13 built the chokepoint but *nothing in the running app called it* — DD-8/DD-11 were guarding a path with no traffic. This wires the agent runtime through it (their first **runtime** caller) and closes the DD-11 loop with the `agent_reaper`.
*   **#1 — Agent → connector**: `LangGraphRunner` now takes `mcp: MCPConnectorPort` + `kill_registry`. The `scope` flows into the graph config; the **code** and **ticket** workers fetch through `self._mcp.call_tool(... session_id=agent_session_id ...)` (so DD-11 keys per agent-session) via a shared `_fetch_via_mcp` helper. Per-worker outcome handling: `PolicyViolation` → that worker degrades (`success=False`) and the run continues; `TrajectoryKill` is **re-raised** (cumulative risk is fatal to the session, not one source); transport/network errors are isolated. `mcp`/`scope` absent (unit tests) → simulated fallback. The **log** worker stays simulated — no phase-1 MCP tool for logs (a Loki/CloudWatch connector is FUTURE).
*   **#2 — Reaper hook on KILL**: new `core/domain/agent_control.py::AgentKillRegistry` — the in-process hand-off between the runner (records the killed session) and the `agent_reaper` daemon (drains it, calls `agent.terminate()` as a backstop). On a `TrajectoryKill` the runner emits a terminal `event: killed` (so the client learns *why*) and records the session; `RunAgentUseCase` maps it to the new `AgentStatus.KILLED` and ends the stream cleanly (deliberate verdict, not an orchestrator failure). `start_daemons(settings, *, agent, kill_registry)` now receives both from the container.
*   **One design decision (DD-15)**: routing the runner through the connector adds a *second* `.call_tool(` site, which the static chokepoint guard would flag. Resolved with a **two-tier allowlist** — `connector.py` (calls the raw transport, PDP-first) **+** `langgraph_runner.py` (calls the *connector port*, which IS the PDP entry; DI never hands it the raw transport, so it structurally cannot bypass). The guard still fails on any *new* `.call_tool(` site.
*   **Wiring**: `di.py` adds a shared `agent_kill_registry` and injects `mcp=self.mcp` + the registry into the runner; `main.py` builds `container.agent` at startup (fails fast on a mis-wired chokepoint) and passes agent + registry to `start_daemons`.
*   **Verification**: new `src/tests/test_agent_mcp_wiring.py` (5) — in-scope workers reach the transport; an under-scoped worker is PDP-denied yet the run completes; a KILL emits `killed` + records the session + never hits the transport; `RunAgentUseCase` persists `KILLED`; the reaper drains the registry and calls `terminate()`. `uv run pytest src/tests -q` -> **79 passed**; changed files ruff-clean; DI + app-factory smoke-checked.
*   **Deliberately out of scope**: real `ClientSession` transport (ST-3), `api/routes/mcp.py`, DD-10 credential broker / DD-12 approval backend, Redis-backed `SessionRiskStore`, Phoenix spans.

---

## Session 15: DD-11 risk persisted to Valkey — cross-worker / restart-safe — 2026-06-28
*   **Trigger**: `TrajectoryMonitor` held cumulative risk **in-process** — lost on restart and not shared across workers, so a horizontally-scaled deploy silently defeated DD-11 (the slow attack just spreads calls across processes). `SessionRiskState` was already serializable for this.
*   **Built**:
    *   **`core/domain/policy/trajectory.py`** — `SessionRiskState.to_dict()/from_dict()` (handles the `deque[Effect]` + `set` fields) — the "serializable" promise made real.
    *   **`core/ports/session_risk_store.py`** — `SessionRiskStorePort` (async `load`/`save`/`delete`).
    *   **`adapters/policy/session_risk_store.py`** — `ValkeySessionRiskStore` over the existing `CachePort` (no second Redis client): JSON under `risk:{session_id}` with a TTL = agent-session window.
    *   **`TrajectoryMonitor`** — gains optional `store`; sync `observe`/`risk`/`reset` **unchanged** (existing tests untouched); new **`observe_async`** hydrates from the store → scores → writes back, and **`forget`** clears both tiers. The connector now calls `observe_async`.
*   **Two decisions**: **(a) fail-soft** — a Valkey outage degrades to in-process accumulation (a weaker DD-11) and **never** raises on the action path; security is not bypassed (in-proc still accrues), only cross-worker sharing is lost. **(b) load→modify→save is not atomic** (DD-16): within one agent session tool calls are sequential, so it's sufficient for the threat model; a Lua CAS is FUTURE. Off-switch: `RISK_STORE_ENABLED` (in-process only).
*   **Wiring**: `di.py` builds `ValkeySessionRiskStore(self.cache, ttl=...)` and injects it into the monitor when `risk_store_enabled`; `RISK_STORE_ENABLED` / `RISK_STORE_TTL_SECONDS` settings + `.env.example`.
*   **Verification**: new `test_session_risk_store.py` (4) — state round-trip; store save/load/delete over a fake cache; **two monitor instances sharing one backend accumulate across "workers"** (no cross-session bleed); a `FailingCache` proves fail-soft. `uv run pytest src/tests -q` -> **83 passed**; changed files ruff-clean; DI + app-factory smoke-checked.
*   **Out of scope**: atomic CAS for concurrent same-session writers, wiring `forget` into the `agent_reaper` on kill (trivial follow-up), Phoenix spans.

---

## Session 16: DD-13 Layer 0 — datamarked, spoof-resistant RAG context block — 2026-06-28
*   **Trigger**: the untrusted-context *framing* already existed in `send_message.py` (+ a regression test), but the structural gate had a real hole: a retrieved chunk containing the literal `----- END CONTEXT -----` line (or a bare dashed rule) could **close the block early** and have everything after it read as trusted instructions. DD-13 calls for a *datamarked* block — that part wasn't built.
*   **Built** (`core/use_cases/chat/send_message.py`):
    *   `_neutralize_delimiters(text)` — defangs any chunk line that mimics the begin/end markers or is a bare dashed rule (replaced with a placeholder), so a passage can't forge the boundary.
    *   `_format_context(chunks)` — renders each chunk **neutralized + datamarked**: every context line is prefixed with a sentinel (`│ `) the system prompt tells the model to trust; text not so prefixed (or mimicking markers) is not trusted context. Replaces the old inline `[{i}] {text}` join.
    *   System prompt template now built from `_CTX_BEGIN/_CTX_END/_DATAMARK` constants (kept in sync) and explains the datamark rule.
*   **Why neutralize *and* datamark**: structure is the primary gate (DD-13), but a delimiter you can spoof isn't structure. Neutralization removes the spoof; datamarking gives the model a positive signal for "this region is data." Injected instructions still appear — but inside the block, datamarked, as data.
*   **Tradeoff**: a legit bare-dashed line (markdown rule) in a chunk is replaced with a placeholder — rare, low harm, worth it for a spoof-proof boundary.
*   **Verification**: `test_chat_security.py` +3 — every context line carries the datamark; a chunk embedding the END marker leaves exactly **one** real closing marker in the rendered prompt (forgery defanged) while the injected instruction survives *as data*; a bare dashed rule is removed. `uv run pytest src/tests -q` -> **86 passed**. (Two pre-existing E501/RUF005 in untouched lines left per the Session 12 cosmetic-backlog decision.)
*   **Out of scope**: DD-13 Layer 1 (ingest-time screening — ingestion worker) and Layer 2 (consume the stored `injection_risk` flag at retrieval: down-rank + ⚠-mark flagged chunks) — separate work on the retrieval/ingestion paths.

---

## Session 17: Full session observability — Arize Phoenix adapter (OpenInference + OTel) — 2026-06-28
*   **Goal**: full session observability via an Arize Phoenix adapter using the *server's* feature set (traces, Sessions, evals, datasets, embedding drift/UMAP) — but architecturally swappable: switching to Langfuse must be "write an adapter + rewire DI," nothing in `core`.
*   **Seam (the portability contract)** — rewrote `core/ports/observability.py` as a **vendor-neutral** port: `SpanKind`, `ObsAttr` (neutral attribute vocabulary), an `ObsSpan` handle (mid-span enrichment), and `span()/record_eval/curate_dataset/get_traces/get_evals/get_datasets/drift_check/close`. `core` and use-cases speak only this; **no OpenInference/OTel/Phoenix import in `core`**. The Phoenix adapter translates neutral→OpenInference; a future `adapters/observability/langfuse/` would translate neutral→Langfuse.
*   **Lightweight, no embedded server** — Phoenix runs as the Docker container (the *server*). We add only `arize-phoenix-client` + `openinference-semantic-conventions` + `openinference-instrumentation` (no heavy `arize-phoenix`, no pandas, no `px.launch_app()`). Decided after confirming UMAP/embedding-drift are *server* features unlocked by attaching embedding vectors to spans, not by the pip package.
*   **Built**:
    *   `adapters/observability/phoenix/` — `semconv.py` (neutral→OpenInference; flattens messages/documents/embeddings; literal keys, drift-guarded against the installed constants by a test), `tracing.py` (OTel span over the existing provider, `using_attributes` session propagation, accumulates neutral attrs for exit-time metric/drift derivation), `drift.py` (Valkey running-centroid tracker), `client.py` (the adapter: spans + `AsyncClient` read/eval/dataset + drift; **fail-soft everywhere**).
    *   `observability/` shared, neutral — `metrics.py` (OTel counters/histograms: PDP decisions, trajectory risk/kills, guard blocks, tokens, eval scores — derived from span attrs), `drift.py` (pure centroid Euclidean/cosine + PSI, Phoenix-documented methodology), `otel.py` extended with an opt-in Bedrock+LangChain/LangGraph auto-instrumentation toggle attached to *our* provider.
    *   `adapters/observability/noop.py` — safe default when `OTEL_ENABLED=false` (mirrors `NullGuardAdapter`).
    *   `core/use_cases/observability/` — `evaluate_turn.py` (LLM-judge panel mirroring Phoenix's Hallucination/QA Correctness/Relevance/Toxicity templates — single-word rails, explanation-before-label, temp 0, rail→{0,1}; judges via our `LLMPort`, **no `arize-phoenix-evals`/pandas**) + `get_phoenix_data.py` (read facade).
    *   `api/routes/observability.py` (+ schema) — `GET /observability/{traces,evals,datasets,drift}` and `POST /feedback` (human annotation, `annotator_kind=HUMAN`).
*   **Producer instrumentation** (all via the port, fail-soft, obs optional so existing tests stay obs-free):
    *   MCP connector — one `TOOL` span per `call_tool` carrying the **DD-8 decision + DD-11 risk/signals + target/env**; denied/killed calls record an ERROR span. No new transport path, so the chokepoint allowlist is unchanged.
    *   Chat pipeline — `chat.guard` (GUARDRAIL), `chat.embed` (EMBEDDING; the query vector feeds Phoenix's embedding/UMAP view **and** the drift signal), `chat.retrieval` (RETRIEVER + documents), `chat.llm` (LLM + output). All tagged `session.id`/`tenant.id`/`user.id` → Phoenix **Sessions** grouping. Captures the LLM span id and fires a **sampled** (`EVAL_SAMPLE_RATE`), fire-and-forget online eval — never blocks the stream.
    *   Agent runner — root `AGENT` span; the connector's per-tool spans nest under it (contextvars propagate into `create_task`).
*   **Settings/flags**: `PHOENIX_API_KEY`, `OTEL_AUTOINSTRUMENT` (extra: `autoinstrument`), `EVAL_ENABLED`, `EVAL_SAMPLE_RATE`. Project = `OTEL_SERVICE_NAME` (Phoenix routes spans to a project by the `openinference.project.name` resource attr — `otel.py` sets it == `OTEL_SERVICE_NAME`).
*   **Verification**: `test_observability.py` — semconv mapping + official-constant match, drift math + tracker (warm-up→baseline→drift, fail-soft), NoOp, Phoenix span emission via in-memory OTel exporter (OpenInference attrs + session id + mid-span enrichment), drift-feed from embedding span, eval rail parsing + 4-evaluator panel, connector TOOL span on allow/deny, chat pipeline spans + sampled eval scheduling. `uv run pytest src/tests -q` -> **104 passed**. New code ruff-clean (one pre-existing E501 in an untouched cache-hit line left per Session 12 backlog).
*   **Live verification (ST-4, run 2026-06-28 against a local Phoenix container)**: end-to-end **passed** — 6 spans with correct OpenInference kinds (AGENT/LLM/TOOL/RETRIEVER/EMBEDDING/GUARDRAIL) all grouped under one `session.id`; `record_eval` annotation attached + read back; `curate_dataset` created a dataset; `drift_check` returned `ok`. **Two fixes applied from the run**: (1) this Phoenix routes projects by `openinference.project.name`, not `service.name` — `otel.py` now sets both; (2) the dataset client wants `inputs=`/`outputs=`/`metadata=` iterables, not `examples=` — `curate_dataset` adapts.
*   **Still future**: eyeball the UMAP embedding view + auto-instrumentation in the UI (ST-4 items 4, 7); Experiments API; a Prometheus/collector scrape of the OTel metrics.

## Session 18: doc-sync + LOG_TO_FILE test — close the tests/logging build-plan items — 2026-06-29
*   **Trigger**: the build plan still listed "tests + logging" (Session 10) as open and the prompt-guard caller as deferred, but both had actually landed — the docs lagged the code. This session verifies, fills the one real gap (a logging test), and re-syncs the plan.
*   **Verified already-done**: the **Prompt Guard caller** is complete end-to-end (built in Session 8): `GuardPort` + `HttpGuardAdapter`/`NullGuardAdapter` + DI bind, fail-closed step-0 `screen()` in **both** `send_message` and `run_agent`, routes wire `container.guard`, lifespan closes the client. `test_guard.py` (6 tests) green. No code change needed.
*   **LOG_TO_FILE**: `_configure_logging` in `api/main.py` was already implemented (stdout handler always; optional `FileHandler` under `LOG_DIR/LOG_FILE` when `LOG_TO_FILE` true; `basicConfig(..., force=True)`) but had **no test**. Added `tests/test_logging.py` — asserts stdout-only when the flag is off (and no dir created) and a `FileHandler` + created dir when on; snapshots/restores the root logger so `force=True` doesn't leak handlers into the rest of the suite.
*   **Verification**: `uv run pytest src/tests -q` -> **106 passed** (104 + 2 logging); new test ruff-clean.
*   **Doc sync**: ticked the Session 10 build-plan boxes (tests + `LOG_TO_FILE`), added an explicit "Prompt Guard caller" done-line under Session 5, and updated the prompt-guard-sidecar build-plan banner to note the core-side caller is wired. No DD — no new architectural decision (fail-closed was decided in Session 8 / DD-7); this is plan↔code reconciliation. No smoke test — no live-service behavior beyond what ST-4 already covers.

## Session 19: surface the turn span_id on the chat SSE — unblock frontend feedback — 2026-06-29
*   **Trigger**: the SPA's 👍/👎 feedback (frontend F2/F4) needs the turn's trace span id to call `POST /feedback`, but `POST /chat/{id}/message` streamed bare tokens only — the `span_id` was captured internally (Session 17) and never exposed. This is the small backend addition F2 flagged as the blocker.
*   **Use case** (`core/use_cases/chat/send_message.py`): `execute()` gained an optional `on_span: Callable[[str], None] | None` callback, invoked **once** with the LLM span id the moment the `chat.llm` span opens (before the first token). Cache hits and guard refusals open no LLM span, so it is never called there. The yielded token stream is **byte-for-byte unchanged** — `on_span` is a side channel, not a new yield type — so the existing exact-token assertions still hold. No new import beyond `collections.abc.Callable`; no I/O, no port; the callback is pure notification, so the hexagonal invariants are untouched. (Also folded the long-standing E501 on the cache-hit `logger.error` line into a wrapped call while here.)
*   **Route** (`api/routes/chat.py`): the SSE generator passes `on_span=` a closure that stashes the id, then emits a one-shot **`event: meta\ndata: {"span_id": …}`** frame just before the first `data:` token. Distinct event name ⇒ the bare-token contract the FE relies on is preserved; clients that ignore `meta` are unaffected.
*   **Verification**: `uv run pytest src/tests -q` → **108 passed** (106 + 2 new). New tests in `test_observability.py`: `on_span` reports the span id **exactly once** with the token list intact, and is **not** called on a cache hit. Touched files ruff-clean; `mypy src` shows no new errors in the touched files (the repo's pre-existing mypy backlog is unchanged). No DD — additive, follows the DD-17 observability seam and DD-19 feedback plan. Live end-to-end (meta frame → feedback annotation in Phoenix) is **ST-F4** (`docs/smoke-tests.md`, PENDING).

## Session 20: unit-coverage backfill of the three untested use-cases — 2026-06-30
*   **Trigger**: a coverage sweep (`grep -rl <use-case> src/tests`) found three core use-cases with **zero** direct tests — `retrieval/search_chunks.py`, `chat/manage_session.py`, `agent/manage_artifacts.py`. The first is a security-spine surface (`/search` "enforces the identical scope as /chat"), so it was the priority. No production code changed — this session only adds tests.
*   **`test_search_chunks.py` (7 tests)**: the load-bearing assertion is **scope pass-through identity** — the exact `PermissionScope` object handed to `execute()` reaches `RetrieverPort.search()` unchanged (the use case must never widen/narrow/re-derive it, since the adapter turns it into the Qdrant payload filter). Plus: text is embedded once and the *vector* (not the text) is searched; `limit` → `top_k` (default 5); and embed/search failures **propagate fail-closed** (never a silent empty result that the UI would render as "no chunks matched your scope") with `search` not reached on an embed failure.
*   **`test_manage_session.py` (12 tests)**: cache-hit short-circuit (store untouched); corrupted `session:`/`history` cache **degrades to Postgres** instead of raising; store-miss creates a session whose `tenant_id`/`subject_id` come from the **scope, not the client**; every store lookup is scoped to `scope.tenant_id` (tenant isolation); history miss caches with the 2h sliding TTL (7200) and an **empty** history is deliberately not cached; `refresh_session_cache` writes `session:{id}` with the given TTL.
*   **`test_manage_artifacts.py` (15 tests)**: tenant pass-through on both reads; `get_artifact` → `None` on not-found; row→Monaco-descriptor mapping with missing-field tolerance; and a parametrized table over the language/MIME derivation incl. the unknown-extension `plaintext`/`text/plain` fallback and case-insensitive extensions.
*   **Verification**: `uv run pytest src/tests -q` → **142 passed** (108 + 34 new); the three files are ruff-clean. No DD (test-only, no architectural decision); no smoke test (pure unit logic, no live services). Build-plan Session-10 test line bumped 104→142 with the three new suites noted.

---

## Session 21: fix a lost-update race in the trajectory monitor's persisted risk (DD-16 hardening) — 2026-06-30
*   **Trigger**: review of DD-16 (a Kleppmann-style critique) flagged that `ValkeySessionRiskStore` does a non-atomic load→modify→save while the comment justified it with "tool calls are sequential." That premise is **false here**: `langgraph_runner.py` is a Map-Reduce fan-out — `_route_planner` `Send`s `code_worker` + `ticket_worker` in one superstep, both calling the *same* connector → `observe_async` with the *same* `session_id` on the *one* shared `TrajectoryMonitor`. So two concurrent persisted read-modify-writes interleave and lose an increment; because a lost update always **under-counts** risk, it weakens KILL/REQUIRE_APPROVAL detection (the attacker just parallelizes mutating calls). The pure in-process `observe` was already safe (synchronous, no interleave) — persistence (Session 15) introduced the race.
*   **Fix** (`core/use_cases/policy/trajectory_monitor.py`): `observe_async` now holds a **per-session `asyncio.Lock`** (lazy `_lock_for`, lazily created — `get`-then-`set` has no `await` between, so two coroutines can't both miss) across the whole load→score→save. Per-session granularity so distinct sessions don't serialize; `reset`/`forget` evict the lock alongside the state. The no-store path returns the sync `observe` directly (it never needed a lock). Atomicity enforced in the use-case (where the multi-step invariant lives), **not** by reimplementing the stateful `_score` in Lua. Comment in `session_risk_store.py` corrected to point at the real enforcement.
*   **Test** (`test_session_risk_store.py` +2 = 8): the existing cross-worker test only ran the two monitors **sequentially**, so it never exercised concurrency — that's how the race slipped through. Added a `YieldingCache` double (`await asyncio.sleep(0)` in get/set) so gathered coroutines actually interleave, and `test_concurrent_same_session_does_not_lose_updates` — **seed the session** (the lost update is on the `loaded is not None` *clobber* path; from empty, the shared in-process dict masks it), then `asyncio.gather` two `observe_async` calls and assert the total equals the strict-sequential baseline. Plus `test_distinct_sessions_do_not_serialize` for the per-session granularity.
*   **Issues Faced & Resolved**: (1) first cut of the concurrency test passed *even with the lock disabled* — starting from an empty session, the first writer's `loaded is None` so the clobber is skipped and the shared in-process state accumulates correctly, hiding the race; fixed by seeding the session so both racers hit the clobber path. (2) Confirmed the test is genuinely race-catching by temporarily replacing `async with self._lock_for(...)` with `if True:` — it failed **0.48 vs 0.72** (exactly one lost `write` increment), then passed once restored.
*   **Verification**: `uv run pytest src/tests/test_mcp.py test_agent_mcp_wiring.py test_trajectory_monitor.py test_session_risk_store.py test_architecture.py test_pdp_chokepoint.py -q` → **33 passed**; `trajectory_monitor.py` + `session_risk_store.py` ruff-clean and mypy-clean (the only mypy hits on the changed files are the repo-wide untyped-test-fn pattern). DD-16 gets a dated **addendum** (rule (b) corrected). No smoke test (the lock is in-process; no live-service behavior). Cross-process concurrent same-session writers remain **FUTURE** (Valkey CAS, not a distributed lock).

---

## Session 22: turn-persistence idempotency needs an end-to-end key (DD-21) — 2026-06-30
*   **Trigger**: a Kleppmann-style review (4th finding) noted that persistence was *built* idempotent — `messages` `ON CONFLICT (message_id) DO NOTHING`, `turns` `ON CONFLICT (turn_id) DO UPDATE`, and `Message`'s docstring even calls `message_id` "the idempotency key" — but every id was a fresh server-side `uuid4()` minted in `send_message.execute()` and `ChatMessageRequest` carried no client key. An idempotency key that isn't stable across the retry can't dedup: under at-least-once delivery (double-click, proxy/LB POST retry, dropped SSE → reconnect-and-resend) each attempt minted new ids, the `ON CONFLICT` never matched, and a duplicate user+assistant turn was inserted (plus a re-billed LLM call). Correctness + cost, not a breach — scope filtering is unaffected.
*   **Fix**: made the key **end-to-end**. `ChatMessageRequest.message_id` (optional, client-generated, <=128 chars) -> `chat.py` route -> `execute(client_message_id=...)`; all three persisted ids derive from the one resolved id (`<id>` user, `<id>:a` assistant, `<id>:t` turn) so a retry collides on every PK. No client key -> fresh `uuid4()` fallback = today's behavior, so it's backward-compatible/opt-in. Applied in **both** persist paths (cache-hit short-circuit and the normal stream path). Dedups *persistence*; suppressing duplicate *work* on an in-flight key is `# FUTURE EXTENSION`.
*   **Test** (`test_chat_security.py` +2 = 10): `test_client_message_id_makes_persisted_ids_stable_across_retry` (two executes, same `client_message_id` -> identical `message_id`/`turn_id`/assistant id, so ON CONFLICT dedups) and `test_without_client_message_id_ids_differ_per_request` (fallback mints distinct ids — the documented at-least-once behavior).
*   **Issues Faced & Resolved**: mypy reported 8 errors in `send_message.py`; confirmed **pre-existing** (stashed the edit -> same 8 on the original: `list(EmbeddingVector)` and `retrieval_result.chunks` tuple-vs-`list` at the `_format_context`/`Turn` calls). My change adds **zero** new mypy errors and is out of scope for those, so left untouched.
*   **Verification**: `uv run pytest src/tests -q` -> **146 passed** (144 + 2); changed files (`send_message.py`, `schemas/chat.py`, `routes/chat.py`, `test_chat_security.py`) ruff-clean. **DD-21** added. No smoke test (no new live-service behavior; the dedup is exercised by unit tests over the store contract).

---

## Session 23: full Cognito auth — introduce the TokenVerifierPort seam + RS256/JWKS verifier (DD-19 addendum) — 2026-07-01
*   **Trigger**: "set up full Cognito auth so we can connect quickly once AWS infra is available." The locked decision (build plan) + DD-19 both anticipated this as "swap the verifier adapter for RS256/JWKS later" — but the HS256 decode was **inline in the middleware**, so there was no adapter to swap. This session extracts the seam and lands the Cognito verifier behind it, config-gated (no live pool yet).
*   **Scope decision (recorded, DD-19 addendum)**: user first picked "verify + backend `/auth` login endpoints", then — on seeing DD-19's "no login/token-issuing route" invariant — chose to **honor DD-19: verify-only**. The login UI stays *their own* screen (not Cognito Hosted UI); the browser authenticates **directly** against Cognito via `amazon-cognito-identity-js` (USER_SRP_AUTH) and sends `Authorization: Bearer` — so the backend never touches credentials and stays a pure verifier. That frontend adapter (`frontend/src/auth/cognito.ts`, Option B) is separate-deployable work, **not** in this Core-API session.
*   **Port** (`core/ports/token_verifier.py`): `TokenVerifierPort.verify(token) -> Mapping` returning **canonical** claims (`tenant_id`/`permissions`/`sub`) + `close()`; `TokenVerificationError(detail)` carries a client-safe 401 message. The port owns no vendor symbol (holds the `core` import rule).
*   **Adapters** (`adapters/auth/`): `HS256TokenVerifier` wraps the exact former inline logic (dev tokens already canonical → pass-through). `CognitoJwtVerifier` does RS256 end-to-end: async httpx JWKS fetch, `kid`→key cache (TTL + refresh-once on unknown kid, with a 30s refresh-floor so a random-`kid` flood can't force a fetch per request), verifies signature/`iss`/`exp`/`token_use` + app-client binding (`aud` for id tokens, `client_id` for access — Cognito access tokens carry no `aud`), and is the **anti-corruption layer**: maps `cognito:groups`→`permissions`, `custom:tenant_id`→`tenant_id` (both claim names configurable) so neither middleware nor `PermissionScope` learns a Cognito name. Fails closed on any JWKS/verify problem.
*   **Wiring**: `config/di.py` gains `token_verifier` — the **only** binding point — selecting Cognito vs HS256 by `AUTH_PROVIDER`. `api/main.py` adds the middleware with `verifier=container.token_verifier` and closes it on shutdown. `api/middleware/auth.py` is now transport-agnostic: `await verifier.verify()` → 401 on `TokenVerificationError`, `PermissionScope.from_claims` → 403 (unchanged split). `settings.py` adds `AUTH_PROVIDER` + `COGNITO_*` (region defaults to `AWS_REGION`); `.env.example` mirrors them. `PermissionScope.from_claims` widened `dict`→`Mapping` (the port returns `Mapping`).
*   **Token choice**: default `COGNITO_TOKEN_USE=access` (correct API-auth token, carries `cognito:groups`); `=id` is a one-env-var fallback that reads `custom:tenant_id` without a pre-token-generation Lambda. Configurable, so no code change either way.
*   **Issues Faced & Resolved**: (1) `mypy src` flags `main.py`'s `add_middleware(AuthMiddleware, …)` as a factory-protocol conflict — **confirmed pre-existing** by stashing the change: HEAD already errored identically on the old `secret/algorithm/…` signature (`app: FastAPI` vs the ASGI factory type). Net-new mypy errors from this session: **zero** (new modules type-clean in isolation). Left the pattern as-is to match the repo-wide convention. (2) Dropped a `test_stale_cache_triggers_refresh` test as meaningless — the 30s refresh-floor prevents the refetch inside the test window, so it couldn't prove what it asserted; the cache-hit test already covers caching.
*   **Verification**: `uv run pytest src/tests -q` → **156 passed** (146 + 10 new in `test_cognito_verifier.py`: happy-path + group/tenant mapping, expired/wrong-iss/wrong-client_id/wrong-token_use/unknown-kid rejection, id-token `aud` check, JWKS cached-once, JWKS-fetch-fails-closed; `test_auth.py` rewired to the HS256 verifier). `ruff check src` clean; new modules `mypy`-clean. **DD-19 addendum** added (verify-only stance + verifier-port seam + token/claim mapping). Live Cognito verification is **ST-COG (PENDING)** — needs a real user pool.

---

## Session 24: make the Valkey cache fail-soft — an outage must degrade to a miss, not 500 the chat path (DD-24) — 2026-07-01
*   **Trigger**: a first-principles review flagged the cache as the one documented resilience gap — "Cache is not fail-soft; a Valkey blip 500s the chat path." `ValkeyAdapter.get/set/touch/evict/evict_pattern` had **no** try/except, and `send_message.execute()` awaits `self._cache.get(cache_key)` (single-turn response probe) + `evict`/`set` unguarded, so a `RedisError` propagates out of the use-case → 500 on `/chat`. This contradicted the platform's own explicit doctrine everywhere else: obs fail-soft (DD-17), guard fail-**closed** (DD-22) — the cache had no stated posture and defaulted to fail-hard.
*   **Fix** (`adapters/cache/valkey.py`): every method now catches `redis.exceptions.RedisError`, logs a warning, and returns the **miss sentinel** — `get`→`None`, `touch`→`False`, `evict_pattern`→`0`, `set`/`evict`→no-op. Centralized in the **adapter**, not the ~15 call sites: every caller already treats a miss as "fall back to the authoritative source" (`response:`/`chunk:` recompute, `session:` hydrates from Postgres in `ManageSessionUseCase`, `risk:` degrades to the monitor's in-process accumulator), so "backend down" == "key absent" for all of them, and centralizing means a future caller can't forget a guard and silently reintroduce the 500. Caught `RedisError` (the redis-py base), **not** bare `Exception`, so a genuine bug still surfaces while the backend soft-fails.
*   **DD-11 convergence check (the one subtlety)**: making `get` soft-fail could in principle weaken the trajectory monitor's risk accumulation — but it doesn't. `observe_async` keeps its in-process `self._sessions[session_id]` whether `store.load` **raises** (its `except` branch) or **returns `None`** (`loaded is not None` is false); both paths leave the accumulator untouched, so the adapter returning `None` on outage is behaviorally identical to it raising. No security regression; the monitor's existing fail-soft tests stay green.
*   **Test** (`test_cache_valkey.py`, new, 8): a `_FakeRedis` double (built via `ValkeyAdapter.__new__` to skip the real connection pool) — happy-path get/set/touch/evict/evict_pattern delegation, then `boom=True` raising `RedisConnectionError` on every op proving each method returns its miss sentinel without raising.
*   **Issues Faced & Resolved**: mypy reports 2 errors on `valkey.py` (`from_url` untyped-call, `get` returning `Any`) — confirmed **pre-existing** by stashing the change (identical 2 on HEAD, just at lines 23/30 instead of 34/42). Net-new mypy errors: **zero**. Left them as the repo-wide redis-client typing pattern.
*   **Verification**: `uv run pytest src/tests/test_cache_valkey.py test_session_risk_store.py test_chat_security.py test_architecture.py -q` → **26 passed**; `valkey.py` + `test_cache_valkey.py` ruff-clean. **DD-24** added, build-plan box ticked. No smoke test — the failure path is exercised by unit tests over the adapter (no live-service behavior beyond what ST-1's existing chat E2E already covers); a real Valkey-down chat request degrading to recompute is implicitly covered there.
