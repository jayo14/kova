from __future__ import annotations

import logging
import re
import uuid
from typing import Any
from urllib.parse import urljoin, urlparse

from app.config.settings import settings
from app.engine.browser.session import _is_safe_url
from app.modules.product_graph.schemas import Page

logger = logging.getLogger(__name__)

UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
NUMERIC_REGEX = re.compile(r"^\d+$")


def parameterize_url_path(path: str) -> str:
    """Normalize dynamic segments like IDs, UUIDs, numbers into parameter tokens like :id."""
    segments = [s for s in path.strip("/").split("/") if s]
    if not segments:
        return "/"

    normalized = []
    for seg in segments:
        if NUMERIC_REGEX.match(seg) or UUID_REGEX.match(seg):
            normalized.append(":id")
        elif len(seg) >= 20 and re.match(r"^[0-9a-zA-Z_-]+$", seg):
            normalized.append(":id")
        else:
            normalized.append(seg)

    return "/" + "/".join(normalized)


class DiscoveryCrawler:
    def __init__(
        self,
        project_id: uuid.UUID,
        base_url: str,
        depth_budget: int = 3,
        max_pages: int = 50,
    ):
        self.project_id = project_id
        self.base_url = base_url.rstrip("/")
        # Enforce hard limits
        self.depth_budget = min(max(depth_budget, 1), 5)
        self.max_pages = min(max(max_pages, 1), 200)

        parsed_base = urlparse(self.base_url)
        self.base_host = (parsed_base.hostname or "").lower()
        self.base_port = parsed_base.port

        self.visited_urls: set[str] = set()
        self.discovered_pages: dict[str, Page] = {}  # pattern -> Page
        self.coverage_map: dict[str, str] = {}  # exact URL -> page.id str
        self.warnings: list[str] = []

    def is_internal_url(self, url: str) -> bool:
        """Check if URL belongs to the target application origin and is safe."""
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if host != self.base_host:
                return False
            if self.base_port and parsed.port and parsed.port != self.base_port:
                return False
            # SSRF check
            if not _is_safe_url(url, allow_loopback=not settings.is_production):
                self.warnings.append(f"Skipping unsafe or blocked URL (SSRF): {url}")
                return False
            return True
        except Exception:
            return False

    async def crawl(self, browser_page: Any) -> list[Page]:
        """Perform a BFS crawl over the application up to depth_budget and max_pages."""
        queue: list[tuple[str, int]] = [(self.base_url, 0)]
        self.visited_urls.add(self.base_url)

        while queue and len(self.discovered_pages) < self.max_pages:
            current_url, depth = queue.pop(0)

            try:
                # SSRF safeguard
                if not _is_safe_url(current_url, allow_loopback=not settings.is_production):
                    logger.warning("SSRF blocked URL during crawl: %s", current_url)
                    continue

                logger.debug("Crawling URL: %s at depth %d", current_url, depth)
                await browser_page.goto(current_url, wait_until="domcontentloaded", timeout=15000)
                await browser_page.wait_for_timeout(500)

                # Extract page info
                title = await browser_page.title()
                actual_url = browser_page.url or current_url
                parsed = urlparse(current_url)
                pattern = parameterize_url_path(parsed.path)

                if pattern not in self.discovered_pages:
                    page_obj = Page(
                        project_id=self.project_id,
                        url_pattern=pattern,
                        title=title.strip() if title else pattern,
                        requires_auth=False,
                        source="discovered",
                        confidence=1.0,
                    )
                    self.discovered_pages[pattern] = page_obj

                page_id_str = str(self.discovered_pages[pattern].id)
                self.coverage_map[current_url] = page_id_str
                self.coverage_map[actual_url] = page_id_str

                if depth >= self.depth_budget:
                    continue

                # Extract links from page
                links: list[str] = await browser_page.evaluate("""
                    () => {
                        const hrefs = [];
                        document.querySelectorAll('a[href]').forEach(a => {
                            const h = a.getAttribute('href');
                            if (h && !h.startsWith('#') && !h.startsWith('javascript:') && !h.startsWith('mailto:') && !h.startsWith('tel:')) {
                                hrefs.push(a.href);
                            }
                        });
                        return hrefs;
                    }
                """)

                for href in links:
                    clean_href = href.split("#")[0].rstrip("/")
                    if not clean_href:
                        continue
                    if self.is_internal_url(clean_href) and clean_href not in self.visited_urls:
                        self.visited_urls.add(clean_href)
                        queue.append((clean_href, depth + 1))

            except Exception as e:
                logger.warning("Error crawling URL %s: %s", current_url, e)
                self.warnings.append(f"Crawl error on {current_url}: {str(e)}")

        return list(self.discovered_pages.values())
