"""Application settings via pydantic-settings.

All environment-driven configuration is declared here with explicit type hints.
No ``os.getenv()`` is used anywhere else in the codebase; ``get_settings()`` is
the single source of truth. The returned Settings instance is cached with
``functools.lru_cache`` so the process parses ``.env`` exactly once per
interpreter lifetime (cheap on hot paths, predictable for tests via
``get_settings.cache_clear()``).
"""

from functools import lru_cache

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Project metadata
    PROJECT_NAME: str = "Fudz API v2"
    VERSION: str = "0.1.0"
    API_V2_PREFIX: str = "/api/v2"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development | staging | production
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    WORKERS: int = 1
    ALLOWED_HOSTS: list[str] = ["*"]  # tighten in later phases
    CORS_ALLOW_ALL_ORIGINS: bool = True  # tighten in later phases
    CORS_ALLOWED_ORIGINS: list[str] = []

    # Database (PostGIS)
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "fudz"
    DB_PASSWORD: str = "password"
    DB_NAME: str = "fudz_v2"
    DB_SSLMODE: str = "prefer"  # prefer | require | verify-full | disable
    DB_POOL_MIN_SIZE: int = 1
    DB_POOL_MAX_SIZE: int = 20
    DB_ECHO: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """Async (asyncpg) SQLAlchemy URL built from the DB_* parts."""
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Sync (psycopg2) SQLAlchemy URL used by Alembic's offline/DDL path."""
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # Redis
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_URL: str | None = None  # override; if None, built from HOST:PORT

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL_RESOLVED(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # JWT (placeholders; Phase 1 wires these)
    JWT_SECRET: str = "change-me-in-env"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TTL_MINUTES: int = 15
    JWT_REFRESH_TTL_DAYS: int = 7
    JWT_ISSUER: str = "fudz-api-v2"
    JWT_AUDIENCE: str = "fudz-clients"

    # Google OAuth (placeholders; Phase 1)
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # Throttle rates (placeholders; mirror v1, wired by slowapi in a later phase)
    RATE_LIMIT_OTP: str = "5/minute"
    RATE_LIMIT_PASSWORD_RESET: str = "3/hour"
    RATE_LIMIT_GOOGLE_AUTH: str = "10/minute"
    RATE_LIMIT_USER: str = "1000/hour"
    RATE_LIMIT_ANON: str = "100/hour"

    # Storage / Firebase / SMS (placeholders; later phases)
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = ""
    R2_CUSTOM_DOMAIN: str = ""
    FIREBASE_CREDENTIALS_PATH: str = ""
    TEXTBEE_API_KEY: str = ""
    TEXTBEE_DEVICE_ID: str = ""


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings singleton (parsed once per process)."""
    return Settings()
