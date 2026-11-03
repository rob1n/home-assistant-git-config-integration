"""Git Config Updater: install changes to a git-managed Home Assistant configuration from the UI.

One config entry per checkout. It polls the GitHub branch, shows pending commits as an update
entity (with a changelog) and, on Install, fast-forwards the checkout, checks the configuration,
rolls back on errors, reloads, and raises a "Restart needed" repair when a reload isn't enough.
"""
from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_RESTART
from .coordinator import GitConfigCoordinator, GitConfigUpdaterEntry

PLATFORMS = [Platform.UPDATE]


async def async_setup_entry(hass: HomeAssistant, entry: GitConfigUpdaterEntry) -> bool:
    coordinator = GitConfigCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GitConfigUpdaterEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: GitConfigUpdaterEntry) -> None:
    """Drop this entry's pending "Restart needed" repair."""
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_RESTART}_{entry.entry_id}")


async def _options_updated(hass: HomeAssistant, entry: GitConfigUpdaterEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
