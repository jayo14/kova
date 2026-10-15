from types import SimpleNamespace
import uuid

import pytest

from app.modules.flows.dependency_resolver import DependencyResolutionError, resolve_dependency_plan


def flow(name, *, dependencies=None, provides=None, steps=None):
    return SimpleNamespace(
        id=uuid.uuid4(), version=1, name=name, steps=steps or [], preconditions=None,
        success_condition={"text_visible": f"{name} ready"},
        dependencies=dependencies or [], provides_capabilities=provides or [],
    )


def test_dependency_plan_is_ordered_and_deduplicated():
    auth = flow("auth", provides=["authenticated"])
    data = flow("data", dependencies=[{"kind": "capability", "value": "authenticated"}], provides=["has-data"])
    target = flow("target", dependencies=[
        {"kind": "flow", "value": str(data.id)},
        {"kind": "capability", "value": "authenticated"},
    ])
    plan = resolve_dependency_plan(target, [auth, data, target])
    assert [item["id"] for item in plan] == [str(auth.id), str(data.id)]


def test_dependency_plan_rejects_missing_capability():
    target = flow("target", dependencies=[{"kind": "capability", "value": "authenticated"}])
    with pytest.raises(DependencyResolutionError) as err:
        resolve_dependency_plan(target, [target])
    assert err.value.code == "MISSING_CAPABILITY"


def test_dependency_plan_rejects_ambiguous_capability():
    target = flow("target", dependencies=[{"kind": "capability", "value": "authenticated"}])
    providers = [flow("one", provides=["authenticated"]), flow("two", provides=["authenticated"]), target]
    with pytest.raises(DependencyResolutionError) as err:
        resolve_dependency_plan(target, providers)
    assert err.value.code == "AMBIGUOUS_CAPABILITY"


def test_dependency_plan_detects_cycles():
    one = flow("one")
    two = flow("two")
    one.dependencies = [{"kind": "flow", "value": str(two.id)}]
    two.dependencies = [{"kind": "flow", "value": str(one.id)}]
    with pytest.raises(DependencyResolutionError) as err:
        resolve_dependency_plan(one, [one, two])
    assert err.value.code == "DEPENDENCY_CYCLE"


def state_flow(name, *, requires=None, produces=None, consumes=None, mutates=None, reset_strategy="none", cost=1, persona=None, requires_credential=False):
    from app.modules.flows.schemas import FlowStateContract
    contract = FlowStateContract(
        requires=requires or [],
        produces=produces or [],
        consumes=consumes or [],
        mutates=mutates or [],
        reset_strategy=reset_strategy if reset_strategy in {"none", "re_establish", "create_new", "skip_if_exists"} else "create_new",
        cost=cost,
        persona=persona,
        requires_credential=requires_credential,
    )
    return SimpleNamespace(
        id=uuid.uuid4(),
        version=1,
        name=name,
        steps=[],
        preconditions=None,
        success_condition={"text_visible": f"{name} ready"},
        state_contract=contract,
        dependencies=[],
        provides_capabilities=[],
        reset_strategy=reset_strategy,
        persona=persona,
        cost=cost,
    )


def test_resolve_execution_plan_linear():
    from app.modules.flows.dependency_resolver import resolve_execution_plan
    from app.modules.flows.schemas import StateAssertion

    c = state_flow("C", produces=[StateAssertion(key="Y", value=True)])
    b = state_flow("B", requires=[StateAssertion(key="Y", value=True)], produces=[StateAssertion(key="X", value=True)])
    a = state_flow("A", requires=[StateAssertion(key="X", value=True)])

    plan = resolve_execution_plan(a, [a, b, c])
    assert [s.flow_id for s in plan.steps] == [str(c.id), str(b.id), str(a.id)]
    assert plan.steps[0].role == "prerequisite"
    assert plan.steps[1].role == "prerequisite"
    assert plan.steps[2].role == "target"
    assert plan.unresolved == []
    assert plan.estimated_cost == 3


def test_resolve_execution_plan_reusable_capability():
    from app.modules.flows.dependency_resolver import resolve_execution_plan
    from app.modules.flows.schemas import StateAssertion

    c = state_flow("C", produces=[StateAssertion(key="authenticated", value=True)])
    a = state_flow("A", requires=[StateAssertion(key="authenticated", value=True)])
    b = state_flow("B", requires=[StateAssertion(key="authenticated", value=True)])

    plan = resolve_execution_plan([a, b], [a, b, c])
    assert [s.flow_id for s in plan.steps] == [str(c.id), str(a.id), str(b.id)]
    assert plan.steps[0].role == "prerequisite"
    assert plan.steps[1].role == "target"
    assert plan.steps[2].role == "target"
    assert plan.unresolved == []


def test_resolve_execution_plan_state_contamination():
    from app.modules.flows.dependency_resolver import resolve_execution_plan
    from app.modules.flows.schemas import StateAssertion

    a = state_flow(
        "A",
        produces=[StateAssertion(key="assignment_submitted", value=True)],
        mutates=["assignment.status"],
        reset_strategy="create_new_assignment",
    )
    b = state_flow("B", requires=[StateAssertion(key="assignment_available", value=True)])
    reset_flow = state_flow("create_new_assignment", produces=[StateAssertion(key="assignment_available", value=True)])

    plan = resolve_execution_plan([a, b], [a, b, reset_flow])
    assert [s.flow_id for s in plan.steps] == [str(a.id), str(reset_flow.id), str(b.id)]
    assert plan.steps[1].role == "teardown"
    assert any("State contamination detected" in w for w in plan.warnings)


def test_resolve_execution_plan_unsatisfiable():
    from app.modules.flows.dependency_resolver import resolve_execution_plan
    from app.modules.flows.schemas import StateAssertion

    a = state_flow("A", requires=[StateAssertion(key="superuser", value=True)])
    plan = resolve_execution_plan(a, [a])
    assert len(plan.unresolved) == 1
    assert plan.unresolved[0].key == "superuser"
    assert plan.steps == []
    assert plan.estimated_cost == 0


def test_resolve_execution_plan_cycle():
    from app.modules.flows.dependency_resolver import resolve_execution_plan
    from app.modules.flows.schemas import StateAssertion

    a = state_flow("A", requires=[StateAssertion(key="X", value=True)], produces=[StateAssertion(key="Y", value=True)])
    b = state_flow("B", requires=[StateAssertion(key="Y", value=True)], produces=[StateAssertion(key="X", value=True)])

    plan = resolve_execution_plan(a, [a, b])
    assert len(plan.unresolved) > 0
    assert any("cycle" in w.lower() for w in plan.warnings)
    assert plan.steps == []


def test_resolve_execution_plan_cost_and_current_state():
    from app.modules.flows.dependency_resolver import resolve_execution_plan
    from app.modules.flows.schemas import StateAssertion

    cheap = state_flow("CheapLogin", produces=[StateAssertion(key="authenticated", value=True)], cost=1)
    expensive = state_flow("ExpensiveSignup", produces=[StateAssertion(key="authenticated", value=True)], cost=10)
    target = state_flow("Target", requires=[StateAssertion(key="authenticated", value=True)])

    # Prefers lowest cost
    plan = resolve_execution_plan(target, [target, expensive, cheap])
    assert [s.flow_id for s in plan.steps] == [str(cheap.id), str(target.id)]
    assert any("Alternative capability providers available" in w for w in plan.warnings)

    # When already authenticated in current_state, skip setup
    plan_with_state = resolve_execution_plan(target, [target, expensive, cheap], current_state={"authenticated": True})
    assert [s.flow_id for s in plan_with_state.steps] == [str(target.id)]
