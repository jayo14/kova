"""Deterministic, evidence-based report helpers for persisted executions."""
from __future__ import annotations

import datetime
from dataclasses import asdict, is_dataclass
from enum import Enum
import re
from urllib.parse import urlsplit, urlunsplit
import uuid


def sanitize_text(value: object, *, limit: int = 1000) -> str:
    """Remove common secret-bearing values and compound credentials before persisting/rendering diagnostics."""
    text = str(value or "")
    # 1. Authorization header format
    text = re.sub(r"(?i)\bauthorization\s*:\s*(?:bearer|basic|token)?\s*[^\s,;\"}\]]+", "Authorization: [REDACTED]", text)
    # 2. Bearer / Basic / Token auth values
    text = re.sub(r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]+", r"\1 [REDACTED]", text)
    # 3. Standalone JWT tokens
    text = re.sub(r"\beyJ[a-zA-Z0-9_-]{8,}\.eyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]+", "[JWT REDACTED]", text)
    # 4. JSON key-value pairs in text / DOM snapshots (handles unescaped and escaped quotes)
    text = re.sub(
        r'(?i)\\*[\"\']([a-zA-Z0-9_-]*(?:password|passwd|token|secret|apiKey|api_key|session|clientSecret|privateKey|accessToken|refreshToken)[a-zA-Z0-9_-]*)\\*[\"\']\s*[:=]\s*\\*[\"\']([^\"\'\\\\]+)\\*[\"\']',
        r'\"\1\": \"[REDACTED]\"',
        text,
    )
    # 5. Key-value pairs in text (query strings, config, cookies)
    text = re.sub(
        r"(?i)(password|passwd|token|secret|cookie|set-cookie|api[_-]?key|session[_-]?id|session|jwt|client[_-]?secret|private[_-]?key)(\s*[:=]\s*)([^\s,;\"}\]]+)",
        r"\1\2[REDACTED]",
        text,
    )
    # 6. URLs with credentials and query parameters (HTTP, DB, Redis, AMQP)
    text = re.sub(r"(?:https?|postgres(?:ql)?|mysql|redis|amqp)://[^\s\"\'\)]+", lambda match: _safe_url(match.group(0)), text)
    return text[:limit]


_SENSITIVE_PATTERNS = (
    "password",
    "passwd",
    "token",
    "secret",
    "authorization",
    "cookie",
    "api_key",
    "access_key",
    "credential",
    "auth_token",
    "session",
    "session_id",
    "jwt",
    "private_key",
    "client_secret",
    "id_token",
    "refresh_token",
    "access_token",
)


def _is_sensitive_key(key: str) -> bool:
    norm = str(key).lower().replace("-", "_")
    return any(p in norm for p in _SENSITIVE_PATTERNS)


def sanitize_payload(payload: object) -> object:
    """Redact secret fields recursively before execution events are persisted,

    and guarantee that the resulting structure is strictly JSON-serializable.
    """
    if payload is None:
        return None
    if isinstance(payload, (int, float, bool)):
        return payload
    if isinstance(payload, (uuid.UUID, datetime.date, datetime.datetime, datetime.time)):
        return str(payload) if isinstance(payload, uuid.UUID) else payload.isoformat()
    if isinstance(payload, Enum):
        return payload.value
    if is_dataclass(payload) and not isinstance(payload, type):
        try:
            return sanitize_payload(asdict(payload))
        except Exception:
            return sanitize_payload(vars(payload))
    if hasattr(payload, "model_dump") and callable(payload.model_dump):
        try:
            return sanitize_payload(payload.model_dump(mode="json"))
        except Exception:
            return sanitize_payload(payload.model_dump())
    if hasattr(payload, "dict") and callable(payload.dict):
        try:
            return sanitize_payload(payload.dict())
        except Exception:
            pass
    if isinstance(payload, dict):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(str(key))
            else sanitize_payload(value)
            for key, value in payload.items()
        }
    if isinstance(payload, (list, tuple, set)):
        return [sanitize_payload(value) for value in payload]
    if isinstance(payload, str):
        return sanitize_text(payload, limit=5000)
    if hasattr(payload, "__dict__"):
        try:
            return sanitize_payload(vars(payload))
        except Exception:
            pass
    return sanitize_text(str(payload), limit=5000)



def _safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "[REDACTED]" if parsed.query else "", ""))
    except ValueError:
        return "[URL REDACTED]"


