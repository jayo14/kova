from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.flows.models import Flow
from app.modules.product_graph.models import (
    ProductAction,
    ProductCapability,
    ProductDependency,
    ProductGoal,
    ProductInvariant,
    ProductPage,
    ProductPersona,
    ProductState,
)
from app.modules.product_graph.repository import ProductGraphRepository
from app.modules.product_graph.schemas import (
    Action,
    Capability,
    Dependency,
    DiscoveryResult,
    FlowGraphNode,
    Goal,
    GraphDiff,
    Invariant,
    Page,
    Persona,
    ProductGraphExport,
    State,
)
from app.modules.projects.models import Project


def _dump_model(m: Any) -> dict:
    if hasattr(m, "model_dump"):
        return m.model_dump()
    return dict(m)


class ProductGraphService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ProductGraphRepository(db)

    async def _get_project(self, project_id: uuid.UUID) -> Project:
        res = await self.db.execute(select(Project).where(Project.id == project_id))
        project = res.scalar_one_or_none()
        if not project:
            raise ValueError(f"Project {project_id} not found")
        return project

    async def export(self, project_id: uuid.UUID) -> dict[str, Any]:
        """Export the complete structured product graph for a project."""
        project = await self._get_project(project_id)

        goals = await self.repo.list_goals_by_project(project_id)
        personas = await self.repo.list_personas_by_project(project_id)
        pages = await self.repo.list_pages_by_project(project_id)
        actions = await self.repo.list_actions_by_project(project_id)
        capabilities = await self.repo.list_capabilities_by_project(project_id)
        states = await self.repo.list_states_by_project(project_id)
        dependencies = await self.repo.list_dependencies_by_project(project_id)
        invariants = await self.repo.list_invariants_by_project(project_id)

        flows_res = await self.db.execute(select(Flow).where(Flow.project_id == project_id))
        flows = list(flows_res.scalars().all())

        export_data = {
            "project_id": str(project_id),
            "version": project.product_graph_version or 1,
            "updated_at": (project.product_graph_updated_at or project.updated_at or datetime.now(timezone.utc)).isoformat(),
            "goals": [Goal.model_validate(g).model_dump(mode="json") for g in goals],
            "personas": [Persona.model_validate(p).model_dump(mode="json") for p in personas],
            "pages": [Page.model_validate(p).model_dump(mode="json") for p in pages],
            "actions": [Action.model_validate(a).model_dump(mode="json") for a in actions],
            "capabilities": [Capability.model_validate(c).model_dump(mode="json") for c in capabilities],
            "states": [State.model_validate(s).model_dump(mode="json") for s in states],
            "flows": [
                {
                    "id": str(f.id),
                    "project_id": str(f.project_id),
                    "name": f.name,
                    "description": f.description,
                    "goal_id": str(f.goal_id) if f.goal_id else None,
                    "persona_id": str(f.persona_id) if f.persona_id else None,
                    "page_ids": f.page_ids or [],
                    "state_contract": f.state_contract or {},
                    "repeatability": f.repeatability,
                    "status": f.status,
                    "criticality": f.criticality,
                }
                for f in flows
            ],
            "dependencies": [Dependency.model_validate(d).model_dump(mode="json") for d in dependencies],
            "invariants": [Invariant.model_validate(i).model_dump(mode="json") for i in invariants],
        }
        return export_data

    async def upsert_from_discovery(
        self, project_id: uuid.UUID, discovery_result: DiscoveryResult
    ) -> dict[str, Any]:
        """Merge discovered entities into the product graph preserving user edits."""
        project = await self._get_project(project_id)

        # 1. Personas
        for persona in discovery_result.personas:
            p_data = _dump_model(persona)
            existing_personas = await self.repo.list_personas_by_project(project_id)
            existing = next((p for p in existing_personas if p.name == p_data["name"]), None)
            if existing:
                merged_caps = list(set((existing.default_capabilities or []) + (p_data.get("default_capabilities") or [])))
                await self.repo.update_persona(existing.id, default_capabilities=merged_caps)
            else:
                await self.repo.create_persona(
                    project_id=project_id,
                    persona_id=uuid.UUID(str(p_data["id"])) if p_data.get("id") else None,
                    name=p_data["name"],
                    description=p_data.get("description"),
                    credentials_required=p_data.get("credentials_required", False),
                    default_capabilities=p_data.get("default_capabilities", []),
                )

        # 2. Goals
        for goal in discovery_result.goals:
            g_data = _dump_model(goal)
            existing_goals = await self.repo.list_goals_by_project(project_id)
            existing = next((g for g in existing_goals if g.name == g_data["name"]), None)
            if existing:
                # Never overwrite a user_provided goal!
                if existing.source != "user_provided":
                    await self.repo.update_goal(
                        existing.id,
                        description=g_data.get("description") or existing.description,
                        persona_id=g_data.get("persona_id") or existing.persona_id,
                        success_criteria=g_data.get("success_criteria") or existing.success_criteria,
                    )
            else:
                await self.repo.create_goal(
                    project_id=project_id,
                    goal_id=uuid.UUID(str(g_data["id"])) if g_data.get("id") else None,
                    name=g_data["name"],
                    description=g_data.get("description"),
                    persona_id=g_data.get("persona_id"),
                    success_criteria=g_data.get("success_criteria", []),
                    source=g_data.get("source", "discovered"),
                )

        # 3. Pages
        page_id_map: dict[uuid.UUID, uuid.UUID] = {}
        for page in discovery_result.pages:
            pg_data = _dump_model(page)
            orig_id = uuid.UUID(str(pg_data["id"])) if pg_data.get("id") else None
            existing = await self.repo.get_page_by_url_pattern(project_id, pg_data["url_pattern"])
            if existing:
                if orig_id:
                    page_id_map[orig_id] = existing.id
                merged_files = list(set((existing.source_files or []) + (pg_data.get("source_files") or [])))
                await self.repo.update_page(
                    existing.id,
                    title=pg_data.get("title") or existing.title,
                    source_files=merged_files,
                    last_seen_at=datetime.now(timezone.utc),
                )
            else:
                new_page_id = orig_id or uuid.uuid4()
                if orig_id:
                    page_id_map[orig_id] = new_page_id
                await self.repo.create_page(
                    project_id=project_id,
                    page_id=new_page_id,
                    url_pattern=pg_data["url_pattern"],
                    title=pg_data.get("title"),
                    requires_auth=pg_data.get("requires_auth", False),
                    required_state=pg_data.get("required_state", []),
                    source_files=pg_data.get("source_files", []),
                )

        # 4. Actions
        for action in discovery_result.actions:
            act_data = _dump_model(action)
            orig_page_id = uuid.UUID(str(act_data["page_id"]))
            target_page_id = page_id_map.get(orig_page_id, orig_page_id)
            target_page = await self.repo.get_page(target_page_id)
            if not target_page:
                continue
            existing_actions = await self.repo.list_actions_by_page(target_page_id)
            existing = next(
                (a for a in existing_actions if a.selector == act_data["selector"] and a.action_type == act_data["action_type"]),
                None,
            )
            if existing:
                await self.repo.update_action(
                    existing.id,
                    name=act_data.get("name") or existing.name,
                    expected_effect=act_data.get("expected_effect") or existing.expected_effect,
                    mutates=act_data.get("mutates") or existing.mutates,
                )
            else:
                await self.repo.create_action(
                    project_id=project_id,
                    action_id=uuid.UUID(str(act_data["id"])) if act_data.get("id") else None,
                    page_id=target_page_id,
                    name=act_data["name"],
                    selector=act_data["selector"],
                    action_type=act_data.get("action_type", "click"),
                    expected_effect=act_data.get("expected_effect", []),
                    mutates=act_data.get("mutates", []),
                )

        # 5. Capabilities — preserve user edits!
        for cap in discovery_result.capabilities:
            c_data = _dump_model(cap)
            existing = await self.repo.get_capability_by_name(project_id, c_data["name"])
            if existing:
                if existing.user_edited:
                    # User edit is preserved! Only union new provider flow IDs
                    new_providers = list(set((existing.provider_flow_ids or []) + (c_data.get("provider_flow_ids") or [])))
                    await self.repo.update_capability(existing.id, provider_flow_ids=new_providers)
                else:
                    merged_files = list(set((existing.source_files or []) + (c_data.get("source_files") or [])))
                    merged_providers = list(set((existing.provider_flow_ids or []) + (c_data.get("provider_flow_ids") or [])))
                    await self.repo.update_capability(
                        existing.id,
                        description=c_data.get("description") or existing.description,
                        requires_capabilities=c_data.get("requires_capabilities") or existing.requires_capabilities,
                        requires_state=c_data.get("requires_state") or existing.requires_state,
                        produces_state=c_data.get("produces_state") or existing.produces_state,
                        kind=c_data.get("kind") or existing.kind,
                        source_files=merged_files,
                        provider_flow_ids=merged_providers,
                    )
            else:
                await self.repo.create_capability(
                    project_id=project_id,
                    capability_id=uuid.UUID(str(c_data["id"])) if c_data.get("id") else None,
                    name=c_data["name"],
                    description=c_data.get("description"),
                    requires_capabilities=c_data.get("requires_capabilities", []),
                    requires_state=c_data.get("requires_state", []),
                    produces_state=c_data.get("produces_state", []),
                    kind=c_data.get("kind", "primary"),
                    source_files=c_data.get("source_files", []),
                    provider_flow_ids=c_data.get("provider_flow_ids", []),
                    user_edited=False,
                )

        # 6. States
        for state in discovery_result.states:
            s_data = _dump_model(state)
            existing = await self.repo.get_state_by_key(project_id, s_data["key"])
            if not existing:
                await self.repo.create_state(
                    project_id=project_id,
                    state_id=uuid.UUID(str(s_data["id"])) if s_data.get("id") else None,
                    key=s_data["key"],
                    value_type=s_data.get("value_type", "bool"),
                    default_value=s_data.get("default_value"),
                    description=s_data.get("description"),
                )

        # 7. Invariants
        for inv in discovery_result.invariants:
            i_data = _dump_model(inv)
            existing_invs = await self.repo.list_invariants_by_project(project_id)
            existing = next((i for i in existing_invs if i.name == i_data["name"]), None)
            if existing:
                merged_flows = list(set((existing.checked_by_flow_ids or []) + (i_data.get("checked_by_flow_ids") or [])))
                await self.repo.update_invariant(
                    existing.id,
                    assertion=i_data.get("assertion") or existing.assertion,
                    checked_by_flow_ids=merged_flows,
                )
            else:
                await self.repo.create_invariant(
                    project_id=project_id,
                    invariant_id=uuid.UUID(str(i_data["id"])) if i_data.get("id") else None,
                    name=i_data["name"],
                    assertion=i_data["assertion"],
                    checked_by_flow_ids=i_data.get("checked_by_flow_ids", []),
                )

        # Bump version and save snapshot
        new_version = (project.product_graph_version or 1) + 1
        project.product_graph_version = new_version
        project.product_graph_updated_at = datetime.now(timezone.utc)
        await self.db.flush()

        snapshot = await self.export(project_id)
        await self.repo.create_version(
            project_id=project_id,
            version=new_version,
            change_summary="Discovery sync",
            snapshot=snapshot,
        )
        await self.db.commit()
        return snapshot

    async def merge_user_edit(
        self,
        project_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        patch: dict[str, Any],
    ) -> Any:
        """Apply a manual user edit to an entity in the product graph, marking it user-edited and bumping version."""
        project = await self._get_project(project_id)

        updated_entity = None
        if entity_type == "capability":
            patch["user_edited"] = True
            updated_entity = await self.repo.update_capability(entity_id, **patch)
        elif entity_type == "goal":
            patch["source"] = "user_provided"
            updated_entity = await self.repo.update_goal(entity_id, **patch)
        elif entity_type == "page":
            updated_entity = await self.repo.update_page(entity_id, **patch)
        elif entity_type == "action":
            updated_entity = await self.repo.update_action(entity_id, **patch)
        elif entity_type == "persona":
            updated_entity = await self.repo.update_persona(entity_id, **patch)
        elif entity_type == "state":
            updated_entity = await self.repo.update_state(entity_id, **patch)
        elif entity_type == "invariant":
            updated_entity = await self.repo.update_invariant(entity_id, **patch)
        else:
            raise ValueError(f"Unknown entity type: {entity_type}")

        if not updated_entity:
            raise ValueError(f"{entity_type} {entity_id} not found")

        # Bump version
        new_version = (project.product_graph_version or 1) + 1
        project.product_graph_version = new_version
        project.product_graph_updated_at = datetime.now(timezone.utc)
        await self.db.flush()

        snapshot = await self.export(project_id)
        await self.repo.create_version(
            project_id=project_id,
            version=new_version,
            change_summary=f"User edit on {entity_type} {entity_id}",
            snapshot=snapshot,
        )
        await self.db.commit()
        return updated_entity

    async def diff(
        self, from_version: int, to_version: int, project_id: uuid.UUID
    ) -> GraphDiff:
        """Compute the structural diff between two product graph versions."""
        v_from = await self.repo.get_version_by_number(project_id, from_version)
        v_to = await self.repo.get_version_by_number(project_id, to_version)

        snap_from = v_from.snapshot if v_from else {}
        snap_to = v_to.snapshot if v_to else {}

        # If to_version is the current version and no snapshot exists yet, export current
        if not snap_to:
            project = await self._get_project(project_id)
            if project.product_graph_version == to_version:
                snap_to = await self.export(project_id)

        entity_keys = [
            "goals",
            "personas",
            "pages",
            "actions",
            "capabilities",
            "states",
            "flows",
            "dependencies",
            "invariants",
        ]

        added: dict[str, list[dict[str, Any]]] = {}
        removed: dict[str, list[dict[str, Any]]] = {}
        changed: dict[str, list[dict[str, Any]]] = {}

        for k in entity_keys:
            from_items = {str(item.get("id") or item.get("key") or item.get("name")): item for item in snap_from.get(k, [])}
            to_items = {str(item.get("id") or item.get("key") or item.get("name")): item for item in snap_to.get(k, [])}

            # Added
            added_ids = set(to_items.keys()) - set(from_items.keys())
            if added_ids:
                added[k] = [to_items[i] for i in added_ids]

            # Removed
            removed_ids = set(from_items.keys()) - set(to_items.keys())
            if removed_ids:
                removed[k] = [from_items[i] for i in removed_ids]

            # Changed
            common_ids = set(from_items.keys()) & set(to_items.keys())
            changes_for_key = []
            for cid in common_ids:
                before = from_items[cid]
                after = to_items[cid]
                # Compare without timestamps
                b_cmp = {k2: v2 for k2, v2 in before.items() if not k2.endswith("_at")}
                a_cmp = {k2: v2 for k2, v2 in after.items() if not k2.endswith("_at")}
                if b_cmp != a_cmp:
                    changes_for_key.append({
                        "id": cid,
                        "before": before,
                        "after": after,
                    })
            if changes_for_key:
                changed[k] = changes_for_key

        return GraphDiff(
            from_version=from_version,
            to_version=to_version,
            added=added,
            removed=removed,
            changed=changed,
        )
