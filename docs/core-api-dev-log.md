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
