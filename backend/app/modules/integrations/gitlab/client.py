"""GitLab API client for MR diff fetching and comment automation."""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)


class GitLabClient:
    """Client for GitLab REST API v4."""

    def __init__(self, token: Optional[str] = None, base_url: str = "https://gitlab.com/api/v4"):
        self.token = token
        self.base_url = base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Kova-Continuous-Validation/1.0",
        }
        if self.token:
            headers["PRIVATE-TOKEN"] = self.token
        return headers

    async def get_mr_diff(self, project_id: str | int, mr_iid: int) -> str:
        """Fetch unified diff for a GitLab merge request."""
        encoded_project = quote_plus(str(project_id))
        url = f"{self.base_url}/projects/{encoded_project}/merge_requests/{mr_iid}/diffs"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code == 200:
                diffs = resp.json()
                combined = []
                for d in diffs:
                    old_path = d.get("old_path", "")
                    new_path = d.get("new_path", "")
                    diff_text = d.get("diff", "")
                    combined.append(f"--- a/{old_path}\n+++ b/{new_path}\n{diff_text}")
                return "\n".join(combined)
            logger.warning("Failed to fetch MR diffs for %s!%s: %s %s", project_id, mr_iid, resp.status_code, resp.text)
            return ""

    async def list_mr_notes(self, project_id: str | int, mr_iid: int) -> list[dict]:
        """List discussion notes/comments on a merge request."""
        encoded_project = quote_plus(str(project_id))
        url = f"{self.base_url}/projects/{encoded_project}/merge_requests/{mr_iid}/notes"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code == 200:
                return resp.json()
            return []

    async def get_mr_note_id_by_marker(self, project_id: str | int, mr_iid: int, marker: str) -> Optional[int]:
        """Find an existing MR note containing the given marker."""
        notes = await self.list_mr_notes(project_id, mr_iid)
        for note in notes:
            body = note.get("body", "")
            if marker in body:
                return note.get("id")
        return None

    async def post_mr_comment(self, project_id: str | int, mr_iid: int, body: str) -> dict:
        """Post a new note on a merge request."""
        encoded_project = quote_plus(str(project_id))
        url = f"{self.base_url}/projects/{encoded_project}/merge_requests/{mr_iid}/notes"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"body": body}, headers=self._headers())
            try:
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.warning("GitLab post_mr_comment failed: %s", e)
                return {"error": str(e), "status_code": resp.status_code}

    async def update_mr_comment(self, project_id: str | int, mr_iid: int, note_id: int, body: str) -> dict:
        """Update an existing note on a merge request."""
        encoded_project = quote_plus(str(project_id))
        url = f"{self.base_url}/projects/{encoded_project}/merge_requests/{mr_iid}/notes/{note_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.put(url, json={"body": body}, headers=self._headers())
            try:
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.warning("GitLab update_mr_comment failed: %s", e)
                return {"error": str(e), "status_code": resp.status_code}

    async def post_or_update_mr_comment(
        self,
        project_id: str | int,
        mr_iid: int,
        body: str,
        marker: str = "<!-- kova-validation -->",
    ) -> dict:
        """Update existing note with marker or post a new note to prevent clutter."""
        existing_id = await self.get_mr_note_id_by_marker(project_id, mr_iid, marker)
        if existing_id:
            logger.info("Found existing Kova MR note #%s on %s!%s; updating", existing_id, project_id, mr_iid)
            return await self.update_mr_comment(project_id, mr_iid, existing_id, body)
        return await self.post_mr_comment(project_id, mr_iid, body)

    async def get_file_content(self, project_id: str | int, path: str, ref: str = "main") -> Optional[str]:
        """Fetch raw file content from GitLab repository at a given ref."""
        encoded_project = quote_plus(str(project_id))
        encoded_path = quote_plus(path.lstrip("/"))
        url = f"{self.base_url}/projects/{encoded_project}/repository/files/{encoded_path}/raw?ref={ref}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code == 200:
                return resp.text
            return None
