import uuid
import pytest
from datetime import datetime, timezone

from app.modules.flows.models import Flow
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.validation.impact_analysis import ChangeImpactAnalyzer, extract_files_from_diff
from app.modules.validation.models import ProductModel, ValidationRun, ValidationStatus
from app.modules.validation.schemas import (
    DiscoveredCapability,
    ImpactReport,
    ProductModelCreate,
    ProductModelUpdate,
    ValidationCreate,
    ValidationRequest,
    FlowValidationResult,
    ValidationReport,
)
from app.modules.flows.dependency_resolver import ExecutionPlan, ExecutionStep
from app.modules.validation.planner import TargetedRegressionPlanner
from app.modules.validation.runner import ValidationRunner
from app.modules.validation.aggregator import ResultAggregator
from unittest.mock import AsyncMock, MagicMock
from app.modules.validation.selector import RegressionFlowSelector
from app.modules.validation.service import ValidationService


def test_extract_files_from_diff():
    sample_diff = """diff --git a/backend/app/auth/login.py b/backend/app/auth/login.py
--- a/backend/app/auth/login.py
+++ b/backend/app/auth/login.py
@@ -1,3 +1,3 @@
-def login():
+def login_v2():
diff --git a/frontend/components/Navbar.tsx b/frontend/components/Navbar.tsx
+++ b/frontend/components/Navbar.tsx
@@ -1 +1 @@
"""
    files = extract_files_from_diff(sample_diff)
    assert "backend/app/auth/login.py" in files
    assert "frontend/components/Navbar.tsx" in files


def test_impact_analysis_direct_mapping_and_shared_components():
    analyzer = ChangeImpactAnalyzer(
        product_model={
            "capabilities": [
                {
                    "name": "authentication",
                    "routes": ["/login", "/signup"],
                    "source_files": ["backend/app/auth/*"],
                    "kind": "shared",
                },
                {
                    "name": "navigation",
                    "routes": ["/"],
                    "source_files": ["frontend/components/Navbar.tsx"],
                    "kind": "shared",
                },
                {
                    "name": "course_enrollment",
                    "routes": ["/courses/enroll", "/courses"],
                    "source_files": ["app/courses/enroll/page.tsx"],
                },
            ]
        }
    )

    # 1. Course enrollment changes
    report = analyzer.analyze(changed_files=["app/courses/enroll/page.tsx"])
    assert "course_enrollment" in report.affected_capabilities
    assert "/courses/enroll" in report.affected_routes
    assert report.recommended_scope == "targeted"
    assert report.confidence == 1.0
    assert report.product_graph_consulted is True

    # 2. Shared authentication code changes broaden scope and detect auth capability
    report_auth = analyzer.analyze(changed_files=["backend/app/auth/jwt_tokens.py"])
    assert "authentication" in report_auth.affected_capabilities
    assert report_auth.recommended_scope == "expanded"
    assert report_auth.confidence == 0.85
    assert report_auth.product_graph_consulted is True

    # 3. Shared layout/nav changes downstream effects
    report_nav = analyzer.analyze(changed_files=["frontend/components/Navbar.tsx"])
    assert len(report_nav.downstream_effects) > 0
    assert report_nav.recommended_scope == "expanded"

    # 4. Irrelevant file changes flag uncertainty and expand scope rather than silently skipping
    report_unknown = analyzer.analyze(changed_files=["misc/tool.py"])
    assert report_unknown.recommended_scope == "expanded"
    assert report_unknown.confidence == 0.60
    assert len(report_unknown.uncertainty) > 0
    assert "misc/tool.py" in report_unknown.unmatched_files


def test_impact_analysis_empty_product_graph_full_scope():
    analyzer = ChangeImpactAnalyzer(product_model={})
    report = analyzer.analyze(changed_files=["src/foo/bar.ts"])
    assert report.product_graph_consulted is False
    assert report.recommended_scope == "full"
    assert report.confidence == 0.0
    assert report.unmatched_files == ["src/foo/bar.ts"]
    assert "No Product Graph available; cannot perform targeted validation. Run Product Discovery first." in report.uncertainties


