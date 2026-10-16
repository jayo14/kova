"""Source control diff and config fetcher for GitHub and GitLab."""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.modules.integrations.github.client import GitHubClient
from app.modules.integrations.gitlab.client import GitLabClient
from app.modules.integrations.models import Integration
from app.modules.integrations.repository import IntegrationRepository

logger = logging.getLogger(__name__)


def extract_changed_files_from_diff(diff_content: str) -> list[str]:
    """Parse unified diff to extract list of modified file paths."""
    changed = set()
    for line in diff_content.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                changed.add(path)
        elif line.startswith("--- a/") and not line.startswith("--- a//dev/null"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                changed.add(path)
    return sorted(list(changed))


class DiffFetcher:
    """Fetches diffs and repository configuration files across VCS providers."""

    def __init__(self, repo: IntegrationRepository):
        self.repo = repo

    async def fetch_pr_diff(self, integration: Integration, pr_or_mr_id: int) -> str:
        """Fetch unified diff for the given PR or MR."""
        _, decrypted_token = await self.repo.get_decrypted_secrets(integration)

        if integration.provider == "github":
            client = GitHubClient(token=decrypted_token)
            return await client.get_pr_diff(integration.provider_repo_id, pr_or_mr_id)
        elif integration.provider == "gitlab":
            client = GitLabClient(token=decrypted_token)
            return await client.get_mr_diff(integration.provider_repo_id, pr_or_mr_id)
        else:
            raise ValueError(f"Unsupported provider: {integration.provider}")

    async def fetch_kova_config(
        self, integration: Integration, ref: str = "main"
    ) -> Optional[str]:
        """Fetch .kova.yml config content if present in repository."""
        _, decrypted_token = await self.repo.get_decrypted_secrets(integration)
        path = integration.kova_config_path or ".kova.yml"

        if integration.provider == "github":
            client = GitHubClient(token=decrypted_token)
            return await client.get_file_content(integration.provider_repo_id, path, ref=ref)
        elif integration.provider == "gitlab":
            client = GitLabClient(token=decrypted_token)
            return await client.get_file_content(integration.provider_repo_id, path, ref=ref)
        return None
