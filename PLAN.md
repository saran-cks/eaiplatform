# Enterprise AI Platform

Permission-scoped RAG, agents, MCP, and A2A on a hexagonal (ports-and-adapters) core.
This file is the top-level index; the detailed plans, decisions, and chronological build
logs live under [`docs/`](docs/).

## Deployables

| Service | Path | Role |
|---------|------|------|
| Core API | `src/` | Always-on FastAPI app — auth, chat (RAG), agents. Hexagonal: `core` depends on nothing internal; adapters/api/config wire it. |
| Embedding sidecar | `sidecars/model_server/` | bge-m3 dense+sparse embeddings (gRPC). |
| Prompt Guard sidecar | `sidecars/prompt_guard/` | Llama Prompt Guard 2 injection/jailbreak screening (HTTP). |
| Ingestion worker | `ingestion_worker/` | Standalone container: acquire → gate → parse → guard → chunk → embed → dual-write. Decoupled; coupled only via the shared schema. |

The Core API and the ingestion worker share **no code** — only data at rest in Qdrant +
Postgres (+ Phoenix). That schema is pinned in [`contracts/`](contracts/) and
cross-enforced by tests on both sides.

## Key docs

- **Architecture:** [`docs/core-api-architecture.md`](docs/core-api-architecture.md)
- **Build plan:** [`docs/core-api-build-plan.md`](docs/core-api-build-plan.md)
- **Design decisions (incl. the DD-7…DD-13 security model):** [`docs/design-decisions.md`](docs/design-decisions.md)
- **Cross-service contracts:** [`contracts/README.md`](contracts/README.md)
- **Dev logs:** core-api, ingestion-worker, embedding/prompt-guard sidecars, and
  architecture-enforcement — all under [`docs/`](docs/).
- **Manual smoke tests (deferred live checks):** [`docs/smoke-tests.md`](docs/smoke-tests.md)

## Development

```bash
uv run pytest src/tests                              # core-api tests
uv run python -m pytest ingestion_worker/tests       # ingestion-worker tests (decoupled)
uv run ruff check src ingestion_worker               # lint
```

Dependencies are managed with `uv` (not pip).
