"""Plan and action validation between AI proposals and the deterministic runtime.

The model is an untrusted planner (spec §25). Every proposal passes through:

    schema validation  (Pydantic — done at parse time)
  → safety validation  (policy: forbidden actions/values/URLs)
  → runtime capability validation (action types the executor supports)
  → target validation  (target resolvable to deterministic form)
  → condition validation (Verifier-known keys only)
  → credential validation (secrets come only from the CredentialStore)

A rejected proposal never reaches ActionExecutor.
"""

import logging
import re
from urllib.parse import urlparse

from app.engine.ai.schemas import ActionProposal, JourneyPlan, ProposedStep
from app.engine.verification.verifier import KNOWN_CONDITION_KEYS

logger = logging.getLogger(__name__)


class ProposalRejected(Exception):
    """A proposal failed validation. Carries a safe, non-secret reason."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# Actions the deterministic executor can actually carry out (capability gate).
# 'request_human'/'abort' are loop-level controls, validated separately.
RUNTIME_ACTIONS = frozenset({
    "navigate", "click", "type", "clear", "select", "check", "uncheck",
    "wait", "press", "scroll", "create_email", "read_email", "extract_link",
    "observe",
})
LOOP_ACTIONS = frozenset({"request_human", "abort"})

# Value patterns that must never appear in AI-proposed literal values.
CREDENTIAL_VALUE_PATTERNS = (
    re.compile(r"password\s*[:=]", re.I),
    re.compile(r"(api[_-]?key|secret|token)\s*[:=]", re.I),
)


def validate_condition(condition: dict, context: str) -> None:
    """A proposed verification condition must be machine-checkable."""
    if not isinstance(condition, dict):
        raise ProposalRejected(f"{context}: verification condition must be an object")
    unknown = [k for k in condition.keys() if k not in KNOWN_CONDITION_KEYS]
    if unknown:
        raise ProposalRejected(
            f"{context}: unknown verification keys {unknown} — the fail-closed "
            f"verifier would treat this as UNVERIFIED"
        )


def validate_target_url(url: str) -> str:
    """AI-proposed navigation targets go through the same SSRF policy."""
    if not url or not url.strip():
        raise ProposalRejected("navigate action requires a URL")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise ProposalRejected(f"navigate blocked: unsupported scheme '{parsed.scheme}'")
    # Full SSRF check happens again inside BrowserSession.navigate — this is
    # the early proposal-level gate.
    from app.engine.browser.session import _is_safe_url
    if not _is_safe_url(url.strip()):
        raise ProposalRejected(f"navigate blocked by URL security policy: {url}")
    return url.strip()


def _validate_value(value: str) -> None:
    """No literal secrets in AI proposals — credentials come via credential_intent."""
    for pattern in CREDENTIAL_VALUE_PATTERNS:
        if pattern.search(value or ""):
            raise ProposalRejected(
                "proposal appears to embed a credential in a literal value; "
                "use credential_intent instead"
            )
    if len(value) > 500:
        raise ProposalRejected("value exceeds 500 chars")


def validate_action_proposal(
    proposal: ActionProposal,
    allowed_hosts: set[str] | None = None,
) -> ActionProposal:
    """Full validation pipeline for one action proposal. Raises ProposalRejected."""
    if proposal.action not in RUNTIME_ACTIONS and proposal.action not in LOOP_ACTIONS:
        raise ProposalRejected(f"unsupported action '{proposal.action}'")

    _validate_value(proposal.value or "")

    # Condition validation — any condition the AI proposes must be real
    if proposal.verification:
        validate_condition(proposal.verification, f"action '{proposal.action}'")

    # Navigation targets: scheme + SSRF + (when known) app-host allowlist
    if proposal.action == "navigate":
        url = validate_target_url(proposal.value)
        if allowed_hosts:
            host = (urlparse(url).hostname or "").lower()
            if host not in allowed_hosts:
                raise ProposalRejected(
                    f"navigate to non-application host '{host}' is not permitted"
                )

    # Email-extracted links are separately validated at navigation time by
    # validate_email_link; here we just ensure no raw URL lands in click/type.
    if proposal.action in ("click", "type") and isinstance(proposal.target, dict):
        css = proposal.target.get("css", "")
        if isinstance(css, str) and css.startswith(("http://", "https://")):
            raise ProposalRejected("URLs cannot be used as CSS targets")

    return proposal


def validate_journey_plan(plan: JourneyPlan) -> JourneyPlan:
    """Validate a full AI journey plan before it becomes executable steps."""
    if not plan.steps:
        raise ProposalRejected("journey plan has no steps")
    validate_condition(plan.success_condition, "journey success_condition")
    for i, step in enumerate(plan.steps):
        if step.action not in RUNTIME_ACTIONS:
            raise ProposalRejected(f"step {i}: unsupported action '{step.action}'")
        _validate_value(step.value or "")
        if step.verification:
            validate_condition(step.verification, f"step {i}")
        if step.action == "navigate" and step.value:
            validate_target_url(step.value)
    return plan


def proposal_to_raw_action(
    proposal: ActionProposal,
    identity_email: str | None,
    resolve_credential: "object | None" = None,
) -> dict | None:
    """Convert a validated proposal into a raw ActionExecutor action dict.

    Credential-bearing fields resolve values from the deterministic store at
    execution time — the AI never sees or provides secrets. Returns None for
    loop-level actions (observe/request_human/abort) which the loop handles.
    """
    action = proposal.action

    if action == "create_email" or action == "read_email" or action == "extract_link" or action == "observe":
        return None  # handled by the agent loop itself

    if action == "navigate":
        return {"type": "navigate", "value": proposal.value, "target": {}}

    if action == "wait":
        return {"type": "wait", "value": proposal.value or "1000", "target": {}}

    if action == "press":
        return {"type": "press", "key": proposal.value or "Enter", "target": {}}

    if action == "scroll":
        direction = "down" if (proposal.value or "down") != "up" else "up"
        return {"type": "scroll", "direction": direction, "amount": 400, "target": {}}

    # click/type/clear/select/check/uncheck need a target
    target = _deterministic_target(proposal.target or {})
    if not target:
        raise ProposalRejected(f"action '{action}' has no resolvable target")

    raw: dict = {"type": action, "target": target}

    if action == "type":
        if proposal.credential_intent == "email":
            if not identity_email:
                raise ProposalRejected("email credential requested but identity not established")
            raw["value"] = identity_email
        elif proposal.credential_intent in ("password", "new_password"):
            if resolve_credential is None:
                raise ProposalRejected("credential requested but no resolver configured")
            cred_value = resolve_credential(proposal.credential_intent)
            if not cred_value:
                raise ProposalRejected(
                    f"credential intent '{proposal.credential_intent}' has no configured credential"
                )
            raw["value"] = cred_value
        elif proposal.value:
            raw["value"] = proposal.value
        else:
            raise ProposalRejected("type action has no value or credential_intent")

    return raw


def _deterministic_target(semantic_target: dict) -> dict:
    """Convert an AI semantic target into the ActionTarget dict form.

    Accepts: css (pre-validated), test_id, role+name, label, text candidates.
    Candidate text lists collapse to a Playwright text selector union.
    """
    target: dict = {}

    if semantic_target.get("test_id"):
        target["test_id"] = str(semantic_target["test_id"])[:200]
        return target
    if semantic_target.get("css") and isinstance(semantic_target["css"], str) and len(semantic_target["css"]) < 300:
        target["css"] = semantic_target["css"]
        return target
    if semantic_target.get("role") and semantic_target.get("name"):
        target["role"] = str(semantic_target["role"])[:50]
        target["name"] = str(semantic_target["name"])[:200]
        return target
    if semantic_target.get("label"):
        target["label"] = str(semantic_target["label"])[:200]
        return target

    candidates = semantic_target.get("candidate_text") or []
    if isinstance(candidates, str):
        candidates = [candidates]
    texts = [str(c)[:60] for c in candidates if c and len(str(c)) >= 2][:4]
    if texts:
        # Playwright text selector union across candidates — resolved
        # deterministically by TargetResolver with ambiguity handling.
        parts = []
        for t in texts:
            clean = t.replace("'", "\\'")
            parts.append(f"[role='button']:has-text('{clean}')")
            parts.append(f"a:has-text('{clean}')")
            parts.append(f"button:has-text('{clean}')")
        target["css"] = ", ".join(parts)
        return target

    return {}
