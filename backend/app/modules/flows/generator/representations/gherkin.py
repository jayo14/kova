from app.modules.flows.generator.schemas import ExecutionStep


def to_gherkin_representation(flow_name: str, steps: list[ExecutionStep]) -> str:
    """Generate human-readable Gherkin feature specification from execution steps.

    Gherkin is strictly an export format, never the primary source of truth.
    """
    lines = [
        f"Feature: {flow_name}",
        f"  Scenario: Execute {flow_name}",
    ]

    has_given = False
    has_when = False
    has_then = False

    for step in steps:
        if step.action == "navigate":
            prefix = "Given" if not has_given else "And"
            url = step.value or step.target or "/"
            lines.append(f"    {prefix} the user navigates to \"{url}\"")
            has_given = True
        elif step.action == "locate":
            # Locates can be represented or omitted if coupled with input/click
            if step.description:
                prefix = "When" if not has_when else "And"
                lines.append(f"    {prefix} the user locates \"{step.target}\"")
                has_when = True
        elif step.action == "input":
            prefix = "When" if not has_when else "And"
            target_str = step.target or "the field"
            val_str = str(step.value) if step.value is not None else ""
            lines.append(f"    {prefix} the user enters \"{val_str}\" into \"{target_str}\"")
            has_when = True
        elif step.action in ("click", "submit"):
            prefix = "When" if not has_when else "And"
            target_str = step.target or "button"
            lines.append(f"    {prefix} the user clicks the \"{target_str}\" element")
            has_when = True
        elif step.action == "assert":
            prefix = "Then" if not has_then else "And"
            assertion_type = step.target or "condition"
            val_str = str(step.value) if step.value is not None else ""
            if "url" in assertion_type.lower():
                lines.append(f"    {prefix} the URL should match \"{val_str}\"")
            elif "text" in assertion_type.lower():
                lines.append(f"    {prefix} the page should contain the text \"{val_str}\"")
            else:
                lines.append(f"    {prefix} the state \"{assertion_type}\" should be \"{val_str}\"")
            has_then = True
        elif step.action == "capture_evidence":
            prefix = "Then" if not has_then else "And"
            lines.append(f"    {prefix} evidence is captured for step \"{step.step_id}\"")
            has_then = True
        elif step.action == "wait":
            prefix = "When" if not has_when else "And"
            lines.append(f"    {prefix} the system waits for {step.value} seconds")
            has_when = True
        else:
            prefix = "When" if not has_when else "And"
            lines.append(f"    {prefix} the user performs {step.action} on \"{step.target or ''}\"")
            has_when = True

    # Fallbacks if steps lacked standard Given/When/Then sections
    if not has_given:
        lines.insert(2, "    Given the application is accessible")
    if not has_when:
        lines.append("    When the flow steps are executed")
    if not has_then:
        lines.append("    Then the target outcome is verified")

    return "\n".join(lines) + "\n"
