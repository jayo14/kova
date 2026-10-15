from typing import Any
from app.modules.flows.generator.schemas import ExecutionStep


def step_navigate(url: str, description: str | None = None) -> ExecutionStep:
    return ExecutionStep(
        action="navigate",
        target=url,
        value=url,
        description=description or f"Navigate to {url}",
    )


def step_locate(selector: str, description: str | None = None) -> ExecutionStep:
    return ExecutionStep(
        action="locate",
        target=selector,
        description=description or f"Locate element {selector}",
    )


def step_input(selector: str, value: str, description: str | None = None) -> ExecutionStep:
    return ExecutionStep(
        action="input",
        target=selector,
        value=value,
        description=description or f"Enter value into {selector}",
    )


def step_click(selector: str, description: str | None = None) -> ExecutionStep:
    return ExecutionStep(
        action="click",
        target=selector,
        description=description or f"Click element {selector}",
    )


def step_assert(
    assertion_type: str,
    value: Any,
    target: str | None = None,
    description: str | None = None,
) -> ExecutionStep:
    return ExecutionStep(
        action="assert",
        target=target or assertion_type,
        value=value,
        description=description or f"Assert {assertion_type}: {value}",
    )


def step_capture_evidence(
    step_id: str,
    purpose: str = "verification",
    description: str | None = None,
) -> ExecutionStep:
    return ExecutionStep(
        action="capture_evidence",
        step_id=step_id,
        purpose=purpose,
        description=description or f"Capture evidence for step {step_id} with purpose {purpose}",
    )


def to_runner_steps(steps: list[ExecutionStep]) -> list[dict[str, Any]]:
    """Convert a sequence of ExecutionSteps into runner-ready dictionaries."""
    return [s.to_runner_dict() for s in steps]
