from playwright.async_api import Page


class BrowserObserver:
    def __init__(self, page: Page):
        self.page = page

    async def observe(self) -> dict:
        title = await self.page.title()
        url = self.page.url

        visible_elements = await self.page.query_selector_all(
            "button, input, textarea, select, a[href], [role='button']"
        )

        elements = []
        for el in visible_elements[:50]:
            try:
                tag = await el.evaluate("el => el.tagName.toLowerCase()")
                text = (await el.inner_text())[:100] if tag not in ("input", "textarea") else ""
                element_type = await el.get_attribute("type") or ""
                placeholder = await el.get_attribute("placeholder") or ""
                selector = await self._build_selector(el)
                elements.append(
                    {
                        "tag": tag,
                        "type": element_type,
                        "text": text,
                        "placeholder": placeholder,
                        "selector": selector,
                    }
                )
            except Exception:
                continue

        return {
            "url": url,
            "title": title,
            "elements": elements,
        }

    async def _build_selector(self, element) -> str:
        element_id = await element.get_attribute("id")
        if element_id:
            return f"#{element_id}"

        data_test_id = await element.get_attribute("data-testid")
        if data_test_id:
            return f"[data-testid='{data_test_id}']"

        name = await element.get_attribute("name")
        if name:
            tag = await element.evaluate("el => el.tagName.toLowerCase()")
            return f"{tag}[name='{name}']"

        classes = await element.get_attribute("class")
        if classes:
            first_class = classes.split()[0]
            tag = await element.evaluate("el => el.tagName.toLowerCase()")
            return f"{tag}.{first_class}"

        return "unknown"