def classify_failure(error_code: str | None, status: str | None = None) -> str | None:
    code = (error_code or "").upper()
    if not code:
        return None
    if code in {"DESTRUCTIVE_ACTION_BLOCKED"}:
        return "destructive_action_blocked"
    if code in {"INJECTION_ATTEMPT_DETECTED", "PROMPT_INJECTION_DETECTED"}:
        return "prompt_injection_detected"
    if code in {"CLIENT_VALIDATION_ERROR", "VALIDATION_FAILED"}:
        return "client_validation_error"
    if code in {"PAGE_ALERT", "SERVER_ERROR", "SERVER_REJECTION"}:
        return "server_rejection"
    if code in {"AUTH_BARRIER", "AUTH_REQUIRED", "EMAIL_VERIFICATION_REQUIRED", "CAPTCHA_REQUIRED"}:
        return "authentication_barrier"
    if code in {"AUTH_BLOCKED", "AUTHENTICATION_FAILED", "CREDENTIALS_MISSING", "FORBIDDEN"}:
        return "authentication_or_authorization"
    if code in {"PREREQUISITE_UNSATISFIED", "PRECONDITION_FAILED"}:
        return "missing_prerequisite"
    if code in {"TARGET_NOT_FOUND", "SELECTOR_AMBIGUOUS", "ELEMENT_NOT_FOUND"}:
        return "element_resolution"
    if code in {"VERIFICATION_FAILED", "ASSERTION_FAILED"}:
        return "application_behavior"
    if code in {"EXECUTION_TIMEOUT", "TIMEOUT", "WORKER_LEASE_EXPIRED"}:
        return "execution_timeout"
    if code in {"NETWORK_ERROR", "PAGE_LOAD_FAILED"}:
        return "network_or_application_server"
    if code in {"EVIDENCE_STORAGE_FAILED", "EVIDENCE_CAPTURE_FAILED"}:
        return "evidence_storage"
    if code in {"BROWSER_START_FAILED", "BROWSER_CRASH", "ACTION_FAILED", "RESOURCE_LIMIT"}:
        return "browser_infrastructure"
    if code in {"FLOW_NOT_RUNNABLE", "FLOW_EMPTY_NO_AGENT"}:
        return "flow_configuration"
    if code in {"AI_PROVIDER_MISCONFIGURED"}:
        return "ai_provider_misconfigured"
    if code in {"AI_PLANNING_FAILED"}:
        return "ai_planning"
    if code in {"DISPATCH_ERROR"}:
        return "dispatch_infrastructure"
    if code in {"ORG_AT_CAPACITY"}:
        return "quota_exceeded"
    return "internal_kova"


def diagnose_failure(error_code: str | None, error_message: str | None) -> dict | None:
    category = classify_failure(error_code)
    if not category:
        return None
    observed = sanitize_text(error_message) or "Kova recorded a failure without additional detail."
    advice = {
        "destructive_action_blocked": "To permit this action, add it to the project's safety_restrictions.destructive_action_allowlist.",
        "prompt_injection_detected": "Review untrusted page content and sanitize inputs to prevent prompt injection attempts.",
        "client_validation_error": "The application rejected form inputs with client-side validation errors. Review required fields and constraints.",
        "server_rejection": "The application server responded with an error banner or rejected the submission. Inspect network logs and console output.",
        "authentication_barrier": "The requested journey requires authentication or additional account verification before it can proceed.",
        "authentication_or_authorization": "Confirm that the configured test account is valid and has the required role.",
        "missing_prerequisite": "Review the flow prerequisites and confirm required application state is available.",
        "element_resolution": "Check whether the expected component rendered and whether its selector still matches uniquely.",
        "application_behavior": "Compare the observed application state with the required outcome and inspect the attached verification evidence.",
        "execution_timeout": "Inspect application responsiveness, network conditions, and the execution time limit.",
        "network_or_application_server": "Inspect the recorded request or navigation outcome; this alone does not establish an application defect.",
        "evidence_storage": "Check private evidence storage availability; missing evidence is not itself proof that the application behavior failed.",
        "browser_infrastructure": "Check worker health and browser startup, action, or shutdown logs.",
        "flow_configuration": "This flow has no executable steps and no autonomous agent path. Add steps in the flow editor, or set AGENT_EXECUTION_ENABLED=true so Kova drives the browser from the objective, or configure any AI provider for dynamic planning (for example GEMINI_API_KEY or OPENROUTER_API_KEY, or the generic AI_API_KEY + AI_MODEL pair).",
        "ai_provider_misconfigured": "The configured AI provider rejected the request (invalid key, wrong model name, or missing provider credentials). Verify the provider key and model in the deployment environment; a single provider key is sufficient.",
        "ai_planning": "Kova reached the AI planner but it could not produce a usable journey. Retry the execution; if it persists, inspect worker logs for the planner response and confirm the provider is reachable from the worker.",
        "dispatch_infrastructure": "Kova failed to start the execution worker path. Check worker logs and Celery broker connectivity.",
        "quota_exceeded": "The organization is at its concurrent execution limit. Wait for running executions to finish or raise the org plan limit.",
        "internal_kova": "Inspect authorized worker diagnostics around this execution.",
    }[category]
    return {
        "category": category,
        "summary": observed,
        "expected": None,
        "observed": observed,
        "reason": f"Kova classified error code {sanitize_text(error_code, limit=100)} as {category.replace('_', ' ')}.",
        "next_step": advice,
        "hypothesis": None,
    }


