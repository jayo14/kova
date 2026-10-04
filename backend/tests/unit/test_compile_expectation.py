import pytest
import uuid
from typing import TypeVar
from pydantic import BaseModel

from app.engine.ai.provider import AIProvider
from app.engine.ai.schemas import CompiledExpectation
from app.engine.verification.verifier import (
    compile_expectation,
    is_vacuous_condition,
    Verifier,
)
from app.engine.execution.runner import FlowRunner

T = TypeVar("T", bound=BaseModel)


class StubExpectationProvider(AIProvider):
    name = "stub_expectation"

    def __init__(self, response_condition: dict, explanation: str = "Test explanation"):
        self._condition = response_condition
        self._explanation = explanation

    @property
    def model_name(self) -> str:
        return "stub-model"

    async def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type[T],
    ) -> T:
        return schema.model_validate({
            "condition": self._condition,
            "explanation": self._explanation,
        })


@pytest.mark.asyncio
async def test_compile_expectation_with_valid_condition():
    provider = StubExpectationProvider({"text_visible": "Dashboard Overview"})
    cond = await compile_expectation("Go to dashboard", "User sees Dashboard Overview", provider=provider)
    assert cond == {"text_visible": "Dashboard Overview"}
    assert not is_vacuous_condition(cond)


@pytest.mark.asyncio
async def test_compile_expectation_rejects_vacuous_url():
    provider = StubExpectationProvider({"url_matches": ".*"})
    cond = await compile_expectation("Navigate", "Page is loaded", provider=provider)
    # Must fail vacuous condition check
    assert is_vacuous_condition(cond)


@pytest.mark.asyncio
async def test_compile_expectation_rejects_structural_container():
    provider = StubExpectationProvider({"element_visible": {"css": "main"}})
    cond = await compile_expectation("Open app", "App container visible", provider=provider)
    # Must fail vacuous condition check
    assert is_vacuous_condition(cond)


@pytest.mark.asyncio
async def test_compile_expectation_heuristic_fallback():
    # Provider None fallback to heuristic
    cond = await compile_expectation("Login", "Redirects to /dashboard", provider=None)
    assert cond == {"url_matches": "/dashboard"}
    assert not is_vacuous_condition(cond)

    # Heuristic with no verifiable signal returns vacuous condition
    vacuous_cond = await compile_expectation("Do something", "main container is there", provider=None)
    assert is_vacuous_condition(vacuous_cond)

