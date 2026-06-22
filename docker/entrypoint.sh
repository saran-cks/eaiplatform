#!/usr/bin/env sh
set -e

# Core API entrypoint. The FastAPI app (api.main:app) is created in Session 2
# (build step 5). Until then this image builds and installs deps fine; running
# it will fail fast with a clear message instead of an opaque ImportError.
if ! python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('api.main') else 1)" 2>/dev/null; then
    echo "[entrypoint] api.main not present yet — implemented in Session 2 (build step 5)." >&2
    echo "[entrypoint] Infra services (postgres/valkey/qdrant/phoenix) run independently." >&2
    exit 1
fi

exec uvicorn api.main:app \
    --host "${API_HOST:-0.0.0.0}" \
    --port "${API_PORT:-8000}" \
    --no-access-log
