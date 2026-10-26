import pytest
from app.modules.exploration.schemas import DiscoveredMission
from app.modules.exploration.journey_validator import (
    deduplicate_and_rank_journeys,
    normalize_journey_intent,
    repair_journey,
)


def test_normalize_journey_intent_detects_synonyms():
    k1 = normalize_journey_intent("Create New Record", "/records/new")
    k2 = normalize_journey_intent("Add Record", "/records/new")
    assert k1 == k2

    k_login1 = normalize_journey_intent("Sign In to Account", "/login")
    k_login2 = normalize_journey_intent("Log In to Account", "/login")
    assert k_login1 == k_login2


def test_deduplicate_candidate_missions_removes_semantic_duplicates():
    m1 = DiscoveredMission(
        id="m1",
        name="Create Record",
        objective="Create a new record in catalog",
        category="crud",
        classification="functional",
        route_analysis={"path": "/records/new"},
        steps=[
            {"type": "navigate", "target": "https://example.com/records/new"},
            {"type": "fill", "target": "#title", "value": "New Item"},
            {"type": "click", "target": "#btn-submit"},
        ],
        successCondition={"record_persisted": {"expected_text": "New Item"}},
    )
    m2 = DiscoveredMission(
        id="m2",
        name="Create New Record",
        objective="Create a new record in catalog",
        category="crud",
        classification="functional",
        route_analysis={"path": "/records/new"},
        steps=[
            {"type": "navigate", "target": "https://example.com/records/new"},
            {"type": "fill", "target": "#title", "value": "New Item"},
            {"type": "click", "target": "#btn-submit"},
        ],
        successCondition={"record_persisted": {"expected_text": "New Item"}},
    )

    results = deduplicate_and_rank_journeys([m1, m2])
    assert len(results) == 1
    assert results[0].id == "m1"


def test_mission_grounding_attaches_concrete_assertions():
    # 1. Create mission repaired with record_persisted
    m_create = DiscoveredMission(
        id="m-create",
        name="Create Project",
        objective="Create a new project entity",
        category="crud",
        classification="functional",
        steps=[{"type": "navigate", "target": "/projects/new"}, {"type": "click", "target": "#save"}],
    )
    repaired_create = repair_journey(m_create)
    assert "record_persisted" in repaired_create.successCondition

    # 2. Search mission repaired with search_results
    m_search = DiscoveredMission(
        id="m-search",
        name="Search Records Catalog",
        objective="Search and filter records",
        category="feature",
        classification="functional",
        steps=[{"type": "navigate", "target": "/records"}, {"type": "fill", "target": "#q", "value": "query"}],
    )
    repaired_search = repair_journey(m_search)
    assert "search_results" in repaired_search.successCondition

    # 3. Auth mission repaired with auth_verified
    m_auth = DiscoveredMission(
        id="m-auth",
        name="Sign In",
        objective="Sign into user account",
        category="auth",
        classification="setup",
        steps=[{"type": "navigate", "target": "/login"}, {"type": "click", "target": "#login"}],
    )
    repaired_auth = repair_journey(m_auth)
    assert "auth_verified" in repaired_auth.successCondition


def test_ranking_prioritizes_functional_workflow_over_auth():
    m_auth = DiscoveredMission(
        id="m-auth",
        name="Sign In",
        objective="Sign into account",
        category="auth",
        classification="setup",
        steps=[{"type": "navigate", "target": "/login"}, {"type": "click", "target": "#login"}],
        successCondition={"auth_verified": True},
    )
    m_functional = DiscoveredMission(
        id="m-func",
        name="Create Record",
        objective="Create a new record",
        category="feature",
        classification="functional",
        steps=[
            {"type": "navigate", "target": "/records/new"},
            {"type": "fill", "target": "#title", "value": "Test"},
            {"type": "click", "target": "#submit"},
        ],
        successCondition={"record_persisted": {"expected_text": "Test"}},
    )

    ranked = deduplicate_and_rank_journeys([m_auth, m_functional])
    assert len(ranked) == 2
    # Functional journey should be recommended ahead of auth setup
    assert ranked[0].id == "m-func"
    assert ranked[0].recommended is True
    assert ranked[1].id == "m-auth"
    assert ranked[1].recommended is False
