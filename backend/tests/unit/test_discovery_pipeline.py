import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.engine.exploration.discovery.ai_assistant import AIAssistant
from app.engine.exploration.discovery.auth_detector import AuthDetector
from app.engine.exploration.discovery.capability_extractor import CapabilityExtractor
from app.engine.exploration.discovery.crawler import DiscoveryCrawler, parameterize_url_path
from app.engine.exploration.discovery.invariant_inferrer import InvariantInferrer
from app.engine.exploration.discovery.persona_detector import PersonaDetector
from app.engine.exploration.discovery.pipeline import DiscoveryPipeline
from app.modules.product_graph.schemas import (
    Action,
    Capability,
    DiscoveryResult,
    Goal,
    Invariant,
    Page,
    StateAssertion,
    StateMutation,
)


def test_parameterize_url_path():
    assert parameterize_url_path("/courses/123") == "/courses/:id"
    assert parameterize_url_path("/courses/a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11") == "/courses/:id"
    assert parameterize_url_path("/dashboard") == "/dashboard"
    assert parameterize_url_path("/") == "/"


@pytest.mark.asyncio
async def test_discovery_crawler_bfs_and_depth_budget():
    project_id = uuid.uuid4()
    crawler = DiscoveryCrawler(project_id=project_id, base_url="http://127.0.0.1:8000", depth_budget=2, max_pages=10)

    mock_page = AsyncMock()
    mock_page.url = "http://127.0.0.1:8000"
    mock_page.title = AsyncMock(return_value="Home")
    # Return links on first call, empty on subsequent
    mock_page.evaluate = AsyncMock(side_effect=[
        ["http://127.0.0.1:8000/courses/101", "http://127.0.0.1:8000/about"],
        [],
        [],
    ])

    pages = await crawler.crawl(mock_page)
    patterns = [p.url_pattern for p in pages]
    assert "/" in patterns
    assert "/courses/:id" in patterns
    assert "/about" in patterns
    assert len(pages) == 3


@pytest.mark.asyncio
async def test_auth_detector_mapping(monkeypatch):
    from app.engine.browser.auth import AuthSignalBundle
    from app.engine.exploration.discovery import auth_detector as auth_detector_module

    async def fake_observe(page, url=None):
        return AuthSignalBundle(
            url_path_is_auth=False,
            visible_password_input_count=1,
            visible_email_input_count=1,
            visible_otp_input_count=0,
            has_remember_me_checkbox=False,
            has_forgot_password_link=False,
        )

    monkeypatch.setattr(auth_detector_module, "observe_auth_signals", fake_observe)
    detector = AuthDetector()
    page = Page(project_id=uuid.uuid4(), url_pattern="/login")

    mock_browser_page = AsyncMock()
    await detector.inspect_page_auth(mock_browser_page, page)
    assert page.requires_auth is True
    assert len(page.required_state) == 1
    assert page.required_state[0].key == "authenticated"
    assert page.required_state[0].value is False


@pytest.mark.asyncio
async def test_persona_detector_role_switching():
    project_id = uuid.uuid4()
    detector = PersonaDetector(project_id=project_id)

    mock_browser_page = AsyncMock()
    mock_browser_page.evaluate = AsyncMock(return_value=["student", "instructor"])

    pages = [
        Page(project_id=project_id, url_pattern="/student/courses"),
        Page(project_id=project_id, url_pattern="/instructor/grading"),
    ]

    personas = await detector.detect_personas(mock_browser_page, pages)
    names = {p.name for p in personas}
    assert "student" in names
    assert "instructor" in names
    for p in personas:
        assert p.credentials_required is True
        assert len(p.default_capabilities) > 0


@pytest.mark.asyncio
async def test_capability_extractor_actions():
    project_id = uuid.uuid4()
    extractor = CapabilityExtractor(project_id=project_id)
    page_obj = Page(project_id=project_id, url_pattern="/courses/:id", source_files=["courses.py"])

    mock_browser_page = AsyncMock()
    mock_browser_page.evaluate = AsyncMock(return_value=[
        {
            "text": "Enroll Now",
            "tag": "button",
            "type": "button",
            "selector": "button#enroll-btn",
        },
        {
            "text": "Submit Feedback",
            "tag": "button",
            "type": "submit",
            "selector": "button#submit-feedback",
        },
    ])

    actions, caps, states = await extractor.extract_actions_and_capabilities(mock_browser_page, page_obj)
    assert len(actions) == 2
    action_names = [a.name for a in actions]
    assert "Enroll Now" in action_names

    enroll_act = next(a for a in actions if a.name == "Enroll Now")
    assert enroll_act.mutates == ["enrolled"]
    assert enroll_act.source == "heuristic"
    assert enroll_act.confidence == 0.65

    cap_names = {c.name for c in caps}
    assert "course_enrollment" in cap_names
    state_keys = {s.key for s in states}
    assert "enrolled" in state_keys


