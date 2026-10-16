"""GitHub API client for diff fetching and PR comment automation."""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class GitHubClient:
    """Client for GitHub REST API v3."""

    def __init__(self, token: Optional[str] = None, base_url: str = "https://api.github.com"):
        self.token = token
        self.base_url = base_url.rstrip("/")

    def _headers(self, custom_accept: Optional[str] = None) -> dict[str, str]:
        headers = {
            "Accept": custom_accept or "application/vnd.github.v3+json",
            "User-Agent": "Kova-Continuous-Validation/1.0",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        return headers

    async def get_pr_diff(self, repo: str, pr_number: int) -> str:
        """Fetch unified diff for a pull request."""
        url = f"{self.base_url}/repos/{repo}/pulls/{pr_number}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers(custom_accept="application/vnd.github.v3.diff"))
            if resp.status_code == 200:
                return resp.text
            logger.warning("Failed to fetch diff for %s#%s: %s %s", repo, pr_number, resp.status_code, resp.text)
            return ""

    async def list_pr_comments(self, repo: str, pr_number: int) -> list[dict]:
        """List comments on an issue/pull request."""
        url = f"{self.base_url}/repos/{repo}/issues/{pr_number}/comments"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
            return []

    async def get_pr_comment_id_by_marker(self, repo: str, pr_number: int, marker: str) -> Optional[int]:
        """Find an existing comment containing the given marker."""
        comments = await self.list_pr_comments(repo, pr_number)
        for comment in comments:
            body = comment.get("body", "")
            if marker in body:
                return comment.get("id")
        return None

    async def post_pr_comment(self, repo: str, pr_number: int, body: str) -> dict:
        """Post a new comment on a pull request."""
        url = f"{self.base_url}/repos/{repo}/issues/{pr_number}/comments"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"body": body}, headers=self._headers())
            try:
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.warning("GitHub post_pr_comment failed: %s", e)
                return {"error": str(e), "status_code": resp.status_code}

    async def update_pr_comment(self, repo: str, comment_id: int, body: str) -> dict:
        """Update an existing comment on a pull request."""
        url = f"{self.base_url}/repos/{repo}/issues/comments/{comment_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.patch(url, json={"body": body}, headers=self._headers())
            try:
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.warning("GitHub update_pr_comment failed: %s", e)
                return {"error": str(e), "status_code": resp.status_code}

    async def post_or_update_pr_comment(
        self,
        repo: str,
        pr_number: int,
        body: str,
        marker: str = "<!-- kova-validation -->",
    ) -> dict:
        """Update existing comment with marker or post a new comment to avoid PR clutter."""
        existing_id = await self.get_pr_comment_id_by_marker(repo, pr_number, marker)
        if existing_id:
            logger.info("Found existing Kova comment #%s on %s#%s; updating", existing_id, repo, pr_number)
            return await self.update_pr_comment(repo, existing_id, body)
        return await self.post_pr_comment(repo, pr_number, body)

    async def get_file_content(self, repo: str, path: str, ref: str = "main") -> Optional[str]:
        """Fetch raw file content from repository at a given git ref."""
        url = f"{self.base_url}/repos/{repo}/contents/{path.lstrip('/')}?ref={ref}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code == 200:
                data = resp.json()
                if "content" in data and data.get("encoding") == "base64":
                    return base64.b64decode(data["content"]).decode("utf-8")
            return None
