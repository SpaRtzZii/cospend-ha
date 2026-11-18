"""Entité de base : rattache chaque capteur à l'appareil de son projet."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CospendCoordinator, ProjectData


class CospendEntity(CoordinatorEntity[CospendCoordinator]):
    """Entité d'un projet Cospend (un appareil par projet)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CospendCoordinator, project_id: str) -> None:
        super().__init__(coordinator)
        self._project_id = project_id
        project = coordinator.data[project_id].project
        entry_id = coordinator.config_entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry_id}_{project_id}")},
            name=project.name,
            manufacturer="Nextcloud Cospend",
            model="Project",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=f"{coordinator.client.base_url}/apps/cospend/p/{project_id}",
        )

    @property
    def project_data(self) -> ProjectData | None:
        return self.coordinator.data.get(self._project_id) if self.coordinator.data else None

    @property
    def available(self) -> bool:
        return super().available and self.project_data is not None
