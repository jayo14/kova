"""Change detection and impact analysis engine."""
from __future__ import annotations

import re
from typing import Any

from app.modules.validation.schemas import ImpactReport


def extract_files_from_diff(diff_content: str | None) -> list[str]:
    """Extract list of modified file paths from a unified git diff."""
    if not diff_content:
        return []
    files: set[str] = set()
    for line in diff_content.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                files.add(path)
        elif line.startswith("--- a/") and not line.startswith("--- a/dev/null"):
            path = line[6:].strip()
            if path:
                files.add(path)
        elif line.startswith("diff --git a/"):
            parts = line.split()
            if len(parts) >= 4:
                p = parts[3].removeprefix("b/").strip()
                if p:
                    files.add(p)
    return sorted(files)


class ChangeImpactAnalyzer:
    """Deterministically maps changed files and commit signals to product model capabilities."""

    def __init__(self, product_model: dict | None = None, flows: list[dict] | None = None):
        self.product_model = product_model or {}
        self.flows = flows or []

    def analyze(
        self,
        changed_files: list[str] | None = None,
        diff_content: str | None = None,
        commit_message: str | None = None,
    ) -> ImpactReport:
        files: set[str] = set(changed_files or [])
        if diff_content:
            files.update(extract_files_from_diff(diff_content))

        cleaned_files = sorted(f.strip() for f in files if f.strip())
        affected_capabilities: set[str] = set()
        affected_routes: set[str] = set()
        reasons: dict[str, str] = {}
        downstream_effects: list[str] = []
        uncertainties: list[str] = []

        if not cleaned_files and not commit_message:
            return ImpactReport(
                changed_files=[],
                affected_capabilities=[],
                affected_routes=[],
                reasons={},
                confidence=1.0,
                uncertainty=["No file changes or diff provided; defaulting to targeted validation."],
                recommended_scope="targeted",
                downstream_effects=[],
            )

        # 1. Analyze each file path deterministically
        shared_auth_changed = False
        shared_nav_changed = False
        schema_changed = False

        for f in cleaned_files:
            lower = f.lower()

            # Shared authentication & credentials
            if any(term in lower for term in ["auth", "login", "session", "credential", "jwt", "token", "user", "signup", "register"]):
                affected_capabilities.add("authentication")
                reasons["authentication"] = f"File {f} touches authentication or user session logic."
                shared_auth_changed = True

            # Navigation & shell headers
            if any(term in lower for term in ["nav", "header", "sidebar", "menu", "layout", "app-shell", "shell"]):
                shared_nav_changed = True
                downstream_effects.append(f"Global layout/navigation altered by {f}; affects top-level route accessibility.")

            # Database / Schema migrations
            if "alembic" in lower or "migration" in lower or "models" in lower or "schema" in lower:
                schema_changed = True
                downstream_effects.append(f"Database schema or model modified by {f}; may alter persisted entity state.")

            # Route & capability heuristics based on known paths
            if "course" in lower or "enroll" in lower:
                affected_capabilities.add("course_enrollment")
                reasons["course_enrollment"] = f"File {f} modifies course enrollment or material logic."
                downstream_effects.append("Downstream course content access and assignment submission workflows potentially affected.")

            if "assign" in lower or "grade" in lower or "submission" in lower:
                affected_capabilities.add("assignment_submission")
                reasons["assignment_submission"] = f"File {f} modifies assignment or grading workflows."

            if "cart" in lower or "checkout" in lower or "order" in lower or "payment" in lower:
                affected_capabilities.add("checkout")
                reasons["checkout"] = f"File {f} modifies order, cart, or payment handling."

            if "profile" in lower or "account" in lower or "settings" in lower:
                affected_capabilities.add("profile_management")
                reasons["profile_management"] = f"File {f} alters user profile or account settings."

            # Map Next.js / frontend page routes (app/.../page.tsx or pages/...)
            route_match = re.search(r"(?:app|pages)/([a-zA-Z0-9_\-\/\[\]]+?)(?:/page|\.[a-zA-Z]+$)", f)
            if route_match:
                extracted_route = "/" + route_match.group(1).replace("[", ":").replace("]", "")
                # Normalize route
                clean_route = re.sub(r"/+", "/", extracted_route)
                affected_routes.add(clean_route)
                reasons[clean_route] = f"Source route file {f} was directly modified."

        # 2. Check capabilities registered in the stored ProductModel
        stored_caps = self.product_model.get("capabilities", [])
        for cap in stored_caps:
            cap_name = cap.get("name") if isinstance(cap, dict) else str(cap)
            cap_routes = cap.get("routes", []) if isinstance(cap, dict) else []
            # If any affected route belongs to this capability
            if any(r in affected_routes for r in cap_routes):
                affected_capabilities.add(cap_name)
                reasons[cap_name] = f"Capability {cap_name} contains route affected by code change."

        # 3. Analyze commit message keywords if available
        if commit_message:
            msg_lower = commit_message.lower()
            if "auth" in msg_lower or "login" in msg_lower:
                affected_capabilities.add("authentication")
                reasons.setdefault("authentication", "Commit message explicitly mentions authentication.")
            if "enroll" in msg_lower or "course" in msg_lower:
                affected_capabilities.add("course_enrollment")
                reasons.setdefault("course_enrollment", "Commit message explicitly references course enrollment.")
            if "breaking" in msg_lower or "migration" in msg_lower or "refactor" in msg_lower:
                uncertainties.append("Commit message signals refactor or breaking change; broader impact possible.")

        # 4. Determine confidence and recommended validation scope
        confidence = 1.0
        recommended_scope = "targeted"

        if shared_auth_changed or shared_nav_changed or schema_changed:
            recommended_scope = "expanded"
            uncertainties.append("Shared system component or schema modified; recommended scope expanded to verify downstream workflows.")
            confidence = 0.85

        if len(cleaned_files) > 20:
            recommended_scope = "full"
            uncertainties.append(f"Large diff across {len(cleaned_files)} files; recommended full regression validation.")
            confidence = 0.75

        # If no deterministic capabilities were detected despite file changes, flag uncertainty and broaden scope!
        if cleaned_files and not affected_capabilities and not affected_routes:
            recommended_scope = "expanded"
            uncertainties.append("Modified files could not be mapped to specific known capabilities; expanding scope to avoid missing regressions.")
            confidence = 0.60

        return ImpactReport(
            changed_files=cleaned_files,
            affected_capabilities=sorted(affected_capabilities),
            affected_routes=sorted(affected_routes),
            reasons=reasons,
            confidence=confidence,
            uncertainty=uncertainties,
            recommended_scope=recommended_scope,
            downstream_effects=downstream_effects,
        )
