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
    PROJECT_NAME: str = "Fudgo API"
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

    # WebSocket (Phase 4)
    WS_MAX_CONNECTIONS_PER_USER: int = 5
    WS_PING_INTERVAL_S: int = 30
    WS_PONG_TIMEOUT_S: int = 10

    # Stripe (Phase 5)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_API_TIMEOUT_S: int = 10

    # M-Pesa Daraja (Phase 5)
    MPESA_ENVIRONMENT: str = "sandbox"
    MPESA_CONSUMER_KEY: str = ""
    MPESA_CONSUMER_SECRET: str = ""
    MPESA_SHORTCODE: str = ""
    MPESA_PASSKEY: str = ""
    MPESA_STK_PUSH_CALLBACK_URL: str = ""
    MPESA_API_TIMEOUT_S: int = 15

    # Payment behavior (Phase 5)
    PENDING_PAYMENT_CART_TTL_MINUTES: int = 30
    PENDING_PAYMENT_SWEEP_INTERVAL_S: int = 300
    STRIPE_MIN_AMOUNT_KES: float = 10.00
    MPESA_MIN_AMOUNT_KES: float = 1.00

    # Celery (Phase 5: PENDING_PAYMENT sweep only)
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_ALWAYS_EAGER: bool = True  # bypasses broker in tests
    DATABASE_URL_SYNC: str = ""

    # Firebase / FCM (Phase 6) -- JSON string of the service account, never a file
    FIREBASE_CREDENTIALS_JSON: str = ""
    FIREBASE_PROJECT_ID: str = ""

    # Plunk (email, Phase 6)
    PLUNK_API_KEY: str = ""
    PLUNK_FROM_EMAIL: str = "no-reply@fudgo.com"
    PLUNK_FROM_NAME: str = "Fudgo"

    # TextBee (SMS, Phase 6)
    TEXTBEE_API_KEY: str = ""
    TEXTBEE_DEVICE_ID: str = ""
    TEXTBEE_SENDER_ID: str = "Fudgo"

    # Platform economics (Phase 6)
    PLATFORM_FEE_PERCENT: float = 0.15
    COURIER_DELIVERY_FEE_PERCENT: float = 0.10

    # Payout scheduling (Phase 6)
    PAYOUT_PROCESSING_HOUR_UTC: int = 2
    PAYOUT_MIN_ORDER_AGE_HOURS: int = 24
    PAYOUT_RETRY_BACKOFF_S: int = 3600

    # Auto-dispatch (Phase 6)
    AUTO_DISPATCH_TIMEOUT_S: int = 60

    # Database (PostGIS)
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "fudgo"
    DB_PASSWORD: str = "password"
    DB_NAME: str = "fudgo"
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
    JWT_ISSUER: str = "fudgo-api"
    JWT_AUDIENCE: str = "fudgo-clients"

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
    R2_BUCKET_NAME: str = "fudgo-media"
    R2_CUSTOM_DOMAIN: str = ""
    R2_REGION: str = "auto"
    R2_ENDPOINT_URL: str = ""
    MAX_UPLOAD_SIZE_MB: int = 5
    ALLOWED_IMAGE_MIME_TYPES: list[str] = [
        "image/jpeg",
        "image/png",
        "image/webp",
    ]
    MAX_IMAGE_DIMENSION_PX: int = 4096
    DEFAULT_SEARCH_RADIUS_KM: float = 5.0
    MAX_SEARCH_RADIUS_KM: float = 50.0
    FIREBASE_CREDENTIALS_PATH: str = ""  # legacy; unused in v2 (env JSON only)


@lru_cache
def get_settings() -> Settings:
    """Return the cached Settings singleton (parsed once per process)."""
    return Settings()