def format_destructive_blocked_banner(action_label: str, reason: str | None = None) -> str:
    """Format a prominent warning banner when an execution is blocked due to destructive action."""
    fallback_reason = "This action is destructive and not in the project's allowlist."
    return (
        f"⚠️ Execution BLOCKED: Kova detected a destructive action and refused to execute it.\n\n"
        f"Action: \"{action_label}\"\n"
        f"Reason: {reason or fallback_reason}\n\n"
        f"To permit this action:\n"
        f"1. Review whether this action is necessary for the validation scenario.\n"
        f"2. If yes, add \"{action_label.lower()}\" to the project's safety_restrictions.destructive_action_allowlist.\n"
        f"3. Re-run the execution."
    )


def format_prompt_injection_banner(evidence: str) -> str:
    """Format a security-focused warning banner when prompt injection is detected."""
    return (
        f"🚨 SECURITY: Prompt-injection attempt detected and blocked.\n\n"
        f"The application under test contained content that appeared to instruct Kova's AI to take an unsafe action. Kova refused to execute the proposed action.\n\n"
        f"Evidence: {evidence}\n\n"
        f"This is NOT a defect in the application under test — it is a sign that the application may contain malicious content. Review the page manually before re-running."
    )


def diagnose_verification(check: dict, step_name: str | None = None) -> dict:
    expected = sanitize_payload(check.get("expected"))
    observed = sanitize_payload(check.get("actual", check.get("observed")))
    check_type = sanitize_text(check.get("type") or "required outcome")
    where = f" during {sanitize_text(step_name)}" if step_name else ""
    return {
        "category": "application_behavior",
        "summary": f"The required {check_type} outcome was not verified{where}.",
        "expected": expected,
        "observed": observed,
        "reason": "A persisted required verification check reported that the observed result did not match the expected condition.",
        "next_step": "Compare the expected and observed values, then inspect the associated step evidence and application state.",
        "hypothesis": None,
    }


def build_timeline(events: list[object], execution_status: str | None = None) -> list[dict]:
    """Group durable events into ordered steps without manufacturing missing results.

    When the overall execution_status is COMPLETED, unverified steps that completed
    their action successfully are promoted to 'passed' to avoid contradictory counts.
    """
    steps: dict[str, dict] = {}
    order: list[str] = []
    for event in events:
        event_type = getattr(event, "event_type", "")
        payload = getattr(event, "payload", {}) or {}
        if not isinstance(payload, dict):
            continue
        index = payload.get("step", payload.get("step_index"))
        step_id = payload.get("step_id")
        if index is None and step_id is None:
            continue
        key = str(step_id or index)
        if key not in steps:
            steps[key] = {"step_id": step_id, "sequence": index, "status": "incomplete", "evidence": []}
            order.append(key)
        item = steps[key]
        if event_type == "action.started":
            item.update({"action": payload.get("type") or payload.get("action"), "target": sanitize_text(payload.get("target")), "expected": payload.get("expected_outcome"), "started_at": payload.get("started_at"), "status": "running"})
        elif event_type == "action.completed":
            item.update({"action": payload.get("type") or payload.get("action") or item.get("action"), "completed_at": payload.get("completed_at"), "duration_ms": payload.get("duration_ms"), "url": _safe_url(payload.get("url", "")), "action_result": "completed", "status": "unverified"})
        elif event_type in {"verification.passed", "verification.failed", "step_postcondition"}:
            checks = sanitize_payload(payload.get("checks") or payload.get("verification", {}).get("checks", []))
            passed = event_type == "verification.passed" or (event_type == "step_postcondition" and payload.get("passed") is True)
            failed = event_type == "verification.failed" or (event_type == "step_postcondition" and payload.get("passed") is False)
            item.update({"verification": {"verdict": "passed" if passed else "failed" if failed else "inconclusive", "checks": checks, "expected": sanitize_payload(payload.get("expected")), "observed": sanitize_payload(payload.get("observed"))}, "status": "passed" if passed else "failed" if failed else "unverified"})
        elif event_type == "evidence.captured":
            item["evidence"].append({"evidence_id": payload.get("evidence_id"), "type": payload.get("type"), "title": payload.get("title")})
        elif event_type in {"action.failed", "execution.failed"}:
            item.update({"status": "error", "error": sanitize_text(payload.get("error_message") or payload.get("error"))})

    # Promote unverified steps to passed on successful executions
    is_success = execution_status and execution_status.lower() in ("completed", "passed")
    if is_success:
        for item in steps.values():
            if item["status"] == "unverified" and item.get("action_result") == "completed":
                item["status"] = "passed"

    return [steps[key] for key in sorted(order, key=lambda item: (steps[item].get("sequence") is None, steps[item].get("sequence") or 0))]


