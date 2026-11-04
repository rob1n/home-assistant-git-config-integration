"""Fold GitHub Actions workflow runs and commit statuses into one CI status for a commit.

Fine-grained personal access tokens can't read check runs (GitHub only allows that for GitHub
Apps), so workflow runs are the only way to see Actions results with this kind of token.
"""
from __future__ import annotations

from typing import Any

SUCCESS, FAILURE, PENDING, NONE, UNKNOWN = "success", "failure", "pending", "none", "unknown"

_FAILED_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"}
_OK_CONCLUSIONS = {"success", "neutral", "skipped"}


def combine(workflow_runs: dict[str, Any] | None, statuses: dict[str, Any] | None) -> str:
    """`workflow_runs` is the /actions/runs response filtered to one commit, `statuses` the
    /commits/{sha}/status response; either may be None when the token can't read it. Failure wins
    over pending, pending over success. The runs endpoint lists each run once, as its latest attempt."""
    if workflow_runs is None and statuses is None:
        return UNKNOWN
    results: list[str] = []
    for run in (workflow_runs or {}).get("workflow_runs", []):
        if run.get("status") != "completed":
            results.append(PENDING)
        elif run.get("conclusion") in _FAILED_CONCLUSIONS:
            results.append(FAILURE)
        elif run.get("conclusion") in _OK_CONCLUSIONS:
            results.append(SUCCESS)
        else:
            results.append(PENDING)
    for st in (statuses or {}).get("statuses", []):
        state = st.get("state")
        results.append({"success": SUCCESS, "pending": PENDING}.get(state, FAILURE))
    if not results:
        return NONE
    for status in (FAILURE, PENDING):
        if status in results:
            return status
    return SUCCESS
