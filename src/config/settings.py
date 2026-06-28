"""Single source of truth for configuration.

Every environment variable the application reads is declared here. Nothing else
in the codebase calls ``os.environ`` directly. Grouped by concern; flat env names
match ``.env.example``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "staging", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    # --- Application ---
    app_name: str = Field("core-api", alias="APP_NAME")
    app_env: Environment = Field("local", alias="APP_ENV")
    debug: bool = Field(False, alias="DEBUG")
    log_level: LogLevel = Field("INFO", alias="LOG_LEVEL")
    log_to_file: bool = Field(False, alias="LOG_TO_FILE")
    log_dir: str = Field("./logs", alias="LOG_DIR")
    log_file: str = Field("core-api.log", alias="LOG_FILE")

    # --- API server ---
    api_host: str = Field("0.0.0.0", alias="API_HOST")
    api_port: int = Field(8000, alias="API_PORT")

    # --- JWT (HS256 shared secret) ---
    jwt_secret: str = Field("change-me-dev-only", alias="JWT_SECRET")
    jwt_algorithm: str = Field("HS256", alias="JWT_ALGORITHM")
    jwt_issuer: str = Field("core-api", alias="JWT_ISSUER")
    jwt_audience: str = Field("core-api-clients", alias="JWT_AUDIENCE")
    jwt_access_ttl_seconds: int = Field(3600, alias="JWT_ACCESS_TTL_SECONDS")
    jwt_refresh_ttl_seconds: int = Field(2_592_000, alias="JWT_REFRESH_TTL_SECONDS")

    # --- Postgres ---
    postgres_host: str = Field("postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")
    postgres_db: str = Field("core", alias="POSTGRES_DB")
    postgres_user: str = Field("core", alias="POSTGRES_USER")
    postgres_password: str = Field("core", alias="POSTGRES_PASSWORD")
    postgres_pool_min: int = Field(2, alias="POSTGRES_POOL_MIN")
    postgres_pool_max: int = Field(10, alias="POSTGRES_POOL_MAX")

    # --- Valkey ---
    valkey_host: str = Field("valkey", alias="VALKEY_HOST")
    valkey_port: int = Field(6379, alias="VALKEY_PORT")
    valkey_db: int = Field(0, alias="VALKEY_DB")
    valkey_password: str = Field("", alias="VALKEY_PASSWORD")

    # --- Qdrant ---
    qdrant_host: str = Field("qdrant", alias="QDRANT_HOST")
    qdrant_http_port: int = Field(6333, alias="QDRANT_HTTP_PORT")
    qdrant_grpc_port: int = Field(6334, alias="QDRANT_GRPC_PORT")
    qdrant_use_grpc: bool = Field(True, alias="QDRANT_USE_GRPC")
    qdrant_api_key: str = Field("", alias="QDRANT_API_KEY")
    qdrant_collection: str = Field("knowledge", alias="QDRANT_COLLECTION")

    # --- Model server sidecar (bge-m3 embeddings; gRPC) ---
    model_server_host: str = Field("model_server", alias="MODEL_SERVER_HOST")
    model_server_port: int = Field(50051, alias="MODEL_SERVER_PORT")
    embed_model: str = Field("bge-m3", alias="EMBED_MODEL")
    embed_dim: int = Field(1024, alias="EMBED_DIM")
    embed_sparse_enabled: bool = Field(True, alias="EMBED_SPARSE_ENABLED")

    # --- Prompt Guard sidecar (HTTP) ---
    guard_enabled: bool = Field(True, alias="GUARD_ENABLED")
    guard_gateway_url: str = Field("http://guard_gateway:8001", alias="GUARD_GATEWAY_URL")

    # --- MCP external connectors (read-only phase 1; writes FUTURE) ---
    mcp_enabled: bool = Field(True, alias="MCP_ENABLED")
    # Mock transport (canned results, no live MCP servers) until real connectors land.
    mcp_mock_mode: bool = Field(True, alias="MCP_MOCK_MODE")

    # --- AWS Bedrock ---
    aws_region: str = Field("us-east-1", alias="AWS_REGION")
    aws_access_key_id: str = Field("", alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field("", alias="AWS_SECRET_ACCESS_KEY")
    aws_session_token: str = Field("", alias="AWS_SESSION_TOKEN")
    bedrock_model_id: str = Field("anthropic.claude-sonnet-4-6", alias="BEDROCK_MODEL_ID")
    bedrock_fast_model_id: str = Field(
        "anthropic.claude-haiku-4-5-20251001", alias="BEDROCK_FAST_MODEL_ID"
    )
    bedrock_max_tokens: int = Field(4096, alias="BEDROCK_MAX_TOKENS")
    bedrock_temperature: float = Field(0.2, alias="BEDROCK_TEMPERATURE")

    # --- Phoenix / OpenTelemetry ---
    otel_enabled: bool = Field(True, alias="OTEL_ENABLED")
    otel_service_name: str = Field("core-api", alias="OTEL_SERVICE_NAME")
    otel_exporter_otlp_endpoint: str = Field(
        "http://phoenix:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    phoenix_http_endpoint: str = Field("http://phoenix:6006", alias="PHOENIX_HTTP_ENDPOINT")

    # --- Cache TTLs (seconds) ---
    cache_response_ttl: int = Field(3600, alias="CACHE_RESPONSE_TTL")
    cache_chunk_ttl: int = Field(86_400, alias="CACHE_CHUNK_TTL")
    session_ttl: int = Field(7200, alias="SESSION_TTL")

    # --- Retrieval ---
    retrieval_top_k: int = Field(5, alias="RETRIEVAL_TOP_K")
    rrf_k: int = Field(60, alias="RRF_K")
    rerank_enabled: bool = Field(False, alias="RERANK_ENABLED")
    rerank_score_spread_threshold: float = Field(0.15, alias="RERANK_SCORE_SPREAD_THRESHOLD")

    # --- Agent lifecycle ---
    agent_session_ttl_seconds: int = Field(1800, alias="AGENT_SESSION_TTL_SECONDS")
    agent_max_iterations: int = Field(12, alias="AGENT_MAX_ITERATIONS")
    agent_max_concurrency: int = Field(4, alias="AGENT_MAX_CONCURRENCY")

    # --- A2A interop ---
    a2a_enabled: bool = Field(True, alias="A2A_ENABLED")
    a2a_registry_url: str = Field("", alias="A2A_REGISTRY_URL")

    # --- Queue ---
    queue_name: str = Field("ingestion", alias="QUEUE_NAME")

    # --- Daemon intervals (seconds) ---
    reaper_interval: int = Field(60, alias="REAPER_INTERVAL")
    watchdog_interval: int = Field(30, alias="WATCHDOG_INTERVAL")
    cleanup_interval: int = Field(120, alias="CLEANUP_INTERVAL")

    # --- Derived ---
    @computed_field  # type: ignore[prop-decorator]
    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def valkey_url(self) -> str:
        auth = f":{self.valkey_password}@" if self.valkey_password else ""
        return f"redis://{auth}{self.valkey_host}:{self.valkey_port}/{self.valkey_db}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_http_port}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def model_server_target(self) -> str:
        return f"{self.model_server_host}:{self.model_server_port}"


@lru_cache
def get_settings() -> Settings:
    """Cached singleton accessor. Use this everywhere instead of constructing Settings()."""
    return Settings()
