from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.flows.models import Flow
from app.modules.product_graph.models import (
    ProductAction,
    ProductCapability,
    ProductDependency,
    ProductGoal,
    ProductGraphVersion,
    ProductInvariant,
    ProductPage,
    ProductPersona,
    ProductState,
)


class ProductGraphRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ----------------- Goal -----------------
    async def create_goal(
        self,
        project_id: uuid.UUID,
        name: str,
        description: str | None = None,
        persona_id: uuid.UUID | None = None,
        success_criteria: list[dict] | None = None,
        source: str = "discovered",
        goal_id: uuid.UUID | None = None,
    ) -> ProductGoal:
        goal = ProductGoal(
            id=goal_id or uuid.uuid4(),
            project_id=project_id,
            name=name,
            description=description,
            persona_id=persona_id,
            success_criteria=success_criteria or [],
            source=source,
        )
        self.db.add(goal)
        await self.db.flush()
        return goal

    async def get_goal(self, goal_id: uuid.UUID) -> ProductGoal | None:
        result = await self.db.execute(select(ProductGoal).where(ProductGoal.id == goal_id))
        return result.scalar_one_or_none()

    async def list_goals_by_project(self, project_id: uuid.UUID) -> list[ProductGoal]:
        result = await self.db.execute(select(ProductGoal).where(ProductGoal.project_id == project_id))
        return list(result.scalars().all())

    async def update_goal(self, goal_id: uuid.UUID, **kwargs: Any) -> ProductGoal | None:
        goal = await self.get_goal(goal_id)
        if not goal:
            return None
        for key, value in kwargs.items():
            if hasattr(goal, key) and value is not None:
                setattr(goal, key, value)
        await self.db.flush()
        await self.db.refresh(goal)
        return goal

    async def delete_goal(self, goal_id: uuid.UUID) -> bool:
        goal = await self.get_goal(goal_id)
        if not goal:
            return False
        await self.db.delete(goal)
        await self.db.flush()
        return True

    # ----------------- Persona -----------------
    async def create_persona(
        self,
        project_id: uuid.UUID,
        name: str,
        description: str | None = None,
        credentials_required: bool = False,
        default_capabilities: list[str] | None = None,
        persona_id: uuid.UUID | None = None,
    ) -> ProductPersona:
        persona = ProductPersona(
            id=persona_id or uuid.uuid4(),
            project_id=project_id,
            name=name,
            description=description,
            credentials_required=credentials_required,
            default_capabilities=default_capabilities or [],
        )
        self.db.add(persona)
        await self.db.flush()
        return persona

    async def get_persona(self, persona_id: uuid.UUID) -> ProductPersona | None:
        result = await self.db.execute(select(ProductPersona).where(ProductPersona.id == persona_id))
        return result.scalar_one_or_none()

    async def list_personas_by_project(self, project_id: uuid.UUID) -> list[ProductPersona]:
        result = await self.db.execute(select(ProductPersona).where(ProductPersona.project_id == project_id))
        return list(result.scalars().all())

    async def update_persona(self, persona_id: uuid.UUID, **kwargs: Any) -> ProductPersona | None:
        persona = await self.get_persona(persona_id)
        if not persona:
            return None
        for key, value in kwargs.items():
            if hasattr(persona, key) and value is not None:
                setattr(persona, key, value)
        await self.db.flush()
        await self.db.refresh(persona)
        return persona

    async def delete_persona(self, persona_id: uuid.UUID) -> bool:
        persona = await self.get_persona(persona_id)
        if not persona:
            return False
        await self.db.delete(persona)
        await self.db.flush()
        return True

    # ----------------- Page -----------------
    async def create_page(
        self,
        project_id: uuid.UUID,
        url_pattern: str,
        title: str | None = None,
        requires_auth: bool = False,
        required_state: list[dict] | None = None,
        source_files: list[str] | None = None,
        page_id: uuid.UUID | None = None,
    ) -> ProductPage:
        page = ProductPage(
            id=page_id or uuid.uuid4(),
            project_id=project_id,
            url_pattern=url_pattern,
            title=title,
            requires_auth=requires_auth,
            required_state=required_state or [],
            source_files=source_files or [],
        )
        self.db.add(page)
        await self.db.flush()
        return page

    async def get_page(self, page_id: uuid.UUID) -> ProductPage | None:
        result = await self.db.execute(select(ProductPage).where(ProductPage.id == page_id))
        return result.scalar_one_or_none()

    async def get_page_by_url_pattern(self, project_id: uuid.UUID, url_pattern: str) -> ProductPage | None:
        result = await self.db.execute(
            select(ProductPage).where(
                ProductPage.project_id == project_id,
                ProductPage.url_pattern == url_pattern,
            )
        )
        return result.scalar_one_or_none()

    async def list_pages_by_project(self, project_id: uuid.UUID) -> list[ProductPage]:
        result = await self.db.execute(select(ProductPage).where(ProductPage.project_id == project_id))
        return list(result.scalars().all())

    async def update_page(self, page_id: uuid.UUID, **kwargs: Any) -> ProductPage | None:
        page = await self.get_page(page_id)
        if not page:
            return None
        for key, value in kwargs.items():
            if hasattr(page, key) and value is not None:
                setattr(page, key, value)
        await self.db.flush()
        await self.db.refresh(page)
        return page

    async def delete_page(self, page_id: uuid.UUID) -> bool:
        page = await self.get_page(page_id)
        if not page:
            return False
        await self.db.delete(page)
        await self.db.flush()
        return True

    # ----------------- Action -----------------
    async def create_action(
        self,
        project_id: uuid.UUID,
        page_id: uuid.UUID,
        name: str,
        selector: str,
        action_type: str = "click",
        expected_effect: list[dict] | None = None,
        mutates: list[str] | None = None,
        action_id: uuid.UUID | None = None,
    ) -> ProductAction:
        action = ProductAction(
            id=action_id or uuid.uuid4(),
            project_id=project_id,
            page_id=page_id,
            name=name,
            selector=selector,
            action_type=action_type,
            expected_effect=expected_effect or [],
            mutates=mutates or [],
        )
        self.db.add(action)
        await self.db.flush()
        return action

    async def get_action(self, action_id: uuid.UUID) -> ProductAction | None:
        result = await self.db.execute(select(ProductAction).where(ProductAction.id == action_id))
        return result.scalar_one_or_none()

    async def list_actions_by_page(self, page_id: uuid.UUID) -> list[ProductAction]:
        result = await self.db.execute(select(ProductAction).where(ProductAction.page_id == page_id))
        return list(result.scalars().all())

    async def list_actions_by_project(self, project_id: uuid.UUID) -> list[ProductAction]:
        result = await self.db.execute(select(ProductAction).where(ProductAction.project_id == project_id))
        return list(result.scalars().all())

    async def update_action(self, action_id: uuid.UUID, **kwargs: Any) -> ProductAction | None:
        action = await self.get_action(action_id)
        if not action:
            return None
        for key, value in kwargs.items():
            if hasattr(action, key) and value is not None:
                setattr(action, key, value)
        await self.db.flush()
        await self.db.refresh(action)
        return action

    async def delete_action(self, action_id: uuid.UUID) -> bool:
        action = await self.get_action(action_id)
        if not action:
            return False
        await self.db.delete(action)
        await self.db.flush()
        return True

    # ----------------- Capability -----------------
    async def create_capability(
        self,
        project_id: uuid.UUID,
        name: str,
        description: str | None = None,
        requires_capabilities: list[str] | None = None,
        requires_state: list[dict] | None = None,
        produces_state: list[dict] | None = None,
        kind: str = "primary",
        source_files: list[str] | None = None,
        provider_flow_ids: list[str] | None = None,
        user_edited: bool = False,
        capability_id: uuid.UUID | None = None,
    ) -> ProductCapability:
        capability = ProductCapability(
            id=capability_id or uuid.uuid4(),
            project_id=project_id,
            name=name,
            description=description,
            requires_capabilities=requires_capabilities or [],
            requires_state=requires_state or [],
            produces_state=produces_state or [],
            kind=kind,
            source_files=source_files or [],
            provider_flow_ids=provider_flow_ids or [],
            user_edited=user_edited,
        )
        self.db.add(capability)
        await self.db.flush()
        return capability

    async def get_capability(self, capability_id: uuid.UUID) -> ProductCapability | None:
        result = await self.db.execute(select(ProductCapability).where(ProductCapability.id == capability_id))
        return result.scalar_one_or_none()

    async def get_capability_by_name(self, project_id: uuid.UUID, name: str) -> ProductCapability | None:
        result = await self.db.execute(
            select(ProductCapability).where(
                ProductCapability.project_id == project_id,
                ProductCapability.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def list_capabilities_by_project(self, project_id: uuid.UUID) -> list[ProductCapability]:
        result = await self.db.execute(
            select(ProductCapability).where(ProductCapability.project_id == project_id)
        )
        return list(result.scalars().all())

    async def update_capability(self, capability_id: uuid.UUID, **kwargs: Any) -> ProductCapability | None:
        capability = await self.get_capability(capability_id)
        if not capability:
            return None
        for key, value in kwargs.items():
            if hasattr(capability, key) and value is not None:
                setattr(capability, key, value)
        await self.db.flush()
        await self.db.refresh(capability)
        return capability

    async def delete_capability(self, capability_id: uuid.UUID) -> bool:
        capability = await self.get_capability(capability_id)
        if not capability:
            return False
        await self.db.delete(capability)
        await self.db.flush()
        return True

    # ----------------- State -----------------
    async def create_state(
        self,
        project_id: uuid.UUID,
        key: str,
        value_type: str = "bool",
        default_value: Any = None,
        description: str | None = None,
        state_id: uuid.UUID | None = None,
    ) -> ProductState:
        state = ProductState(
            id=state_id or uuid.uuid4(),
            project_id=project_id,
            key=key,
            value_type=value_type,
            default_value=default_value,
            description=description,
        )
        self.db.add(state)
        await self.db.flush()
        return state

    async def get_state(self, state_id: uuid.UUID) -> ProductState | None:
        result = await self.db.execute(select(ProductState).where(ProductState.id == state_id))
        return result.scalar_one_or_none()

    async def get_state_by_key(self, project_id: uuid.UUID, key: str) -> ProductState | None:
        result = await self.db.execute(
            select(ProductState).where(
                ProductState.project_id == project_id,
                ProductState.key == key,
            )
        )
        return result.scalar_one_or_none()

    async def list_states_by_project(self, project_id: uuid.UUID) -> list[ProductState]:
        result = await self.db.execute(select(ProductState).where(ProductState.project_id == project_id))
        return list(result.scalars().all())

    async def update_state(self, state_id: uuid.UUID, **kwargs: Any) -> ProductState | None:
        state = await self.get_state(state_id)
        if not state:
            return None
        for key, value in kwargs.items():
            if hasattr(state, key) and value is not None:
                setattr(state, key, value)
        await self.db.flush()
        await self.db.refresh(state)
        return state

    async def delete_state(self, state_id: uuid.UUID) -> bool:
        state = await self.get_state(state_id)
        if not state:
            return False
        await self.db.delete(state)
        await self.db.flush()
        return True

    # ----------------- Dependency -----------------
    async def create_dependency(
        self,
        project_id: uuid.UUID,
        flow_id: uuid.UUID,
        depends_on_kind: str,
        depends_on_id: str,
        required: bool = True,
        dependency_id: uuid.UUID | None = None,
    ) -> ProductDependency:
        dep = ProductDependency(
            id=dependency_id or uuid.uuid4(),
            project_id=project_id,
            flow_id=flow_id,
            depends_on_kind=depends_on_kind,
            depends_on_id=depends_on_id,
            required=required,
        )
        self.db.add(dep)
        await self.db.flush()
        return dep

    async def get_dependency(self, dependency_id: uuid.UUID) -> ProductDependency | None:
        result = await self.db.execute(
            select(ProductDependency).where(ProductDependency.id == dependency_id)
        )
        return result.scalar_one_or_none()

    async def list_dependencies_by_flow(self, flow_id: uuid.UUID) -> list[ProductDependency]:
        result = await self.db.execute(
            select(ProductDependency).where(ProductDependency.flow_id == flow_id)
        )
        return list(result.scalars().all())

    async def list_dependencies_by_project(self, project_id: uuid.UUID) -> list[ProductDependency]:
        result = await self.db.execute(
            select(ProductDependency).where(ProductDependency.project_id == project_id)
        )
        return list(result.scalars().all())

    async def delete_dependency(self, dependency_id: uuid.UUID) -> bool:
        dep = await self.get_dependency(dependency_id)
        if not dep:
            return False
        await self.db.delete(dep)
        await self.db.flush()
        return True

    # ----------------- Invariant -----------------
    async def create_invariant(
        self,
        project_id: uuid.UUID,
        name: str,
        assertion: dict,
        checked_by_flow_ids: list[str] | None = None,
        violated_count: int = 0,
        invariant_id: uuid.UUID | None = None,
    ) -> ProductInvariant:
        inv = ProductInvariant(
            id=invariant_id or uuid.uuid4(),
            project_id=project_id,
            name=name,
            assertion=assertion,
            checked_by_flow_ids=checked_by_flow_ids or [],
            violated_count=violated_count,
        )
        self.db.add(inv)
        await self.db.flush()
        return inv

    async def get_invariant(self, invariant_id: uuid.UUID) -> ProductInvariant | None:
        result = await self.db.execute(
            select(ProductInvariant).where(ProductInvariant.id == invariant_id)
        )
        return result.scalar_one_or_none()

    async def list_invariants_by_project(self, project_id: uuid.UUID) -> list[ProductInvariant]:
        result = await self.db.execute(
            select(ProductInvariant).where(ProductInvariant.project_id == project_id)
        )
        return list(result.scalars().all())

    async def update_invariant(self, invariant_id: uuid.UUID, **kwargs: Any) -> ProductInvariant | None:
        inv = await self.get_invariant(invariant_id)
        if not inv:
            return None
        for key, value in kwargs.items():
            if hasattr(inv, key) and value is not None:
                setattr(inv, key, value)
        await self.db.flush()
        await self.db.refresh(inv)
        return inv

    async def delete_invariant(self, invariant_id: uuid.UUID) -> bool:
        inv = await self.get_invariant(invariant_id)
        if not inv:
            return False
        await self.db.delete(inv)
        await self.db.flush()
        return True

    # ----------------- Versions -----------------
    async def create_version(
        self,
        project_id: uuid.UUID,
        version: int,
        change_summary: str | None = None,
        snapshot: dict | None = None,
    ) -> ProductGraphVersion:
        v = ProductGraphVersion(
            id=uuid.uuid4(),
            project_id=project_id,
            version=version,
            change_summary=change_summary,
            snapshot=snapshot or {},
        )
        self.db.add(v)
        await self.db.flush()
        return v

    async def get_latest_version(self, project_id: uuid.UUID) -> ProductGraphVersion | None:
        result = await self.db.execute(
            select(ProductGraphVersion)
            .where(ProductGraphVersion.project_id == project_id)
            .order_by(desc(ProductGraphVersion.version))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_version_by_number(
        self, project_id: uuid.UUID, version: int
    ) -> ProductGraphVersion | None:
        result = await self.db.execute(
            select(ProductGraphVersion).where(
                ProductGraphVersion.project_id == project_id,
                ProductGraphVersion.version == version,
            )
        )
        return result.scalar_one_or_none()

    async def list_versions_by_project(self, project_id: uuid.UUID) -> list[ProductGraphVersion]:
        result = await self.db.execute(
            select(ProductGraphVersion)
            .where(ProductGraphVersion.project_id == project_id)
            .order_by(ProductGraphVersion.version.asc())
        )
        return list(result.scalars().all())

    # ----------------- Graph-Traversal Helpers -----------------
    async def flows_producing_capability(
        self, project_id: uuid.UUID, capability_name: str
    ) -> list[Flow]:
        """Return all flows in a project that produce or provide capability_name."""
        flows_res = await self.db.execute(
            select(Flow).where(Flow.project_id == project_id)
        )
        all_flows = list(flows_res.scalars().all())

        # Also get capability provider_flow_ids
        cap = await self.get_capability_by_name(project_id, capability_name)
        explicit_provider_ids = set(cap.provider_flow_ids) if cap and cap.provider_flow_ids else set()

        matching = []
        for flow in all_flows:
            flow_id_str = str(flow.id)
            if flow_id_str in explicit_provider_ids:
                matching.append(flow)
                continue
            if flow.capability == capability_name:
                matching.append(flow)
                continue
            if capability_name in (flow.provides_capabilities or []):
                matching.append(flow)
                continue
            # Check state_contract productions
            if flow.state_contract and cap and cap.produces_state:
                produces_keys = {p.get("key") for p in flow.state_contract.get("produces", [])}
                target_keys = {m.get("key") for m in cap.produces_state}
                if target_keys and target_keys.issubset(produces_keys):
                    matching.append(flow)
                    continue

        return matching

    async def flows_requiring_state(
        self, project_id: uuid.UUID, state_key: str
    ) -> list[Flow]:
        """Return all flows in a project that require state_key."""
        flows_res = await self.db.execute(
            select(Flow).where(Flow.project_id == project_id)
        )
        all_flows = list(flows_res.scalars().all())

        matching = []
        for flow in all_flows:
            # Check state_contract.requires
            if flow.state_contract:
                requires = flow.state_contract.get("requires", [])
                if any(r.get("key") == state_key for r in requires if isinstance(r, dict)):
                    matching.append(flow)
                    continue
            # Check preconditions dict
            if flow.preconditions and state_key in flow.preconditions:
                matching.append(flow)
                continue
        return matching

    async def pages_touched_by_flow(self, flow_id: uuid.UUID) -> list[ProductPage]:
        """Return all pages touched by flow_id via page_ids or route matching."""
        flow_res = await self.db.execute(select(Flow).where(Flow.id == flow_id))
        flow = flow_res.scalar_one_or_none()
        if not flow:
            return []

        pages_res = await self.db.execute(
            select(ProductPage).where(ProductPage.project_id == flow.project_id)
        )
        all_pages = list(pages_res.scalars().all())

        page_ids_set = {str(pid) for pid in (flow.page_ids or [])}
        routes_set = set(flow.routes or [])

        # Also extract navigation URLs from flow steps
        for step in (flow.steps or []):
            if isinstance(step, dict):
                act = step.get("action") or step.get("type")
                if act == "navigate":
                    val = step.get("url") or step.get("value")
                    if val and isinstance(val, str):
                        routes_set.add(val)

        matching = []
        for page in all_pages:
            if str(page.id) in page_ids_set:
                matching.append(page)
            elif page.url_pattern in routes_set:
                matching.append(page)
            elif any(r.endswith(page.url_pattern) or page.url_pattern.endswith(r) for r in routes_set):
                matching.append(page)

        return matching

    async def capabilities_produced_by_flow(
        self, flow_id: uuid.UUID
    ) -> list[ProductCapability]:
        """Return all capabilities produced by flow_id."""
        flow_res = await self.db.execute(select(Flow).where(Flow.id == flow_id))
        flow = flow_res.scalar_one_or_none()
        if not flow:
            return []

        caps_res = await self.db.execute(
            select(ProductCapability).where(ProductCapability.project_id == flow.project_id)
        )
        all_caps = list(caps_res.scalars().all())

        flow_id_str = str(flow.id)
        matching = []
        for cap in all_caps:
            if flow_id_str in (cap.provider_flow_ids or []):
                matching.append(cap)
            elif cap.name == flow.capability:
                matching.append(cap)
            elif cap.name in (flow.provides_capabilities or []):
                matching.append(cap)

        return matching

    async def invariants_checked_by_flow(
        self, flow_id: uuid.UUID
    ) -> list[ProductInvariant]:
        """Return all invariants checked by flow_id."""
        flow_res = await self.db.execute(select(Flow).where(Flow.id == flow_id))
        flow = flow_res.scalar_one_or_none()
        if not flow:
            return []

        invs_res = await self.db.execute(
            select(ProductInvariant).where(ProductInvariant.project_id == flow.project_id)
        )
        all_invs = list(invs_res.scalars().all())

        flow_id_str = str(flow.id)
        return [inv for inv in all_invs if flow_id_str in (inv.checked_by_flow_ids or [])]
