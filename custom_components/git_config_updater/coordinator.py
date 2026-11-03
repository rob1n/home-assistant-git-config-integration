"""Checks the branch for new commits and installs them into the local checkout."""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config import async_check_ha_config_file
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.hassio import is_hassio
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_BRANCH,
    CONF_PATH,
    CONF_REPOSITORY,
    CONF_TOKEN,
    DEFAULT_PACKAGES_DIR,
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
    GITHUB_WEB,
    ISSUE_RESTART,
    OPT_BACKUP,
    OPT_PACKAGES_DIR,
    OPT_RESTART_GLOBS,
    OPT_SCAN_MINUTES,
)
from .core import changelog
from .core.ci import UNKNOWN
from .core.gitops import Change, Commit, Git, GitError
from .core.restart import Verdict, needs_restart
from .github import GitHub, GitHubAuthError, GitHubError

_LOGGER = logging.getLogger(__name__)

type GitConfigUpdaterEntry = ConfigEntry[GitConfigCoordinator]


@dataclass
class Status:
    installed: str
    latest: str
    update_available: bool = False
    fast_forward: bool = True
    commits: list[Commit] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    verdict: Verdict = field(default_factory=Verdict)
    blocked: list[str] = field(default_factory=list)
    ci: str = UNKNOWN
    compare_url: str | None = None

    @property
    def summary(self) -> str | None:
        if not self.update_available:
            return None
        return changelog.summary(self.commits, self.ci, self.verdict, self.blocked)

    @property
    def notes(self) -> str | None:
        if not self.update_available:
            return None
        return changelog.notes(self.commits, self.changes, self.ci, self.verdict, self.blocked,
                               self.compare_url, self.fast_forward)


class InstallError(HomeAssistantError):
    """An install step failed; the message is shown in the update dialog."""