def test_impact_analysis_source_file_matching():
    analyzer = ChangeImpactAnalyzer(
        product_model={
            "capabilities": [
                {
                    "name": "custom_widget",
                    "routes": [],
                    "source_files": ["src/foo/bar.ts"],
                }
            ]
        }
    )
    report = analyzer.analyze(changed_files=["src/foo/bar.ts"])
    assert report.affected_capabilities == ["custom_widget"]
    assert report.product_graph_consulted is True
    assert report.unmatched_files == []


def test_impact_analysis_unmatched_file_regression():
    analyzer = ChangeImpactAnalyzer(
        product_model={
            "capabilities": [
                {"name": "cap_a", "source_files": ["src/a.ts"], "routes": []},
                {"name": "cap_b", "source_files": ["src/b.ts"], "routes": []},
            ]
        }
    )
    report = analyzer.analyze(changed_files=["src/widgets/foobar.ts"])
    assert report.unmatched_files == ["src/widgets/foobar.ts"]
    assert "foobar" not in report.affected_capabilities
    assert report.recommended_scope == "expanded"
    assert report.confidence <= 0.60


def test_regression_selector_scopes_and_explanations():
    flow1 = Flow(
        id=uuid.uuid4(),
        name="Login Flow",
        capability="authentication",
        routes=["/login"],
        criticality="critical",
        status="active",
        provides_capabilities=["auth"],
    )
    flow2 = Flow(
        id=uuid.uuid4(),
        name="Enroll in Course",
        capability="course_enrollment",
        routes=["/courses"],
        criticality="high",
        status="active",
        dependencies=[{"kind": "capability", "value": "auth"}],
        provides_capabilities=["enrolled"],
    )
    flow3 = Flow(
        id=uuid.uuid4(),
        name="Submit Assignment",
        capability="assignment_submission",
        routes=["/assignments"],
        criticality="medium",
        status="active",
        dependencies=[{"kind": "capability", "value": "enrolled"}],
    )
    flow_stale = Flow(
        id=uuid.uuid4(),
        name="Deprecated Flow",
        capability="authentication",
        status="stale",
    )

    flows = [flow1, flow2, flow3, flow_stale]
    selector = RegressionFlowSelector(flows)

    # Targeted scope: only course enrollment affected
    impact = ImpactReport(
        changed_files=["app/courses/page.tsx"],
        affected_capabilities=["course_enrollment"],
        affected_routes=["/courses"],
        confidence=1.0,
        recommended_scope="targeted",
    )
    selected, reasons, exclusions = selector.select(impact, scope="targeted")

    # flow2 is directly affected, and flow1 is pulled in automatically as its dependency!
    selected_ids = [str(f.id) for f in selected]
    assert str(flow2.id) in selected_ids
    assert str(flow1.id) in selected_ids
    assert str(flow3.id) not in selected_ids
    assert str(flow_stale.id) not in selected_ids

    # Topological order: prerequisite flow1 must execute before flow2
    assert selected_ids.index(str(flow1.id)) < selected_ids.index(str(flow2.id))

    # Reasons are explainable
    assert "directly affected capability" in reasons[str(flow2.id)]
    assert "Prerequisite dependency" in reasons[str(flow1.id)]
    assert "Flow is marked as stale" in exclusions[str(flow_stale.id)]

    # Full regression: all active flows selected
    full_selected, full_reasons, _ = selector.select(impact, scope="full")
    full_ids = [str(f.id) for f in full_selected]
    assert str(flow1.id) in full_ids
    assert str(flow2.id) in full_ids
    assert str(flow3.id) in full_ids
    assert str(flow_stale.id) not in full_ids


