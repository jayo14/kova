from __future__ import annotations

import logging
import uuid
from typing import Any

from app.modules.product_graph.schemas import Page, Persona

logger = logging.getLogger(__name__)

KNOWN_ROLES = {
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
        """Detect personas from role switchers, role-scoped routes, and UI options."""
        detected_roles: dict[str, dict[str, Any]] = {}

        # 1. Inspect DOM for role-switcher controls
        try:
            dom_roles = await browser_page.evaluate("""
                () => {
                    const roles = new Set();
                    // Check select dropdowns
                    document.querySelectorAll('select').forEach(sel => {
                        const name = (sel.name || sel.id || '').toLowerCase();
                        if (name.includes('role') || name.includes('user') || name.includes('persona')) {
                            Array.from(sel.options).forEach(opt => {
                                const txt = (opt.textContent || opt.value || '').trim();
                                if (txt && txt.length < 30) roles.add(txt);
                            });
                        }
                    });
                    // Check buttons/tabs/radios with role indicators
                    document.querySelectorAll('[data-role], [data-persona], [role="tab"], button, label').forEach(el => {
                        const txt = (el.textContent || '').trim().toLowerCase();
                        const roleAttr = (el.getAttribute('data-role') || el.getAttribute('data-persona') || '').toLowerCase();
                        if (roleAttr) roles.add(roleAttr);
                        ['student', 'instructor', 'teacher', 'admin', 'manager', 'seller', 'buyer', 'member'].forEach(k => {
                            if (txt === k || txt.startsWith(k + ' ') || txt.includes('sign in as ' + k) || txt.includes('login as ' + k)) {
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

        # 2. Inspect route path patterns
        for p in pages:
            path_lower = p.url_pattern.lower()
            for known, caps in KNOWN_ROLES.items():
                if f"/{known}" in path_lower or f":{known}" in path_lower:
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