# ---------------------------------------------------------------------------
# Validation Report Signing & HTML Generation (Chunk 13)
# ---------------------------------------------------------------------------
import hashlib
import hmac
import time
import uuid
from pathlib import Path
from typing import Any, Optional, Union

import jinja2

_TEMPLATES_DIR = Path(__file__).resolve().parents[3] / "templates"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=jinja2.select_autoescape(["html", "xml"]),
)


def generate_validation_signature(validation_id: uuid.UUID, expires_at: int | None = None) -> str:
    """Generate a HMAC-SHA256 signature for a validation report."""
    from app.modules.auth.dependencies import _get_jwt_secret
    from app.config.settings import settings

    secret = _get_jwt_secret()
    ttl_seconds = settings.SIGNED_URL_TTL_DAYS * 86400
    expires_at = expires_at if expires_at is not None else int(time.time()) + ttl_seconds
    msg = f"validation:{validation_id}:{expires_at}"
    digest = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{expires_at}.{digest}"


def verify_validation_signature(validation_id: uuid.UUID, signature: str) -> bool:
    """Verify HMAC signature and check expiry timestamp."""
    from app.modules.auth.dependencies import _get_jwt_secret

    try:
        expiry_text, supplied = signature.split(".", 1)
        expires_at = int(expiry_text)
    except (ValueError, TypeError):
        return False

    if expires_at < int(time.time()):
        return False

    secret = _get_jwt_secret()
    msg = f"validation:{validation_id}:{expires_at}"
    expected = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


