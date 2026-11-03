"""Config flow: repository, branch, token and checkout path; options: interval, backup, rules."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, override

import probatio
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_BRANCH,
    CONF_NAME,
    CONF_PATH,
    CONF_REPOSITORY,
    CONF_TOKEN,
    DEFAULT_BRANCH,
    DEFAULT_NAME,
    DEFAULT_PACKAGES_DIR,
    DEFAULT_SCAN_MINUTES,
    DOMAIN,
    GITHUB_WEB,
    OPT_BACKUP,
    OPT_PACKAGES_DIR,
    OPT_RESTART_GLOBS,
    OPT_SCAN_MINUTES,
)
from .core.gitops import Git, GitMissing
from .github import GitHub, GitHubAuthError, GitHubError, GitHubNotFound

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_PASSWORD = selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))


async def _validate(hass: HomeAssistant, data: Mapping[str, Any]) -> dict[str, str]:
    """Errors keyed by field ("base" for general ones); empty when everything checks out."""
    errors: dict[str, str] = {}
    repo = data[CONF_REPOSITORY].strip().removesuffix(".git")
    if not _REPO.match(repo):
        return {CONF_REPOSITORY: "invalid_repository"}
    git = Git(data[CONF_PATH], f"{GITHUB_WEB}/{repo}.git")
    try:
        if not await hass.async_add_executor_job(git.is_repo):
            errors[CONF_PATH] = "not_a_checkout"
    except GitMissing:
        return {"base": "git_missing"}
    gh = GitHub(async_get_clientsession(hass), repo, data[CONF_TOKEN])
    try:
        await gh.repository_info()
    except GitHubAuthError:
        errors[CONF_TOKEN] = "invalid_auth"
    except GitHubNotFound:
        errors[CONF_REPOSITORY] = "repository_not_found"
    except GitHubError:
        errors["base"] = "cannot_connect"
    else:
        try:
            await gh.branch_head(data[CONF_BRANCH])
        except GitHubNotFound:
            errors[CONF_BRANCH] = "branch_not_found"
        except GitHubError:
            errors["base"] = "cannot_connect"
    return errors


class GitConfigUpdaterFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    @override
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return GitConfigUpdaterOptions()

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_REPOSITORY] = user_input[CONF_REPOSITORY].strip().removesuffix(".git")
            await self.async_set_unique_id(
                f"{user_input[CONF_REPOSITORY].lower()}@{user_input[CONF_BRANCH]}:{user_input[CONF_PATH]}")
            self._abort_if_unique_id_configured()
            errors = await _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        defaults = user_input or {}
        schema = probatio.Schema({
            probatio.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
            probatio.Required(CONF_REPOSITORY, default=defaults.get(CONF_REPOSITORY, "")): str,
            probatio.Required(CONF_BRANCH, default=defaults.get(CONF_BRANCH, DEFAULT_BRANCH)): str,
            probatio.Required(CONF_TOKEN): _PASSWORD,
            probatio.Required(CONF_PATH, default=defaults.get(CONF_PATH, self.hass.config.config_dir)): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @override
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """A new token, e.g. after the old one expired."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_TOKEN: user_input[CONF_TOKEN]}
            errors = await _validate(self.hass, data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=probatio.Schema({probatio.Required(CONF_TOKEN): _PASSWORD}),
            errors=errors,
            description_placeholders={"repository": entry.data[CONF_REPOSITORY]},
        )


class GitConfigUpdaterOptions(OptionsFlow):
    @override
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        schema = probatio.Schema({
            probatio.Required(OPT_SCAN_MINUTES, default=o.get(OPT_SCAN_MINUTES, DEFAULT_SCAN_MINUTES)):
                selector.NumberSelector(selector.NumberSelectorConfig(
                    min=1, max=1440, step=1, unit_of_measurement="min", mode=selector.NumberSelectorMode.BOX)),
            probatio.Required(OPT_BACKUP, default=o.get(OPT_BACKUP, False)): selector.BooleanSelector(),
            probatio.Required(OPT_PACKAGES_DIR, default=o.get(OPT_PACKAGES_DIR, DEFAULT_PACKAGES_DIR)): str,
            probatio.Optional(OPT_RESTART_GLOBS, description={"suggested_value": o.get(OPT_RESTART_GLOBS, "")}):
                selector.TextSelector(selector.TextSelectorConfig(multiline=True)),
        })
        return self.async_show_form(step_id="init", data_schema=schema)
