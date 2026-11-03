from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.git_config_updater.const import DOMAIN
from custom_components.git_config_updater.github import GitHubAuthError, GitHubError, GitHubNotFound

GH = "custom_components.git_config_updater.config_flow.GitHub"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def no_setup():
    with patch("custom_components.git_config_updater.async_setup_entry", return_value=True) as m:
        yield m


def user_input(path, **kw):
    return {"name": "Home Assistant config", "repository": "someone/ha-config", "branch": "main",
            "token": "tok", "path": str(path)} | kw


async def start(hass):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def test_success(hass: HomeAssistant, repos, no_setup):
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    with patch(f"{GH}.repository_info", AsyncMock(return_value={})), \
            patch(f"{GH}.branch_head", AsyncMock(return_value="a" * 40)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input(repos.checkout, repository="someone/ha-config.git"))
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Home Assistant config"
    assert result["data"]["repository"] == "someone/ha-config"


@pytest.mark.parametrize(("exc", "where", "field", "error"), [
    (GitHubAuthError("x"), "repository_info", "token", "invalid_auth"),
    (GitHubNotFound("x"), "repository_info", "repository", "repository_not_found"),
    (GitHubError("x"), "repository_info", "base", "cannot_connect"),
    (GitHubNotFound("x"), "branch_head", "branch", "branch_not_found"),
])
async def test_github_errors(hass, repos, exc, where, field, error):
    result = await start(hass)
    mocks = {"repository_info": AsyncMock(return_value={}), "branch_head": AsyncMock(return_value="a" * 40)}
    mocks[where] = AsyncMock(side_effect=exc)
    with patch(f"{GH}.repository_info", mocks["repository_info"]), patch(f"{GH}.branch_head", mocks["branch_head"]):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input(repos.checkout))
    assert result["type"] is FlowResultType.FORM and result["errors"] == {field: error}


async def test_invalid_repository_and_path(hass, tmp_path):
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input(tmp_path, repository="not a repo"))
    assert result["errors"] == {"repository": "invalid_repository"}
    with patch(f"{GH}.repository_info", AsyncMock(return_value={})), \
            patch(f"{GH}.branch_head", AsyncMock(return_value="a" * 40)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input(tmp_path / "missing"))
    assert result["errors"] == {"path": "not_a_checkout"}


async def test_already_configured(hass, repos):
    MockConfigEntry(domain=DOMAIN, unique_id=f"someone/ha-config@main:{repos.checkout}").add_to_hass(hass)
    result = await start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input(repos.checkout))
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_reauth_updates_token(hass, repos, no_setup):
    entry = MockConfigEntry(domain=DOMAIN, data=user_input(repos.checkout), unique_id="u")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with patch(f"{GH}.repository_info", AsyncMock(return_value={})), \
            patch(f"{GH}.branch_head", AsyncMock(return_value="a" * 40)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"token": "new"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reauth_successful"
    assert entry.data["token"] == "new"


async def test_options(hass, repos, no_setup):
    entry = MockConfigEntry(domain=DOMAIN, data=user_input(repos.checkout), unique_id="u")
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "scan_interval": 10, "backup": True, "packages_dir": "packages", "restart_globs": "www/**/*.js"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["scan_interval"] == 10 and entry.options["restart_globs"] == "www/**/*.js"
