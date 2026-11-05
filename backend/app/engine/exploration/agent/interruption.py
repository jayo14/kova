"""Intelligent interface obstruction and modal handling for autonomous exploration.

Enables Kova to investigate and reason about modals, dialogs, popovers, banners,
overlays, permission requests, onboarding screens, and other interface interruptions
before interacting. Distinguishes optional distractions, necessary prerequisites,
consequential decisions, and opportunities to discover application capabilities.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from app.engine.exploration.agent.schemas import AgentActionProposal, ExplorationAction
from app.engine.exploration.agent.understanding import ApplicationUnderstanding

logger = logging.getLogger(__name__)


class InterruptionType(str, Enum):
    """Categorization of an interface interruption based on purpose and semantics."""
    OPTIONAL_PROMPT = "optional_prompt"             # Install app, newsletter, announcements, promotions, tips
    REQUIRED_SETUP = "required_setup"               # Mandatory workspace creation, profile completion, onboarding
    PERMISSION_REQUEST = "permission_request"       # Notifications, geolocation, device access, external integration
    CONFIRMATION_DIALOG = "confirmation_dialog"     # Action confirmation, unsaved changes, discard alerts
    CHOICE_SELECTION = "choice_selection"           # Role/persona choice, mode/theme switch, preference selection
    BLOCKING_OBSTRUCTION = "blocking_obstruction"   # Non-dismissible overlay or unclassified blocker


class InterruptionDecision(str, Enum):
    """Reasoned action to take regarding an interface interruption."""
    DISMISS = "dismiss"                             # Close, minimize, or move out of the way
    COMPLETE_REQUIRED = "complete_required"         # Complete legitimate prerequisite using safe synthetic values
    MAKE_INFORMED_CHOICE = "make_informed_choice"   # Make a principled decision (e.g., decline invasive permissions)
    PRESERVE_AND_DEFER = "preserve_and_defer"       # Leave unresolved if underlying workspace remains interactive
    REQUEST_ASSISTANCE = "request_assistance"       # Halt and request human action for consequential decisions


@dataclass
class InterruptionAnalysis:
    """Rich semantic analysis of an encountered interface interruption."""
    interruption_type: InterruptionType
    decision: InterruptionDecision
    confidence: float
    reason: str
    title: str = ""
    description: str = ""
    is_modal: bool = True
    is_obstructing: bool = True
    can_dismiss: bool = True
    dismiss_control: dict[str, Any] | None = None
    action_control: dict[str, Any] | None = None
    required_inputs: list[dict[str, Any]] = field(default_factory=list)
    fields_to_fill: dict[str, Any] = field(default_factory=dict)
    event_description: str = ""
    action_proposal: AgentActionProposal | None = None


# Semantic pattern groupings (contextual indicators, not hardcoded CSS selectors)
INSTALL_PATTERNS = [
    r"\binstall\b", r"\bdesktop app\b", r"\bnative app\b", r"\bpwa\b",
    r"\badd to home\b", r"\bget the app\b", r"\bdownload app\b",
]

PROMO_ANNOUNCEMENT_PATTERNS = [
    r"\bwhat's new\b", r"\bannouncement\b", r"\bnewsletter\b", r"\bsubscribe\b",
    r"\bfeedback\b", r"\brate us\b", r"\bsurvey\b", r"\btour\b", r"\bproduct update\b",
    r"\bcookie preferences\b", r"\baccept cookies\b",
]

PERMISSION_PATTERNS = [
    r"\bnotifications?\b", r"\blocation\b", r"\bcamera\b", r"\bmicrophone\b",
    r"\bpermission\b", r"\ballow access\b", r"\bdevice access\b",
]

CONFIRMATION_PATTERNS = [
    r"\bare you sure\b", r"\bconfirm\b", r"\bdiscard changes\b", r"\bleave site\b",
    r"\bproceed\b", r"\bcontinue without saving\b",
]

REQUIRED_SETUP_PATTERNS = [
    r"\bworkspace name\b", r"\bcreate workspace\b", r"\bset up your workspace\b",
    r"\bname your (team|organization|project|workspace)\b", r"\bcomplete your profile\b",
    r"\bonboarding\b", r"\bgetting started\b", r"\bstep \d+ of \d+\b",
]

DISMISS_KEYWORDS = [
    "got it", "dismiss", "close", "not now", "maybe later", "skip",
    "later", "no thanks", "cancel", "remind me later", "continue without",
    "✕", "×", "close dialog", "close modal",
]


class InterruptionEvaluator:
    """Investigates, reasons about, and proposes actions for interface interruptions."""

    @staticmethod
    def evaluate(
        dialog: dict[str, Any],
        page_context: dict[str, Any],
        understanding: ApplicationUnderstanding,
    ) -> InterruptionAnalysis:
        """Analyzes a dialog or obstruction and determines the appropriate response."""
        title = str(dialog.get("title") or dialog.get("accessible_name") or "").strip()
        text = str(dialog.get("text") or "").strip()
        desc = str(dialog.get("description") or "").strip()
        combined_text = f"{title}\n{desc}\n{text}".lower()

        role = str(dialog.get("role") or "").lower()
        is_modal = bool(dialog.get("is_modal", True) or dialog.get("aria_modal", False))
        is_obstructing = bool(dialog.get("is_obstructing", True))
        buttons: list[dict[str, Any]] = dialog.get("buttons") or []
        inputs: list[dict[str, Any]] = dialog.get("inputs") or []

        # Find available dismiss controls
        dismiss_btn = InterruptionEvaluator._find_dismiss_button(buttons)
        can_dismiss = bool(dismiss_btn or dialog.get("can_dismiss", False))

        # Check required fields
        required_inputs = [inp for inp in inputs if inp.get("required") or inp.get("state", {}).get("required")]

        # 1. Evaluate Install App / PWA Prompts (e.g. Log2Def PWA prompt)
        if any(re.search(pat, combined_text, re.I) for pat in INSTALL_PATTERNS):
            if can_dismiss:
                btn_name = (dismiss_btn or {}).get("name") or (dismiss_btn or {}).get("text") or "Got it"
                return InterruptionAnalysis(
                    interruption_type=InterruptionType.OPTIONAL_PROMPT,
                    decision=InterruptionDecision.DISMISS,
                    confidence=0.95,
                    reason=f"Optional application installation prompt detected ({title or 'Install App'}); dismissing via '{btn_name}' to access workspace.",
                    title=title or "Install Application",
                    description=desc,
                    is_modal=is_modal,
                    is_obstructing=is_obstructing,
                    can_dismiss=True,
                    dismiss_control=dismiss_btn,
                    event_description=f"Dismissing optional installation prompt: {title or 'Install App'}",
                )

        # 2. Evaluate Promotional / Marketing / Announcement / Cookie Prompts
        if any(re.search(pat, combined_text, re.I) for pat in PROMO_ANNOUNCEMENT_PATTERNS):
            if can_dismiss:
                return InterruptionAnalysis(
                    interruption_type=InterruptionType.OPTIONAL_PROMPT,
                    decision=InterruptionDecision.DISMISS,
                    confidence=0.9,
                    reason=f"Optional announcement/promotional interruption ({title or 'Announcement'}); dismissing to resume exploration.",
                    title=title or "Announcement",
                    description=desc,
                    is_modal=is_modal,
                    is_obstructing=is_obstructing,
                    can_dismiss=True,
                    dismiss_control=dismiss_btn,
                    event_description=f"Dismissing optional announcement: {title or 'Notice'}",
                )

        # 3. Evaluate Permission Requests (Notifications, Location, etc.)
        if any(re.search(pat, combined_text, re.I) for pat in PERMISSION_PATTERNS):
            # Prefer declining/blocking optional browser permissions to prevent native prompt lockup
            decline_btn = InterruptionEvaluator._find_button_matching(
                buttons, ["don't allow", "block", "deny", "not now", "decline", "never", "disable", "later"]
            )
            target_btn = decline_btn or dismiss_btn
            if target_btn:
                return InterruptionAnalysis(
                    interruption_type=InterruptionType.PERMISSION_REQUEST,
                    decision=InterruptionDecision.MAKE_INFORMED_CHOICE,
                    confidence=0.88,
                    reason=f"Optional permission request detected ({title or 'Permissions'}); choosing non-invasive decline to maintain test stability.",
                    title=title or "Permission Request",
                    description=desc,
                    is_modal=is_modal,
                    is_obstructing=is_obstructing,
                    can_dismiss=True,
                    action_control=target_btn,
                    event_description=f"Declining optional permission request: {title or 'Permissions'}",
                )

        # 4. Evaluate Required Setup / Onboarding Steps
        is_setup_text = any(re.search(pat, combined_text, re.I) for pat in REQUIRED_SETUP_PATTERNS)
        if is_setup_text or (inputs and not can_dismiss):
            # Determine if we can supply safe synthetic test inputs
            fields_to_fill = {}
            needs_human = False

            for inp in inputs:
                name_attr = (inp.get("name") or inp.get("id") or inp.get("label") or "").lower()
                inp_type = (inp.get("type") or "text").lower()

                if any(w in name_attr for w in ["card", "payment", "ssn", "phone", "otp", "billing", "tax"]):
                    needs_human = True
                    break
                elif any(w in name_attr for w in ["workspace", "team", "org", "company"]):
                    fields_to_fill[inp.get("selector") or name_attr] = "Kova Test Workspace"
                elif any(w in name_attr for w in ["name", "full name", "display"]):
                    fields_to_fill[inp.get("selector") or name_attr] = "Test Explorer"
                elif any(w in name_attr for w in ["role", "title", "job"]):
                    fields_to_fill[inp.get("selector") or name_attr] = "QA Engineer"
                elif inp_type == "checkbox":
                    fields_to_fill[inp.get("selector") or name_attr] = True
                else:
                    fields_to_fill[inp.get("selector") or name_attr] = "Test Value"

            if needs_human:
                return InterruptionAnalysis(
                    interruption_type=InterruptionType.REQUIRED_SETUP,
                    decision=InterruptionDecision.REQUEST_ASSISTANCE,
                    confidence=0.9,
                    reason=f"Required setup requires consequential or sensitive information ({title or 'Setup'}); requesting human assistance.",
                    title=title or "Required Setup",
                    description=desc,
                    is_modal=is_modal,
                    is_obstructing=True,
                    can_dismiss=False,
                    event_description=f"Required setup requires human assistance: {title or 'Setup'}",
                )

            submit_btn = InterruptionEvaluator._find_button_matching(
                buttons, ["continue", "next", "submit", "save", "create", "done", "finish", "get started"]
            )
            return InterruptionAnalysis(
                interruption_type=InterruptionType.REQUIRED_SETUP,
                decision=InterruptionDecision.COMPLETE_REQUIRED,
                confidence=0.85,
                reason=f"Legitimate required setup wizard detected ({title or 'Setup'}); completing with safe synthetic test inputs.",
                title=title or "Required Setup",
                description=desc,
                is_modal=is_modal,
                is_obstructing=is_obstructing,
                can_dismiss=can_dismiss,
                required_inputs=inputs,
                fields_to_fill=fields_to_fill,
                action_control=submit_btn,
                event_description=f"Completing required workspace setup: {title or 'Setup'}",
            )

        # 5. Evaluate Confirmation Dialogs
        if any(re.search(pat, combined_text, re.I) for pat in CONFIRMATION_PATTERNS):
            confirm_btn = InterruptionEvaluator._find_button_matching(
                buttons, ["ok", "confirm", "yes", "proceed", "continue"]
            )
            target = confirm_btn or dismiss_btn
            return InterruptionAnalysis(
                interruption_type=InterruptionType.CONFIRMATION_DIALOG,
                decision=InterruptionDecision.MAKE_INFORMED_CHOICE,
                confidence=0.8,
                reason=f"Confirmation dialog detected ({title or 'Confirmation'}); confirming intended operation.",
                title=title or "Confirmation",
                description=desc,
                is_modal=is_modal,
                is_obstructing=is_obstructing,
                can_dismiss=can_dismiss,
                action_control=target,
                event_description=f"Confirming dialog prompt: {title or 'Confirmation'}",
            )

        # 6. Default Fallback
        if can_dismiss:
            return InterruptionAnalysis(
                interruption_type=InterruptionType.OPTIONAL_PROMPT,
                decision=InterruptionDecision.DISMISS,
                confidence=0.75,
                reason=f"Non-essential interface obstruction detected ({title or 'Dialog'}); dismissing to access underlying page.",
                title=title or "Dialog",
                description=desc,
                is_modal=is_modal,
                is_obstructing=is_obstructing,
                can_dismiss=True,
                dismiss_control=dismiss_btn,
                event_description=f"Dismissing interface obstruction: {title or 'Dialog'}",
            )

        if not is_modal and not is_obstructing:
            return InterruptionAnalysis(
                interruption_type=InterruptionType.OPTIONAL_PROMPT,
                decision=InterruptionDecision.PRESERVE_AND_DEFER,
                confidence=0.7,
                reason=f"Non-modal notification banner does not obstruct interaction; preserving and deferring.",
                title=title or "Banner",
                description=desc,
                is_modal=False,
                is_obstructing=False,
                can_dismiss=False,
                event_description=f"Preserving non-blocking banner: {title or 'Banner'}",
            )

        return InterruptionAnalysis(
            interruption_type=InterruptionType.BLOCKING_OBSTRUCTION,
            decision=InterruptionDecision.DISMISS,
            confidence=0.6,
            reason=f"Encountered interface obstruction without explicit controls; attempting dismissal via Escape key.",
            title=title or "Obstruction",
            description=desc,
            is_modal=is_modal,
            is_obstructing=is_obstructing,
            can_dismiss=False,
            event_description=f"Attempting Escape dismissal for obstruction: {title or 'Obstruction'}",
        )

    @staticmethod
    def _find_dismiss_button(buttons: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Finds the most suitable dismissal or close control from available buttons."""
        for b in buttons:
            name = str(b.get("name") or b.get("text") or b.get("aria_label") or "").strip().lower()
            if any(kw == name or f" {kw} " in f" {name} " or name.startswith(kw) for kw in DISMISS_KEYWORDS):
                return b
        for b in buttons:
            name = str(b.get("name") or b.get("text") or b.get("aria_label") or "").strip().lower()
            if any(kw in name for kw in ["got it", "dismiss", "close", "cancel", "✕", "×", "skip", "not now"]):
                return b
        return None

    @staticmethod
    def _find_button_matching(buttons: list[dict[str, Any]], keywords: list[str]) -> dict[str, Any] | None:
        """Finds a button matching any of the specified semantic keywords."""
        for b in buttons:
            name = str(b.get("name") or b.get("text") or b.get("aria_label") or "").strip().lower()
            if any(kw in name for kw in keywords):
                return b
        return None

    @staticmethod
    def propose_action_for_interruption(
        analysis: InterruptionAnalysis,
        dialog: dict[str, Any],
        node_id: str,
    ) -> AgentActionProposal | None:
        """Converts an interruption analysis into an executable AgentActionProposal."""
        if analysis.decision == InterruptionDecision.PRESERVE_AND_DEFER:
            return None

        dialog_sel = dialog.get("selector")

        if analysis.decision == InterruptionDecision.DISMISS:
            target = {
                "dialog_title": analysis.title,
                "dialog_selector": dialog_sel,
            }
            if analysis.dismiss_control:
                target["selector"] = analysis.dismiss_control.get("selector")
                target["text"] = analysis.dismiss_control.get("name") or analysis.dismiss_control.get("text")
                target["name"] = target["text"]

            return AgentActionProposal(
                action=ExplorationAction.DISMISS_INTERRUPTION,
                target=target,
                reason=analysis.reason,
                confidence=analysis.confidence,
                expected_effect="Dismiss interface obstruction and restore interaction with workspace",
            )

        if analysis.decision in (InterruptionDecision.COMPLETE_REQUIRED, InterruptionDecision.MAKE_INFORMED_CHOICE):
            target = {
                "dialog_title": analysis.title,
                "dialog_selector": dialog_sel,
                "fields": analysis.fields_to_fill,
            }
            if analysis.action_control:
                target["selector"] = analysis.action_control.get("selector")
                target["text"] = analysis.action_control.get("name") or analysis.action_control.get("text")
                target["name"] = target["text"]

            action_type = ExplorationAction.COMPLETE_INTERRUPTION if analysis.fields_to_fill else ExplorationAction.CLICK_CONTROL
            return AgentActionProposal(
                action=action_type,
                target=target,
                reason=analysis.reason,
                confidence=analysis.confidence,
                expected_effect="Satisfy required setup interaction to unlock application workspace",
            )

        return None
