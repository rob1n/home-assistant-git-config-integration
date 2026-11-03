import base64
import subprocess

import pytest

from custom_components.git_config_updater.core.gitops import LATEST_REF, Git, GitError, auth_env

from ..gitrepo import git


def test_auth_env_keeps_token_out_of_argv():
    env = auth_env("secret-token")
    header = env["GIT_CONFIG_VALUE_0"]
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert base64.b64decode(header.removeprefix("Authorization: Basic ")).decode() == "x-access-token:secret-token"
    assert env["GIT_CONFIG_KEY_1"] == "credential.helper" and env["GIT_CONFIG_VALUE_1"] == ""
    assert "GIT_CONFIG_COUNT" not in auth_env(None)


def test_fetch_log_changes_and_fast_forward(repos):
    g = Git(str(repos.checkout), repos.url)
    base = g.head()
    repos.commit({"packages/lights.yaml": "input_boolean:\n  party: {}\n", "new.yaml": "x: 1\n"}, "Change lights")
    repos.commit({"dashboards/home.yaml": None}, "Drop dashboard")
    head = g.fetch("main")
    assert head == repos.remote_head()
    assert g.has_commit(head) and g.head() == base
    assert [c.subject for c in g.log(base, head)] == ["Drop dashboard", "Change lights"]
    assert {(c.status, c.path) for c in g.changes(base, head)} == {
        ("M", "packages/lights.yaml"), ("A", "new.yaml"), ("D", "dashboards/home.yaml")}
    assert g.show(head, "new.yaml") == "x: 1\n" and g.show(base, "new.yaml") is None
    assert g.is_ancestor(base, head) and not g.is_ancestor(head, base)
    g.merge_ff(head)
    assert g.head() == head
    # Fetching never moved origin's tracking branch or wrote to .git/config.
    assert git(repos.checkout, "rev-parse", "origin/main") == base
    assert "extraHeader" not in (repos.checkout / ".git" / "config").read_text()
    assert git(repos.checkout, "rev-parse", LATEST_REF) == head


def test_rename_detected(repos):
    g = Git(str(repos.checkout), repos.url)
    base = g.head()
    git(repos.dev, "mv", "dashboards/home.yaml", "dashboards/main.yaml")
    git(repos.dev, "commit", "--quiet", "-m", "Rename")
    git(repos.dev, "push", "--quiet", "origin", "main")
    head = g.fetch("main")
    [ch] = g.changes(base, head)
    assert (ch.status, ch.old_path, ch.path) == ("R", "dashboards/home.yaml", "dashboards/main.yaml")


def test_dirty_and_same_as(repos):
    g = Git(str(repos.checkout), repos.url)
    head = repos.commit({"packages/lights.yaml": "input_boolean: {}\n"}, "Edit")
    g.fetch("main")
    (repos.checkout / "packages/lights.yaml").write_text("input_boolean: {}\n")  # same as the update
    (repos.checkout / "configuration.yaml").write_text("changed: on the host\n")  # a real local edit
    (repos.checkout / "untracked.yaml").write_text("ignored: true\n")
    assert sorted(g.dirty()) == ["configuration.yaml", "packages/lights.yaml"]
    assert g.same_as(head, "packages/lights.yaml")
    assert not g.same_as(head, "configuration.yaml")
    g.restore(["packages/lights.yaml"])
    assert g.dirty() == ["configuration.yaml"]


def test_reset_hard_rolls_back(repos):
    g = Git(str(repos.checkout), repos.url)
    base = g.head()
    head = repos.commit({"configuration.yaml": "broken: [\n"}, "Break it")
    g.fetch("main")
    g.merge_ff(head)
    g.reset_hard(base)
    assert g.head() == base and "broken" not in (repos.checkout / "configuration.yaml").read_text()


def test_non_fast_forward_merge_fails(repos):
    g = Git(str(repos.checkout), repos.url)
    (repos.checkout / "local.yaml").write_text("x: 1\n")
    git(repos.checkout, "add", "local.yaml")
    git(repos.checkout, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "local")
    head = repos.commit({"other.yaml": "y: 2\n"}, "Remote")
    g.fetch("main")
    assert not g.is_ancestor(g.head(), head)
    with pytest.raises(GitError):
        g.merge_ff(head)


def test_errors_redact_the_token(repos):
    g = Git(str(repos.checkout), "file:///does/not/exist.git", token="tok-123")
    with pytest.raises(GitError) as err:
        g.fetch("main")
    assert "tok-123" not in str(err.value)


def test_is_repo(tmp_path, repos):
    assert Git(str(repos.checkout), repos.url).is_repo()
    assert not Git(str(tmp_path / "nope"), repos.url).is_repo()


def test_same_as_compares_symlinks_by_target(repos):
    g = Git(str(repos.checkout), repos.url)
    (repos.dev / "AGENTS.md").write_text("agents\n")
    (repos.dev / "CLAUDE.md").symlink_to("AGENTS.md")
    git(repos.dev, "add", "AGENTS.md", "CLAUDE.md")
    git(repos.dev, "commit", "--quiet", "-m", "Link")
    git(repos.dev, "push", "--quiet", "origin", "main")
    head = g.fetch("main")
    link = repos.checkout / "CLAUDE.md"
    link.symlink_to("AGENTS.md")  # the same link, before the update arrives
    assert g.same_as(head, "CLAUDE.md")
    link.unlink()
    link.write_text("agents\n")  # same content, but a regular file instead of the link
    assert not g.same_as(head, "CLAUDE.md")


def test_read_commands_take_no_optional_locks(repos, monkeypatch):
    g = Git(str(repos.checkout), repos.url)
    seen = {}
    real_run = subprocess.run

    def spy(cmd, **kw):
        seen.update(kw["env"])
        return real_run(cmd, **kw)

    monkeypatch.setattr("custom_components.git_config_updater.core.gitops.subprocess.run", spy)
    g.dirty()
    assert seen["GIT_OPTIONAL_LOCKS"] == "0"
