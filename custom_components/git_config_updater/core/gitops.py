"""A small wrapper around the git binary, for one local checkout.

Everything is synchronous (run it in an executor). Authentication for fetching is passed per call
through the environment (GIT_CONFIG_COUNT/KEY/VALUE), so the token never lands in `.git/config`, in
the remote URL or on the command line, and the checkout's own `origin` is left alone.
"""
from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Where fetched commits are kept: a private ref, so `origin` and its tracking branches are not
# touched by checks (only a successful install moves the tracking branch, see `install`).
LATEST_REF = "refs/git-config-updater/latest"
FETCH_TIMEOUT = 120
LOCAL_TIMEOUT = 60


class GitError(Exception):
    """A git command failed; the message is shown to the user."""


class GitMissing(GitError):
    """The git binary is not installed."""


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    date: str  # ISO 8601, committer date
    author: str


@dataclass(frozen=True)
class Change:
    status: str  # A, M, D, R (renamed), C, T
    path: str  # the new path for renames
    old_path: str | None = None


def auth_env(token: str | None) -> dict[str, str]:
    """Environment for an authenticated HTTPS fetch from GitHub (token as Basic auth password)."""
    env = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env |= {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
            # No credential helper may prompt or store anything.
            "GIT_CONFIG_KEY_1": "credential.helper",
            "GIT_CONFIG_VALUE_1": "",
        }
    return env


class Git:
    """Git commands on the checkout at `path`, fetching from `url` (e.g. https://github.com/o/r.git)."""

    def __init__(self, path: str, url: str, token: str | None = None) -> None:
        self.path = str(Path(path))
        self.url = url
        self._token = token

    def _run(self, *args: str, auth: bool = False, check: bool = True,
             timeout: int = LOCAL_TIMEOUT, binary: bool = False) -> subprocess.CompletedProcess:
        env = os.environ.copy() | {"LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0"}
        if auth:
            env |= auth_env(self._token)
        # The checkout may be owned by another user than the one running Home Assistant.
        cmd = ["git", "-c", f"safe.directory={self.path}", "-C", self.path, *args]
        try:
            res = subprocess.run(cmd, capture_output=True, env=env, timeout=timeout,
                                 text=not binary, check=False)
        except FileNotFoundError as err:
            raise GitMissing("git is not installed") from err
        except subprocess.TimeoutExpired as err:
            raise GitError(f"git {args[0]} timed out after {timeout} s") from err
        if check and res.returncode != 0:
            err = res.stderr if not binary else res.stderr.decode(errors="replace")
            raise GitError(f"git {args[0]} failed: {self._redact(err.strip())[:500]}")
        return res

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "***") if self._token else text

    # --- reading -------------------------------------------------------------------------------

    def is_repo(self) -> bool:
        try:
            return self._run("rev-parse", "--is-inside-work-tree", check=False).stdout.strip() == "true"
        except GitMissing:
            raise
        except GitError:
            return False

    def head(self) -> str:
        return self._run("rev-parse", "HEAD").stdout.strip()

    def has_commit(self, sha: str) -> bool:
        return self._run("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode == 0

    def is_ancestor(self, older: str, newer: str) -> bool:
        return self._run("merge-base", "--is-ancestor", older, newer, check=False).returncode == 0

    def log(self, base: str, head: str, limit: int = 200) -> list[Commit]:
        """Commits in head but not in base, newest first."""
        out = self._run("log", f"--max-count={limit}", "--format=%H%x1f%s%x1f%cI%x1f%an%x1e",
                        f"{base}..{head}").stdout
        commits = []
        for rec in out.split("\x1e"):
            rec = rec.strip("\n")
            if rec:
                sha, subject, date, author = rec.split("\x1f")
                commits.append(Commit(sha, subject, date, author))
        return commits

    def changes(self, base: str, head: str) -> list[Change]:
        out = self._run("diff", "--name-status", "-z", "-M", base, head).stdout
        parts = out.split("\0")
        changes, i = [], 0
        while i < len(parts) and parts[i]:
            status = parts[i][0]
            if status in ("R", "C"):
                changes.append(Change(status, parts[i + 2], parts[i + 1]))
                i += 3
            else:
                changes.append(Change(status, parts[i + 1]))
                i += 2
        return changes

    def show(self, rev: str, path: str) -> str | None:
        """A file's content at a revision, or None if it doesn't exist there."""
        res = self._run("show", f"{rev}:{path}", check=False)
        return res.stdout if res.returncode == 0 else None

    def dirty(self) -> list[str]:
        """Tracked files with local changes (staged or not). Untracked files don't count."""
        out = self._run("status", "--porcelain=v1", "-z", "--untracked-files=no").stdout
        parts = [p for p in out.split("\0") if p]
        files, i = [], 0
        while i < len(parts):
            entry = parts[i]
            files.append(entry[3:])
            # Renames carry the old path as the next entry.
            i += 2 if entry[0] in ("R", "C") else 1
        return files

    def same_as(self, rev: str, path: str) -> bool:
        """The working file equals its content at `rev` (a local edit that the update makes anyway)."""
        res = self._run("show", f"{rev}:{path}", check=False, binary=True)
        file = Path(self.path, path)
        if res.returncode != 0:
            return not file.exists()
        return file.is_file() and file.read_bytes() == res.stdout

    def has_remote(self, name: str) -> bool:
        return name in self._run("remote").stdout.split()

    # --- network -------------------------------------------------------------------------------

    def fetch(self, branch: str) -> str:
        """Fetch the branch into LATEST_REF and return its commit."""
        self._run("fetch", "--quiet", "--no-tags", "--no-write-fetch-head", self.url,
                  f"+refs/heads/{branch}:{LATEST_REF}", auth=True, timeout=FETCH_TIMEOUT)
        return self._run("rev-parse", LATEST_REF).stdout.strip()

    # --- writing -------------------------------------------------------------------------------

    def restore(self, paths: list[str]) -> None:
        if paths:
            self._run("checkout", "--", *paths)

    def merge_ff(self, sha: str) -> None:
        self._run("merge", "--ff-only", "--quiet", sha)

    def reset_hard(self, sha: str) -> None:
        self._run("reset", "--hard", "--quiet", sha)

    def update_ref(self, ref: str, sha: str) -> None:
        self._run("update-ref", ref, sha)
