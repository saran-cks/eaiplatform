# Prompt Guard sidecar — Llama Prompt Guard 2 (86M), injection/jailbreak screening (HTTP, CPU-only).
# Build context = repo root:  docker build -f sidecars/prompt_guard/Dockerfile .
#
# GATED MODEL: weights are NOT baked in. Either mount a pre-downloaded models/ dir,
# or pass HF_TOKEN at RUNTIME (not build) so the first start downloads PG2. Never
# bake a token into the image.
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/sidecars/prompt_guard/models \
    GUARD_MODELS_DIR=/app/sidecars/prompt_guard/models \
    CUDA_VISIBLE_DEVICES=""

# CPU-only torch keeps the image small; then the rest of the deps.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install "transformers>=4.40.0" "fastapi>=0.110.0" "uvicorn[standard]>=0.29.0" "pydantic>=2.6.0"

COPY sidecars/__init__.py /app/sidecars/__init__.py
COPY sidecars/prompt_guard /app/sidecars/prompt_guard

EXPOSE 8001
CMD ["python", "-m", "sidecars.prompt_guard.app"]
