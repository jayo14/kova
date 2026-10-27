import pytest

from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.suites.comparison import compare_runs
from app.modules.suites.prioritization import prioritize_flows
from app.modules.suites.schemas import SuiteCreate, SuiteRunRequest, SuiteUpdate
from app.modules.suites.service import SuiteService
from app.modules.users.models import User


def assertion(key: str, status: str) -> dict:
    return {"key": key, "status": status, "type": "check"}


def test_compare_runs_classifies_each_transition():
    baseline = [
        {
            "flow_id": "a",
            "flow_name": "A",
            "status": "passed",
            "assertions": [assertion("login", "passed")],
        },
        {
            "flow_id": "b",
            "flow_name": "B",
            "status": "failed",
            "assertions": [assertion("cart", "failed")],
        },
        {
            "flow_id": "c",
            "flow_name": "C",
            "status": "passed",
            "assertions": [assertion("pay", "passed")],
        },
        {
            "flow_id": "d",
            "flow_name": "D",
            "status": "passed",
            "assertions": [assertion("gone", "passed")],
        },
    ]
    current = [
        {
            "flow_id": "a",
            "flow_name": "A",
            "status": "failed",
            "assertions": [assertion("login", "failed")],
        },
        {
            "flow_id": "b",
            "flow_name": "B",
            "status": "passed",
            "assertions": [assertion("cart", "passed")],
        },
        {
            "flow_id": "c",
            "flow_name": "C",
            "status": "passed",
            "assertions": [assertion("refund", "passed")],
        },
        {
            "flow_id": "e",
            "flow_name": "E",
            "status": "passed",
            "assertions": [assertion("new", "passed")],
        },
    ]

    result = compare_runs(
        baseline_run_id="baseline",
        baseline_reason="explicit",
        baseline_items=baseline,
        current_items=current,
    )

    classes = {flow["flow_id"]: flow["classification"] for flow in result["flows"]}
    assert classes == {
        "a": "new_failure",
        "b": "recovered_failure",
        "c": "changed_test",
        "d": "removed_coverage",
        "e": "new_coverage",
    }
    assert result["verdict"] == "regression"
    assert result["counts"]["new_failure"] == 1


def test_compare_runs_without_baseline_marks_new_coverage():
    result = compare_runs(
        baseline_run_id=None,
        baseline_reason=None,
        baseline_items=None,
        current_items=[
            {"flow_id": "a", "flow_name": "A", "status": "passed", "assertions": []},
        ],
    )
    assert result["flows"][0]["classification"] == "new_coverage"
    assert result["verdict"] == "unchanged"


def test_targeted_mode_only_keeps_changed_flows():
    flows = [
        {
            "id": "1",
            "name": "Checkout",
            "routes": ["/checkout"],
            "criticality": "critical",
        },
        {
            "id": "2",
            "name": "Settings",
            "routes": ["/settings"],
            "criticality": "critical",
        },
    ]
    selected = prioritize_flows(
        flows,
        mode="targeted",
        changed_files=["src/app/checkout/CheckoutPage.tsx"],
    )
    assert [item["name"] for item in selected] == ["Checkout"]
    assert "priority_matched" not in selected[0]
    assert selected[0]["priority_score"] > 0


def test_prioritized_mode_orders_all_flows():
    flows = [
        {"id": "1", "name": "Settings", "routes": ["/settings"], "criticality": "low"},
        {
            "id": "2",
            "name": "Checkout",
            "routes": ["/checkout"],
            "criticality": "critical",
        },
    ]
    selected = prioritize_flows(
        flows,
        mode="prioritized",
        changed_files=["src/app/checkout/page.tsx"],
    )
    assert [item["name"] for item in selected] == ["Checkout", "Settings"]


@pytest.fixture
async def suite_context(db_session):
    user = User(email="suite@example.com", password_hash="x", name="Suite")
    db_session.add(user)
    await db_session.flush()

    project = Project(user_id=user.id, name="Shop", base_url="http://localhost:3000")
    db_session.add(project)
    await db_session.flush()

    flows = []
    for name, route in (
        ("Checkout", "/checkout"),
        ("Login", "/login"),
        ("Search", "/search"),
    ):
        flow = Flow(
            project_id=project.id,
            name=name,
            routes=[route],
            steps=[{"action": "navigate", "url": route}],
            criticality="high",
        )
        db_session.add(flow)
        flows.append(flow)
    await db_session.commit()
    return {"user": user, "project": project, "flows": flows}


class FakeExecutor:
    def __init__(self) -> None:
        self.statuses: dict[str, str] = {}
        self.calls: list[str] = []

    async def __call__(self, flow, run):
        name = flow["name"]
        self.calls.append(name)
        status = self.statuses.get(name, "passed")
        return {
            "status": status,
            "duration_ms": 10,
            "execution_id": None,
            "assertions": [
                assertion("check", status if status != "failed" else "failed")
            ],
            "error": None,
        }


