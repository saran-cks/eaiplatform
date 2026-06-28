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
