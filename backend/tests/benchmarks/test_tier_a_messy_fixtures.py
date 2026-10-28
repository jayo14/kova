"""Contract tests for local stress fixtures and their ground-truth labels."""

import pytest
from httpx import ASGITransport, AsyncClient
from pathlib import Path
import yaml

from benchmarks.fixtures.messy_support import make_app
from benchmarks.suites.default import load_messy_suite


def test_messy_tier_has_fifteen_per_labeled_fixtures():
    suite = load_messy_suite()
    assert len(suite.fixtures) == 15
    assert len({fixture.fixture_id for fixture in suite.fixtures}) == 15
    assert all(fixture.expected_scenarios for fixture in suite.fixtures)
    assert all(fixture.path.joinpath("labels.yml").exists() for fixture in suite.fixtures)


def test_public_nightly_targets_are_https_and_have_permission_sources():
    target_file = Path(__file__).parents[2] / "benchmarks" / "fixtures" / "tier_b_public.yml"
    targets = yaml.safe_load(target_file.read_text(encoding="utf-8"))
    assert len(targets) >= 10
    assert all(item["url"].startswith("https://") for item in targets)
    assert all(item.get("permission_source") for item in targets)


@pytest.mark.asyncio
async def test_local_fixture_pages_load_and_expose_labels():
    suite = load_messy_suite()
    for fixture in suite.fixtures:
        async with AsyncClient(
            transport=ASGITransport(app=make_app(fixture.app_factory)),
            base_url="http://fixture.test",
        ) as client:
            response = await client.get("/")
            assert response.status_code == 200, fixture.fixture_id
            assert "<main>" in response.text, fixture.fixture_id


@pytest.mark.asyncio
async def test_success_toast_is_checked_against_persisted_record():
    async with AsyncClient(
        transport=ASGITransport(app=make_app("silent_failure")),
        base_url="http://fixture.test",
    ) as client:
        await client.post("/api/save")
        assert (await client.get("/api/records")).json()["records"] == []

    async with AsyncClient(
        transport=ASGITransport(app=make_app("toast_success")),
        base_url="http://fixture.test",
    ) as client:
        await client.post("/api/save")
        assert len((await client.get("/api/records")).json()["records"]) == 1


@pytest.mark.asyncio
async def test_flaky_fixture_fails_once_then_succeeds():
    async with AsyncClient(
        transport=ASGITransport(app=make_app("slow_flaky_api")),
        base_url="http://fixture.test",
        timeout=10,
    ) as client:
        first = await client.post("/api/submit")
        second = await client.post("/api/submit")
        assert first.status_code == 503
        assert second.status_code == 200
