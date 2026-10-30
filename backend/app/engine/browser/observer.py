"""Deterministic page observer.

Extracts structured semantic information from a page without visual AI.
Returns buttons, links, inputs, selects, forms, and visible text.
"""

import asyncio
import logging
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)


class PageObserver:
    """Extracts structured observations from a Playwright Page.

    Deterministic only — no visual AI, no LLM calls.
    Parses the DOM to find interactive elements and their attributes.
    """

    def __init__(self, page: Page):
        self.page = page

    async def observe(self) -> dict[str, Any]:
        """Observe the current page and return structured data.

        Returns:
            {
                "url": str,
                "title": str,
                "elements": [
                    {"type": str, "name": str, "label": str, "role": str, ...},
                    ...
                ],
                "forms": [...],
                "text": str
            }
        """
        for attempt in range(3):
            try:
                try:
                    await self.page.wait_for_load_state("domcontentloaded", timeout=2000)
                except Exception:
                    pass

                url = self.page.url
                title = await self.page.title()

                elements = []
                elements.extend(await self._observe_buttons())
                elements.extend(await self._observe_links())
                elements.extend(await self._observe_inputs())
                elements.extend(await self._observe_textareas())
                elements.extend(await self._observe_selects())

                # Shadow DOM: descend into open shadow roots across frames.
                shadow_elements = await self._observe_shadow_dom()
                elements.extend(shadow_elements)

                forms = await self._observe_forms()

                text = await self._observe_visible_text()

                headings = await self._observe_headings()
                dialogs = await self._observe_dialogs()
                alerts = await self._observe_alerts()

                from app.engine.browser.auth import observe_auth_signals
                auth_signals = await observe_auth_signals(self.page, url)

                # Build routes/interactive summaries for exploration
                routes = []
                for el in elements:
                    if el.get("type") == "link":
                        routes.append({"href": el.get("href"), "text": el.get("name") or el.get("label")})
                interactive_elements = [e for e in elements if e.get("type") in ("button", "link", "input")]
                # Cross-origin iframe detection
                frames = await self._get_frames()
                cross_origin_count = sum(1 for f in frames if f is not self.page.main_frame and f is not None)
                return {
                    "url": url,
                    "title": title,
                    "elements": elements,
                    "forms": forms,
                    "text": text,
                    "headings": headings,
                    "dialogs": dialogs,
                    "alerts": alerts,
                    "auth_signals": auth_signals,
                    "routes": routes,
                    "interactive_elements": interactive_elements,
                    "primary_actions": [e for e in elements if e.get("type") == "button"][:20],
                    "iframes_observed": len(frames) > 1,
                    "cross_origin_iframes": cross_origin_count > 0,
                    "shadow_dom_scanned": True,
                    "shadow_element_count": len(shadow_elements),
                }
            except Exception as e:
                if ("Execution context was destroyed" in str(e) or "navigating" in str(e).lower()) and attempt < 2:
                    await asyncio.sleep(0.3)
                    continue
                raise

    async def _get_frames(self) -> list[Any]:
        frames = [self.page.main_frame]
        try:
            for f in getattr(self.page, "frames", []):
                if f != self.page.main_frame:
                    frames.append(f)
        except Exception:
            pass
        return frames

    async def _observe_shadow_dom(self) -> list[dict]:
        """Descend into open shadow roots across all frames and collect interactive elements.

        Closed shadow roots cannot be pierced and are silently skipped.
        Returns elements tagged with ``"in_shadow_dom": True``.
        """
        results: list[dict] = []
        frames = await self._get_frames()
        for frame in frames:
            try:
                frame_id = frame.url or frame.name or "main"
                is_subframe = frame is not self.page.main_frame
                # Query all elements that host an open shadow root.
                hosts = await frame.query_selector_all("*")
                for host in hosts[:200]:
                    try:
                        shadow_root = await host.evaluate_handle("el => el.shadowRoot")
                        if shadow_root is None:
                            continue
                        # Only open shadow roots expose elements via querySelector.
                        buttons = await shadow_root.query_selector_all(
                            "button, [role='button'], input[type='submit'], input[type='button'], "
                            "[role='link'], a[href], input, textarea, select, [contenteditable='true'], [onclick]"
                        )
                        for el in buttons:
                            try:
                                if not await el.is_visible():
                                    continue
                                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                                name = await self._infer_element_name(el, tag)
                                selector = await self._build_selector(el)
                                bbox = await self._get_bbox(el)
                                entry = {
                                    "type": "button" if tag == "button" else ("input" if tag in ("input", "textarea", "select") else "link"),
                                    "name": name or selector,
                                    "accessible_name": name,
                                    "label": name,
                                    "role": await self._get_role(el, tag),
                                    "selector": selector,
                                    "bounding_box": bbox,
                                    "state": {"visible": True},
                                    "frame": frame_id,
                                    "is_subframe": is_subframe,
                                    "in_shadow_dom": True,
                                }
                                results.append(await self._enrich_element(entry, el))
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception:
                continue
        return results

    async def _get_bbox(self, element) -> dict[str, float] | None:
        try:
            box = await element.bounding_box()
            if box:
                return {
                    "x": round(box["x"], 1),
                    "y": round(box["y"], 1),
                    "width": round(box["width"], 1),
                    "height": round(box["height"], 1),
                }
        except Exception:
            pass
        return None

    async def _observe_buttons(self) -> list[dict]:
        """Extract visible buttons across main frame, child frames, and custom clickable divs.

        Includes custom clickable elements (contenteditable, cursor:pointer, onclick)
        and enriches each element with role, ARIA attributes, onclick handler, and an
        inferred accessible name.
        """
        results = []
        frames = await self._get_frames()
        for frame in frames:
            try:
                frame_id = frame.url or frame.name or "main"
                is_subframe = (frame != self.page.main_frame)
                buttons = await frame.query_selector_all(
                    "button, [role='button'], input[type='submit'], input[type='button'], "
                    "div[role='button'], div.custom-btn, [tabindex='0'][role='button'], "
                    "[contenteditable='true'], [contenteditable=''], [onclick]"
                )
                for btn in buttons:
                    try:
                        if not await btn.is_visible():
                            continue
                        tag = await btn.evaluate("el => el.tagName.toLowerCase()")
                        name = await self._infer_element_name(btn, tag)
                        label = await self._get_element_label(btn)
                        role = await self._get_role(btn, tag)
                        selector = await self._build_selector(btn)
                        bbox = await self._get_bbox(btn)
                        disabled = False
                        try:
                            disabled = await btn.is_disabled()
                        except Exception:
                            pass
                        results.append(await self._enrich_element({
                            "type": "button",
                            "name": name or label or selector,
                            "accessible_name": name or label,
                            "label": label,
                            "role": role or "button",
                            "selector": selector,
                            "bounding_box": bbox,
                            "state": {"visible": True, "disabled": disabled},
                            "frame": frame_id,
                            "is_subframe": is_subframe,
                        }, btn))
                    except Exception:
                        continue
            except Exception:
                continue
        return results

    async def _observe_links(self) -> list[dict]:
        """Extract all visible links across frames, enriched with ARIA and clickability hints."""
        results = []
        frames = await self._get_frames()
        for frame in frames:
            try:
                frame_id = frame.url or frame.name or "main"
                is_subframe = (frame != self.page.main_frame)
                links = await frame.query_selector_all("a[href], [role='link']")
                for link in links:
                    try:
                        if not await link.is_visible():
                            continue
                        text = (await link.inner_text()).strip()[:200]
                        href = await link.get_attribute("href") or ""
                        selector = await self._build_selector(link)
                        bbox = await self._get_bbox(link)
                        entry = {
                            "type": "link",
                            "name": text,
                            "accessible_name": text,
                            "label": text,
                            "role": "link",
                            "href": href,
                            "selector": selector,
                            "bounding_box": bbox,
                            "state": {"visible": True},
                            "frame": frame_id,
                            "is_subframe": is_subframe,
                        }
                        results.append(await self._enrich_element(entry, link))
                    except Exception:
                        continue
            except Exception:
                continue
        return results

    async def _observe_inputs(self) -> list[dict]:
        """Extract visible input elements across all frames, enriched with ARIA hints."""
        results = []
        frames = await self._get_frames()
        for frame in frames:
            try:
                frame_id = frame.url or frame.name or "main"
                is_subframe = (frame != self.page.main_frame)
                inputs = await frame.query_selector_all(
                    "input[type='text'], input[type='password'], input[type='email'], "
                    "input[type='number'], input[type='tel'], input[type='url'], "
                    "input[type='search'], input:not([type]), input[type='checkbox'], input[type='radio']"
                )
                for inp in inputs:
                    try:
                        if not await inp.is_visible():
                            continue
                        name = await inp.get_attribute("name") or ""
                        placeholder = await inp.get_attribute("placeholder") or ""
                        input_type = await inp.get_attribute("type") or "text"
                        label = await self._get_element_label(inp)
                        selector = await self._build_selector(inp)
                        bbox = await self._get_bbox(inp)
                        entry = {
                            "type": "input",
                            "name": name or placeholder or selector,
                            "accessible_name": label or placeholder or name,
                            "label": label or placeholder,
                            "role": "textbox" if input_type not in ("checkbox", "radio") else input_type,
                            "input_type": input_type,
                            "placeholder": placeholder,
                            "selector": selector,
                            "bounding_box": bbox,
                            "state": {
                                "visible": True,
                                "disabled": False,
                                "required": False,
                                "filled": False,
                                "validation_message": "",
                            },
                            "frame": frame_id,
                            "is_subframe": is_subframe,
                        }
                        try:
                            input_value = await inp.input_value()
                        except Exception:
                            input_value = ""
                        disabled = False
                        try:
                            disabled = await inp.is_disabled()
                        except Exception:
                            pass
                        required = False
                        try:
                            required = bool(await inp.get_attribute("required") is not None)
                        except Exception:
                            pass
                        val_msg = ""
                        try:
                            val_msg = await inp.evaluate("el => el.validationMessage || ''")
                        except Exception:
                            pass
                        entry["state"] = {
                            "visible": True,
                            "disabled": disabled,
                            "required": required,
                            "filled": bool(input_value.strip()),
                            "validation_message": val_msg,
                        }
                        results.append(await self._enrich_element(entry, inp))
                    except Exception:
                        continue
            except Exception:
                continue
        return results

    async def _observe_textareas(self) -> list[dict]:
        """Extract all visible textarea elements."""
        textareas = await self.page.query_selector_all("textarea")
        results = []
        for ta in textareas:
            try:
                if not await ta.is_visible():
                    continue
                name = await ta.get_attribute("name") or ""
                placeholder = await ta.get_attribute("placeholder") or ""
                label = await self._get_element_label(ta)
                selector = await self._build_selector(ta)
                entry = {
                    "type": "textarea",
                    "name": name or placeholder or selector,
                    "label": label or placeholder,
                    "role": "textbox",
                    "placeholder": placeholder,
                    "selector": selector,
                }
                results.append(await self._enrich_element(entry, ta))
            except Exception:
                continue
        return results

    async def _observe_selects(self) -> list[dict]:
        """Extract all visible select elements with their options."""
        selects = await self.page.query_selector_all("select")
        results = []
        for sel in selects:
            try:
                if not await sel.is_visible():
                    continue
                name = await sel.get_attribute("name") or ""
                label = await self._get_element_label(sel)
                selector = await self._build_selector(sel)

                options = await sel.query_selector_all("option")
                option_list = []
                for opt in options:
                    value = await opt.get_attribute("value") or ""
                    text = (await opt.inner_text()).strip()
                    option_list.append({"value": value, "text": text})

                entry = {
                    "type": "select",
                    "name": name or selector,
                    "label": label,
                    "role": "combobox",
                    "options": option_list,
                    "selector": selector,
                }
                results.append(await self._enrich_element(entry, sel))
            except Exception:
                continue
        return results

    async def _observe_forms(self) -> list[dict]:
        """Extract all forms on the page."""
        forms = await self.page.query_selector_all("form")
        results = []
        for form in forms:
            try:
                form_id = await form.get_attribute("id") or ""
                action = await form.get_attribute("action") or ""
                method = await form.get_attribute("method") or "get"
                selector = await self._build_selector(form)

                inputs = await form.query_selector_all("input, textarea, select")
                field_names = []
                for inp in inputs:
                    name = await inp.get_attribute("name") or ""
                    if name:
                        field_names.append(name)

                results.append({
                    "id": form_id,
                    "action": action,
                    "method": method.lower(),
                    "fields": field_names,
                    "selector": selector,
                })
            except Exception:
                continue
        return results

    async def _observe_visible_text(self) -> str:
        """Extract visible text content from the page body."""
        try:
            body = await self.page.query_selector("body")
            if body:
                text = await body.inner_text()
                return text[:5000]
        except Exception:
            pass
        return ""

    async def _get_element_name(self, element) -> str:
        """Get a human-readable name for an element."""
        return await self._infer_element_name(element, "")

    async def _infer_element_name(self, element, tag: str) -> str:
        """Infer a human-readable name for an element from multiple fallback sources.

        Order: aria-label → title → placeholder → nearby text → icon alt text →
        inner text → name attribute → id.
        Never returns product-specific keywords.
        """
        # 1. aria-label
        try:
            aria_label = await element.get_attribute("aria-label")
            if aria_label and aria_label.strip():
                return aria_label.strip()
        except Exception:
            pass

        # 2. title attribute
        try:
            title = await element.get_attribute("title")
            if title and title.strip():
                return title.strip()
        except Exception:
            pass

        # 3. placeholder (inputs/textareas)
        try:
            placeholder = await element.get_attribute("placeholder")
            if placeholder and placeholder.strip():
                return placeholder.strip()
        except Exception:
            pass

        # 4. aria-labelledby → referenced element text
        try:
            labelled_by = await element.get_attribute("aria-labelledby")
            if labelled_by:
                for ref_id in labelled_by.split():
                    ref = await self.page.query_selector(f"#{ref_id}")
                    if ref:
                        txt = (await ref.inner_text()).strip()
                        if txt:
                            return txt[:100]
        except Exception:
            pass

        # 5. icon alt text / inner img/svg within buttons
        try:
            icon_text = await element.evaluate(
                """el => {
                    const img = el.querySelector('img[alt]');
                    if (img && img.alt.trim()) return img.alt.trim();
                    const svg = el.querySelector('svg[aria-label]');
                    if (svg && svg.getAttribute('aria-label').trim()) return svg.getAttribute('aria-label').trim();
                    return '';
                }"""
            )
            if icon_text:
                return icon_text
        except Exception:
            pass

        # 6. inner text
        try:
            text = (await element.inner_text()).strip()
            if text:
                return text[:100]
        except Exception:
            pass

        # 7. name attribute
        try:
            name = await element.get_attribute("name")
            if name:
                return name
        except Exception:
            pass

        # 8. id
        try:
            element_id = await element.get_attribute("id")
            if element_id:
                return element_id
        except Exception:
            pass

        return ""

    async def _enrich_element(self, entry: dict, element) -> dict:
        """Add role, ARIA attributes, onclick, cursor:pointer, contenteditable fields.

        These help the executor resolve targets on badly-marked-up pages.
        """
        try:
            # ARIA attributes
            attrs = await element.evaluate(
                """el => {
                    const out = {};
                    for (const attr of el.attributes) {
                        if (attr.name.startsWith('aria-')) out[attr.name] = attr.value;
                    }
                    return out;
                }"""
            )
            if attrs:
                entry["aria"] = attrs
        except Exception:
            pass

        # onclick handler present
        try:
            onclick = await element.get_attribute("onclick")
            if onclick:
                entry["onclick"] = onclick
        except Exception:
            pass

        # cursor:pointer style (computed)
        try:
            cursor = await element.evaluate(
                "el => window.getComputedStyle(el)?.cursor || ''"
            )
            if cursor and "pointer" in cursor:
                entry["cursor_pointer"] = True
        except Exception:
            pass

        # contenteditable
        try:
            ce = await element.get_attribute("contenteditable")
            if ce is not None:
                entry["contenteditable"] = ce
        except Exception:
            pass

        return entry

    async def _get_element_label(self, element) -> str:
        """Get the label text associated with an element.

        Looks for:
        1. aria-label attribute
2. Associated <label> element (via for= attribute or nesting)
3. title attribute
        """
        # Try aria-label
        aria_label = await element.get_attribute("aria-label")
        if aria_label:
            return aria_label

        # Try to find associated label via for= attribute
        element_id = await element.get_attribute("id")
        if element_id:
            label = await self.page.query_selector(f"label[for='{element_id}']")
            if label:
                text = (await label.inner_text()).strip()
                if text:
                    return text

        # Try nesting inside a label
        label_text = await element.evaluate(
            """el => {
                const label = el.closest('label');
                if (label) {
                    // Get text content excluding nested form elements
                    const clone = label.cloneNode(true);
                    clone.querySelectorAll('input, textarea, select, button').forEach(e => e.remove());
                    return clone.textContent.trim();
                }
                return '';
            }"""
        )
        if label_text:
            return label_text[:200]

        # Try title attribute
        title = await element.get_attribute("title")
        if title:
            return title

        return ""

    async def _get_role(self, element, tag: str) -> str:
        """Determine the ARIA role of an element."""
        # Check explicit role attribute
        role = await element.get_attribute("role")
        if role:
            return role

        # Infer from tag
        role_map = {
            "button": "button",
            "a": "link",
            "input": "textbox",
            "textarea": "textbox",
            "select": "combobox",
            "h1": "heading",
            "h2": "heading",
            "h3": "heading",
            "h4": "heading",
            "h5": "heading",
            "h6": "heading",
            "nav": "navigation",
            "main": "main",
            "form": "form",
            "img": "image",
            "table": "table",
            "ul": "list",
            "ol": "list",
        }
        return role_map.get(tag, "")

    async def _build_selector(self, element) -> str:
        """Build a CSS selector for an element."""
        element_id = await element.get_attribute("id")
        if element_id:
            return f"#{element_id}"

        data_test_id = await element.get_attribute("data-testid")
        if data_test_id:
            return f"[data-testid='{data_test_id}']"

        aria_label = await element.get_attribute("aria-label")
        if aria_label:
            tag = await element.evaluate("el => el.tagName.toLowerCase()")
            clean_aria = aria_label.replace("'", "\\'")
            return f"{tag}[aria-label='{clean_aria}']"

        name = await element.get_attribute("name")
        if name:
            tag = await element.evaluate("el => el.tagName.toLowerCase()")
            return f"{tag}[name='{name}']"

        tag = await element.evaluate("el => el.tagName.toLowerCase()")

        # If element has short distinctive text, ground selector with text
        try:
            text = await element.evaluate("el => el.innerText?.trim() || ''")
            if text and 2 <= len(text) <= 40 and "\n" not in text:
                clean_text = text.replace("'", "\\'")
                return f"{tag}:has-text('{clean_text}')"
        except Exception:
            pass

        classes = await element.get_attribute("class")
        if classes:
            class_list = classes.split()
            # Filter out common utility class prefixes from Tailwind / utility frameworks
            utility_prefixes = (
                "inline-", "flex", "grid", "relative", "absolute", "fixed", "sticky",
                "w-", "h-", "min-", "max-", "p-", "px-", "py-", "pt-", "pb-", "pl-", "pr-",
                "m-", "mx-", "my-", "mt-", "mb-", "ml-", "mr-", "text-", "bg-", "border",
                "rounded", "shadow", "hover:", "focus:", "active:", "disabled:", "items-",
                "justify-", "transition", "duration", "ease", "cursor-", "overflow-"
            )
            semantic_classes = [
                c for c in class_list
                if not any(c.startswith(p) for p in utility_prefixes)
            ]
            chosen_class = semantic_classes[0] if semantic_classes else class_list[0]
            return f"{tag}.{chosen_class}"

        return tag

    async def _observe_headings(self) -> list[str]:
        """Extract visible headings from h1-h6 and role='heading'."""
        try:
            headings_el = await self.page.query_selector_all("h1, h2, h3, [role='heading']")
            results = []
            for h in headings_el:
                try:
                    if await h.is_visible():
                        txt = (await h.inner_text()).strip()
                        if txt:
                            results.append(txt[:100])
                except Exception:
                    continue
            return results[:6]
        except Exception:
            return []

    async def _observe_dialogs(self) -> list[dict]:
        """Extract visible modal dialogs and alerts."""
        results = []
        frames = await self._get_frames()
        for frame in frames:
            try:
                modals = await frame.query_selector_all(
                    "dialog[open], [role='dialog'], [role='alertdialog'], [aria-modal='true'], .modal:not([style*='display: none'])"
                )
                for m in modals:
                    try:
                        if await m.is_visible():
                            txt = (await m.inner_text()).strip()[:300]
                            box = await self._get_bbox(m)
                            results.append({"text": txt, "bounding_box": box})
                    except Exception:
                        continue
            except Exception:
                continue
        return results[:5]

    async def _observe_alerts(self) -> list[str]:
        """Extract visible alerts, toasts, error banners, and validation notifications."""
        results = []
        frames = await self._get_frames()
        for frame in frames:
            try:
                alerts_el = await frame.query_selector_all(
                    "[role='alert'], [role='status'], .toast, .alert, .error, .notification, :invalid"
                )
                for a in alerts_el:
                    try:
                        if await a.is_visible():
                            txt = (await a.inner_text()).strip()
                            if txt and txt[:150] not in results:
                                results.append(txt[:150])
                    except Exception:
                        continue
            except Exception:
                continue
        return results[:8]


# Additional helper methods for enhanced observation
