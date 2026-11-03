"""The update entity end to end against temporary git repositories (GitHub API calls mocked)."""
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_mock_service

from custom_components.git_config_updater.const import DOMAIN

from .gitrepo import git

ENTITY = "update.home_assistant_config"
CO = "custom_components.git_config_updater.coordinator"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def check_config():
    with patch(f"{CO}.async_check_ha_config_file", AsyncMock(return_value=None)) as m:
        yield m


@pytest.fixture
async def setup(hass: HomeAssistant, repos, check_config):
    """Set up the integration with github.com replaced by the file:// remote."""
    reload_calls = async_mock_service(hass, "homeassistant", "reload_all")
    entry = MockConfigEntry(domain=DOMAIN, title="Home Assistant config", unique_id="u", data={
        "name": "Home Assistant config", "repository": repos.repository, "branch": "main",
        "token": "tok", "path": str(repos.checkout)})
    entry.add_to_hass(hass)
    with patch(f"{CO}.GITHUB_WEB", repos.base_url), \
            patch(f"{CO}.GitHub.branch_head", AsyncMock(side_effect=lambda _b: repos.remote_head())), \
            patch(f"{CO}.GitHub.ci_status", AsyncMock(return_value="success")):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, reload_calls


async def refresh(hass, entry):
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    return hass.states.get(ENTITY)


async def install(hass):
    await hass.services.async_call("update", "install", {"entity_id": ENTITY}, blocking=True)
    await hass.async_block_till_done()


async def test_up_to_date(hass, repos, setup):
    state = hass.states.get(ENTITY)
    assert state.state == "off"
    assert state.attributes["installed_version"] == repos.head()[:7]
    assert state.attributes["latest_version"] == repos.head()[:7]


async def test_update_available_with_notes(hass, repos, setup):
    entry, _ = setup
    new = repos.commit({"packages/lights.yaml": "input_boolean:\n  party: {}\n"}, "Tweak lights")
    state = await refresh(hass, entry)
    assert state.state == "on"
    assert state.attributes["latest_version"] == new[:7]
    assert state.attributes["release_summary"] == "1 commit · CI ✅ passed · reload only"
    assert "compare" in state.attributes["release_url"]
    notes = entry.runtime_data.data.notes
    assert "Tweak lights" in notes and "### Commits (1)" in notes
    assert "reload, no restart" in notes


async def test_install_fast_forward_and_reload(hass, repos, setup):
    entry, reload_calls = setup
    new = repos.commit({"packages/lights.yaml": "input_boolean:\n  party: {}\n"}, "Tweak lights")
    await refresh(hass, entry)
    await install(hass)
    assert repos.head() == new
    assert git(repos.checkout, "rev-parse", "origin/main") == new
    assert len(reload_calls) == 1
    state = hass.states.get(ENTITY)
    assert state.state == "off" and state.attributes["installed_version"] == new[:7]
    assert not ir.async_get(hass).async_get_issue(DOMAIN, f"restart_required_{entry.entry_id}")


async def test_install_raises_restart_repair(hass, repos, setup):
    entry, _ = setup
    repos.commit({"configuration.yaml": "homeassistant:\n  name: Home\n"}, "Core change")
    await refresh(hass, entry)
    await install(hass)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"restart_required_{entry.entry_id}")
    assert issue and issue.is_fixable
    assert "configuration.yaml changed" in issue.translation_placeholders["reasons"]


async def test_dirty_tree_blocks_install(hass, repos, setup):
    entry, reload_calls = setup
    base = repos.head()
    repos.commit({"packages/lights.yaml": "input_boolean: {}\n"}, "Edit")
    (repos.checkout / "configuration.yaml").write_text("edited: on the host\n")
    state = await refresh(hass, entry)
    assert "blocked by 1 local change" in state.attributes["release_summary"]
    with pytest.raises(HomeAssistantError, match="Local changes .* configuration.yaml"):
        await install(hass)
    assert repos.head() == base and not reload_calls


async def test_dirty_file_matching_the_update_is_fine(hass, repos, setup):
    entry, _ = setup
    new = repos.commit({"packages/lights.yaml": "input_boolean: {}\n"}, "Edit")
    (repos.checkout / "packages/lights.yaml").write_text("input_boolean: {}\n")
    await refresh(hass, entry)
    await install(hass)
    assert repos.head() == new


async def test_failed_check_rolls_back(hass, repos, setup, check_config):
    entry, reload_calls = setup
    base = repos.head()
    repos.commit({"packages/lights.yaml": "input_boolean: [broken\n"}, "Break")
    await refresh(hass, entry)
    check_config.return_value = "Invalid config for input_boolean"
    with pytest.raises(HomeAssistantError, match="rolled back to .* Invalid config for input_boolean"):
        await install(hass)
    assert repos.head() == base
    assert "broken" not in (repos.checkout / "packages/lights.yaml").read_text()
    assert git(repos.checkout, "rev-parse", "origin/main") == base
    assert not reload_calls


async def test_non_fast_forward_refused(hass, repos, setup):
    entry, _ = setup
    (repos.checkout / "local.yaml").write_text("x: 1\n")
    git(repos.checkout, "add", "local.yaml")
    git(repos.checkout, "-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "local")
    local = repos.head()
    repos.commit({"other.yaml": "y: 2\n"}, "Remote")
    state = await refresh(hass, entry)
    assert state.state == "on"
    with pytest.raises(HomeAssistantError, match="isn't a fast-forward"):
        await install(hass)
    assert repos.head() == local


async def test_backup_option_calls_backup(hass, repos, setup):
    entry, _ = setup
    backup_calls = async_mock_service(hass, "backup", "create")
    repos.commit({"packages/lights.yaml": "input_boolean: {}\n"}, "Edit")
    await refresh(hass, entry)
    await hass.services.async_call("update", "install", {"entity_id": ENTITY, "backup": True}, blocking=True)
    assert len(backup_calls) == 1
