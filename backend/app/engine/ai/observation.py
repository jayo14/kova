"""Compact semantic observations from the Playwright runtime.

The deterministic PageObserver remains the source of browser facts (spec §3/§7).
This module renders its raw output into a bounded, structured view suitable for
AI reasoning — never raw HTML dumps. Elements are ranked by interactivity and state.
"""

from typing import Any


def rank_interactive_elements(
    elements: list[dict[str, Any]], dialogs: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Rank interactive elements by importance, state, dialog context, and visibility."""
    scored: list[tuple[float, dict[str, Any]]] = []
    has_active_dialog = bool(dialogs)

    dialog_boxes = [
        d.get("bounding_box") for d in (dialogs or []) if isinstance(d, dict) and d.get("bounding_box")
    ]

    for el in elements:
        if not isinstance(el, dict):
            continue

        score = 0.0
        role = (el.get("role") or "").lower()
        etype = (el.get("type") or "").lower()
        name = (el.get("accessible_name") or el.get("name") or el.get("label") or "").lower()
        state = el.get("state") or {}
        box = el.get("bounding_box") or {}

        # Base role weighting
        if role in ("button",) or etype == "button":
            score += 40.0
        elif role in ("textbox",) or etype in ("input", "textarea"):
            score += 35.0
        elif role in ("combobox",) or etype == "select":
            score += 25.0
        elif role in ("link",) or etype == "link":
            score += 15.0

        # Primary action cues
        if any(kw in name for kw in ("submit", "continue", "next", "sign in", "login", "save", "publish", "enroll", "verify", "enter")):
            score += 25.0
        if el.get("input_type") == "submit" or "primary" in (el.get("selector") or "").lower():
            score += 20.0

        # State cues
        if state.get("required") and not state.get("filled"):
            score += 30.0
        elif not state.get("filled") and etype in ("input", "textarea"):
            score += 15.0
        if state.get("invalid"):
            score += 25.0
        if state.get("disabled"):
            score -= 50.0

        # Viewport position
        if box:
            bx, by, bw, bh = box.get("x", 0), box.get("y", 0), box.get("width", 0), box.get("height", 0)
            if bx >= 0 and by >= 0 and bw > 0 and bh > 0:
                score += 20.0
                # In active dialog bounding box
                for dbox in dialog_boxes:
                    if dbox and (dbox.get("x", 0) <= bx <= dbox.get("x", 0) + dbox.get("width", 0)) and \
                       (dbox.get("y", 0) <= by <= dbox.get("y", 0) + dbox.get("height", 0)):
                        score += 50.0

        scored.append((score, el))

    # Sort descending by score
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored]


def compute_observation_diff(
    prev: dict[str, Any] | None, curr: dict[str, Any]
) -> dict[str, Any]:
    """Compute structural diff between previous and current observations."""
    if not prev:
        new_names = [
            e.get("accessible_name") or e.get("name") or e.get("selector", "")
            for e in curr.get("elements", [])
            if isinstance(e, dict)
        ]
        return {
            "url_changed": False,
            "new_elements": new_names[:20],
            "removed_elements": [],
            "new_alerts": curr.get("alerts", [])[:5],
            "diff_summary": "Initial page observation",
        }

    prev_url = prev.get("url", "")
    curr_url = curr.get("url", "")
    url_changed = (prev_url != curr_url)

    def _el_key(e: dict) -> str:
        return f"{e.get('type')}:{e.get('role')}:{e.get('name') or e.get('selector')}:{e.get('frame')}"

    prev_keys = {_el_key(e) for e in prev.get("elements", []) if isinstance(e, dict)}
    curr_keys = {_el_key(e) for e in curr.get("elements", []) if isinstance(e, dict)}

    new_el_names = [
        e.get("accessible_name") or e.get("name") or e.get("selector", "")
        for e in curr.get("elements", [])
        if isinstance(e, dict) and _el_key(e) not in prev_keys
    ]
    removed_el_names = [
        e.get("accessible_name") or e.get("name") or e.get("selector", "")
        for e in prev.get("elements", [])
        if isinstance(e, dict) and _el_key(e) not in curr_keys
    ]

    prev_alerts = set(prev.get("alerts", []))
    new_alerts = [a for a in curr.get("alerts", []) if a not in prev_alerts]

    changes = []
    if url_changed:
        changes.append(f"URL changed from '{prev_url}' to '{curr_url}'")
    if new_el_names:
        changes.append(f"New elements: {', '.join(str(n) for n in new_el_names[:5])}")
    if removed_el_names:
        changes.append(f"Removed elements: {', '.join(str(n) for n in removed_el_names[:5])}")
    if new_alerts:
        changes.append(f"New alerts: {', '.join(str(a) for a in new_alerts[:3])}")

    return {
        "url_changed": url_changed,
        "from_url": prev_url if url_changed else None,
        "to_url": curr_url if url_changed else None,
        "new_elements": new_el_names[:20],
        "removed_elements": removed_el_names[:20],
        "new_alerts": new_alerts,
        "diff_summary": "; ".join(changes) if changes else "No DOM changes detected",
    }


def build_semantic_observation(
    observation: dict[str, Any], previous_observation: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Render a PageObserver result into a structured semantic view with ranked elements and diffs."""
    raw_elements = observation.get("elements", [])
    dialogs = observation.get("dialogs", [])
    alerts = observation.get("alerts", [])
    text = observation.get("text", "") or ""

    # Rank interactive elements instead of arbitrary truncation
    ranked_elements = rank_interactive_elements(raw_elements, dialogs=dialogs)

    buttons = []
    links = []
    inputs = []
    selects = []

    for el in ranked_elements:
        etype = el.get("type")
        name = (el.get("accessible_name") or el.get("name") or "").strip()[:80]
        if not name:
            name = (el.get("selector") or "").strip()[:80]
        if not name:
            continue

        item_data = {
            "name": name,
            "role": el.get("role", ""),
            "selector": el.get("selector", ""),
            "bounding_box": el.get("bounding_box"),
            "state": el.get("state", {}),
            "frame": el.get("frame", "main"),
        }

        if etype == "button":
            buttons.append(item_data)
        elif etype == "link":
            item_data["href"] = (el.get("href") or "")[:120]
            links.append(item_data)
        elif etype in ("input", "textarea"):
            item_data["input_type"] = el.get("input_type", "text")
            item_data["placeholder"] = (el.get("placeholder") or "")[:40]
            item_data["label"] = (el.get("label") or "")[:40]
            item_data["filled"] = bool((el.get("state") or {}).get("filled"))
            inputs.append(item_data)
        elif etype == "select":
            item_data["options"] = [o.get("text", "")[:30] for o in (el.get("options") or [])[:6]]
            selects.append(item_data)

    headings = observation.get("headings") or [ln.strip() for ln in text.splitlines() if ln.strip()][:6]
    diff = compute_observation_diff(previous_observation, observation)

    return {
        "url": observation.get("url", ""),
        "title": (observation.get("title") or "")[:100],
        "headings": headings[:6],
        "dialogs": dialogs[:5],
        "alerts": alerts[:8],
        "ranked_elements": ranked_elements[:40],
        "buttons": buttons,
        "links": links,
        "inputs": inputs,
        "selects": selects,
        "forms": [
            {
                "action": (f.get("action") or "")[:80],
                "method": f.get("method", ""),
                "fields": f.get("fields", [])[:8],
            }
            for f in (observation.get("forms") or [])[:5]
        ],
        "text_excerpt": text[:600],
        "auth_signals": detect_auth_signals(observation),
        "diff": diff,
    }


def detect_auth_signals(observation: dict[str, Any]) -> list[str]:
    """Cheap deterministic auth-state signals from an observation."""
    signals: list[str] = []
    url = (observation.get("url") or "").lower()
    elements = observation.get("elements", [])
    text = (observation.get("text") or "").lower()
    dialog_text = " ".join([d.get("text", "").lower() for d in observation.get("dialogs", []) if isinstance(d, dict)])
    alert_text = " ".join([a.lower() for a in observation.get("alerts", []) if isinstance(a, str)])
    all_text = f"{text} {dialog_text} {alert_text}"

    if any(kw in url for kw in ("/login", "/signin", "/sign-in", "/auth")):
        signals.append("login_page_url")
    if any(el.get("input_type") == "password" for el in elements if el.get("type") == "input"):
        signals.append("password_field_present")
    if any(kw in all_text for kw in ("forgot password", "reset password", "forgot your password", "can't access", "cant access", "recover account", "recovery")):
        signals.append("password_recovery_link_present")
    if any(kw in all_text for kw in ("check your email", "verify your email", "confirm your account", "sent a link", "recovery email sent", "instructions have been sent", "email sent")):
        signals.append("email_verification_prompt")
    if any(kw in all_text for kw in ("dashboard", "welcome back", "sign out", "log out", "logout")):
        signals.append("authenticated_indicators")
    return signals
