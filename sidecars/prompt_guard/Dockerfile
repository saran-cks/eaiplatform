# syntax=docker/dockerfile:1
# Prompt Guard sidecar — Llama Prompt Guard 2 (86M), injection/jailbreak screening
# over HTTP (CPU-only). Installs from uv.lock for reproducibility; CPU torch comes
# from the pytorch-cpu index pinned in pyproject.toml (no CUDA wheels). Mirrors the
# uv pattern in docker/Dockerfile (Core API).
#
# Build context = repo root:  docker build -f sidecars/prompt_guard/Dockerfile .
#
# GATED MODEL: weights are NOT baked in. Mount a pre-downloaded models/ dir, or pass
# HF_TOKEN at RUNTIME (never at build) so the first start downloads PG2. Never bake a token.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    HF_HOME=/app/sidecars/prompt_guard/models \
    GUARD_MODELS_DIR=/app/sidecars/prompt_guard/models \
    CUDA_VISIBLE_DEVICES=""

# uv binary from the official distroless image (matches docker/Dockerfile).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer — cached unless lock/manifest changes. --frozen forbids silent
# lock drift; the venv lands at /app/sidecars/prompt_guard/.venv.
COPY sidecars/prompt_guard/pyproject.toml sidecars/prompt_guard/uv.lock* /app/sidecars/prompt_guard/
RUN --mount=type=cache,target=/root/.cache/uv \
    cd /app/sidecars/prompt_guard && uv sync --no-dev --no-install-project --frozen

# Application source (host .venv + models/ excluded via .dockerignore, so the
# container's freshly-built .venv survives this merge).
COPY sidecars/__init__.py /app/sidecars/__init__.py
COPY sidecars/prompt_guard /app/sidecars/prompt_guard

# Use the project venv; `python -m` from /app puts the `sidecars` package on sys.path.
ENV PATH="/app/sidecars/prompt_guard/.venv/bin:$PATH"

EXPOSE 8001
CMD ["python", "-m", "sidecars.prompt_guard.app"]
