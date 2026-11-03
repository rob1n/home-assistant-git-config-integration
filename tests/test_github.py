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