def test_previously_failing_flow_included_for_defect_recovery():
    flow1 = Flow(id=uuid.uuid4(), name="Flow 1", capability="misc", status="active")
    flow2 = Flow(id=uuid.uuid4(), name="Flow 2", capability="other", status="active")
    selector = RegressionFlowSelector([flow1, flow2])

    impact = ImpactReport(changed_files=["file.txt"], affected_capabilities=["misc"], confidence=1.0)
    # flow2 failed previously, so it must be included even if capability doesn't match
    selected, reasons, _ = selector.select(
        impact, scope="targeted", previously_failing_flow_ids={str(flow2.id)}
    )
    selected_ids = [str(f.id) for f in selected]
    assert str(flow1.id) in selected_ids
    assert str(flow2.id) in selected_ids
    assert "verify defect recovery" in reasons[str(flow2.id)]


@pytest.mark.asyncio
async def test_product_model_versioning_and_persistence(db_session):
    user = User(id=uuid.uuid4(), email="pm-user@kova.local")
    db_session.add(user)
    await db_session.commit()

    project = Project(id=uuid.uuid4(), user_id=user.id, name="Kova Academy", base_url="https://academy.test")
    db_session.add(project)
    await db_session.commit()

    service = ValidationService(db_session)

    # 1. First retrieval seeds version 1
    m1 = await service.get_latest_product_model(project.id)
    assert m1.version == 1
    assert m1.name == "Kova Academy Model"
    assert len(m1.capabilities) >= 2

    # 2. Updating persists version 2 without overwriting historical version 1
    m2 = await service.update_product_model(
        project.id,
        ProductModelUpdate(
            name="Kova Academy Model v2",
            capabilities=[{"name": "grading", "routes": ["/grades"]}],
        ),
    )
    await db_session.commit()
    assert m2.version == 2

    history = await service.list_product_models(project.id)
    assert len(history) == 2
    versions = [h.version for h in history]
    assert versions == [2, 1]


def test_baseline_diff_computation():
    service = ValidationService(None)
    current_map = {
        "flow-1": "COMPLETED",
        "flow-2": "FAILED",
        "flow-3": "BLOCKED",
        "flow-4": "COMPLETED",
    }
    baseline_map = {
        "flow-1": "FAILED",      # recovered
        "flow-2": "COMPLETED",   # newly failing
        "flow-4": "COMPLETED",   # unchanged passing
    }

    diff = service._compute_baseline_diff(
        current_map=current_map,
        baseline_map=baseline_map,
        baseline_id=uuid.uuid4(),
    )

    assert "flow-2" in diff.newly_failing
    assert "flow-1" in diff.recovered
    assert "flow-4" in diff.unchanged_passing
    assert "flow-3" in diff.blocked
    assert len(diff.status_changed) >= 2


