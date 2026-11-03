"""The few GitHub REST calls Git Config Updater needs: token and repo check, branch head, CI status.
Commits, files and diffs come from git itself (see core/gitops.py)."""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import GITHUB_API
from .core import ci

TIMEOUT = aiohttp.ClientTimeout(total=20)


class GitHubError(Exception):
    """GitHub could not be reached or answered with an error."""


class GitHubAuthError(GitHubError):
    """The token is invalid or expired."""


class GitHubNotFound(GitHubError):
    """The repository or branch doesn't exist, or the token can't see it."""


class GitHub:
    def __init__(self, session: aiohttp.ClientSession, repository: str, token: str) -> None:
        self._session = session
        self.repository = repository
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "home-assistant-git-config-updater",
        }

    async def _get(self, path: str) -> Any:
        try:
            async with self._session.get(f"{GITHUB_API}{path}", headers=self._headers,
                                         timeout=TIMEOUT) as resp:
                if resp.status == 401:
                    raise GitHubAuthError("GitHub rejected the token")
                if resp.status == 404:
                    raise GitHubNotFound(path)
                if resp.status == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
                    raise GitHubError("GitHub API rate limit reached")
                if resp.status == 403:
                    raise GitHubNotFound(path)  # no permission for this endpoint
                if resp.status >= 400:
                    raise GitHubError(f"GitHub answered HTTP {resp.status}")
                return await resp.json()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise GitHubError(f"GitHub unreachable ({type(err).__name__})") from err

    async def repository_info(self) -> dict[str, Any]:
        """The repository; raises GitHubAuthError, GitHubNotFound or GitHubError."""
        return await self._get(f"/repos/{self.repository}")

    async def branch_head(self, branch: str) -> str:
        data = await self._get(f"/repos/{self.repository}/branches/{branch}")
        return data["commit"]["sha"]

    async def ci_status(self, sha: str) -> str:
        """success / failure / pending / none / unknown (the token can't read checks)."""
        async def maybe(path: str) -> Any:
            try:
                return await self._get(path)
            except GitHubNotFound:
                return None
        runs, statuses = await asyncio.gather(
            maybe(f"/repos/{self.repository}/commits/{sha}/check-runs?per_page=100"),
            maybe(f"/repos/{self.repository}/commits/{sha}/status"),
        )
        return ci.combine(runs, statuses)
