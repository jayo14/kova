from typing import Any
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AWS SES / Sessy Email Settings
    AWS_REGION: str = "eu-central-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    SES_CONFIGURATION_SET: str = "production-ses"
    SES_FROM_EMAIL: str = ""

    CREDENTIAL_ENCRYPTION_KEY: str = ""
    FRONTEND_URL: str = "http://localhost:3000"
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 1.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 1.0
    model_config = {
        "env_file": (".env", "backend/.env", "../backend/.env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/kova"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, v: Any) -> str:
        default_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/kova"
        if not v or not isinstance(v, str) or not v.strip():
            return default_url
        url = v.strip().strip("'\"")
        # Strip accidental pasted key names (e.g. DATABASE_URL=postgresql...)
        if "=" in url:
            prefix, _, rest = url.partition("=")
            if prefix.strip().lower() in ("database_url", "export database_url"):
                url = rest.strip().strip("'\"")
        # Ensure asyncpg driver for SQLAlchemy async engine
        if url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]
        return url

    CORS_ORIGINS: str = "https://kova.app,https://www.kova.app,https://kova-x.vercel.app"

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
        # Always guarantee core and production preview frontends
        origins.extend(["https://kova-x.vercel.app", "https://kova.app", "https://www.kova.app"])
        if not self.is_production:
            origins.extend(["http://localhost:3000", "http://127.0.0.1:3000"])
        return list(dict.fromkeys(origins))

    RUMPTYCLOUD_S3_ENDPOINT: str = "https://s3.rumptycloud.com"
    RUMPTYCLOUD_ACCESS_KEY_ID: str = ""
    RUMPTYCLOUD_SECRET_ACCESS_KEY: str = ""
    RUMPTYCLOUD_BUCKET_NAME: str = ""
    RUMPTYCLOUD_PUBLIC_URL_PREFIX: str = ""
    STORAGE_BUCKET_PREFIX: str = "kova"

    OIDC_ISSUER_URL: str | None = None
    OIDC_AUDIENCE: str = "authenticated"
    JWT_SECRET_KEY: str = ""
    FAIL_ON_NETWORK_ERRORS: bool = True
    AGENT_EXECUTION_ENABLED: bool = False  # default off in code; enabled via env in deployment
    AGENT_EXECUTION_MAX_DURATION_SECONDS: int = 600
    VLM_ENABLED: bool = False
    VLM_MODEL: str = "gpt-4o-mini"
    VLM_API_KEY: str = ""
    VLM_BASE_URL: str = "https://api.openai.com/v1"

    @model_validator(mode="after")
    def validate_production_keys(self) -> "Settings":
        if self.is_production:
            if (
                not self.JWT_SECRET_KEY
                or self.JWT_SECRET_KEY == "dev-secret-key-change-me"
                or len(self.JWT_SECRET_KEY) < 32
            ):
                raise ValueError(
                    "In production, JWT_SECRET_KEY must be set, cannot be 'dev-secret-key-change-me', and must be at least 32 characters long."
                )
            dev_fernet_key = "k9_8TqZfUvYx3W1eR7tL5mN2pQ4sA6dF8gH0jK2lM4o="
            key = (self.CREDENTIAL_ENCRYPTION_KEY or "").strip()
            if not key or key == dev_fernet_key:
                raise ValueError(
                    "In production, CREDENTIAL_ENCRYPTION_KEY must be set and cannot be the default dev key."
                )
            try:
                import base64
                raw = base64.urlsafe_b64decode(key.encode("utf-8"))
                if len(raw) != 32:
                    raise ValueError
                from cryptography.fernet import Fernet
                Fernet(key.encode("utf-8"))
            except Exception:
                raise ValueError(
                    "In production, CREDENTIAL_ENCRYPTION_KEY must be a valid 32-byte url-safe base64-encoded Fernet key."
                )
            if self.DEV_ALLOW_MOCKS:
                raise ValueError("DEV_ALLOW_MOCKS cannot be enabled in production.")
            if self.REQUIRE_PRODUCTION_INTEGRATIONS:
                missing = []
                if not self.STRIPE_SECRET_KEY:
                    missing.append("STRIPE_SECRET_KEY")
                if not self.STRIPE_WEBHOOK_SECRET:
                    missing.append("STRIPE_WEBHOOK_SECRET")
                if not (self.AWS_ACCESS_KEY_ID and self.AWS_SECRET_ACCESS_KEY and self.SES_FROM_EMAIL):
                    missing.append("AWS_SES")
                if missing:
                    raise ValueError(
                        f"In production with REQUIRE_PRODUCTION_INTEGRATIONS, missing required credentials: {', '.join(missing)}"
                    )
        return self

    @property
    def effective_jwt_issuer(self) -> str | None:
        return self.OIDC_ISSUER_URL
    TEMPMAIL_SERVICE_URL: str = ""   # e.g. http://localhost:8200 (fixture mail service)
    TEMPMAIL_API_KEY: str = ""
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    @field_validator("CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", mode="after")
    @classmethod
    def normalize_celery_urls(cls, v: str) -> str:
        if v and v.startswith("rediss://") and "ssl_cert_reqs" not in v:
            sep = "&" if "?" in v else "?"
            return f"{v}{sep}ssl_cert_reqs=CERT_NONE"
        return v
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    EVIDENCE_CAPTURE_VIDEO: bool = True
    EVIDENCE_CAPTURE_TRACE: bool = False
    EVIDENCE_VIDEO_DIR: str = "/tmp/kova_videos"
    RATE_LIMIT_PER_MINUTE: int = 300
    DISCOVERY_MAX_DEPTH: int = 3
    DISCOVERY_MAX_PAGES: int = 50

    @field_validator("DISCOVERY_MAX_DEPTH", mode="before")
    @classmethod
    def cap_discovery_depth(cls, v: Any) -> int:
        val = int(v) if v is not None else 3
        return min(max(val, 1), 5)

    SIGNED_URL_TTL_DAYS: int = 30

    @field_validator("DISCOVERY_MAX_PAGES", mode="before")
    @classmethod
    def cap_discovery_pages(cls, v: Any) -> int:
        val = int(v) if v is not None else 50
        return min(max(val, 1), 200)

    # Page readiness: how long Kova waits for a slow / sleeping deployment to
    # serve the real application before reporting it as unresolved.
    PAGE_READINESS_TIMEOUT_SECONDS: float = 20.0
    PAGE_READINESS_RETRY_INTERVALS: str = "0.5,1.0,2.0,3.0"

    @field_validator("PAGE_READINESS_TIMEOUT_SECONDS", mode="before")
    @classmethod
    def cap_page_readiness_timeout(cls, v: Any) -> float:
        val = float(v) if v is not None else 20.0
        return min(max(val, 1.0), 120.0)

    @property
    def page_readiness_intervals(self) -> tuple[float, ...]:
        intervals: list[float] = []
        for chunk in str(self.PAGE_READINESS_RETRY_INTERVALS).split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                value = float(chunk)
            except ValueError:
                continue
            if value >= 0:
                intervals.append(value)
        return tuple(intervals) or (0.5, 1.0, 2.0, 3.0)

    # Observability & SRE (Chunk 16)
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = None
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_ALLOWED_IPS: str = "127.0.0.1,::1"
    LOG_FORMAT: str = "text"  # "json" or "text"

    @property
    def prometheus_allowed_ips_list(self) -> list[str]:
        return [ip.strip() for ip in self.PROMETHEUS_ALLOWED_IPS.split(",") if ip.strip()]

    # Billing & Product Surfaces (Chunk 17)
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRO_PRICE_ID: str = "price_pro_default"
    STRIPE_ENTERPRISE_PRICE_ID: str = "price_enterprise_default"
    DEV_ALLOW_MOCKS: bool = False
    REQUIRE_PRODUCTION_INTEGRATIONS: bool = False
    FRONTEND_URL: str = "http://localhost:3000"
    DOCS_URL: str = "https://docs.kova.dev"
    STATUS_PAGE_URL: str = "https://status.kova.dev"

    @property
    def allow_mocks(self) -> bool:
        """Allow mock integrations ONLY when explicitly enabled AND not in production."""
        return bool(self.DEV_ALLOW_MOCKS and not self.is_production)

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def effective_debug(self) -> bool:
        """DEBUG is always False in production regardless of env var."""
        return self.DEBUG and not self.is_production

    def storage_bucket(self, purpose: str) -> str:
        """Get a bucket name for a given purpose.

        Examples:
            settings.storage_bucket("screenshots") -> "kova-screenshots"
            settings.storage_bucket("avatars")     -> "kova-avatars"
        """
        return f"{self.STORAGE_BUCKET_PREFIX}-{purpose}"


settings = Settings()
