"""The update entity: installed = local commit, latest = branch head."""
from __future__ import annotations

from typing import Any, override

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME
from .coordinator import GitConfigCoordinator, GitConfigUpdaterEntry


async def async_setup_entry(hass: HomeAssistant, entry: GitConfigUpdaterEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities([GitConfigUpdate(entry.runtime_data, entry)])


class GitConfigUpdate(CoordinatorEntity[GitConfigCoordinator], UpdateEntity):
    _attr_supported_features = (UpdateEntityFeature.INSTALL | UpdateEntityFeature.PROGRESS
                                | UpdateEntityFeature.RELEASE_NOTES | UpdateEntityFeature.BACKUP)
    _attr_icon = "mdi:source-branch-sync"

    def __init__(self, coordinator: GitConfigCoordinator, entry: GitConfigUpdaterEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = entry.entry_id
        self._attr_name = entry.data[CONF_NAME]
        self._attr_title = f"{coordinator.repository} ({coordinator.branch})"

    @property
    @override
    def entity_picture(self) -> str | None:
        # No brand icon exists for a custom integration; let the icon show.
        return None

    @property
    @override
    def installed_version(self) -> str | None:
        return self.coordinator.data.installed[:7] if self.coordinator.data else None

    @property
    @override
    def latest_version(self) -> str | None:
        data = self.coordinator.data
        if not data:
            return None
        return data.latest[:7] if data.update_available else data.installed[:7]

    @override
    def version_is_newer(self, latest_version: str, installed_version: str) -> bool:
        return bool(self.coordinator.data and self.coordinator.data.update_available)

    @property
    @override
    def release_summary(self) -> str | None:
        return self.coordinator.data.summary if self.coordinator.data else None

    @property
    @override
    def release_url(self) -> str | None:
        data = self.coordinator.data
        return data.compare_url if data and data.update_available else None

    @override
    async def async_release_notes(self) -> str | None:
        return self.coordinator.data.notes if self.coordinator.data else None

    @override
    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        def progress(pct: int) -> None:
            self._attr_in_progress = True
            self._attr_update_percentage = pct
            self.async_write_ha_state()

        try:
            await self.coordinator.async_install(backup, progress)
        finally:
            self._attr_in_progress = False
            self._attr_update_percentage = None
            self.async_write_ha_state()
