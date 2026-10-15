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
)
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
