"""Target resolution for browser automation.

Resolves human-readable target specifications to Playwright locators.
Priority order: data-testid → role+name → label → text → CSS selector.
"""

import logging
from enum import Enum
from typing import Any

from playwright.async_api import Locator, Page

logger = logging.getLogger(__name__)


class ResolutionError(Exception):
    """Base error for target resolution failures."""

    pass


class TargetNotFoundError(ResolutionError):
    """Raised when no element matches the target specification."""

    def __init__(self, target: str, strategy: str = ""):
        self.target = target
        self.strategy = strategy
        msg = f"Target not found: {target}"
        if strategy:
            msg += f" (strategy: {strategy})"
        super().__init__(msg)


class AmbiguousTargetError(ResolutionError):
    """Raised when multiple elements match the target specification."""

    def __init__(self, target: str, count: int, selectors: list[str]):
        self.target = target
        self.count = count
        self.selectors = selectors
        super().__init__(
            f"Ambiguous target '{target}': {count} matches found "
            f"({', '.join(selectors[:3])}{'...' if len(selectors) > 3 else ''})"
        )


class ResolutionStrategy(str, Enum):
    """Available resolution strategies in priority order."""

    TEST_ID = "test_id"
    ROLE_NAME = "role_name"
    LABEL = "label"
    TEXT = "text"
    CSS = "css"


