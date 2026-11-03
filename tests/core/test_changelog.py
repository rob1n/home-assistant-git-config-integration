from custom_components.git_config_updater.core import changelog
from custom_components.git_config_updater.core.gitops import Change, Commit
from custom_components.git_config_updater.core.restart import Verdict

COMMITS = [Commit("a" * 40, "Add *party* mode", "2026-11-03T08:01:00+01:00", "Test"),
           Commit("b" * 40, "Fix [lights]", "2026-11-03T07:59:00+01:00", "Test")]
CHANGES = [Change("M", "packages/lights.yaml"), Change("R", "dashboards/new.yaml", "dashboards/old.yaml"),
           Change("A", "configuration.yaml")]


def test_summary():
    v = Verdict()
    v.add("configuration.yaml changed")
    assert changelog.summary(COMMITS, "success", v, []) == "2 commits · CI ✅ passed · restart needed"
    assert changelog.summary(COMMITS[:1], "unknown", Verdict(), ["a"]) == \
        "1 commit · CI unknown · reload only · blocked by 1 local change"


def test_notes_lists_commits_files_ci_and_restart():
    v = Verdict()
    v.add("configuration.yaml changed")
    md = changelog.notes(COMMITS, CHANGES, "failure", v, [], "https://example.invalid/compare/a...b")
    assert "**CI:** ❌ failed" in md
    assert "**After installing:** restart needed" in md and "- configuration.yaml changed" in md
    assert "- Add \\*party\\* mode (`aaaaaaa`, 2026-11-03 08:01)" in md
    assert "- renamed: dashboards/old.yaml → dashboards/new.yaml" in md
    assert "### Commits (2)" in md and "### Files (3)" in md
    assert md.endswith("[Full diff on GitHub](https://example.invalid/compare/a...b)")


def test_notes_warn_about_blocking_changes_and_non_fast_forward():
    md = changelog.notes(COMMITS, CHANGES, "none", Verdict(), ["packages/local.yaml"], None, fast_forward=False)
    assert "isn't on the branch" in md or "aren't on the branch" in md
    assert "Local changes block the install" in md and "`packages/local.yaml`" in md
    assert "reload, no restart" in md and "Full diff" not in md


def test_long_lists_are_truncated():
    many = [Commit(f"{i:040x}", f"c{i}", "2026-11-03T08:00:00+01:00", "T") for i in range(60)]
    md = changelog.notes(many, [], "none", Verdict(), [], None)
    assert "… and 10 more" in md


def test_hints_for_ha_version_and_editor_files():
    hints = changelog.blocked_hints([".HA_VERSION", "automations.yaml", "packages/x.yaml"], "2026.11.0")
    assert hints[0].startswith("Home Assistant was upgraded") and "(2026.11.0)" in hints[0]
    assert hints[1].startswith("automations.yaml was changed in Home Assistant's editors")
    assert changelog.blocked_hints(["packages/x.yaml"]) == []
    md = changelog.notes(COMMITS, CHANGES, "success", Verdict(), [".HA_VERSION"], None, ha_version="2026.11.0")
    assert "Home Assistant was upgraded" in md


def test_notes_warn_when_ci_is_required_and_not_passed():
    assert "CI hasn't passed" in changelog.notes(COMMITS, CHANGES, "pending", Verdict(), [], None, require_ci=True)
    assert "CI hasn't passed" not in changelog.notes(COMMITS, CHANGES, "success", Verdict(), [], None,
                                                     require_ci=True)
    assert "CI hasn't passed" not in changelog.notes(COMMITS, CHANGES, "failure", Verdict(), [], None)
