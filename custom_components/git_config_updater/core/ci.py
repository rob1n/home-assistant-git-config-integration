"""Fold GitHub check runs and commit statuses into one CI status for a commit."""
from __future__ import annotations

from typing import Any

SUCCESS, FAILURE, PENDING, NONE, UNKNOWN = "success", "failure", "pending", "none", "unknown"

_FAILED_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"}
_OK_CONCLUSIONS = {"success", "neutral", "skipped"}


def combine(check_runs: dict[str, Any] | None, statuses: dict[str, Any] | None) -> str:
    """`check_runs` is the /commits/{sha}/check-runs response, `statuses` the /commits/{sha}/status
    response; either may be None when the token can't read it. Failure wins over pending, pending
    over success."""
    if check_runs is None and statuses is None:
        return UNKNOWN
    results: list[str] = []
    for run in (check_runs or {}).get("check_runs", []):
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
