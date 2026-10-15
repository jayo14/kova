"""Change detection and impact analysis engine."""
from __future__ import annotations

import fnmatch
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


def _file_matches_pattern(file_path: str, pattern: str) -> bool:
    """Check if file matches exact path, suffix, or glob pattern."""
    p = pattern.strip()
    if not p:
        return False
    # Exact or stripped match
    if file_path == p or file_path.lstrip("/") == p.lstrip("/"):
        return True
    # Suffix match (e.g. pattern "Navbar.tsx" matching "frontend/components/Navbar.tsx")
    if file_path.endswith("/" + p.lstrip("/")):
        return True
    # Glob match
    if fnmatch.fnmatch(file_path, p) or fnmatch.fnmatch(file_path.lstrip("/"), p.lstrip("/")):
        return True
    return False


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
        raw_caps = self.product_model.get("capabilities", []) if isinstance(self.product_model, dict) else []
        product_graph_consulted = bool(raw_caps)

        # Empty product graph handling: report honestly when files changed
        if not product_graph_consulted and cleaned_files:
            return ImpactReport(
                changed_files=cleaned_files,
                affected_capabilities=[],
                affected_routes=[],
                reasons={},
                confidence=0.0,
                uncertainty=["No Product Graph available; cannot perform targeted validation. Run Product Discovery first."],
                recommended_scope="full",
                downstream_effects=[],
                product_graph_consulted=False,
                unmatched_files=cleaned_files,
            )

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
                product_graph_consulted=product_graph_consulted,
                unmatched_files=[],
            )

        affected_capabilities: set[str] = set()
        affected_routes: set[str] = set()
        reasons: dict[str, str] = {}
        downstream_effects: list[str] = []
        uncertainties: list[str] = []
        unmatched_files: list[str] = []

        shared_cap_changed = False
        has_shared_caps = any(
            isinstance(cap, dict) and (cap.get("kind") == "shared" or cap.get("is_shared") is True)
            for cap in raw_caps
        )
        if product_graph_consulted and not has_shared_caps:
            uncertainties.append("Product Graph contains no shared capabilities; cannot assess shared component impact.")

        # 1. Analyze each file path deterministically against the Product Graph
        for f in cleaned_files:
            file_matched = False

            # Extract Next.js / frontend page routes (app/.../page.tsx or pages/...)
            route_match = re.search(r"(?:app|pages)/([a-zA-Z0-9_\-\/\[\]]+?)(?:/page|\.[a-zA-Z]+$)", f)
            clean_route = None
            if route_match:
                extracted_route = "/" + route_match.group(1).replace("[", ":").replace("]", "")
                clean_route = re.sub(r"/+", "/", extracted_route)

            for cap in raw_caps:
                if not isinstance(cap, dict):
                    continue
                cap_name = cap.get("name", "")
                if not cap_name:
                    continue

                source_files = cap.get("source_files", [])
                routes = cap.get("routes", [])
                is_shared = cap.get("kind") == "shared" or cap.get("is_shared") is True

                matched_by_source = any(_file_matches_pattern(f, pattern) for pattern in source_files)
                matched_by_route = clean_route is not None and clean_route in routes

                if matched_by_source or matched_by_route:
                    file_matched = True
                    affected_capabilities.add(cap_name)

                    if matched_by_source:
                        reasons[cap_name] = f"File {f} is listed as a source file for capability '{cap_name}' in the Product Graph."
                    else:
                        reasons[cap_name] = f"Source route file {f} matches route '{clean_route}' for capability '{cap_name}' in the Product Graph."

                    if clean_route is not None:
                        affected_routes.add(clean_route)
                        reasons[clean_route] = f"Source route file {f} was directly modified."

                    if is_shared:
                        shared_cap_changed = True
                        downstream_effects.append(
                            f"Shared capability '{cap_name}' modified by {f}; affects downstream workflows."
                        )

            if not file_matched:
                unmatched_files.append(f)
                if clean_route is not None:
                    affected_routes.add(clean_route)
                    reasons[clean_route] = f"Source route file {f} was directly modified."

        # 2. Advisory commit message analysis (broadens scope & adds uncertainties, does not invent capabilities)
        if commit_message:
            msg_lower = commit_message.lower()
            if any(term in msg_lower for term in ["breaking", "migration", "refactor"]):
                uncertainties.append("Commit message signals refactor or breaking change; broader impact possible.")

        # 3. Determine confidence and recommended validation scope
        confidence = 1.0
        recommended_scope = "targeted"

        if shared_cap_changed:
            recommended_scope = "expanded"
            uncertainties.append("Shared system capability modified; recommended scope expanded to verify downstream workflows.")
            confidence = min(confidence, 0.85)

        if unmatched_files:
            if recommended_scope == "targeted":
                recommended_scope = "expanded"
            uncertainties.append(
                f"{len(unmatched_files)} modified file(s) could not be mapped to known capabilities in the Product Graph: "
                f"{', '.join(unmatched_files[:3])}{'...' if len(unmatched_files) > 3 else ''}; expanding scope to avoid missing regressions."
            )
            confidence = min(confidence, 0.60)

        if commit_message and any(term in commit_message.lower() for term in ["breaking", "migration", "refactor"]):
            if recommended_scope == "targeted":
                recommended_scope = "expanded"
            confidence = min(confidence, 0.80)

        if len(cleaned_files) > 20:
            recommended_scope = "full"
            uncertainties.append(f"Large diff across {len(cleaned_files)} files; recommended full regression validation.")
            confidence = min(confidence, 0.75)

        return ImpactReport(
            changed_files=cleaned_files,
            affected_capabilities=sorted(affected_capabilities),
            affected_routes=sorted(affected_routes),
            reasons=reasons,
            confidence=confidence,
            uncertainty=uncertainties,
            recommended_scope=recommended_scope,
            downstream_effects=downstream_effects,
            product_graph_consulted=product_graph_consulted,
            unmatched_files=unmatched_files,
        )
