import uuid
import pytest
from pydantic import ValidationError

from app.modules.flows.schemas import FlowStateContract, StateAssertion, StateMutation
from app.modules.product_graph.schemas import (
    Action,
    Capability,
    Dependency,
    FlowGraphNode,
    Goal,
    GraphDiff,
    Invariant,
    Page,
    Persona,
    ProductGraphExport,
    State,
)


def test_goal_roundtrip():
    project_id = uuid.uuid4()
    persona_id = uuid.uuid4()
    assertion = StateAssertion(key="authenticated", value=True, predicate="eq")
    goal = Goal(
        project_id=project_id,
        name="Student enrollment",
        description="Allows student to enroll in course",
        persona_id=persona_id,
        success_criteria=[assertion],
        source="user_provided",
    )
    dumped = goal.model_dump()
    reconstructed = Goal.model_validate(dumped)
    assert reconstructed.id == goal.id
    assert reconstructed.name == "Student enrollment"
    assert reconstructed.source == "user_provided"
    assert len(reconstructed.success_criteria) == 1
    assert reconstructed.success_criteria[0].key == "authenticated"


def test_persona_roundtrip():
    project_id = uuid.uuid4()
    persona = Persona(
        project_id=project_id,
        name="instructor",
        description="Creates courses and grades students",
        credentials_required=True,
        default_capabilities=["grading", "course_creation"],
    )
    dumped = persona.model_dump()
    reconstructed = Persona.model_validate(dumped)
    assert reconstructed.name == "instructor"
    assert reconstructed.credentials_required is True
    assert "grading" in reconstructed.default_capabilities


def test_page_url_pattern_normalization():
    project_id = uuid.uuid4()
    # Leading slash added, duplicate slashes collapsed, trailing slash removed
    page1 = Page(project_id=project_id, url_pattern="courses//:id")
    assert page1.url_pattern == "/courses/:id"

    page2 = Page(project_id=project_id, url_pattern="//courses///:id/")
    assert page2.url_pattern == "/courses/:id"

    page3 = Page(project_id=project_id, url_pattern="")
    assert page3.url_pattern == "/"

    page4 = Page(project_id=project_id, url_pattern="/")
    assert page4.url_pattern == "/"

    page5 = Page(project_id=project_id, url_pattern="dashboard")
    assert page5.url_pattern == "/dashboard"


def test_action_roundtrip():
    project_id = uuid.uuid4()
    page_id = uuid.uuid4()
    action = Action(
        project_id=project_id,
        page_id=page_id,
        name="Submit Form",
        selector="button[type='submit']",
        action_type="submit",
        expected_effect=[StateAssertion(key="form_submitted", value=True)],
        mutates=["form_submitted"],
    )
    dumped = action.model_dump()
    reconstructed = Action.model_validate(dumped)
    assert reconstructed.name == "Submit Form"
    assert reconstructed.action_type == "submit"
    assert reconstructed.mutates == ["form_submitted"]


def test_capability_roundtrip():
    project_id = uuid.uuid4()
    cap = Capability(
        project_id=project_id,
        name="course_enrollment",
        description="Enroll student in course",
        requires_capabilities=["authentication"],
        requires_state=[StateAssertion(key="authenticated", value=True)],
        produces_state=[StateMutation(key="enrolled", action="set", value=True)],
        kind="primary",
        source_files=["app/routes/enroll.py"],
        provider_flow_ids=["flow-123"],
        user_edited=True,
    )
    dumped = cap.model_dump()
    reconstructed = Capability.model_validate(dumped)
    assert reconstructed.name == "course_enrollment"
    assert reconstructed.kind == "primary"
    assert reconstructed.user_edited is True
    assert len(reconstructed.produces_state) == 1
    assert reconstructed.produces_state[0].key == "enrolled"


def test_state_roundtrip():
    project_id = uuid.uuid4()
    state = State(
        project_id=project_id,
        key="authenticated",
        value_type="bool",
        default_value=False,
        description="Whether user has an active session",
    )
    dumped = state.model_dump()
    reconstructed = State.model_validate(dumped)
    assert reconstructed.key == "authenticated"
    assert reconstructed.value_type == "bool"
    assert reconstructed.default_value is False


def test_dependency_roundtrip():
    project_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    dep = Dependency(
        project_id=project_id,
        flow_id=flow_id,
        depends_on_kind="capability",
        depends_on_id="authentication",
        required=True,
    )
    dumped = dep.model_dump()
    reconstructed = Dependency.model_validate(dumped)
    assert reconstructed.depends_on_kind == "capability"
    assert reconstructed.depends_on_id == "authentication"
    assert reconstructed.required is True


def test_invariant_roundtrip():
    project_id = uuid.uuid4()
    inv = Invariant(
        project_id=project_id,
        name="No negative balances",
        assertion=StateAssertion(key="balance_non_negative", value=True, predicate="eq"),
        checked_by_flow_ids=["flow-1"],
        violated_count=0,
    )
    dumped = inv.model_dump()
    reconstructed = Invariant.model_validate(dumped)
    assert reconstructed.name == "No negative balances"
    assert reconstructed.assertion.key == "balance_non_negative"


def test_invalid_state_assertion_predicate_rejected():
    with pytest.raises(ValidationError):
        StateAssertion(key="logged_in", value=True, predicate="invalid_predicate")  # type: ignore


def test_flow_state_contract_agreement():
    """Ensure FlowGraphNode and FlowStateContract agree with chunk 03 schemas."""
    contract = FlowStateContract(
        requires=[StateAssertion(key="authenticated", value=True, predicate="eq")],
        produces=[StateAssertion(key="profile_updated", value=True, predicate="eq")],
        consumes=["temp_token"],
        mutates=["user_profile"],
        cost=3,
        reset_strategy="re_establish",
    )
    node = FlowGraphNode(
        project_id=uuid.uuid4(),
        name="Update Profile Flow",
        state_contract=contract,
        repeatability="repeatable",
        status="active",
        criticality="high",
    )
    assert node.state_contract is not None
    assert node.state_contract.cost == 3
    assert node.state_contract.reset_strategy == "re_establish"
    assert len(node.state_contract.requires) == 1
    assert len(node.state_contract.produces) == 1
