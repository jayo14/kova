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