def test_invariant_inferrer_proposals():
    project_id = uuid.uuid4()
    inferrer = InvariantInferrer(project_id=project_id)

    actions = [
        Action(
            project_id=project_id,
            page_id=uuid.uuid4(),
            name="Enroll button",
            selector="button#enroll",
            mutates=["enrolled"],
        )
    ]

    invariants = inferrer.infer_invariants(pages=[], actions=actions, capabilities=[])
    assert len(invariants) >= 1
    enroll_inv = next(i for i in invariants if i.name == "Enrolled course appears in student dashboard")
    assert enroll_inv.source == "inferred"
    assert enroll_inv.confidence == 0.5
    assert enroll_inv.assertion.key == "enrolled"


@pytest.mark.asyncio
async def test_ai_assistant_ambiguous_actions():
    # Heuristic fallback when reasoner is None
    assistant_heuristic = AIAssistant(reasoner=None)
    actions = [
        Action(
            project_id=uuid.uuid4(),
            page_id=uuid.uuid4(),
            name="click on element",
            selector="button#save-btn",
            confidence=0.4,
        )
    ]

    proposals = await assistant_heuristic.assist_ambiguous_actions(actions, {"url": "/settings"})
    assert len(proposals) == 1
    assert proposals[0].confidence <= 0.9
    assert proposals[0].accepted is True
    assert actions[0].name == "Save Changes"
    assert actions[0].source == "heuristic_inference"
    assert actions[0].confidence <= 0.9

    # AI proposal when reasoner is present
    mock_reasoner = MagicMock()
    assistant_ai = AIAssistant(reasoner=mock_reasoner)
    actions_ai = [
        Action(
            project_id=uuid.uuid4(),
            page_id=uuid.uuid4(),
            name="button_submit",
            selector="button[type='submit']",
            confidence=0.4,
        )
    ]
    proposals_ai = await assistant_ai.assist_ambiguous_actions(actions_ai, {"url": "/login"})
    assert len(proposals_ai) == 1
    assert actions_ai[0].source == "ai_proposal"
    assert actions_ai[0].name == "Submit Form"



@pytest.mark.asyncio
async def test_incremental_rediscovery():
    project_id = uuid.uuid4()
    pipeline = DiscoveryPipeline(project_id=project_id, base_url="http://127.0.0.1:8000")

    now = datetime.now(timezone.utc)
    fresh_page = Page(
        project_id=project_id,
        url_pattern="/fresh",
        last_seen_at=now,
        source_files=["app/fresh.py"],
    )
    stale_page = Page(
        project_id=project_id,
        url_pattern="/stale",
        last_seen_at=now - timedelta(days=10),
        source_files=["app/stale.py"],
    )
    changed_page = Page(
        project_id=project_id,
        url_pattern="/changed",
        last_seen_at=now,
        source_files=["app/changed.py"],
    )

    mock_browser_page = AsyncMock()
    mock_browser_page.evaluate = AsyncMock(return_value=[])

    # Re-discover with changed_files=["app/changed.py"] and default 7-day cutoff
    result = await pipeline.rediscover(
        mock_browser_page,
        existing_pages=[fresh_page, stale_page, changed_page],
        changed_files=["app/changed.py"],
    )

    recrawled_patterns = {p.url_pattern for p in result.pages}
    assert "/stale" in recrawled_patterns
    assert "/changed" in recrawled_patterns
    assert "/fresh" not in recrawled_patterns


def test_discovery_result_review_required_filtering():
    project_id = uuid.uuid4()
    low_conf_action = Action(
        project_id=project_id,
        page_id=uuid.uuid4(),
        name="Ambiguous Link",
        selector="a.link",
        confidence=0.5,
        source="heuristic",
    )
    high_conf_action = Action(
        project_id=project_id,
        page_id=uuid.uuid4(),
        name="Login Button",
        selector="button#login",
        confidence=0.9,
        source="discovered",
    )

    result = DiscoveryResult(actions=[low_conf_action, high_conf_action])
    review_items = result.review_required
    assert len(review_items) == 1
    assert review_items[0]["name"] == "Ambiguous Link"
    assert review_items[0]["confidence"] == 0.5


