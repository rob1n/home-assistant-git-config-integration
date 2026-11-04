from custom_components.git_config_updater.core import ci


def runs(*items):
    return {"workflow_runs": [{"id": i, "status": s, "conclusion": c} for i, (s, c) in enumerate(items)]}


def test_unknown_when_nothing_readable():
    assert ci.combine(None, None) == ci.UNKNOWN


def test_none_when_no_workflow_ran():
    assert ci.combine(runs(), {"statuses": []}) == ci.NONE
    assert ci.combine({"total_count": 0, "workflow_runs": []}, None) == ci.NONE


def test_success_neutral_skipped():
    assert ci.combine(runs(("completed", "success"), ("completed", "skipped"), ("completed", "neutral")), None) == ci.SUCCESS


def test_failure_wins_over_pending():
    assert ci.combine(runs(("in_progress", None), ("completed", "failure")), None) == ci.FAILURE


def test_cancelled_and_timed_out_count_as_failure():
    assert ci.combine(runs(("completed", "cancelled")), None) == ci.FAILURE
    assert ci.combine(runs(("completed", "timed_out")), None) == ci.FAILURE


def test_pending():
    assert ci.combine(runs(("completed", "success"), ("queued", None)), None) == ci.PENDING
    assert ci.combine(runs(("completed", None)), None) == ci.PENDING


def test_statuses_alone_and_combined():
    assert ci.combine(None, {"statuses": [{"state": "success"}]}) == ci.SUCCESS
    assert ci.combine(None, {"statuses": [{"state": "error"}]}) == ci.FAILURE
    assert ci.combine(runs(("completed", "success")), {"statuses": [{"state": "pending"}]}) == ci.PENDING