class TargetResolver:
    """Resolves target specifications to Playwright Locators.

    Supports multiple resolution strategies with configurable priority.
    Each strategy queries the DOM and returns matching elements.
    The first strategy that finds exactly one match wins.

    Usage:
        resolver = TargetResolver(page)
        locator = await resolver.resolve("email", role="textbox")
        await locator.fill("user@example.com")
    """

    def __init__(self, page: Page):
        self.page = page

    async def resolve(
        self,
        target: str,
        *,
        role: str = "",
        strategy: ResolutionStrategy | None = None,
    ) -> Locator:
        """Resolve a target to a single Playwright Locator.

        Args:
            target: The target value (test ID, name, label, text, or CSS).
            role: Optional ARIA role to narrow role+name resolution.
            strategy: Force a specific strategy. If None, tries all in priority order.

        Returns:
            A Playwright Locator matching exactly one element.

        Raises:
            TargetNotFoundError: No element matches.
            AmbiguousTargetError: Multiple elements match.
        """
        if not target or not target.strip():
            raise TargetNotFoundError(target or "")

        if strategy:
            return await self._resolve_with_strategy(target, role, strategy)

        # Try strategies in priority order
        strategies = [
            (ResolutionStrategy.TEST_ID, self._by_test_id),
            (ResolutionStrategy.ROLE_NAME, self._by_role_name),
            (ResolutionStrategy.LABEL, self._by_label),
            (ResolutionStrategy.TEXT, self._by_text),
            (ResolutionStrategy.CSS, self._by_css),
        ]

        for strat_name, strat_fn in strategies:
            try:
                locator = await strat_fn(target, role)
                count = await locator.count()
                if count == 1:
                    logger.debug(
                        "Resolved '%s' via %s", target, strat_name.value
                    )
                    return locator
                if count > 1:
                    # If only one matching element is visible, prefer it over hidden elements
                    visible_matches = []
                    for idx in range(count):
                        nth_loc = locator.nth(idx)
                        try:
                            if await nth_loc.is_visible():
                                visible_matches.append(nth_loc)
                        except Exception:
                            pass
                    if len(visible_matches) == 1:
                        logger.debug(
                            "Resolved '%s' via single visible match in %s",
                            target,
                            strat_name.value,
                        )
                        return visible_matches[0]

                    selectors = await self._get_match_details(
                        locator, strat_name
                    )
                    raise AmbiguousTargetError(target, count, selectors)
            except (AmbiguousTargetError):
                raise
            except Exception:
                continue

        raise TargetNotFoundError(target)

    async def _resolve_with_strategy(
        self, target: str, role: str, strategy: ResolutionStrategy
    ) -> Locator:
        """Resolve using a specific strategy."""
        strat_map = {
            ResolutionStrategy.TEST_ID: self._by_test_id,
            ResolutionStrategy.ROLE_NAME: self._by_role_name,
            ResolutionStrategy.LABEL: self._by_label,
            ResolutionStrategy.TEXT: self._by_text,
            ResolutionStrategy.CSS: self._by_css,
        }
        strat_fn = strat_map[strategy]
        locator = await strat_fn(target, role)
        count = await locator.count()
        if count == 0:
            raise TargetNotFoundError(target, strategy.value)
        if count > 1:
            visible_matches = []
            for idx in range(count):
                nth_loc = locator.nth(idx)
                try:
                    if await nth_loc.is_visible():
                        visible_matches.append(nth_loc)
                except Exception:
                    pass
            if len(visible_matches) == 1:
                return visible_matches[0]

            selectors = await self._get_match_details(locator, strategy)
            raise AmbiguousTargetError(target, count, selectors)
        return locator

    async def resolve_first_visible(
        self,
        target: str,
        *,
        role: str = "",
        strategy: ResolutionStrategy | None = None,
    ) -> Locator:
        """Resolve target, falling back to the first visible element if multiple match."""
        try:
            return await self.resolve(target, role=role, strategy=strategy)
        except AmbiguousTargetError:
            strategies = [
                (ResolutionStrategy.TEST_ID, self._by_test_id),
                (ResolutionStrategy.ROLE_NAME, self._by_role_name),
                (ResolutionStrategy.LABEL, self._by_label),
                (ResolutionStrategy.TEXT, self._by_text),
                (ResolutionStrategy.CSS, self._by_css),
            ]
            if strategy:
                strategies = [s for s in strategies if s[0] == strategy]

            for strat_name, strat_fn in strategies:
                try:
                    locator = await strat_fn(target, role)
                    count = await locator.count()
                    for idx in range(count):
                        nth_loc = locator.nth(idx)
                        if await nth_loc.is_visible():
                            logger.info(
                                "Fallback resolved ambiguous '%s' to first visible element via %s",
                                target,
                                strat_name.value,
                            )
                            return nth_loc
                except Exception:
                    continue
            raise

    # --- Resolution strategies ---

    async def _by_test_id(self, target: str, role: str) -> Locator:
        """Resolve by data-testid attribute."""
        return self.page.locator(f"[data-testid='{target}']")

    async def _by_role_name(self, target: str, role: str) -> Locator:
        """Resolve by ARIA role and accessible name."""
        if role:
            return self.page.get_by_role(role, name=target)
        # Try common roles
        for try_role in ["button", "link", "textbox", "combobox"]:
            locator = self.page.get_by_role(try_role, name=target)
            if await locator.count() == 1:
                return locator
        return self.page.get_by_role("button", name=target)

    async def _by_label(self, target: str, role: str) -> Locator:
        """Resolve by associated label text."""
        return self.page.get_by_label(target)

    async def _by_text(self, target: str, role: str) -> Locator:
        """Resolve by visible text content."""
        return self.page.get_by_text(target, exact=False)

    async def _by_css(self, target: str, role: str) -> Locator:
        """Resolve by CSS selector (last resort)."""
        return self.page.locator(target)

    # --- Helpers ---

    async def _get_match_details(
        self, locator: Locator, strategy: ResolutionStrategy
    ) -> list[str]:
        """Get selector details for ambiguous matches."""
        selectors = []
        count = await locator.count()
        for i in range(min(count, 5)):
            try:
                el = locator.nth(i)
                selector = await el.evaluate(
                    """el => {
                        if (el.id) return '#' + el.id;
                        if (el.dataset.testid) return '[data-testid=' + el.dataset.testid + ']';
                        if (el.name) return el.tagName.toLowerCase() + '[name=' + el.name + ']';
                        return el.tagName.toLowerCase();
                    }"""
                )
                selectors.append(selector)
            except Exception:
                selectors.append(f"element_{i}")
        return selectors