@pytest.fixture
def lms_product_graph():
    """Realistic LMS product graph fixture with ~10 flows, dependencies, state contracts, and invariants."""
    f_auth_id = str(uuid.uuid4())
    f_browse_id = str(uuid.uuid4())
    f_enroll_id = str(uuid.uuid4())
    f_submit_id = str(uuid.uuid4())
    f_grade_id = str(uuid.uuid4())
    f_discuss_id = str(uuid.uuid4())
    f_profile_id = str(uuid.uuid4())
    f_inactive_id = str(uuid.uuid4())

    p_courses_id = str(uuid.uuid4())
    p_enroll_id = str(uuid.uuid4())
    p_assignment_id = str(uuid.uuid4())
    p_grades_id = str(uuid.uuid4())
    p_discuss_id = str(uuid.uuid4())

    return {
        "capabilities": [
            {
                "id": str(uuid.uuid4()),
                "name": "authentication",
                "kind": "shared",
                "source_files": ["src/components/AuthProvider.tsx", "src/auth/login.ts"],
                "routes": ["/login"],
                "produces_state": [{"key": "authenticated:student"}],
                "provider_flow_ids": [f_auth_id],
            },
            {
                "id": str(uuid.uuid4()),
                "name": "course_browsing",
                "kind": "primary",
                "source_files": ["src/pages/Course.tsx", "src/components/CourseList.tsx"],
                "routes": ["/courses"],
                "provider_flow_ids": [f_browse_id],
            },
            {
                "id": str(uuid.uuid4()),
                "name": "course_enrollment",
                "kind": "primary",
                "source_files": ["src/api/enrollment.ts", "src/pages/Enroll.tsx"],
                "routes": ["/courses/enroll"],
                "produces_state": [{"key": "enrolled:course_X"}],
                "provider_flow_ids": [f_enroll_id],
            },
            {
                "id": str(uuid.uuid4()),
                "name": "assignment_submission",
                "kind": "primary",
                "source_files": ["src/pages/Assignment.tsx"],
                "routes": ["/assignments"],
                "produces_state": [{"key": "assignment:submitted"}],
                "provider_flow_ids": [f_submit_id],
            },
            {
                "id": str(uuid.uuid4()),
                "name": "grade_viewing",
                "kind": "primary",
                "source_files": ["src/pages/Grades.tsx"],
                "routes": ["/grades"],
                "produces_state": [{"key": "grade:viewed"}],
                "provider_flow_ids": [f_grade_id],
            },
            {
                "id": str(uuid.uuid4()),
                "name": "discussions",
                "kind": "primary",
                "source_files": ["src/pages/Discussion.tsx"],
                "routes": ["/discussions"],
                "provider_flow_ids": [f_discuss_id],
            },
        ],
        "pages": [
            {"id": p_courses_id, "url_pattern": "/courses", "source_files": ["src/pages/Course.tsx"]},
            {"id": p_enroll_id, "url_pattern": "/courses/enroll", "source_files": ["src/pages/Enroll.tsx"]},
            {"id": p_assignment_id, "url_pattern": "/assignments", "source_files": ["src/pages/Assignment.tsx"]},
            {"id": p_grades_id, "url_pattern": "/grades", "source_files": ["src/pages/Grades.tsx"]},
            {"id": p_discuss_id, "url_pattern": "/discussions", "source_files": ["src/pages/Discussion.tsx"]},
        ],
        "flows": [
            {
                "id": f_auth_id,
                "name": "authenticate_as_student",
                "capability": "authentication",
                "routes": ["/login"],
                "status": "active",
                "active": True,
                "state_contract": {
                    "produces": [{"key": "authenticated:student", "value": True}],
                },
            },
            {
                "id": f_browse_id,
                "name": "browse_courses",
                "capability": "course_browsing",
                "page_ids": [p_courses_id],
                "routes": ["/courses"],
                "status": "active",
                "active": True,
                "dependencies": [{"kind": "capability", "value": "authentication"}],
                "state_contract": {
                    "requires": [{"key": "authenticated:student", "value": True}],
                },
            },
            {
                "id": f_enroll_id,
                "name": "enroll_in_course",
                "capability": "course_enrollment",
                "page_ids": [p_courses_id, p_enroll_id],
                "routes": ["/courses/enroll"],
                "status": "active",
                "active": True,
                "dependencies": [{"kind": "capability", "value": "authentication"}],
                "state_contract": {
                    "requires": [{"key": "authenticated:student", "value": True}],
                    "produces": [{"key": "enrolled:course_X", "value": True}],
                    "mutates": ["enrolled:course_X"],
                },
            },
            {
                "id": f_submit_id,
                "name": "submit_assignment",
                "capability": "assignment_submission",
                "page_ids": [p_assignment_id],
                "routes": ["/assignments"],
                "status": "active",
                "active": True,
                "dependencies": [
                    {"kind": "capability", "value": "authentication"},
                    {"kind": "flow", "value": f_enroll_id},
                ],
                "state_contract": {
                    "requires": [
                        {"key": "authenticated:student", "value": True},
                        {"key": "enrolled:course_X", "value": True},
                    ],
                    "produces": [{"key": "assignment:submitted", "value": True}],
                    "mutates": ["assignment.status"],
                },
            },
            {
                "id": f_grade_id,
                "name": "view_grade",
                "capability": "grade_viewing",
                "page_ids": [p_grades_id],
                "routes": ["/grades"],
                "status": "active",
                "active": True,
                "dependencies": [{"kind": "capability", "value": "authentication"}],
                "state_contract": {
                    "requires": [
                        {"key": "authenticated:student", "value": True},
                        {"key": "enrolled:course_X", "value": True},
                        {"key": "assignment:submitted", "value": True},
                    ],
                    "produces": [{"key": "grade:viewed", "value": True}],
                },
            },
            {
                "id": f_discuss_id,
                "name": "participate_in_discussion",
                "capability": "discussions",
                "page_ids": [p_discuss_id],
                "routes": ["/discussions"],
                "status": "active",
                "active": True,
                "dependencies": [{"kind": "capability", "value": "authentication"}],
                "state_contract": {
                    "requires": [{"key": "authenticated:student", "value": True}],
                },
            },
            {
                "id": f_profile_id,
                "name": "view_student_profile",
                "capability": "authentication",
                "routes": ["/profile"],
                "status": "active",
                "active": True,
                "dependencies": [{"kind": "capability", "value": "authentication"}],
                "state_contract": {
                    "requires": [{"key": "authenticated:student", "value": True}],
                },
            },
            {
                "id": f_inactive_id,
                "name": "draft_unreviewed_flow",
                "capability": "course_browsing",
                "status": "inactive",
                "active": False,
                "state_contract": {},
            },
        ],
        "dependencies": [
            {
                "id": str(uuid.uuid4()),
                "flow_id": f_browse_id,
                "depends_on_kind": "flow",
                "depends_on_id": f_auth_id,
            },
            {
                "id": str(uuid.uuid4()),
                "flow_id": f_submit_id,
                "depends_on_kind": "flow",
                "depends_on_id": f_enroll_id,
            },
        ],
        "invariants": [
            {
                "id": str(uuid.uuid4()),
                "name": "Enrolled courses appear on dashboard",
                "assertion": {"key": "enrolled:course_X", "predicate": "eq", "value": True},
                "checked_by_flow_ids": [f_enroll_id],
            }
        ],
    }


