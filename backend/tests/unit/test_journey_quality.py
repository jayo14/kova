"""Unit tests for journey quality validation, outcome verification, and ranking."""

import pytest
from app.modules.exploration.schemas import DiscoveredMission
from app.modules.exploration.journey_validator import (
    is_vague_outcome,
    validate_journey,
    repair_journey,
    score_journey,
    deduplicate_and_rank_journeys,
)


def test_is_vague_outcome():
    assert is_vague_outcome(None) is True
    assert is_vague_outcome("") is True
    assert is_vague_outcome("verify visible feedback") is True
    assert is_vague_outcome("Verify page loaded") is True
    assert is_vague_outcome("Expected results present") is True
    assert is_vague_outcome("Page responds") is True

    # Concrete outcomes are NOT vague
    assert is_vague_outcome("Application processes entries and renders generated technical report document") is False
    assert is_vague_outcome("Simulation completes and renders detailed evaluation feedback and scoring metrics") is False
    assert is_vague_outcome("New record is created and appears in list or confirmation view") is False


def test_validate_journey_rejects_shallow_navigation():
    shallow_mission = DiscoveredMission(
        id="m1",
        name="Navigate to Features",
        title="Navigate to Features",
        description="Open landing page and click Features",
        objective="Verify that visitor can navigate to Features",
        persona="Visitor",
        category="feature",
        journey=["Open app", "Click Features", "Verify page loaded"],
        steps=[
            {"type": "navigate", "url": "https://example.com"},
            {"type": "click", "target": "#features-link"},
        ],
        successCondition={"url_matches": "/features"},
        confidence=0.7,
        classification="functional",  # Incorrectly claiming to be functional when it's only navigation
        is_core=False,
    )

    result = validate_journey(shallow_mission)
    assert result.is_valid is False
    assert any(d.code == "SHALLOW_NAVIGATION" for d in result.defects)


def test_validate_journey_rejects_vague_outcome():
    vague_mission = DiscoveredMission(
        id="m2",
        name="Create Report",
        title="Create Report",
        description="Click Create report",
        objective="Verify visible feedback",
        persona="Student",
        category="feature",
        journey=["Open app", "Click Create", "Verify visible feedback"],
        steps=[
            {"type": "navigate", "url": "https://example.com/reports"},
            {"type": "click", "target": "button:has-text('Create')"},
        ],
        successCondition={"element_count": {"selector": "div, section, p", "min": 1}},
        confidence=0.6,
        expected_outcome="Verify visible feedback",
        classification="functional",
        is_core=True,
    )

    result = validate_journey(vague_mission)
    assert result.is_valid is False
    assert any(d.code == "VAGUE_OUTCOME" for d in result.defects)


def test_repair_journey_enhances_weak_flow():
    weak_mission = DiscoveredMission(
        id="m3",
        name="Generate Report",
        title="Generate Report",
        description="Create report from entries",
        objective="Create report",
        persona="Student",
        category="workflow",
        journey=["Open app", "Generate report"],
        steps=[
            {"type": "navigate", "url": "https://example.com/report/new"},
            {"type": "click", "target": "button:has-text('Generate')"},
        ],
        successCondition=None,
        confidence=0.5,
        user_goal="Generate technical report",
        classification="functional",
        is_core=True,
    )

    repaired = repair_journey(weak_mission)
    assert repaired.successCondition is not None
    assert repaired.expected_outcome is not None
    assert not is_vague_outcome(repaired.expected_outcome)
    assert "Generate Report" in repaired.expected_outcome


