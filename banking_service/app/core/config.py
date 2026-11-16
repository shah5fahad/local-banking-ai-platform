"""Banking service configuration loaded from environment / .env file."""
from __future__ import annotations

from pydantic import Field

from banking_common.settings import BaseAppSettings


class BankingSettings(BaseAppSettings):
    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    database_url: str = Field(
        default="sqlite:////data/banking.db",
        alias="BANKING_DATABASE_URL",
    )

    # ------------------------------------------------------------------
    # JWT & Secrets
    # ------------------------------------------------------------------
    jwt_algorithm: str = Field(default="HS256", alias="BANKING_JWT_ALGORITHM")
    jwt_secret: str = Field(
        default="change-me-min-32-chars-dev-only-not-prod",
        alias="BANKING_JWT_SECRET",
    )
    secret_key: str = Field(
        default="change-me-min-32-chars-dev-only-not-prod",
        alias="BANKING_SECRET_KEY",
    )
    jwt_private_key_path: str | None = Field(
        default=None, alias="BANKING_JWT_PRIVATE_KEY_PATH"
    )
    jwt_public_key_path: str | None = Field(
        default=None, alias="BANKING_JWT_PUBLIC_KEY_PATH"
    )
    access_token_expire_minutes: int = Field(
        default=15, alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    refresh_token_expire_days: int = Field(
        default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS"
    )

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    password_hash_scheme: str = Field(
        default="argon2", alias="PASSWORD_HASH_SCHEME"
    )
    field_encryption_key: str = Field(
        default="change-me-base64-32-bytes", alias="FIELD_ENCRYPTION_KEY"
    )
    account_hash_pepper: str = Field(
        default="change-me", alias="ACCOUNT_HASH_PEPPER"
    )
    # Comma-separated "name:key" pairs, e.g. "ai-service:secret123"
    service_api_keys: str = Field(
        default="ai-service:change-me-service-key", alias="SERVICE_API_KEYS"
    )

    # ------------------------------------------------------------------
    # Transfer limits
    # ------------------------------------------------------------------
    transfer_per_txn_limit_minor: int = Field(
        default=20_000_000, alias="TRANSFER_PER_TXN_LIMIT_MINOR"
    )
    transfer_daily_limit_minor: int = Field(
        default=50_000_000, alias="TRANSFER_DAILY_LIMIT_MINOR"
    )
    transfer_approval_expiry_seconds: int = Field(
        default=300, alias="TRANSFER_APPROVAL_EXPIRY_SECONDS"
    )
    duplicate_window_seconds: int = Field(
        default=120, alias="DUPLICATE_WINDOW_SECONDS"
    )

    # ------------------------------------------------------------------
    # Auth method
    # ------------------------------------------------------------------
    txn_auth_method: str = Field(default="PIN", alias="TXN_AUTH_METHOD")
    txn_auth_max_attempts: int = Field(default=5, alias="TXN_AUTH_MAX_ATTEMPTS")

    # ------------------------------------------------------------------
    # Rate limiting / CORS
    # ------------------------------------------------------------------
    rate_limit_login: str = Field(default="5/minute", alias="RATE_LIMIT_LOGIN")
    cors_origins: str = Field(
        default="http://localhost:8501", alias="CORS_ORIGINS"
    )

    # ------------------------------------------------------------------
    # Auto-created account & card defaults
    # ------------------------------------------------------------------
    default_bank_name: str = Field(
        default="Local Bank", alias="DEFAULT_BANK_NAME"
    )
    default_bank_ifsc: str = Field(
        default="LOCL0001001", alias="DEFAULT_BANK_IFSC"
    )
    default_bank_branch: str = Field(
        default="Main Branch", alias="DEFAULT_BANK_BRANCH"
    )
    initial_account_balance_minor: int = Field(
        default=10_000_000, alias="INITIAL_ACCOUNT_BALANCE_MINOR"
    )
    default_card_network: str = Field(
        default="VISA", alias="DEFAULT_CARD_NETWORK"
    )
    default_card_credit_limit_minor: int = Field(
        default=20_000_000, alias="DEFAULT_CARD_CREDIT_LIMIT_MINOR"
    )

    # ------------------------------------------------------------------
    # Computed helpers
    # ------------------------------------------------------------------

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a list (split on comma)."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def service_api_keys_dict(self) -> dict[str, str]:
        """Parse "name:key,name2:key2" into a dict."""
        result: dict[str, str] = {}
        for pair in self.service_api_keys.split(","):
            pair = pair.strip()
            if ":" in pair:
                name, key = pair.split(":", 1)
                result[name.strip()] = key.strip()
        return result


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_settings: BankingSettings | None = None


def get_settings() -> BankingSettings:
    """Return the singleton BankingSettings instance (lazy-initialised)."""
    global _settings
    if _settings is None:
        _settings = BankingSettings()
    return _settings
