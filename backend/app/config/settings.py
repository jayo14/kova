from typing import Any
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
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

    CORS_ORIGINS: str = "https://kova.app,https://www.kova.app"

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
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

    @property
    def effective_jwt_issuer(self) -> str | None:
        return self.OIDC_ISSUER_URL
    TEMPMAIL_SERVICE_URL: str = ""   # e.g. http://localhost:8200 (fixture mail service)
    TEMPMAIL_API_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

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
