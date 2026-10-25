import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, JSONCompat


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (Index("ix_projects_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    product_graph_version: Mapped[int] = mapped_column(
        default=1, server_default="1"
    )
    product_graph_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True
    )

    product_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    env_config: Mapped[dict] = mapped_column(JSONCompat, default=dict, server_default="{}")
    execution_limits: Mapped[dict] = mapped_column(JSONCompat, default=dict, server_default="{}")
    safety_restrictions: Mapped[dict] = mapped_column(JSONCompat, default=dict, server_default="{}")
    browser_settings: Mapped[dict] = mapped_column(JSONCompat, default=dict, server_default="{}")
    test_credentials_ref: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("credentials.id", ondelete="SET NULL", use_alter=True), nullable=True
    )

    user = relationship("User", backref="projects")
    organization = relationship("Organization", back_populates="projects")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")

    @property
    def logo_url(self) -> str | None:
        """Returns the project's brand logo or favicon URL from env_config or base_url."""
        if isinstance(self.env_config, dict):
            val = self.env_config.get("logo_url") or self.env_config.get("favicon_url")
            if val:
                return val
        if self.base_url:
            import re
            from urllib.parse import urlparse
            try:
                host = urlparse(self.base_url).hostname
                if host:
                    clean_host = re.sub(r"^www\d*\.", "", host.lower())
                    return f"https://www.google.com/s2/favicons?domain={clean_host}&sz=128"
            except Exception:
                pass
        return None
