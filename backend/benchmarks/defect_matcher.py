"""Ground truth defect matcher for benchmark validation (§14, Prompt A).

Evaluates execution data, events, verifications, and evidence against known defects.
A defect counts as detected only if:
1. The execution/report contains a failed check or finding matching ground_truth.yml
2. Non-empty evidence (screenshot, DOM snapshot, or network log) is attached.
"""

from typing import Any


def match_defects(
    known_defects: list[dict[str, Any]],
    events: list[Any],
    network_responses: list[dict[str, Any]],
    verification: dict[str, Any] | None,
    evidence_items: list[dict[str, Any]],
    page_text: str = "",
    final_url: str = "",
    visual_findings: list[dict[str, Any]] | None = None,
    auth_result: Any | None = None,
) -> tuple[int, list[str], bool, float, str]:
    """Match recorded execution findings against ground truth known defects.

    Returns:
        (detected_count, detected_ids, evidence_valid, evidence_completeness, notes)
    """
    detected_ids: list[str] = []
    notes: list[str] = []

    # Check evidence validity: must have non-empty screenshot or recorded artifacts
    has_valid_evidence = False
    evidence_count = len(evidence_items)

    for ev in evidence_items:
        meta = ev.get("metadata", {}) if isinstance(ev, dict) else getattr(ev, "metadata", {}) or {}
        size = meta.get("size_bytes", 0) or meta.get("screenshot_size", 0)
        image_bytes = ev.get("image_bytes") if isinstance(ev, dict) else getattr(ev, "image_bytes", None)
        storage_url = ev.get("storage_url") if isinstance(ev, dict) else getattr(ev, "storage_url", None)
        screenshot = ev.get("screenshot") if isinstance(ev, dict) else getattr(ev, "screenshot", None)
        if (image_bytes and len(image_bytes) > 500) or size > 500 or storage_url or screenshot:
            has_valid_evidence = True
            break

    # Also check events for evidence screenshots
    for e in events:
        etype = getattr(e, "event_type", e.get("event_type", "") if isinstance(e, dict) else "")
        payload = getattr(e, "payload", e.get("payload", {}) if isinstance(e, dict) else {}) or {}
        if etype in ("browser.screenshot", "evidence.captured"):
            screenshot_data = payload.get("screenshot") or payload.get("image_bytes") or payload.get("data")
            if screenshot_data and len(screenshot_data) > 500:
                has_valid_evidence = True
                evidence_count += 1
            elif payload.get("size_bytes", 0) > 500 or payload.get("screenshot_size", 0) > 500:
                has_valid_evidence = True
                evidence_count += 1

    evidence_completeness = 1.0 if has_valid_evidence else (0.5 if evidence_count > 0 else 0.0)

    # Process each known defect
    for defect in known_defects:
        d_id = defect.get("id", "")
        d_method = defect.get("detection_method", "")
        d_loc = defect.get("location", "")
        d_type = defect.get("type", "")

        matched = False

        if d_method == "network_response_inspection":
            # Check for 5xx on location or 401 on profile
            has_500 = any(
                r.get("status") == 500 and (not d_loc or d_loc in r.get("url", ""))
                for r in network_responses
            )
            has_401_expiry = any(
                r.get("status") == 401 and "profile" in r.get("url", "")
                for r in network_responses
            ) or ("session has expired" in page_text.lower())

            # Also check network.error events
            event_net_500 = any(
                (getattr(e, "event_type", e.get("event_type", "") if isinstance(e, dict) else "") == "network.error"
                 and (getattr(e, "payload", e.get("payload", {}) if isinstance(e, dict) else {}) or {}).get("status") == 500)
                for e in events
            )

            if (has_500 or event_net_500 or has_401_expiry) and has_valid_evidence:
                matched = True
                detected_ids.append(d_id)
                notes.append(f"Network defect detected: {defect.get('description')}")

        elif d_method == "auth_verification":
            # Check for auth failure on login
            auth_failed = False
            if auth_result is not None:
                auth_failed = not getattr(auth_result, "success", False)
            has_401 = any(r.get("status") == 401 for r in network_responses)
            has_auth_err_text = "authentication failed" in page_text.lower() or "invalid credentials" in page_text.lower()
            if (auth_failed or has_401 or has_auth_err_text) and has_valid_evidence:
                matched = True
                detected_ids.append(d_id)
                notes.append(f"Auth failure defect detected: {defect.get('description')}")

        elif d_method == "authorization_check":
            # Non-admin accessed sensitive admin route without 403
            reached_admin = "/admin" in final_url or "admin console" in page_text.lower()
            not_forbidden = not any(r.get("status") == 403 for r in network_responses)
            if reached_admin and not_forbidden and has_valid_evidence:
                matched = True
                detected_ids.append(d_id)
                notes.append(f"Authorization defect detected: {defect.get('description')}")

        elif d_method == "visual_diff":
            # Visual check: element off-canvas or visual anomaly
            off_canvas = False
            if visual_findings:
                off_canvas = any(f.get("off_canvas", False) or f.get("x", 0) < 0 for f in visual_findings)
            if off_canvas and has_valid_evidence:
                matched = True
                detected_ids.append(d_id)
                notes.append(f"Visual defect detected: {defect.get('description')}")

        if not matched:
            notes.append(f"Known defect {d_id} not detected or missing evidence")

    detected_count = len(detected_ids)
    notes_str = "; ".join(notes) if notes else "No defects reported"

    return detected_count, detected_ids, has_valid_evidence, evidence_completeness, notes_str