def test_score_and_rank_prioritizes_functional_capabilities_over_auth_and_navigation():
    auth_mission = DiscoveredMission(
        id="m-auth",
        name="Log In",
        title="Log In to account",
        description="Authenticate user session",
        objective="Verify login works",
        persona="User",
        category="auth",
        journey=["Open app", "Enter email and password", "Submit login", "Verify dashboard loads"],
        steps=[
            {"type": "navigate", "url": "https://example.com/login"},
            {"type": "type", "target": "input[type='email']", "value": "test@example.com"},
            {"type": "type", "target": "input[type='password']", "value": "password"},
            {"type": "click", "target": "button[type='submit']"},
        ],
        successCondition={"auth_verified": {"auth_path": "/login"}},
        confidence=0.8,
        expected_outcome="User is authenticated and redirected to dashboard",
        classification="auth",
        is_core=False,
    )

    nav_mission = DiscoveredMission(
        id="m-nav",
        name="Explore Features & Navigation",
        title="Explore Features & Navigation",
        description="Navigate primary sections",
        objective="Confirm primary application views render",
        persona="Visitor",
        category="navigation",
        journey=["Open app", "Scroll page", "Confirm main views render"],
        steps=[
            {"type": "navigate", "url": "https://example.com"},
            {"type": "scroll", "direction": "down", "amount": 600},
        ],
        successCondition={"element_count": {"selector": "h1, h2, a", "min": 2}},
        confidence=0.7,
        expected_outcome="Main application interface and interactive controls render",
        classification="navigation",
        is_core=False,
    )

    report_mission = DiscoveredMission(
        id="m-report",
        name="Generate SIWES Technical Report",
        title="Generate SIWES Technical Report",
        description="Enter logbook activity and generate technical report artifact",
        objective="Verify student can generate technical report with document viewer output",
        persona="Student",
        category="workflow",
        journey=[
            "Open app",
            "Open report generation interface",
            "Input logbook weekly activity entries",
            "Submit and trigger report generation",
            "Verify generated report document renders in viewer",
        ],
        steps=[
            {"type": "navigate", "url": "https://example.com/reports/new"},
            {"type": "type", "target": "textarea[name='log_entry']", "value": "Week 1-4 telemetry firmware implementation."},
            {"type": "click", "target": "button:has-text('Generate Report')"},
        ],
        successCondition={"element_count": {"selector": ".report-viewer, [role='document']", "min": 1}},
        confidence=0.9,
        expected_outcome="Application processes logbook entries and renders synthesized report document",
        classification="functional",
        is_core=True,
    )

    defence_mission = DiscoveredMission(
        id="m-defence",
        name="Complete Mock Defence Session",
        title="Complete Mock Defence Session",
        description="Launch mock defence simulation, answer technical questions, and review evaluation feedback",
        objective="Verify student can complete mock defence and receive evaluation scores",
        persona="Student",
        category="workflow",
        journey=[
            "Open app",
            "Launch mock defence",
            "Answer question prompt",
            "Submit response",
            "Verify evaluation feedback and score metrics render",
        ],
        steps=[
            {"type": "navigate", "url": "https://example.com/defence"},
            {"type": "click", "target": "button:has-text('Start Defence')"},
            {"type": "type", "target": "textarea", "value": "The telemetry pipeline uses deterministic buffering."},
            {"type": "click", "target": "button:has-text('Submit Answer')"},
        ],
        successCondition={"element_count": {"selector": ".evaluation-feedback, .score-badge", "min": 1}},
        confidence=0.88,
        expected_outcome="Simulation completes and renders detailed evaluation feedback and scoring metrics",
        classification="functional",
        is_core=True,
    )

    ranked = deduplicate_and_rank_journeys([auth_mission, nav_mission, report_mission, defence_mission])

    # Core functional workflow MUST be recommended #1
    assert len(ranked) >= 3
    assert ranked[0].id == "m-report"
    assert ranked[0].recommended is True
    assert "SIWES Technical Report" in ranked[0].name
    assert ranked[0].ranking_rationale is not None
    assert "tests core capability" in ranked[0].ranking_rationale

    # Auth and navigation must NOT be recommended over core features
    assert ranked[1].id == "m-defence"
    assert not any(m.recommended for m in ranked[1:])
