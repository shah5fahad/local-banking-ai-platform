"""AI service configuration."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict

from banking_common.settings import BaseAppSettings

_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class AISettings(BaseAppSettings):
    """Settings for the AI service, loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=(str(_ROOT_ENV), ".env"),
        env_file_encoding="utf-8",
        extra="allow",
        populate_by_name=True,
        env_prefix="AI_",
        case_sensitive=False,
    )

    database_url: str = Field(
        default="sqlite:///./ai_service.db",
        validation_alias=AliasChoices("AI_DATABASE_URL", "DATABASE_URL", "database_url"),
    )
    banking_service_url: str = Field(
        default="http://banking_service:8000",
        validation_alias=AliasChoices("AI_BANKING_SERVICE_URL", "BANKING_SERVICE_URL", "banking_service_url"),
    )
    secret_key: str = Field(
        default="change-me-min-32-chars-dev-only-not-prod",
        validation_alias=AliasChoices(
            "AI_SECRET_KEY",
            "BANKING_JWT_SECRET",
            "BANKING_JWT_VERIFY_KEY",
            "SECRET_KEY",
            "secret_key",
        ),
    )
    algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices("AI_ALGORITHM", "ALGORITHM", "algorithm"),
    )
    cors_origins: str = Field(
        default="http://localhost:8501",
        validation_alias=AliasChoices("CORS_ORIGINS", "AI_CORS_ORIGINS", "cors_origins"),
    )

    # ------------------------------------------------------------------
    # LLM settings
    # ------------------------------------------------------------------
    llm_provider: str = Field(
        default="fake",
        validation_alias=AliasChoices("AI_LLM_PROVIDER", "LLM_PROVIDER", "llm_provider"),
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("AI_LLM_MODEL", "LLM_MODEL", "llm_model"),
    )
    llm_temperature: float = Field(
        default=0.0,
        validation_alias=AliasChoices("AI_LLM_TEMPERATURE", "LLM_TEMPERATURE", "llm_temperature"),
    )
    llm_max_tokens: int = Field(
        default=2048,
        validation_alias=AliasChoices("AI_LLM_MAX_TOKENS", "LLM_MAX_TOKENS", "llm_max_tokens"),
    )
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("AI_LLM_API_KEY", "LLM_API_KEY", "llm_api_key"),
    )
    llm_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AI_LLM_BASE_URL", "LLM_BASE_URL", "llm_base_url"),
    )

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    embedding_provider: str = Field(
        default="fake",
        validation_alias=AliasChoices("AI_EMBEDDING_PROVIDER", "EMBEDDING_PROVIDER", "embedding_provider"),
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices("AI_EMBEDDING_MODEL", "EMBEDDING_MODEL", "embedding_model"),
    )

    # ------------------------------------------------------------------
    # Vector store
    # ------------------------------------------------------------------
    vector_store_provider: str = Field(
        default="memory",
        validation_alias=AliasChoices("AI_VECTOR_STORE_PROVIDER", "VECTOR_STORE_PROVIDER", "vector_store_provider"),
    )
    vector_store_path: str = Field(
        default="./data/vectorstore",
        validation_alias=AliasChoices("AI_VECTOR_STORE_PATH", "VECTOR_STORE_PATH", "vector_store_path"),
    )

    # ------------------------------------------------------------------
    # RAG settings
    # ------------------------------------------------------------------
    rag_top_k: int = Field(
        default=6,
        validation_alias=AliasChoices("AI_RAG_TOP_K", "RAG_TOP_K", "rag_top_k"),
    )
    rag_min_score: float = Field(
        default=0.3,
        validation_alias=AliasChoices("AI_RAG_MIN_SCORE", "RAG_MIN_SCORE", "rag_min_score"),
    )

    # ------------------------------------------------------------------
    # Service auth
    # ------------------------------------------------------------------
    service_key: str = Field(
        default="ai-service:change-me-service-key",
        validation_alias=AliasChoices("AI_SERVICE_KEY", "SERVICE_KEY", "service_key"),
    )

    # ------------------------------------------------------------------
    # Document upload
    # ------------------------------------------------------------------
    upload_dir: str = Field(
        default="./data/uploads",
        validation_alias=AliasChoices("AI_UPLOAD_DIR", "UPLOAD_DIR", "upload_dir"),
    )
    max_upload_size_mb: int = Field(
        default=20,
        validation_alias=AliasChoices("AI_MAX_UPLOAD_SIZE_MB", "MAX_UPLOAD_SIZE_MB", "max_upload_size_mb"),
    )

    # ------------------------------------------------------------------
    # Search provider
    # ------------------------------------------------------------------
    search_provider: str = Field(
        default="none",
        validation_alias=AliasChoices("AI_SEARCH_PROVIDER", "SEARCH_PROVIDER", "search_provider"),
    )
    search_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("AI_SEARCH_API_KEY", "SEARCH_API_KEY", "search_api_key"),
    )
    search_allowed_domains: str = Field(
        default="",
        validation_alias=AliasChoices("AI_SEARCH_ALLOWED_DOMAINS", "SEARCH_ALLOWED_DOMAINS", "search_allowed_domains"),
    )

    # ------------------------------------------------------------------
    # HITL Expiry Sweeper & Checkpoint Cleanup
    # ------------------------------------------------------------------
    enable_expiry_sweeper: bool = Field(
        default=True,
        validation_alias=AliasChoices("AI_ENABLE_EXPIRY_SWEEPER", "ENABLE_EXPIRY_SWEEPER", "enable_expiry_sweeper"),
    )
    sweeper_interval_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices("AI_SWEEPER_INTERVAL_SECONDS", "SWEEPER_INTERVAL_SECONDS", "sweeper_interval_seconds"),
    )
    checkpoint_retention_days: int = Field(
        default=7,
        validation_alias=AliasChoices("AI_CHECKPOINT_RETENTION_DAYS", "CHECKPOINT_RETENTION_DAYS", "checkpoint_retention_days"),
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a list (split on comma)."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


# @lru_cache
def get_settings() -> AISettings:
    return AISettings()
