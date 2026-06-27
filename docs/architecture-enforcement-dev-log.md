<!-- SCOPE BANNER — read first -->
> **SCOPE — ARCHITECTURE INVARIANT ENFORCEMENT ONLY.** Chronological log for the
> machine-checkable hexagonal-boundary guard (`src/tests/test_architecture.py`) and any
> refactors made to satisfy it. It does **NOT** log feature work on the Core API, the
> sidecars, or the ingestion worker — those have their own dev logs.

# Architecture Enforcement — Chronological Build & Developer Log

Append one dated entry per work session. Newest at the bottom. Keep it factual.

---

## Session 1: Static import-boundary guard + fix existing violations — 2026-06-27
- **Trigger (review feedback)**: "The architecture invariants (core never imports adapters, etc.)
  have no enforcement. A single accidental import would violate them silently. Even a small
  `test_architecture.py` using importlib to assert import boundaries would catch regressions."
- **Built**: `src/tests/test_architecture.py` — a pytest test that enforces the inward-only
  dependency rule of the hexagonal layering. Two tests: (1) `test_no_forbidden_cross_layer_imports`
  walks every `.py` under each internal package and asserts no forbidden cross-layer import;
  (2) `test_invariant_table_only_references_real_packages` keeps the rule table honest against the
  real source tree.
- **Mechanism — AST, not importlib**: chose static `ast` parsing over the suggested `importlib`.
  `importlib.import_module` *executes* each module, which would require every third-party dep
  installed (boto3, grpc, langgraph, …) and could trigger side effects. AST parsing reads the
  import statements without importing — runs dep-free, fast, and can't be fooled by runtime
  trickery. Honored the intent, upgraded the mechanism.
- **Invariant matrix enforced** (dependencies point inward only):

  | Layer | May NOT import |
  |---|---|
  | `core` | `adapters`, `api`, `config`, `daemon`, `observability` |
  | `adapters` | `api`, `daemon` |
  | `observability` | `adapters`, `api`, `daemon`, `config` |

  `config` (the DI composition root) may import everything — that is its job. Relative imports
  (`from . import x`) are ignored; they never cross a top-level layer.
- **Violations the guard immediately caught (3) — all fixed, no exceptions/allowlist**:
  1. `core/use_cases/chat/send_message.py` imported `config.settings.Settings` (used
     `retrieval_top_k`, `cache_response_ttl`). → Constructor now takes those two as plain `int`
     params; DI layer (`api/routes/chat.py`) passes `settings.retrieval_top_k` /
     `settings.cache_response_ttl` in. `core` no longer references `config`.
  2. `core/use_cases/retrieval/search_chunks.py` imported `config.settings.Settings` — a **dead
     import** (never referenced). → Removed.
  3. `observability/otel.py` imported `config.settings.Settings` (type hint + 4 field reads).
     → `init_otel()` now takes plain primitives (`enabled`, `service_name`, `environment`,
     `otlp_endpoint`); `api/main.py` reads settings and passes the values. `observability` no
     longer references `config`. *(This one was surfaced only by the guard — not spotted in the
     pre-build scan, which is exactly the point of the test.)*
- **Callers/tests updated**: `api/routes/chat.py` (SendChat construction), `api/main.py`
  (`init_otel` call), `src/tests/test_chat_security.py` (3 construction sites switched from a
  `MagicMock` settings to explicit `retrieval_top_k=`/`cache_response_ttl=` kwargs).
- **Result**: `uv run pytest src/tests/ -q` → **10 passed**. The boundary guard is green and now
  fails the build on any future inward-rule violation. New test file is ruff-clean.
- **Out of scope (left as-is)**: pre-existing lint debt in touched files (unused `json`/`asyncio`,
  `datetime.UTC` style, line-length) — unrelated to boundaries; not swept into this focused change.
- **Process note**: this "plan → brief for review → execute → dev-log" loop is now the standard
  procedure for review-feedback items going forward.
- **Next / possible follow-ups**: extend the matrix if new top-level packages appear; optionally
  add a deeper rule (e.g. `core` may import only stdlib + `pydantic` + `core.*`) if we want to ban
  *all* third-party framework leakage into the domain, not just internal layers.