async def test_suite_runs_baseline_comparison_and_flakiness(db_session, suite_context):
    executor = FakeExecutor()
    service = SuiteService(db_session, flow_executor=executor)
    suite = await service.create_suite(
        SuiteCreate(
            project_id=suite_context["project"].id,
            name="Smoke",
            flow_ids=[flow.id for flow in suite_context["flows"]],
        ),
        user_id=suite_context["user"].id,
    )

    first = await service.run_suite(
        suite, SuiteRunRequest(), user_id=suite_context["user"].id
    )
    assert first.status == "completed"
    assert first.baseline_run_id is None
    detail = await service.get_run_with_items(first)
    assert [item.position for item in detail["items"]] == [0, 1, 2]
    assert detail["summary"]["total"] == 3
    assert detail["summary"]["verdict"] == "unchanged"

    executor.statuses["Checkout"] = "failed"
    second = await service.run_suite(
        suite, SuiteRunRequest(), user_id=suite_context["user"].id
    )
    detail = await service.get_run_with_items(second)
    assert second.baseline_run_id == first.id
    assert (
        second.baseline_reason
        == f"latest completed run of suite version 1 ({first.id})"
    )
    assert detail["summary"]["new_failures"] == 1
    assert detail["summary"]["verdict"] == "regression"
    assert detail["summary"]["regressed"] is True
    classes = {item.flow_name: item.classification for item in detail["items"]}
    assert classes["Checkout"] == "new_failure"
    assert classes["Login"] == "stable"

    executor.statuses["Checkout"] = "passed"
    await service.run_suite(suite, SuiteRunRequest(), user_id=suite_context["user"].id)
    executor.statuses["Checkout"] = "failed"
    await service.run_suite(suite, SuiteRunRequest(), user_id=suite_context["user"].id)

    flaky = await service.flakiness(suite.id)
    flows = {flow["flow_name"]: flow for flow in flaky["flows"]}
    assert flows["Checkout"]["flaky"] is True
    assert flows["Checkout"]["transitions"] >= 2
    assert flows["Checkout"]["statuses"] == ["passed", "failed", "passed", "failed"]
    assert flows["Login"]["flaky"] is False


async def test_targeted_run_selects_only_impacted_flow(db_session, suite_context):
    executor = FakeExecutor()
    service = SuiteService(db_session, flow_executor=executor)
    suite = await service.create_suite(
        SuiteCreate(
            project_id=suite_context["project"].id,
            name="Targeted",
            flow_ids=[flow.id for flow in suite_context["flows"]],
        ),
        user_id=suite_context["user"].id,
    )

    run = await service.run_suite(
        suite,
        SuiteRunRequest(mode="targeted", changed_files=["src/app/checkout/page.tsx"]),
        user_id=suite_context["user"].id,
    )
    detail = await service.get_run_with_items(run)
    assert executor.calls == ["Checkout"]
    assert detail["summary"]["total"] == 1
    assert detail["items"][0].flow_name == "Checkout"


async def test_update_flow_set_creates_new_version(db_session, suite_context):
    service = SuiteService(db_session, flow_executor=FakeExecutor())
    flows = suite_context["flows"]
    suite = await service.create_suite(
        SuiteCreate(
            project_id=suite_context["project"].id,
            name="Versioned",
            flow_ids=[flows[0].id],
        ),
        user_id=suite_context["user"].id,
    )

    same = await service.update_suite(
        suite,
        SuiteUpdate(flow_ids=[flows[0].id]),
        user_id=suite_context["user"].id,
    )
    assert same.current_version == 1

    updated = await service.update_suite(
        suite,
        SuiteUpdate(flow_ids=[flows[0].id, flows[1].id], notes="add login"),
        user_id=suite_context["user"].id,
    )
    assert updated.current_version == 2
    version = await service.latest_version(updated)
    assert len(version.flow_snapshot) == 2
    assert version.notes == "add login"


async def test_deleted_flow_is_reported_as_error_without_running(
    db_session, suite_context
):
    service = SuiteService(db_session)
    flow = suite_context["flows"][0]
    suite = await service.create_suite(
        SuiteCreate(
            project_id=suite_context["project"].id, name="Stale", flow_ids=[flow.id]
        ),
        user_id=suite_context["user"].id,
    )

    await db_session.delete(flow)
    await db_session.commit()

    run = await service.run_suite(
        suite,
        SuiteRunRequest(mode="targeted", changed_files=["src/checkout/page.tsx"]),
        user_id=suite_context["user"].id,
    )

    assert run.status == "partial"
    detail = await service.get_run_with_items(run)
    assert detail["summary"]["error"] == 1
    assert detail["items"][0].status == "error"
    assert detail["items"][0].failure_signature == "flow:missing"
    assert detail["items"][0].execution_id is None
