import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, JSONCompat


class Organization(Base):
    __tablename__ = "organizations"
    __table_args__ = (
        Index("ix_organizations_slug", "slug", unique=True),
        Index("ix_organizations_owner_user_id", "owner_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    plan: Mapped[str] = mapped_column(
        String(32), nullable=False, default="free", server_default="free"
    )
    tier: Mapped[str] = mapped_column(
        String(32), nullable=False, default="free"
    )
    wrapped_dek: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    owner = relationship("User", foreign_keys=[owner_user_id])
    members = relationship(
        "OrganizationMember", back_populates="organization", cascade="all, delete-orphan"
    )
    quota = relationship(
        "OrganizationQuota", back_populates="organization", uselist=False, cascade="all, delete-orphan"
    )
    projects = relationship("Project", back_populates="organization")
    audit_events = relationship(
        "AuditEvent", back_populates="organization", cascade="all, delete-orphan"
    )


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        Index("ix_org_members_org_user", "org_id", "user_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="member", server_default="member"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    organization = relationship("Organization", back_populates="members")
    user = relationship("User")


class OrganizationQuota(Base):
    __tablename__ = "organization_quotas"
    __table_args__ = (
        Index("ix_organization_quotas_org_id", "org_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    max_concurrent_executions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default="2"
    )
    max_executions_per_day: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, server_default="50"
    )
    max_product_graph_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    max_evidence_storage_mb: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )
    allowed_integrations: Mapped[list] = mapped_column(
        JSONCompat, nullable=False, default=lambda: ["github"]
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    organization = relationship("Organization", back_populates="quota")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        Index("ix_project_members_project_user", "project_id", "user_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="viewer", server_default="viewer"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project = relationship("Project", back_populates="members")
    user = relationship("User")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_org_created", "org_id", "created_at"),
        Index("ix_audit_events_project_id", "project_id"),
        Index("ix_audit_events_actor", "actor_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONCompat, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    organization = relationship("Organization", back_populates="audit_events")
    actor = relationship("User", foreign_keys=[actor_user_id])
    project = relationship("Project", foreign_keys=[project_id])
