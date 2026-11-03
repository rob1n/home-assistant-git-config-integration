from custom_components.git_config_updater.core import ci


def runs(*items):
    return {"check_runs": [{"status": s, "conclusion": c} for s, c in items]}


def test_unknown_when_nothing_readable():
    assert ci.combine(None, None) == ci.UNKNOWN


def test_none_when_no_checks():
    assert ci.combine(runs(), {"statuses": []}) == ci.NONE


def test_success_neutral_skipped():
    assert ci.combine(runs(("completed", "success"), ("completed", "skipped"), ("completed", "neutral")), None) == ci.SUCCESS


def test_failure_wins_over_pending():
    assert ci.combine(runs(("in_progress", None), ("completed", "failure")), None) == ci.FAILURE


def test_pending():
    assert ci.combine(runs(("completed", "success"), ("queued", None)), None) == ci.PENDING


def test_statuses():
    assert ci.combine(None, {"statuses": [{"state": "success"}]}) == ci.SUCCESS
    assert ci.combine(None, {"statuses": [{"state": "error"}]}) == ci.FAILURE
    assert ci.combine(runs(("completed", "success")), {"statuses": [{"state": "pending"}]}) == ci.PENDING
