"""Release summary and notes (markdown) for a pending config update."""
from __future__ import annotations

from collections.abc import Sequence

from .ci import FAILURE, NONE, PENDING, SUCCESS, UNKNOWN
from .gitops import Change, Commit
from .restart import RELOADABLE_FILES, Verdict

MAX_COMMITS = 50
MAX_FILES = 60

CI_TEXT = {
    SUCCESS: "✅ passed",
    FAILURE: "❌ failed",
    PENDING: "⏳ running",
    NONE: "no checks",
    UNKNOWN: "unknown (the token can't read checks)",
}
STATUS_TEXT = {"A": "added", "M": "changed", "D": "deleted", "R": "renamed", "C": "copied", "T": "type changed"}


def short(sha: str) -> str:
    return sha[:7]


def _md(text: str) -> str:
    """Escape markdown in commit subjects and paths."""
    for ch in "\\`*_[]<>|":
        text = text.replace(ch, f"\\{ch}")
    return text


def blocked_hints(blocked: Sequence[str], ha_version: str | None = None) -> list[str]:
    """What to do about the usual blocking local changes (plain text, no markdown)."""
    hints = []
    if ".HA_VERSION" in blocked:
        version = f" ({ha_version})" if ha_version else ""
        hints.append(f"Home Assistant was upgraded and rewrote .HA_VERSION: commit the new version{version} "
                     "to .HA_VERSION in the repository.")
    if editors := [p for p in blocked if p in RELOADABLE_FILES]:
        hints.append(f"{', '.join(editors)} {'was' if len(editors) == 1 else 'were'} changed in Home "
                     "Assistant's editors: copy the file from the host into the repository and commit it.")
    return hints


def ci_blocks(ci: str) -> bool:
    """With "require CI to pass" on, anything but a passed CI blocks the install."""
    return ci != SUCCESS


def summary(commits: Sequence[Commit], ci: str, verdict: Verdict, blocked: Sequence[str]) -> str:
    """One line, at most 255 characters (the update entity's limit)."""
    n = len(commits)
    parts = [f"{n} commit{'s' if n != 1 else ''}", f"CI {CI_TEXT.get(ci, ci).split(' (')[0]}",
             "restart needed" if verdict.needed else "reload only"]
    if blocked:
        parts.append(f"blocked by {len(blocked)} local change{'s' if len(blocked) != 1 else ''}")
    return " · ".join(parts)[:255]


def notes(
    commits: Sequence[Commit],
    changes: Sequence[Change],
    ci: str,
    verdict: Verdict,
    blocked: Sequence[str],
    compare_url: str | None,
    fast_forward: bool = True,
    ha_version: str | None = None,
    require_ci: bool = False,
) -> str:
    out: list[str] = []
    if not fast_forward:
        out += ["> ⚠️ **The local checkout has commits that aren't on the branch.** Install only",
                "> fast-forwards, so it will refuse. Resolve this on the host first.", ""]
    if blocked:
        out += ["> ⚠️ **Local changes block the install.** Commit them to the repo or undo them:", ">"]
        out += [f"> - `{_md(p)}`" for p in blocked[:MAX_FILES]]
        out += [f">\n> {_md(h)}" for h in blocked_hints(blocked, ha_version)]
        out += [""]
    if require_ci and ci_blocks(ci):
        out += ["> ⚠️ **CI hasn't passed for this commit.** The options require it, so install will refuse.",
                ""]
    out += [f"**CI:** {CI_TEXT.get(ci, ci)}  ",
            "**After installing:** " + ("restart needed" if verdict.needed else "reload, no restart"), ""]
    if verdict.needed:
        out += [f"- {_md(r)}" for r in verdict.reasons[:MAX_FILES]] + [""]
    out += [f"### Commits ({len(commits)})", ""]
    for c in commits[:MAX_COMMITS]:
        out.append(f"- {_md(c.subject)} (`{short(c.sha)}`, {c.date[:16].replace('T', ' ')})")
    if len(commits) > MAX_COMMITS:
        out.append(f"- … and {len(commits) - MAX_COMMITS} more")
    out += ["", f"### Files ({len(changes)})", ""]
    for ch in changes[:MAX_FILES]:
        what = STATUS_TEXT.get(ch.status, ch.status)
        name = f"{_md(ch.old_path)} → {_md(ch.path)}" if ch.old_path else _md(ch.path)
        out.append(f"- {what}: {name}")
    if len(changes) > MAX_FILES:
        out.append(f"- … and {len(changes) - MAX_FILES} more")
    if compare_url:
        out += ["", f"[Full diff on GitHub]({compare_url})"]
    return "\n".join(out)