def test_graph_traversal_direct_match(lms_product_graph):
    """Direct match: change src/pages/Course.tsx -> affected_flows includes browse_courses and enroll_in_course."""
    analyzer = ChangeImpactAnalyzer(product_graph=lms_product_graph)
    report = analyzer.analyze(changed_files=["src/pages/Course.tsx"])

    assert "course_browsing" in report.affected_capabilities
    affected_flow_names = {f.name for f in report.affected_flows}
    assert "browse_courses" in affected_flow_names
    assert "enroll_in_course" in affected_flow_names
    # Inactive flows must never be included
    assert "draft_unreviewed_flow" not in affected_flow_names


def test_graph_traversal_state_downstream(lms_product_graph):
    """State downstream: change src/api/enrollment.ts -> affected_flows includes enroll_in_course,

    submit_assignment, and view_grade (because they consume enrolled:course_X).
    Target's prerequisites (authenticate_as_student) must NOT be in affected_flows.
    """
    analyzer = ChangeImpactAnalyzer(product_graph=lms_product_graph)
    report = analyzer.analyze(changed_files=["src/api/enrollment.ts"])

    affected_flow_names = {f.name for f in report.affected_flows}
    assert "enroll_in_course" in affected_flow_names
    assert "submit_assignment" in affected_flow_names
    assert "view_grade" in affected_flow_names

    # Crucial anti-pattern check: authenticate_as_student is a prerequisite, NOT an affected flow!
    assert "authenticate_as_student" not in affected_flow_names

    # However, authenticate_as_student MUST be sequenced in minimal_execution_plan
    assert report.minimal_execution_plan is not None
    plan_step_names = [s.flow_name for s in report.minimal_execution_plan.steps]
    assert "authenticate_as_student" in plan_step_names
    assert plan_step_names[0] == "authenticate_as_student"


