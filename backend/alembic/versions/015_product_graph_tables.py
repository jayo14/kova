"""Add product graph tables and relationships.

Revision ID: 015
Revises: 014
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "015"
down_revision: Union[str, Sequence[str], None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Projects table extensions
    op.add_column("projects", sa.Column("product_graph_version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("projects", sa.Column("product_graph_updated_at", sa.DateTime(timezone=True), nullable=True))

    # 2. Product Personas
    op.create_table(
        "product_personas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("credentials_required", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("default_capabilities", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_personas_project_id", "product_personas", ["project_id"])

    # 3. Product Goals
    op.create_table(
        "product_goals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("persona_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product_personas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("success_criteria", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("source", sa.String(length=32), server_default="discovered", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_goals_project_id", "product_goals", ["project_id"])

    # 4. Product Pages
    op.create_table(
        "product_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url_pattern", sa.String(length=1024), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("requires_auth", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("required_state", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("source_files", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_pages_project_id", "product_pages", ["project_id"])
    op.create_index("ix_product_pages_url_pattern", "product_pages", ["url_pattern"])

    # 5. Product Actions
    op.create_table(
        "product_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("selector", sa.Text(), nullable=False),
        sa.Column("action_type", sa.String(length=32), server_default="click", nullable=False),
        sa.Column("expected_effect", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("mutates", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_actions_project_id", "product_actions", ["project_id"])
    op.create_index("ix_product_actions_page_id", "product_actions", ["page_id"])

    # 6. Product Capabilities
    op.create_table(
        "product_capabilities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("requires_capabilities", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("requires_state", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("produces_state", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("kind", sa.String(length=32), server_default="primary", nullable=False),
        sa.Column("source_files", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("provider_flow_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("user_edited", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_capabilities_project_id", "product_capabilities", ["project_id"])
    op.create_index("ix_product_capabilities_name", "product_capabilities", ["name"])

    # 7. Product States
    op.create_table(
        "product_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value_type", sa.String(length=32), server_default="bool", nullable=False),
        sa.Column("default_value", postgresql.JSONB(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_states_project_id", "product_states", ["project_id"])
    op.create_index("ix_product_states_key", "product_states", ["key"])

    # 8. Flows extensions (goal_id, persona_id, page_ids)
    op.add_column("flows", sa.Column("goal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product_goals.id", ondelete="SET NULL"), nullable=True))
    op.add_column("flows", sa.Column("persona_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("product_personas.id", ondelete="SET NULL"), nullable=True))
    op.add_column("flows", sa.Column("page_ids", postgresql.JSONB(), server_default="[]", nullable=False))

    # 9. Product Dependencies
    op.create_table(
        "product_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("flows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("depends_on_kind", sa.String(length=32), nullable=False),
        sa.Column("depends_on_id", sa.String(length=255), nullable=False),
        sa.Column("required", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_dependencies_project_id", "product_dependencies", ["project_id"])
    op.create_index("ix_product_dependencies_flow_id", "product_dependencies", ["flow_id"])

    # 10. Product Invariants
    op.create_table(
        "product_invariants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("assertion", postgresql.JSONB(), nullable=False),
        sa.Column("checked_by_flow_ids", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("violated_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_invariants_project_id", "product_invariants", ["project_id"])

    # 11. Product Graph Versions
    op.create_table(
        "product_graph_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_product_graph_versions_project_id", "product_graph_versions", ["project_id"])
    op.create_index("ix_product_graph_versions_version", "product_graph_versions", ["project_id", "version"])

    # 12. Migrate legacy data from product_models if present
    conn = op.get_bind()
    try:
        models = conn.execute(sa.text("SELECT id, project_id, version, capabilities, routes, roles FROM product_models")).fetchall()
        for m in models:
            pid = m[1]
            caps = m[3] if isinstance(m[3], list) else []
            for c in caps:
                if isinstance(c, dict) and "name" in c:
                    conn.execute(
                        sa.text(
                            "INSERT INTO product_capabilities (id, project_id, name, description, requires_capabilities, requires_state, produces_state, kind, source_files, provider_flow_ids, user_edited, created_at, updated_at) "
                            "VALUES (:id, :project_id, :name, :description, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, :kind, :source_files, '[]'::jsonb, false, now(), now()) "
                            "ON CONFLICT DO NOTHING"
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "project_id": str(pid),
                            "name": c.get("name"),
                            "description": c.get("description"),
                            "kind": c.get("kind", "primary"),
                            "source_files": str(c.get("source_files", [])).replace("'", '"'),
                        },
                    )
            # Create initial version 1 record
            conn.execute(
                sa.text(
                    "INSERT INTO product_graph_versions (id, project_id, version, change_summary, snapshot, created_at) "
                    "VALUES (:id, :project_id, 1, 'Initial migration from product_models', '{}'::jsonb, now()) "
                    "ON CONFLICT DO NOTHING"
                ),
                {"id": str(uuid.uuid4()), "project_id": str(pid)},
            )
    except Exception:
        # Table might not exist or empty in testing/fresh environments
        pass


def downgrade() -> None:
    op.drop_index("ix_product_graph_versions_version", table_name="product_graph_versions")
    op.drop_index("ix_product_graph_versions_project_id", table_name="product_graph_versions")
    op.drop_table("product_graph_versions")

    op.drop_index("ix_product_invariants_project_id", table_name="product_invariants")
    op.drop_table("product_invariants")

    op.drop_index("ix_product_dependencies_flow_id", table_name="product_dependencies")
    op.drop_index("ix_product_dependencies_project_id", table_name="product_dependencies")
    op.drop_table("product_dependencies")

    op.drop_column("flows", "page_ids")
    op.drop_column("flows", "persona_id")
    op.drop_column("flows", "goal_id")

    op.drop_index("ix_product_states_key", table_name="product_states")
    op.drop_index("ix_product_states_project_id", table_name="product_states")
    op.drop_table("product_states")

    op.drop_index("ix_product_capabilities_name", table_name="product_capabilities")
    op.drop_index("ix_product_capabilities_project_id", table_name="product_capabilities")
    op.drop_table("product_capabilities")

    op.drop_index("ix_product_actions_page_id", table_name="product_actions")
    op.drop_index("ix_product_actions_project_id", table_name="product_actions")
    op.drop_table("product_actions")

    op.drop_index("ix_product_pages_url_pattern", table_name="product_pages")
    op.drop_index("ix_product_pages_project_id", table_name="product_pages")
    op.drop_table("product_pages")

    op.drop_index("ix_product_goals_project_id", table_name="product_goals")
    op.drop_table("product_goals")

    op.drop_index("ix_product_personas_project_id", table_name="product_personas")
    op.drop_table("product_personas")

    op.drop_column("projects", "product_graph_updated_at")
    op.drop_column("projects", "product_graph_version")