class GitConfigCoordinator(DataUpdateCoordinator[Status]):
    def __init__(self, hass: HomeAssistant, entry: GitConfigUpdaterEntry) -> None:
        minutes = entry.options.get(OPT_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN,
                         update_interval=timedelta(minutes=minutes))
        self.repository: str = entry.data[CONF_REPOSITORY]
        self.branch: str = entry.data[CONF_BRANCH]
        self.git = Git(entry.data[CONF_PATH], f"{GITHUB_WEB}/{self.repository}.git", entry.data[CONF_TOKEN])
        self.github = GitHub(async_get_clientsession(hass), self.repository, entry.data[CONF_TOKEN])
        self.install_lock = asyncio.Lock()

    @property
    def _packages_dir(self) -> str:
        return self.config_entry.options.get(OPT_PACKAGES_DIR, DEFAULT_PACKAGES_DIR)

    @property
    def _restart_globs(self) -> list[str]:
        raw = self.config_entry.options.get(OPT_RESTART_GLOBS, "") or ""
        return [g.strip() for g in raw.replace(",", "\n").splitlines() if g.strip()]

    # --- checking --------------------------------------------------------------------------------

    async def _async_update_data(self) -> Status:
        try:
            head = await self.github.branch_head(self.branch)
        except GitHubAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GitHubError as err:
            raise UpdateFailed(str(err)) from err
        try:
            status = await self.hass.async_add_executor_job(self._status, head)
        except GitError as err:
            raise UpdateFailed(str(err)) from err
        if status.update_available:
            try:
                status.ci = await self.github.ci_status(status.latest)
            except GitHubError:
                status.ci = UNKNOWN
        return status

    def _status(self, head: str) -> Status:
        """Compare the checkout with the branch head (runs in an executor)."""
        git = self.git
        installed = git.head()
        if head == installed:
            return Status(installed, head)
        if not git.has_commit(head):
            head = git.fetch(self.branch)
            if head == installed:
                return Status(installed, head)
        if git.is_ancestor(head, installed):
            # The checkout is ahead of the branch (local commits): nothing to install.
            return Status(installed, installed)
        ff = git.is_ancestor(installed, head)
        changes = git.changes(installed, head)
        paths = [p for c in changes for p in (c.path, c.old_path) if p]
        verdict = needs_restart(
            paths, lambda p: (git.show(installed, p), git.show(head, p)),
            self._packages_dir, self._restart_globs)
        blocked = [p for p in git.dirty() if not git.same_as(head, p)]
        return Status(
            installed, head, update_available=True, fast_forward=ff,
            commits=git.log(installed, head), changes=changes, verdict=verdict, blocked=blocked,
            compare_url=f"{GITHUB_WEB}/{self.repository}/compare/{installed[:12]}...{head[:12]}",
        )

    # --- installing ------------------------------------------------------------------------------

    async def async_install(self, backup: bool, progress: Callable[[int], None]) -> None:
        """Steps 1-7 of the README. Raises InstallError with a readable message on failure."""
        if self.install_lock.locked():
            raise InstallError("An install is already running")
        async with self.install_lock:
            await self.async_refresh()
            if not self.last_update_success:
                raise InstallError(f"Couldn't check for updates: {self.last_exception}")
            status = self.data
            if not status.update_available:
                raise InstallError("Already up to date")
            target = status.latest
            progress(5)

            same = await self.hass.async_add_executor_job(self._preflight, target)
            progress(15)

            if backup or self.config_entry.options.get(OPT_BACKUP, False):
                await self._backup(target)
            progress(40)

            try:
                old = await self.hass.async_add_executor_job(self._apply, target, same)
            except GitError as err:
                raise InstallError(f"Couldn't apply the update: {err}") from err
            progress(60)

            if errors := await async_check_ha_config_file(self.hass):
                try:
                    await self.hass.async_add_executor_job(self.git.reset_hard, old)
                except GitError as err:
                    raise InstallError(
                        f"The new configuration is invalid and rolling back to {old[:7]} failed "
                        f"({err}). Fix it on the host. Config errors: {errors}") from err
                raise InstallError(
                    f"The new configuration is invalid, rolled back to {old[:7]}. Errors: {errors}")
            await self.hass.async_add_executor_job(self._after_apply, target)
            progress(75)

            await self.hass.async_add_executor_job(self._touch_dashboards)
            try:
                await self.hass.services.async_call("homeassistant", "reload_all", blocking=True)
            except HomeAssistantError as err:
                raise InstallError(f"Installed {target[:7]}, but reloading failed: {err}") from err
            progress(95)

            if status.verdict.needed:
                ir.async_create_issue(
                    self.hass, DOMAIN, f"{ISSUE_RESTART}_{self.config_entry.entry_id}",
                    is_fixable=True, is_persistent=False, severity=ir.IssueSeverity.WARNING,
                    translation_key=ISSUE_RESTART,
                    translation_placeholders={
                        "version": target[:7],
                        "reasons": "\n".join(f"- {r}" for r in status.verdict.reasons[:20]),
                    },
                    data={"entry_id": self.config_entry.entry_id},
                )
        await self.async_refresh()

    def _preflight(self, target: str) -> list[str]:
        """Refuse on blocking local changes or a non-fast-forward; return dirty files that already
        match the target (safe to reset)."""
        git = self.git
        if not git.has_commit(target):
            git.fetch(self.branch)
        dirty = git.dirty()
        same = [p for p in dirty if git.same_as(target, p)]
        blocked = [p for p in dirty if p not in same]
        if blocked:
            raise InstallError(
                "Local changes to tracked files block the install. Commit them to the repository "
                "or undo them on the host: " + ", ".join(blocked[:20]))
        if not git.is_ancestor(git.head(), target):
            raise InstallError(
                "The checkout has commits that aren't on the branch, so this isn't a fast-forward. "
                "Resolve it on the host.")
        return same

    def _apply(self, target: str, same: list[str]) -> str:
        git = self.git
        old = git.head()
        git.restore(same)
        git.merge_ff(target)
        return old

    def _after_apply(self, target: str) -> None:
        # Keep `git status` on the host sensible: the tracking branch follows the install.
        if self.git.has_remote("origin"):
            self.git.update_ref(f"refs/remotes/origin/{self.branch}", target)

    def _touch_dashboards(self) -> None:
        """YAML dashboards are re-read only when their root file's mtime changes."""
        data: Any = self.hass.data.get("lovelace")
        for dash in (getattr(data, "dashboards", None) or {}).values():
            path = getattr(dash, "path", None)
            if getattr(dash, "mode", None) == "yaml" and path and os.path.isfile(path):
                os.utime(path)

    async def _backup(self, target: str) -> None:
        name = f"Before config update {target[:7]}"
        try:
            if is_hassio(self.hass) and self.hass.services.has_service("hassio", "backup_partial"):
                # A config backup: Home Assistant only, without the database (fast, small).
                await self.hass.services.async_call("hassio", "backup_partial", {
                    "homeassistant": True, "homeassistant_exclude_database": True, "name": name,
                }, blocking=True)
            elif self.hass.services.has_service("backup", "create"):
                await self.hass.services.async_call("backup", "create", blocking=True)
            else:
                raise InstallError("No backup action is available; install without a backup")
        except HomeAssistantError as err:
            if isinstance(err, InstallError):
                raise
            raise InstallError(f"The backup failed, nothing was changed: {err}") from err
