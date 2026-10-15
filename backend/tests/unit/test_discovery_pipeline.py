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
async def test_auth_detector_mapping():
    detector = AuthDetector()
    page = Page(project_id=uuid.uuid4(), url_pattern="/dashboard")

    mock_browser_page = AsyncMock()
    mock_browser_page.evaluate = AsyncMock(return_value={
        "has_password": False,
        "has_username": False,
        "forms": [],
        "auth_endpoints": [],
    })

    await detector.inspect_page_auth(mock_browser_page, page)
    # /dashboard is recognized as protected
    assert page.requires_auth is True
    assert len(page.required_state) == 1
    assert page.required_state[0].key == "authenticated"
    assert page.required_state[0].value is True


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
    assistant = AIAssistant(reasoner=None)
    actions = [
        Action(
            project_id=uuid.uuid4(),
            page_id=uuid.uuid4(),
            name="click on element",
            selector="button#save-btn",
            confidence=0.4,
        )
    ]

    proposals = await assistant.assist_ambiguous_actions(actions, {"url": "/settings"})
    assert len(proposals) == 1
    assert proposals[0].confidence <= 0.9
    assert proposals[0].accepted is True
    assert actions[0].name == "Save Changes"
    assert actions[0].source == "ai_proposal"
    assert actions[0].confidence <= 0.9


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
