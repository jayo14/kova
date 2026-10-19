import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, JSONCompat


class ProductGoal(Base):
    __tablename__ = "product_goals"
    __table_args__ = (
        Index("ix_product_goals_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_personas.id", ondelete="SET NULL"), nullable=True
    )
    success_criteria: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    business_rules: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list, server_default="[]")
    negative_scenarios: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list, server_default="[]")
    acceptance_criteria: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list, server_default="[]")
    unknowns: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list, server_default="[]")
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="inferred", server_default="inferred")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="discovered")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProductPersona(Base):
    __tablename__ = "product_personas"
    __table_args__ = (
        Index("ix_product_personas_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    credentials_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    default_capabilities: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="observed", server_default="observed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )



class ProductPage(Base):
    __tablename__ = "product_pages"
    __table_args__ = (
        Index("ix_product_pages_project_id", "project_id"),
        Index("ix_product_pages_url_pattern", "url_pattern"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    url_pattern: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requires_auth: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required_state: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    source_files: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="observed", server_default="observed")
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProductAction(Base):
    __tablename__ = "product_actions"
    __table_args__ = (
        Index("ix_product_actions_project_id", "project_id"),
        Index("ix_product_actions_page_id", "page_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("product_pages.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    selector: Mapped[str] = mapped_column(Text, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False, default="click")
    expected_effect: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    mutates: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="observed", server_default="observed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProductCapability(Base):
    __tablename__ = "product_capabilities"
    __table_args__ = (
        Index("ix_product_capabilities_project_id", "project_id"),
        Index("ix_product_capabilities_name", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_capabilities: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    requires_state: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    produces_state: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="primary")
    source_files: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    provider_flow_ids: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    user_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="observed", server_default="observed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProductState(Base):
    __tablename__ = "product_states"
    __table_args__ = (
        Index("ix_product_states_project_id", "project_id"),
        Index("ix_product_states_key", "key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    value_type: Mapped[str] = mapped_column(String(32), nullable=False, default="bool")
    default_value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(
        JSONCompat, nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="observed", server_default="observed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProductDependency(Base):
    __tablename__ = "product_dependencies"
    __table_args__ = (
        Index("ix_product_dependencies_project_id", "project_id"),
        Index("ix_product_dependencies_flow_id", "flow_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("flows.id", ondelete="CASCADE"), nullable=False
    )
    depends_on_kind: Mapped[str] = mapped_column(String(32), nullable=False)  # "flow", "capability", "state"
    depends_on_id: Mapped[str] = mapped_column(String(255), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ProductInvariant(Base):
    __tablename__ = "product_invariants"
    __table_args__ = (
        Index("ix_product_invariants_project_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    assertion: Mapped[dict] = mapped_column(JSONCompat, nullable=False)
    checked_by_flow_ids: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    violated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provenance: Mapped[str] = mapped_column(String(32), nullable=False, default="observed", server_default="observed")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )



class ProductGraphVersion(Base):
    __tablename__ = "product_graph_versions"
    __table_args__ = (
        Index("ix_product_graph_versions_project_id", "project_id"),
        Index("ix_product_graph_versions_version", "project_id", "version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONCompat, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
