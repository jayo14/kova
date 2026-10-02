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

                forms = await self._observe_forms()

                text = await self._observe_visible_text()

                headings = await self._observe_headings()
                dialogs = await self._observe_dialogs()
                alerts = await self._observe_alerts()

                return {
                    "url": url,
                    "title": title,
                    "elements": elements,
                    "forms": forms,
                    "text": text,
                    "headings": headings,
                    "dialogs": dialogs,
                    "alerts": alerts,
                }
            except Exception as e:
                if ("Execution context was destroyed" in str(e) or "navigating" in str(e).lower()) and attempt < 2:
                    await asyncio.sleep(0.3)
                    continue
                raise

    async def _observe_buttons(self) -> list[dict]:
        """Extract all visible buttons."""
        buttons = await self.page.query_selector_all(
            "button, [role='button'], input[type='submit'], input[type='button']"
        )
        results = []
        for btn in buttons:
            try:
                if not await btn.is_visible():
                    continue
                tag = await btn.evaluate("el => el.tagName.toLowerCase()")
                name = await self._get_element_name(btn)
                label = await self._get_element_label(btn)
                role = await self._get_role(btn, tag)
                selector = await self._build_selector(btn)
                results.append({
                    "type": "button",
                    "name": name,
                    "label": label,
                    "role": role,
                    "selector": selector,
                })
            except Exception:
                continue
        return results

    async def _observe_links(self) -> list[dict]:
        """Extract all visible links."""
        links = await self.page.query_selector_all("a[href]")
        results = []
        for link in links:
            try:
                if not await link.is_visible():
                    continue
                text = (await link.inner_text()).strip()[:200]
                href = await link.get_attribute("href") or ""
                selector = await self._build_selector(link)
                results.append({
                    "type": "link",
                    "name": text,
                    "label": text,
                    "role": "link",
                    "href": href,
                    "selector": selector,
                })
            except Exception:
                continue
        return results

    async def _observe_inputs(self) -> list[dict]:
        """Extract all visible input elements (text, password, email, etc.)."""
        inputs = await self.page.query_selector_all(
            "input[type='text'], input[type='password'], input[type='email'], "
            "input[type='number'], input[type='tel'], input[type='url'], "
            "input[type='search'], input:not([type])"
        )
        results = []
        for inp in inputs:
            try:
                if not await inp.is_visible():
                    continue
                name = await inp.get_attribute("name") or ""
                placeholder = await inp.get_attribute("placeholder") or ""
                input_type = await inp.get_attribute("type") or "text"
                label = await self._get_element_label(inp)
                selector = await self._build_selector(inp)
                # Empty-input tracking: lets callers tell "form needs filling"
                # from "form already filled" (prevents re-typing loops).
                # Password values are read too — only the boolean ever leaves
                # this module (semantic observations expose `filled`, never values).
                try:
                    input_value = await inp.input_value()
                except Exception:
                    input_value = ""
                results.append({
                    "type": "input",
                    "name": name or placeholder or selector,
                    "label": label or placeholder,
                    "role": "textbox",
                    "input_type": input_type,
                    "placeholder": placeholder,
                    "selector": selector,
                    "filled": bool(input_value.strip()),
                })
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
                results.append({
                    "type": "textarea",
                    "name": name or placeholder or selector,
                    "label": label or placeholder,
                    "role": "textbox",
                    "placeholder": placeholder,
                    "selector": selector,
                })
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

                results.append({
                    "type": "select",
                    "name": name or selector,
                    "label": label,
                    "role": "combobox",
                    "options": option_list,
                    "selector": selector,
                })
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
        # Try aria-label
        aria_label = await element.get_attribute("aria-label")
        if aria_label:
            return aria_label

        # Try text content
        try:
            text = (await element.inner_text()).strip()
            if text:
                return text[:100]
        except Exception:
            pass

        # Try name attribute
        name = await element.get_attribute("name")
        if name:
            return name

        # Try id
        element_id = await element.get_attribute("id")
        if element_id:
            return element_id

        return ""

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
        try:
            modals = await self.page.query_selector_all(
                "dialog[open], [role='dialog'], [role='alertdialog'], .modal:not([style*='display: none'])"
            )
            results = []
            for m in modals:
                try:
                    if await m.is_visible():
                        txt = (await m.inner_text()).strip()[:200]
                        results.append({"text": txt})
                except Exception:
                    continue
            return results[:3]
        except Exception:
            return []

    async def _observe_alerts(self) -> list[str]:
        """Extract visible alerts, error banners, and notifications."""
        try:
            alerts_el = await self.page.query_selector_all("[role='alert'], .error, .alert, .notification")
            results = []
            for a in alerts_el:
                try:
                    if await a.is_visible():
                        txt = (await a.inner_text()).strip()
                        if txt:
                            results.append(txt[:150])
                except Exception:
                    continue
            return results[:4]
        except Exception:
            return []