def test_graph_traversal_dependency_downstream_shared_component(lms_product_graph):
    """Dependency downstream: change src/components/AuthProvider.tsx (shared component)

    -> affected_flows includes every authenticated flow depending on the shared capability.
    """
    analyzer = ChangeImpactAnalyzer(product_graph=lms_product_graph)
    report = analyzer.analyze(changed_files=["src/components/AuthProvider.tsx"])

    assert "authentication" in report.affected_capabilities
    assert report.recommended_scope == "expanded"
    assert report.confidence <= 0.85

    affected_flow_names = {f.name for f in report.affected_flows}
    assert "browse_courses" in affected_flow_names
    assert "enroll_in_course" in affected_flow_names
    assert "submit_assignment" in affected_flow_names
    assert "view_grade" in affected_flow_names
    assert "participate_in_discussion" in affected_flow_names
    assert "view_student_profile" in affected_flow_names


def test_graph_traversal_invariants(lms_product_graph):
    """Invariants: changing enrollment code affects invariant referencing enrolled:course_X."""
    analyzer = ChangeImpactAnalyzer(product_graph=lms_product_graph)
    report = analyzer.analyze(changed_files=["src/api/enrollment.ts"])

    assert len(report.affected_invariants) > 0
    inv_names = {inv.name for inv in report.affected_invariants}
    assert "Enrolled courses appear on dashboard" in inv_names


def test_graph_traversal_minimum_plan_deduplicates_prerequisites(lms_product_graph):
    """Minimum plan de-duplicates: affected_flows includes submit_assignment and view_grade,

    both requiring authenticated:student -> minimal_execution_plan includes authenticate_as_student once.
    """
    analyzer = ChangeImpactAnalyzer(product_graph=lms_product_graph)
    # Changing enrollment triggers both submit_assignment and view_grade downstream
    report = analyzer.analyze(changed_files=["src/api/enrollment.ts"])

    assert report.minimal_execution_plan is not None
    plan_steps = report.minimal_execution_plan.steps
    auth_steps = [s for s in plan_steps if s.flow_name == "authenticate_as_student"]
    assert len(auth_steps) == 1, "authenticate_as_student must appear exactly once in the plan"


def test_graph_traversal_missing_graph_graceful():
    """Missing graph: empty Product Graph -> minimal_execution_plan == None, confidence == 0.0, scope == full."""
    analyzer = ChangeImpactAnalyzer(product_graph={})
    report = analyzer.analyze(changed_files=["src/components/Foo.tsx"])

    assert report.minimal_execution_plan is None
    assert report.confidence == 0.0
    assert report.recommended_scope == "full"
    assert "No Product Graph available" in report.uncertainty[0]
    assert len(report.graph_traversal_log) > 0


def test_graph_traversal_audit_log(lms_product_graph):
    """Graph traversal audit log contains human-readable entries recording traversal decisions."""
    analyzer = ChangeImpactAnalyzer(product_graph=lms_product_graph)
    report = analyzer.analyze(changed_files=["src/api/enrollment.ts"])

    log = report.graph_traversal_log
    assert any("enrollment" in entry for entry in log)
    assert any("produces state" in entry for entry in log)
    assert any("State downstream traversal added" in entry for entry in log)
    assert any("Minimum execution plan:" in entry for entry in log)


def test_graph_traversal_filters_inactive_flows(lms_product_graph):
    """Unreviewed or inactive flows must never be included in affected flows or execution plan."""
    analyzer = ChangeImpactAnalyzer(product_graph=lms_product_graph)
    report = analyzer.analyze(changed_files=["src/pages/Course.tsx"])

    affected_flow_names = {f.name for f in report.affected_flows}
    assert "draft_unreviewed_flow" not in affected_flow_names

    if report.minimal_execution_plan:
        plan_flow_names = {s.flow_name for s in report.minimal_execution_plan.steps}
        assert "draft_unreviewed_flow" not in plan_flow_names


