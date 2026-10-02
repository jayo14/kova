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

    SUPABASE_URL_OVERRIDE: str | None = None
    SUPABASE_PROJECT_REF: str = "127.0.0.1"
    SUPABASE_JWT_ISSUER: str | None = None
    SUPABASE_JWT_AUDIENCE: str = "authenticated"

    @property
    def effective_jwt_issuer(self) -> str | None:
        """JWT issuer: explicit override or auto-derived from project ref.

        Supabase v2 JWTs use ``https://<ref>.supabase.co/auth/v1`` as issuer.
        """
        if self.SUPABASE_JWT_ISSUER:
            return self.SUPABASE_JWT_ISSUER
        if self.SUPABASE_PROJECT_REF and self.SUPABASE_PROJECT_REF != "127.0.0.1":
            return f"https://{self.SUPABASE_PROJECT_REF}.supabase.co/auth/v1"
        return None
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    STORAGE_BUCKET_PREFIX: str = "kova"
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

    @property
    def supabase_url(self) -> str:
        if self.SUPABASE_URL_OVERRIDE:
            return self.SUPABASE_URL_OVERRIDE.rstrip("/")
        if self.SUPABASE_PROJECT_REF and self.SUPABASE_PROJECT_REF != "127.0.0.1":
            return f"https://{self.SUPABASE_PROJECT_REF}.supabase.co"
        return ""

    def storage_bucket(self, purpose: str) -> str:
        """Get a bucket name for a given purpose.

        Examples:
            settings.storage_bucket("screenshots") -> "kova-screenshots"
            settings.storage_bucket("avatars")     -> "kova-avatars"
        """
        return f"{self.STORAGE_BUCKET_PREFIX}-{purpose}"


settings = Settings()
