from __future__ import annotations

import logging
import uuid
from typing import Any

from app.modules.product_graph.schemas import Page, Persona

logger = logging.getLogger(__name__)

KNOWN_ROLES = {
    "developer": ["view_docs", "manage_keys", "test_apis"],
    "admin": ["manage_system", "manage_users"],
    "instructor": ["create_courses", "grade_submissions", "view_reports"],
    "teacher": ["create_courses", "grade_submissions"],
    "student": ["enroll_courses", "view_courses", "submit_assignments"],
    "manager": ["manage_team", "view_reports"],
    "buyer": ["browse_products", "purchase", "view_orders"],
    "seller": ["list_products", "manage_inventory", "view_sales"],
    "member": ["view_content", "edit_profile"],
    "guest": ["browse_public"],
    "user": ["view_dashboard", "edit_profile"],
}


class PersonaDetector:
    def __init__(self, project_id: uuid.UUID):
        self.project_id = project_id

    async def detect_personas(
        self, browser_page: Any, pages: list[Page]
    ) -> list[Persona]:
        """Detect personas from grounded role switchers, role-scoped routes, and UI options."""
        detected_roles: dict[str, dict[str, Any]] = {}

        # 1. Inspect DOM strictly for role-switcher controls, select dropdowns, and portal buttons
        if browser_page:
            try:
                dom_roles = await browser_page.evaluate("""
                    () => {
                        const roles = new Set();
                        // Check select dropdowns
                        document.querySelectorAll('select').forEach(sel => {
                            const name = (sel.name || sel.id || sel.getAttribute('aria-label') || '').toLowerCase();
                            if (name.includes('role') || name.includes('user_type') || name.includes('account_type') || name.includes('persona')) {
                                Array.from(sel.options).forEach(opt => {
                                    const txt = (opt.textContent || opt.value || '').trim();
                                    if (txt && txt.length < 30 && !['select', 'choose', 'all'].includes(txt.toLowerCase())) {
                                        roles.add(txt);
                                    }
                                });
                            }
                        });
                        // Check explicit data attributes
                        document.querySelectorAll('[data-role], [data-persona], [data-account-type]').forEach(el => {
                            const roleAttr = (el.getAttribute('data-role') || el.getAttribute('data-persona') || el.getAttribute('data-account-type') || '').trim();
                            if (roleAttr && roleAttr.length < 30) roles.add(roleAttr);
                        });
                        // Check explicit action buttons with 'sign in as <role>', 'login as <role>', or '<role> portal'
                        document.querySelectorAll('button, a[href]').forEach(el => {
                            const txt = (el.innerText || el.getAttribute('aria-label') || '').trim().toLowerCase();
                            ['student', 'instructor', 'teacher', 'admin', 'manager', 'seller', 'buyer', 'member', 'developer'].forEach(k => {
                                if (
                                    txt === `sign in as ${k}` ||
                                    txt === `login as ${k}` ||
                                    txt === `log in as ${k}` ||
                                    txt === `${k} login` ||
                                    txt === `${k} portal` ||
                                    txt === `${k} sign in`
                                ) {
                                    roles.add(k);
                                }
                            });
                        });
                        return Array.from(roles);
                    }
                """)
                for r in dom_roles:
                    r_clean = r.strip().lower()
                    for known, caps in KNOWN_ROLES.items():
                        if known in r_clean or r_clean in known:
                            detected_roles[known] = {
                                "description": f"Detected role: {known.capitalize()}",
                                "credentials_required": True,
                                "capabilities": caps,
                                "confidence": 0.9,
                            }
            except Exception as e:
                logger.debug("DOM role switcher check encountered: %s", e)

        # 2. Inspect route path patterns with strict boundary checks
        for p in pages:
            path_lower = p.url_pattern.lower()
            for known, caps in KNOWN_ROLES.items():
                if (
                    f"/{known}/" in path_lower
                    or path_lower.endswith(f"/{known}")
                    or path_lower == f"/{known}"
                    or f":{known}" in path_lower
                ):
                    if known not in detected_roles:
                        detected_roles[known] = {
                            "description": f"Role inferred from path prefix {p.url_pattern}",
                            "credentials_required": True,
                            "capabilities": caps,
                            "confidence": 0.8,
                        }

        # If nothing detected, provide at least the baseline user persona
        if not detected_roles:
            detected_roles["standard_user"] = {
                "description": "Default authenticated/unauthenticated user persona",
                "credentials_required": False,
                "capabilities": ["browse", "interact"],
                "confidence": 1.0,
            }

        personas: list[Persona] = []
        for name, meta in detected_roles.items():
            personas.append(
                Persona(
                    project_id=self.project_id,
                    name=name,
                    description=meta["description"],
                    credentials_required=meta["credentials_required"],
                    default_capabilities=meta["capabilities"],
                    source="discovered",
                    confidence=meta["confidence"],
                )
            )

        return personas