@pytest.mark.asyncio
async def test_planner_with_populated_graph(lms_product_graph):
    """Planner on populated graph returns impact report and minimal execution plan."""
    planner = TargetedRegressionPlanner(product_graph=lms_product_graph)
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        changed_files=["src/pages/Enroll.tsx"],
    )
    impact, plan = await planner.plan(req)
    assert impact is not None
    assert "course_enrollment" in impact.affected_capabilities
    assert plan is not None
    step_names = [s.flow_name for s in plan.steps]
    assert "enroll_in_course" in step_names
    # Topological order: prerequisite auth comes before enroll
    auth_idx = step_names.index("authenticate_as_student")
    enroll_idx = step_names.index("enroll_in_course")
    assert auth_idx < enroll_idx


@pytest.mark.asyncio
async def test_planner_with_empty_graph():
    """Planner on empty graph returns confidence 0.0 and None plan."""
    planner = TargetedRegressionPlanner(product_graph={})
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        changed_files=["src/pages/Enroll.tsx"],
    )
    impact, plan = await planner.plan(req)
    assert plan is None
    assert impact.confidence == 0.0
    assert not impact.product_graph_consulted


@pytest.mark.asyncio
async def test_runner_passes_when_all_flows_pass(lms_product_graph):
    """When all target flows pass, overall status is 'passed' and passing prerequisites are omitted from results."""
    planner = TargetedRegressionPlanner(product_graph=lms_product_graph)
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        changed_files=["src/pages/Enroll.tsx"],
    )
    impact, plan = await planner.plan(req)

    mock_exec_service = MagicMock()
    mock_exec_service.batch_execute = AsyncMock(
        return_value=[
            {
                "flow_id": str(uuid.uuid4()),
                "flow_name": "authenticate_as_student",
                "role": "prerequisite",
                "status": "passed",
                "duration_ms": 150,
                "evidence_ids": [str(uuid.uuid4())],
            },
            {
                "flow_id": str(uuid.uuid4()),
                "flow_name": "enroll_in_course",
                "role": "target",
                "status": "passed",
                "duration_ms": 320,
                "evidence_ids": [str(uuid.uuid4()), str(uuid.uuid4())],
                "evidence_counts": {"screenshots": 1, "network_logs": 1},
            },
        ]
    )

    runner = ValidationRunner(execution_service=mock_exec_service)
    report = await runner.run(req, plan=plan, impact_report=impact)

    assert report.overall_status == "passed"
    # Passing prerequisite must be omitted to prevent report pollution
    assert len(report.results) == 1
    assert report.results[0].flow_name == "enroll_in_course"
    assert report.results[0].status == "passed"
    assert len(report.results[0].evidence_ids) == 2
    assert report.evidence_summary.get("screenshots") == 1


@pytest.mark.asyncio
async def test_runner_fails_when_any_flow_fails(lms_product_graph):
    """When any target flow fails, overall status is 'failed'."""
    planner = TargetedRegressionPlanner(product_graph=lms_product_graph)
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        changed_files=["src/pages/Enroll.tsx"],
    )
    impact, plan = await planner.plan(req)

    mock_exec_service = MagicMock()
    mock_exec_service.batch_execute = AsyncMock(
        return_value=[
            {
                "flow_id": str(uuid.uuid4()),
                "flow_name": "enroll_in_course",
                "role": "target",
                "status": "failed",
                "duration_ms": 320,
                "failure_reason": "Button not found",
            },
        ]
    )

    runner = ValidationRunner(execution_service=mock_exec_service)
    report = await runner.run(req, plan=plan, impact_report=impact)

    assert report.overall_status == "failed"
    assert report.results[0].failure_reason == "Button not found"


