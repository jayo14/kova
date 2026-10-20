import uuid
import pytest
from app.modules.exploration.models import ExplorationSession, ExplorationStatus, ExplorationEvent
from app.modules.exploration.schemas import (
    ExplorationCreate,
    ExplorationRead,
    DiscoveredMission,
)


def test_exploration_status_enum():
    assert ExplorationStatus.CREATED.value == "CREATED"
    assert ExplorationStatus.AUTH_REQUIRED.value == "AUTH_REQUIRED"
    assert ExplorationStatus.READY.value == "READY"
    assert ExplorationStatus.FAILED.value == "FAILED"


def test_discovered_mission_schema():
    mission = DiscoveredMission(
        name="Generate Quiz",
        objective="Verify student quiz generation",
        journey=["Open app", "Upload doc", "Generate quiz"],
        recommended=True,
    )
    assert mission.name == "Generate Quiz"
    assert len(mission.journey) == 3
    assert mission.recommended is True


def test_exploration_create_schema():
    create = ExplorationCreate(url="https://tastiq.app.vercel.app", goal="test quiz")
    assert create.url == "https://tastiq.app.vercel.app"
    assert create.goal == "test quiz"


def test_exploration_create_normalizes_bare_domain():
    create = ExplorationCreate(url="github.com", goal="explore")
    assert create.url == "https://github.com"

    create_localhost = ExplorationCreate(url="localhost:3000", goal="test")
    assert create_localhost.url == "http://localhost:3000"
