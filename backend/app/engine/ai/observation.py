"""Compact semantic observations from the Playwright runtime.

The deterministic PageObserver remains the source of browser facts (spec §3/§7).
This module renders its raw output into a bounded, structured view suitable for
AI reasoning — never raw HTML dumps. Budget: ~2KB per observation.
"""

from typing import Any

from app.engine.browser.observer import PageObserver


def build_semantic_observation(observation: dict[str, Any]) -> dict[str, Any]:
    """Render a PageObserver result into a compact semantic view.

    Keeps: url, title, headings, buttons, links (bounded), inputs, forms,
    auth signals. Caps element lists so observations stay cheap.
    """
    elements = observation.get("elements", [])
    text = observation.get("text", "") or ""

    buttons = []
    links = []
    inputs = []
    selects = []
    for el in elements:
        etype = el.get("type")
        name = (el.get("name") or "").strip()[:60]
        if not name:
            continue
        if etype == "button":
            buttons.append({"name": name, "role": el.get("role", ""), "selector": el.get("selector", "")})
        elif etype == "link":
            links.append({"name": name, "href": (el.get("href") or "")[:120], "selector": el.get("selector", "")})
        elif etype in ("input", "textarea"):
            inputs.append({
                "name": name,
                "input_type": el.get("input_type", ""),
                "placeholder": (el.get("placeholder") or "")[:40],
                "label": (el.get("label") or "")[:40],
                "filled": bool(el.get("filled")),
                "selector": el.get("selector", ""),
            })
        elif etype == "select":
            opts = [o.get("text", "")[:30] for o in (el.get("options") or [])[:6]]
            selects.append({"name": name, "options": opts})

    # Headings: prefer real DOM headings from PageObserver if present
    headings = observation.get("headings") or [ln.strip() for ln in text.splitlines() if ln.strip()][:4]
    dialogs = observation.get("dialogs", [])
    alerts = observation.get("alerts", [])

    return {
        "url": observation.get("url", ""),
        "title": (observation.get("title") or "")[:100],
        "headings": headings[:6],
        "dialogs": dialogs[:3],
        "alerts": alerts[:4],
        "buttons": buttons[:15],
        "links": links[:15],
        "inputs": inputs[:10],
        "selects": selects[:5],
        "forms": [
            {
                "action": (f.get("action") or "")[:80],
                "method": f.get("method", ""),
                "fields": f.get("fields", [])[:8],
            }
            for f in (observation.get("forms") or [])[:5]
        ],
        "text_excerpt": text[:400],
        "auth_signals": detect_auth_signals(observation),
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
