import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship, backref

from app.infrastructure.database.base import Base, JSONCompat


class Flow(Base):
    __tablename__ = "flows"
    __table_args__ = (Index("ix_flows_project_id", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    persona: Mapped[dict | None] = mapped_column(JSONCompat, nullable=True)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    success_condition: Mapped[dict | None] = mapped_column(JSONCompat, nullable=True)
    preconditions: Mapped[dict | None] = mapped_column(JSONCompat, nullable=True)
    dependencies: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    provides_capabilities: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    repeatability: Mapped[str] = mapped_column(String(32), nullable=False, default="repeatable", server_default="repeatable")
    reset_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", server_default="active")
    capability: Mapped[str | None] = mapped_column(String(128), nullable=True)
    routes: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list)
    criticality: Mapped[str] = mapped_column(String(32), nullable=False, default="medium", server_default="medium")
    state_contract: Mapped[dict | None] = mapped_column(JSONCompat, nullable=True, default=dict, server_default="{}")
    goal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_goals.id", ondelete="SET NULL"), nullable=True
    )
    persona_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("product_personas.id", ondelete="SET NULL"), nullable=True
    )
    page_ids: Mapped[list] = mapped_column(JSONCompat, nullable=False, default=list, server_default="[]")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="legacy", server_default="legacy")
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0, server_default="1.0")
    active: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    json_repr: Mapped[dict | None] = mapped_column(JSONCompat, nullable=True)
    gherkin_repr: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project = relationship("Project", backref=backref("flows", passive_deletes=True))
