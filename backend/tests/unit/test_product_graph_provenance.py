import uuid
import pytest
from app.modules.product_graph.schemas import (
    Goal,
    Page,
    Action,
    Capability,
    Persona,
    State,
    Invariant,
    Provenance,
)
from app.modules.product_graph.service import (
    PROVENANCE_PRECEDENCE,
    can_overwrite_provenance,
)
from app.modules.validation.models import (
    ProductModel,
    convert_legacy_product_model_to_graph,
)


def test_provenance_enum_values():
    assert Provenance.OBSERVED.value == "observed"
    assert Provenance.EXPECTED.value == "expected"
    assert Provenance.INFERRED.value == "inferred"
    assert Provenance.USER_PROVIDED.value == "user_provided"


def test_goal_epistemic_fields():
    proj_id = uuid.uuid4()
    goal = Goal(
        project_id=proj_id,
        name="Checkout flow",
        description="User completes checkout",
        business_rules=["Cart must not be empty", "User must agree to terms"],
        negative_scenarios=["Declined credit card", "Expired session during payment"],
        unknowns=["What is the retry limit for 3DS verification?"],
        provenance=Provenance.EXPECTED,
    )
    assert goal.provenance == Provenance.EXPECTED
    assert len(goal.business_rules) == 2
    assert len(goal.negative_scenarios) == 2
    assert len(goal.unknowns) == 1
    assert "Cart must not be empty" in goal.business_rules


def test_entity_schemas_default_provenance():
    proj_id = uuid.uuid4()
    page = Page(project_id=proj_id, url_pattern="/settings")
    assert page.provenance == Provenance.OBSERVED

    action = Action(project_id=proj_id, page_id=uuid.uuid4(), name="Click Save", selector="#save-btn")
    assert action.provenance == Provenance.OBSERVED

    capability = Capability(project_id=proj_id, name="Billing Management")
    assert capability.provenance == Provenance.OBSERVED

    persona = Persona(project_id=proj_id, name="Admin User")
    assert persona.provenance == Provenance.OBSERVED

    state = State(project_id=proj_id, key="is_authenticated")
    assert state.provenance == Provenance.OBSERVED

    goal = Goal(project_id=proj_id, name="Explore settings")
    assert goal.provenance == Provenance.INFERRED


def test_provenance_precedence_rules():
    # User provided has highest precedence
    assert PROVENANCE_PRECEDENCE["user_provided"] > PROVENANCE_PRECEDENCE["observed"]
    assert PROVENANCE_PRECEDENCE["observed"] > PROVENANCE_PRECEDENCE["expected"]
    assert PROVENANCE_PRECEDENCE["expected"] > PROVENANCE_PRECEDENCE["inferred"]

    # Inferred cannot overwrite observed
    assert not can_overwrite_provenance(existing_prov="observed", incoming_prov="inferred")
    # Inferred cannot overwrite user_provided
    assert not can_overwrite_provenance(existing_prov="user_provided", incoming_prov="inferred")
    # Inferred cannot overwrite expected
    assert not can_overwrite_provenance(existing_prov="expected", incoming_prov="inferred")

    # Observed CAN overwrite inferred
    assert can_overwrite_provenance(existing_prov="inferred", incoming_prov="observed")
    # User provided CAN overwrite everything
    assert can_overwrite_provenance(existing_prov="observed", incoming_prov="user_provided")
    assert can_overwrite_provenance(existing_prov="inferred", incoming_prov="user_provided")
    assert can_overwrite_provenance(existing_prov="expected", incoming_prov="user_provided")


def test_convert_legacy_product_model_to_graph():
    proj_id = uuid.uuid4()
    legacy = ProductModel(
        project_id=proj_id,
        routes=["/home", "/login", "/checkout"],
        capabilities=["Authentication", "Cart"],
        roles=["admin", "guest"],
        entities=["user_session", "cart_items"],
    )
    graph_dict = convert_legacy_product_model_to_graph(legacy)
    assert graph_dict["project_id"] == str(proj_id)
    assert len(graph_dict["pages"]) == 3
    assert graph_dict["pages"][0]["url_pattern"] == "/home"
    assert graph_dict["pages"][0]["provenance"] == "observed"
    assert len(graph_dict["capabilities"]) == 2
    assert graph_dict["capabilities"][0]["provenance"] == "observed"
    assert len(graph_dict["personas"]) == 2
    assert len(graph_dict["states"]) == 2


@pytest.mark.asyncio
async def test_upsert_from_discovery_preserves_higher_provenance(mocker):
    from unittest.mock import AsyncMock, MagicMock
    from app.modules.product_graph.service import ProductGraphService
    from app.modules.product_graph.schemas import DiscoveryResult, Goal, Page

    mock_db = MagicMock()
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=mock_res)
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()

    service = ProductGraphService(mock_db)

    # Mock _get_project
    mock_proj = MagicMock()
    mock_proj.id = uuid.uuid4()
    mock_proj.product_graph_version = 1
    mock_proj.product_graph_updated_at = None
    mock_proj.updated_at = None
    service._get_project = AsyncMock(return_value=mock_proj)

    from datetime import datetime, timezone

    # Existing goal is user_provided
    existing_goal = MagicMock()
    existing_goal.id = uuid.uuid4()
    existing_goal.project_id = mock_proj.id
    existing_goal.persona_id = None
    existing_goal.name = "Checkout Goal"
    existing_goal.description = "User checkout"
    existing_goal.source = "user_provided"
    existing_goal.provenance = "user_provided"
    existing_goal.success_criteria = []
    existing_goal.business_rules = []
    existing_goal.negative_scenarios = []
    existing_goal.acceptance_criteria = []
    existing_goal.unknowns = []
    existing_goal.confidence = 1.0
    existing_goal.created_at = datetime.now(timezone.utc)

    service.repo.list_goals_by_project = AsyncMock(return_value=[existing_goal])
    service.repo.list_personas_by_project = AsyncMock(return_value=[])
    service.repo.list_pages_by_project = AsyncMock(return_value=[])
    service.repo.list_actions_by_project = AsyncMock(return_value=[])
    service.repo.list_capabilities_by_project = AsyncMock(return_value=[])
    service.repo.list_states_by_project = AsyncMock(return_value=[])
    service.repo.list_dependencies_by_project = AsyncMock(return_value=[])
    service.repo.list_invariants_by_project = AsyncMock(return_value=[])
    service.repo.create_version = AsyncMock()
    service.repo.update_goal = AsyncMock()

    # Discovered goal has inferred provenance
    discovered_goal = Goal(
        project_id=mock_proj.id,
        name="Checkout Goal",
        description="AI inferred checkout",
        provenance=Provenance.INFERRED,
    )

    discovery = DiscoveryResult(
        pages=[],
        actions=[],
        capabilities=[],
        personas=[],
        goals=[discovered_goal],
        states=[],
        invariants=[],
    )

    await service.upsert_from_discovery(mock_proj.id, discovery)

    # Must NOT update user_provided goal with inferred goal
    service.repo.update_goal.assert_not_called()