class ReportGenerator:
    """Generates signed, shareable, and diff-able validation reports."""

    def __init__(self, db: Optional[Any] = None):
        self.db = db

    async def _load_report(self, validation_id: Union[uuid.UUID, str]) -> Any:
        from sqlalchemy import select
        from app.modules.validation.models import ValidationReportModel
        from app.modules.validation.schemas import ValidationReport

        uid = uuid.UUID(str(validation_id))
        stmt = select(ValidationReportModel).where(ValidationReportModel.id == uid)
        res = await self.db.execute(stmt)
        model = res.scalars().first()
        if not model:
            raise ValueError(f"Validation report {validation_id} not found")
        return ValidationReport(
            id=model.id,
            request=model.request,
            impact_report=model.impact_report,
            results=model.results,
            overall_status=model.overall_status,
            duration_ms=model.duration_ms,
            started_at=model.started_at,
            finished_at=model.finished_at,
            evidence_summary=model.evidence_summary,
            signed_url=model.signed_url,
        )

    async def generate_validation_report(
        self,
        validation_id: Union[uuid.UUID, str, Any],
        report: Optional[Any] = None,
        project_name: Optional[str] = None,
    ) -> str:
        """Generate self-contained HTML for a single ValidationReport."""
        from app.modules.validation.schemas import ValidationReport

        if isinstance(validation_id, ValidationReport):
            v_report = validation_id
        elif report is not None:
            v_report = report
        elif self.db is not None:
            v_report = await self._load_report(validation_id)
        else:
            raise ValueError("ValidationReport or DB session required to generate report")

        if getattr(v_report, "summary", None) is None:
            try:
                from app.engine.ai.provider import get_ai_provider
                from app.engine.ai.reasoner import AgentReasoner
                reasoner = AgentReasoner(get_ai_provider())
                v_report.summary = await reasoner.synthesize_report_summary(v_report.model_dump())
            except Exception:
                pass

        gherkin_by_flow: dict[str, str] = {}
        evidence_by_flow: dict[str, list[dict]] = {}


        if self.db is not None:
            from sqlalchemy import select
            from app.modules.flows.models import Flow
            from app.modules.executions.evidence_service import EvidenceService

            flow_ids = [res.flow_id for res in v_report.results]
            if flow_ids:
                stmt_flows = select(Flow).where(Flow.id.in_(flow_ids))
                f_res = await self.db.execute(stmt_flows)
                for f in f_res.scalars().all():
                    if f.gherkin_repr:
                        gherkin_by_flow[str(f.id)] = f.gherkin_repr
                    else:
                        from app.modules.flows.generator.representations.gherkin import to_gherkin_representation
                        from app.modules.flows.generator.schemas import ExecutionStep
                        steps_objs = [
                            ExecutionStep(**s) if isinstance(s, dict) else s
                            for s in (f.steps or [])
                        ]
                        gherkin_by_flow[str(f.id)] = to_gherkin_representation(f.name, steps_objs)

            ev_service = EvidenceService(self.db)
            all_evidence = await ev_service.get_for_validation(v_report.id)
            for ev in all_evidence:
                flow_key = None
                for res in v_report.results:
                    if ev.id in res.evidence_ids or str(ev.id) in [str(eid) for eid in res.evidence_ids]:
                        flow_key = str(res.flow_id)
                        break
                if not flow_key and v_report.results:
                    flow_key = str(v_report.results[0].flow_id)
                if flow_key:
                    if flow_key not in evidence_by_flow:
                        evidence_by_flow[flow_key] = []
                    evidence_by_flow[flow_key].append({
                        "id": str(ev.id),
                        "execution_id": str(ev.execution_id),
                        "title": sanitize_text(ev.title),
                        "purpose": ev.purpose,
                        "step_id": ev.step_id,
                        "storage_url": ev.storage_url,
                        "storage_key": ev.storage_key,
                        "a11y_tree": sanitize_text(ev.a11y_tree, limit=2000) if ev.a11y_tree else None,
                        "dom_snapshot": sanitize_text(ev.dom_snapshot, limit=2000) if ev.dom_snapshot else None,
                        "network_log": sanitize_payload(ev.network_log),
                        "video_url": ev.video_url,
                        "element_locator": sanitize_text(ev.element_locator, limit=200) if ev.element_locator else None,
                        "timestamp_range": ev.timestamp_range,
                        "note": sanitize_text(ev.note, limit=500) if ev.note else None,
                    })

        for res in v_report.results:
            fid = str(res.flow_id)
            if fid not in gherkin_by_flow:
                gherkin_by_flow[fid] = (
                    f"Feature: {res.flow_name}\n"
                    f"  Scenario: Execute {res.flow_name}\n"
                    f"    Given the application is accessible\n"
                    f"    When the flow steps are executed\n"
                    f"    Then the result status is \"{res.status}\"\n"
                )

        template = _jinja_env.get_template("validation_report.html")
        return template.render(
            report=v_report,
            project_name=project_name or "Project",
            gherkin_by_flow=gherkin_by_flow,
            evidence_by_flow=evidence_by_flow,
            is_diff=False,
            diff=None,
            signing_key_id="kova-hmac-v1",
        )

    async def generate_diff_report(
        self,
        validation_id_before: Union[uuid.UUID, str, Any],
        validation_id_after: Optional[Union[uuid.UUID, str, Any]] = None,
        project_name: Optional[str] = None,
    ) -> str:
        """Generate self-contained HTML for a diff between two ValidationReports."""
        from app.modules.validation.differ import ReportDiffer
        from app.modules.validation.schemas import ReportDiff, ValidationReport

        if isinstance(validation_id_before, ReportDiff):
            diff = validation_id_before
            rep_after = diff.report_after
        else:
            if isinstance(validation_id_before, ValidationReport):
                rep_before = validation_id_before
            elif self.db is not None:
                rep_before = await self._load_report(validation_id_before)
            else:
                raise ValueError("ValidationReport or DB session required for before run")

            if isinstance(validation_id_after, ValidationReport):
                rep_after = validation_id_after
            elif self.db is not None and validation_id_after is not None:
                rep_after = await self._load_report(validation_id_after)
            else:
                raise ValueError("ValidationReport or DB session required for after run")

            diff = ReportDiffer.diff(rep_before, rep_after)

        template = _jinja_env.get_template("validation_report.html")
        return template.render(
            report=rep_after,
            project_name=project_name or "Project",
            gherkin_by_flow={},
            evidence_by_flow={},
            is_diff=True,
            diff=diff,
            signing_key_id="kova-hmac-v1",
        )