@pytest.mark.asyncio
async def test_runner_unverified_when_any_flow_unverified(lms_product_graph):
    """When a target flow is unverified, overall status is 'unverified'."""
    planner = TargetedRegressionPlanner(product_graph=lms_product_graph)
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        changed_files=["src/pages/Enroll.tsx"],
    )
    impact, plan = await planner.plan(req)

    mock_exec_service = MagicMock()
    mock_exec_service.batch_execute = AsyncMock(
        return_value=[
            {
                "flow_id": str(uuid.uuid4()),
                "flow_name": "enroll_in_course",
                "role": "target",
                "status": "unverified",
                "duration_ms": 200,
                "failure_reason": "Could not confirm enrollment badge",
            },
        ]
    )

    runner = ValidationRunner(execution_service=mock_exec_service)
    report = await runner.run(req, plan=plan, impact_report=impact)

    assert report.overall_status == "unverified"


@pytest.mark.asyncio
async def test_runner_no_graph():
    """Missing graph reports 'no_graph' fail-closed and executes no flows."""
    mock_exec_service = MagicMock()
    mock_exec_service.batch_execute = AsyncMock()

    runner = ValidationRunner(execution_service=mock_exec_service)
    req = ValidationRequest(project_id=uuid.uuid4(), changed_files=["src/pages/Enroll.tsx"])
    impact = ImpactReport(
        changed_files=["src/pages/Enroll.tsx"],
        confidence=0.0,
        product_graph_consulted=False,
    )
    report = await runner.run(req, plan=None, impact_report=impact)

    assert report.overall_status == "no_graph"
    assert report.results == []
    mock_exec_service.batch_execute.assert_not_called()


@pytest.mark.asyncio
async def test_runner_no_flows_affected(lms_product_graph):
    """Empty plan reports 'no_flows' fail-closed and executes no flows."""
    mock_exec_service = MagicMock()
    mock_exec_service.batch_execute = AsyncMock()

    runner = ValidationRunner(execution_service=mock_exec_service)
    req = ValidationRequest(project_id=uuid.uuid4(), changed_files=["README.md"])
    impact = ImpactReport(
        changed_files=["README.md"],
        confidence=1.0,
        product_graph_consulted=True,
    )
    plan = ExecutionPlan(steps=[])
    report = await runner.run(req, plan=plan, impact_report=impact)

    assert report.overall_status == "no_flows"
    assert report.results == []
    mock_exec_service.batch_execute.assert_not_called()


@pytest.mark.asyncio
async def test_runner_prereq_failure_marks_run_failed(lms_product_graph):
    """If a prerequisite fails, overall status is 'failed' and the failed prerequisite is reported."""
    planner = TargetedRegressionPlanner(product_graph=lms_product_graph)
    req = ValidationRequest(
        project_id=uuid.uuid4(),
        changed_files=["src/pages/Enroll.tsx"],
    )
    impact, plan = await planner.plan(req)

    mock_exec_service = MagicMock()
    mock_exec_service.batch_execute = AsyncMock(
        return_value=[
            {
                "flow_id": str(uuid.uuid4()),
                "flow_name": "authenticate_as_student",
                "role": "prerequisite",
                "status": "failed",
                "duration_ms": 110,
                "failure_reason": "Invalid credentials",
            },
            {
                "flow_id": str(uuid.uuid4()),
                "flow_name": "enroll_in_course",
                "role": "target",
                "status": "skipped",
                "duration_ms": 0,
            },
        ]
    )

    runner = ValidationRunner(execution_service=mock_exec_service)
    report = await runner.run(req, plan=plan, impact_report=impact)

    assert report.overall_status == "failed"
    names = [r.flow_name for r in report.results]
    assert "authenticate_as_student" in names
    prereq_res = next(r for r in report.results if r.flow_name == "authenticate_as_student")
    assert prereq_res.failure_reason == "Invalid credentials"