@pytest.mark.asyncio
async def test_goal_success_criteria_promotion():
    """Verify DiscoveryPipeline populates success_criteria on goals from capability produces_state, with fallback."""
    project_id = uuid.uuid4()
    pipeline = DiscoveryPipeline(project_id=project_id, base_url="http://127.0.0.1:8000")

    # Capability with produces_state
    cap_with_state = Capability(
        project_id=project_id,
        name="enroll_course",
        description="Enroll into a course",
        produces_state=[StateMutation(key="enrolled", value=True, action="set")],
    )

    # Capability without produces_state (fallback to key=cap.name)
    cap_without_state = Capability(
        project_id=project_id,
        name="view_catalog",
        description="View all courses",
        produces_state=[],
    )

    mock_browser_page = AsyncMock()
    mock_browser_page.url = "http://127.0.0.1:8000"
    mock_browser_page.evaluate = AsyncMock(return_value=[])

    pipeline.crawler.crawl = AsyncMock(return_value=[Page(project_id=project_id, url_pattern="/")])
    pipeline.auth_detector.inspect_page_auth = AsyncMock()
    pipeline.capability_extractor.extract_actions_and_capabilities = AsyncMock(return_value=([], [cap_with_state, cap_without_state], []))
    pipeline.ai_assistant.assist_ambiguous_actions = AsyncMock(return_value=[])
    pipeline.persona_detector.detect_personas = AsyncMock(return_value=[])
    pipeline.auth_detector.detect_auth = AsyncMock(return_value=[])
    pipeline.invariant_inferrer.infer_invariants = MagicMock(return_value=[])

    result = await pipeline.discover(mock_browser_page)
    assert len(result.goals) == 2

    enroll_goal = next(g for g in result.goals if "Enroll" in g.name)
    assert len(enroll_goal.success_criteria) == 1
    assert enroll_goal.success_criteria[0].key == "enrolled"
    assert enroll_goal.success_criteria[0].value is True
    assert enroll_goal.success_criteria[0].predicate == "eq"

    catalog_goal = next(g for g in result.goals if "View" in g.name)
    assert len(catalog_goal.success_criteria) == 1
    assert catalog_goal.success_criteria[0].key == "view_catalog"
    assert catalog_goal.success_criteria[0].value is True
    assert catalog_goal.success_criteria[0].predicate == "eq"


@pytest.mark.asyncio
async def test_flow_service_create_from_mission(db_session):
    """Verify FlowService.create_from_mission converts discovery mission to a project Flow."""
    from app.modules.flows.service import FlowService
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(id=uuid.uuid4(), email="mission_promote@example.com")
    db_session.add(user)
    await db_session.flush()

    project = Project(
        id=uuid.uuid4(),
        user_id=user.id,
        name="Promotion Project",
        base_url="http://127.0.0.1:8000",
    )
    db_session.add(project)
    await db_session.flush()

    mission = {
        "id": "mission-test-123",
        "title": "Complete Course Enrollment",
        "description": "Enroll in the selected course and verify dashboard",
        "persona": "student",
        "category": "feature",
        "steps": [
            {"type": "navigate", "url": "http://127.0.0.1:8000/courses"},
            {"type": "click", "target": "button.enroll"},
        ],
        "successCondition": {"url_changed_to": {"to": "/courses/enrolled"}},
        "route_analysis": {"path": "/courses"},
        "confidence": 0.85,
    }

    flow_service = FlowService(db_session)
    flow = await flow_service.create_from_mission(
        project_id=project.id,
        mission=mission,
        user_id=user.id,
        activate_immediately=False,
    )

    assert flow.id is not None
    assert flow.project_id == project.id
    assert flow.name == "Complete Course Enrollment"
    assert flow.source == "user_provided"
    assert flow.active is False
    assert flow.capability == "feature"
    assert flow.confidence == 0.85
    assert flow.persona == {"role": "student"}
    assert flow.success_condition == {"url_changed_to": {"to": "/courses/enrolled"}}
    assert len(flow.steps) == 2
    assert flow.steps[0]["action"] == "navigate"
    assert flow.steps[0]["url"] == "http://127.0.0.1:8000/courses"
    assert flow.steps[1]["action"] == "click"
    assert flow.steps[1]["selector"] == "button.enroll"
