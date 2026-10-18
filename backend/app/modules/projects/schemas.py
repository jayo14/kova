import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EnvironmentConfig(BaseModel):
    target: Literal["development", "staging", "production"] = "staging"
    base_url_override: str | None = None
    allowed_hosts: list[str] | None = None
    blocked_hosts: list[str] | None = None


class ExecutionLimits(BaseModel):
    max_duration_seconds: int = 300
    max_agent_turns: int = 60
    max_retries: int = 3
    max_concurrent_executions: int = 2
    max_evidence_storage_mb: int = 500


class SafetyRestrictions(BaseModel):
    production_access_allowed: bool = False
    payment_actions_allowed: bool = False
    account_deletion_allowed: bool = False
    destructive_action_allowlist: list[str] = Field(default_factory=list)
    forbidden_routes: list[str] = Field(default_factory=list)
    forbidden_selectors: list[str] = Field(default_factory=list)


class BrowserSettings(BaseModel):
    viewport_width: int = 1280
    viewport_height: int = 720
    locale: str = "en-US"
    timezone: str = "America/New_York"
    user_agent_override: str | None = None
    block_images: bool = False


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    base_url: str = Field(min_length=1, pattern=r"^https?://.+")
    product_goal: str | None = None
    env_config: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    execution_limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    safety_restrictions: SafetyRestrictions = Field(default_factory=SafetyRestrictions)
    browser_settings: BrowserSettings = Field(default_factory=BrowserSettings)
    test_credentials_ref: uuid.UUID | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    base_url: str | None = None
    product_goal: str | None = None
    env_config: EnvironmentConfig | None = None
    execution_limits: ExecutionLimits | None = None
    safety_restrictions: SafetyRestrictions | None = None
    browser_settings: BrowserSettings | None = None
    test_credentials_ref: uuid.UUID | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None
    base_url: str
    created_at: datetime
    updated_at: datetime
    product_goal: str | None = None
    env_config: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    execution_limits: ExecutionLimits = Field(default_factory=ExecutionLimits)
    safety_restrictions: SafetyRestrictions = Field(default_factory=SafetyRestrictions)
    browser_settings: BrowserSettings = Field(default_factory=BrowserSettings)
    test_credentials_ref: uuid.UUID | None = None

    @field_validator("env_config", mode="before")
    @classmethod
    def _coerce_env_config(cls, v):
        if not v:
            return EnvironmentConfig()
        if isinstance(v, dict):
            return EnvironmentConfig(**v)
        return v

    @field_validator("execution_limits", mode="before")
    @classmethod
    def _coerce_execution_limits(cls, v):
        if not v:
            return ExecutionLimits()
        if isinstance(v, dict):
            return ExecutionLimits(**v)
        return v

    @field_validator("safety_restrictions", mode="before")
    @classmethod
    def _coerce_safety_restrictions(cls, v):
        if not v:
            return SafetyRestrictions()
        if isinstance(v, dict):
            return SafetyRestrictions(**v)
        return v

    @field_validator("browser_settings", mode="before")
    @classmethod
    def _coerce_browser_settings(cls, v):
        if not v:
            return BrowserSettings()
        if isinstance(v, dict):
            return BrowserSettings(**v)
        return v
