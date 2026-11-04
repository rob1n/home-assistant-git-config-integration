"""How GitHub's error answers map to exceptions."""
import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.git_config_updater.github import GitHub, GitHubError, GitHubNotFound

URL = "https://api.github.com/repos/someone/ha-config"


@pytest.mark.parametrize(("status", "headers", "text"), [
    (403, {"x-ratelimit-remaining": "0"}, ""),  # primary rate limit
    (403, {"retry-after": "60"}, ""),  # secondary rate limit
    (403, {}, '{"message": "You have exceeded a secondary rate limit."}'),
    (429, {}, ""),
])
async def test_rate_limits_are_connection_errors(hass, aioclient_mock, status, headers, text):
    aioclient_mock.get(URL, status=status, headers=headers, text=text)
    with pytest.raises(GitHubError, match="rate limit") as err:
        await GitHub(async_get_clientsession(hass), "someone/ha-config", "tok").repository_info()
    assert not isinstance(err.value, GitHubNotFound)


async def test_plain_forbidden_is_not_found(hass, aioclient_mock):
    aioclient_mock.get(URL, status=403, text='{"message": "Resource not accessible by personal access token"}')
    with pytest.raises(GitHubNotFound):
        await GitHub(async_get_clientsession(hass), "someone/ha-config", "tok").repository_info()


SHA = "a" * 40
RUNS = f"https://api.github.com/repos/someone/ha-config/actions/runs?head_sha={SHA}&per_page=100"
STATUS = f"https://api.github.com/repos/someone/ha-config/commits/{SHA}/status"


async def ci(hass, aioclient_mock, runs=None, status=None):
    for url, spec in ((RUNS, runs), (STATUS, status)):
        code, body = spec or (403, {"message": "Resource not accessible by personal access token"})
        aioclient_mock.get(url, status=code, json=body)
    gh = GitHub(async_get_clientsession(hass), "someone/ha-config", "tok")
    return await gh.ci_status(SHA)


async def test_ci_status_reads_actions_runs(hass, aioclient_mock):
    runs = (200, {"total_count": 1, "workflow_runs": [{"id": 1, "status": "completed", "conclusion": "success"}]})
    assert await ci(hass, aioclient_mock, runs=runs) == "success"
    # No check-runs endpoint is called: fine-grained tokens can't read it.
    assert not any("check-runs" in str(call[1]) for call in aioclient_mock.mock_calls)


async def test_ci_status_failed_run(hass, aioclient_mock):
    runs = (200, {"workflow_runs": [{"id": 1, "status": "completed", "conclusion": "failure"}]})
    assert await ci(hass, aioclient_mock, runs=runs) == "failure"


async def test_ci_status_no_workflow_ran(hass, aioclient_mock):
    assert await ci(hass, aioclient_mock, runs=(200, {"total_count": 0, "workflow_runs": []})) == "none"


async def test_ci_status_unknown_without_permission(hass, aioclient_mock):
    assert await ci(hass, aioclient_mock) == "unknown"


async def test_ci_status_statuses_only(hass, aioclient_mock):
    assert await ci(hass, aioclient_mock, status=(200, {"statuses": [{"state": "failure"}]})) == "failure"
