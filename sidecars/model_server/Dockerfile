# Embedding sidecar — bge-m3 dense+sparse over gRPC (CPU-only).
# Build context = repo root:  docker build -f sidecars/model_server/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/sidecars/model_server/models \
    EMBED_MODELS_DIR=/app/sidecars/model_server/models \
    CUDA_VISIBLE_DEVICES=""

# Deps first for layer caching (kept in sync with pyproject.toml [dependencies]).
RUN pip install "FlagEmbedding>=1.3.0" "grpcio>=1.60.0" "protobuf>=4.25.0"

COPY sidecars/__init__.py /app/sidecars/__init__.py
COPY sidecars/model_server /app/sidecars/model_server

EXPOSE 50051
CMD ["python", "-m", "sidecars.model_server.server"]
