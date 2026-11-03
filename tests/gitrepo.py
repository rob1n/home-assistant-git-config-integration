"""Throwaway git repositories for tests: a bare remote (stands in for GitHub), a developer clone that
commits and pushes, and the checkout Home Assistant runs from."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ENV = os.environ | {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=ENV).stdout.strip()


class Repos:
    """`remote` is at <tmp>/<owner>/<name>.git so `file://<tmp>` can stand in for github.com."""

    def __init__(self, root: Path, owner: str = "someone", name: str = "ha-config") -> None:
        self.root = root
        self.repository = f"{owner}/{name}"
        self.remote = root / owner / f"{name}.git"
        self.dev = root / "dev"
        self.checkout = root / "config"
        self.remote.parent.mkdir(parents=True)
        git(root, "init", "--quiet", "--bare", "-b", "main", str(self.remote))
        git(root, "clone", "--quiet", str(self.remote), str(self.dev))
        git(self.dev, "checkout", "--quiet", "-b", "main")
        self.commit({"configuration.yaml": "homeassistant:\n  packages: !include_dir_named packages\n",
                     "packages/lights.yaml": "input_boolean:\n  party:\n    name: Party\n",
                     "dashboards/home.yaml": "title: Home\nviews: []\n"}, "Initial config")
        git(root, "clone", "--quiet", str(self.remote), str(self.checkout))

    @property
    def base_url(self) -> str:
        return f"file://{self.root}"

    @property
    def url(self) -> str:
        return f"file://{self.remote}"

    def commit(self, files: dict[str, str | None], message: str) -> str:
        """Write (or delete, for None) files in the developer clone, commit and push."""
        for path, content in files.items():
            f = self.dev / path
            if content is None:
                git(self.dev, "rm", "--quiet", path)
                continue
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(content)
            git(self.dev, "add", path)
        git(self.dev, "commit", "--quiet", "-m", message)
        git(self.dev, "push", "--quiet", "origin", "main")
        return git(self.dev, "rev-parse", "HEAD")

    def head(self, where: Path | None = None) -> str:
        return git(where or self.checkout, "rev-parse", "HEAD")

    def remote_head(self) -> str:
        return git(self.remote, "rev-parse", "refs/heads/main")
