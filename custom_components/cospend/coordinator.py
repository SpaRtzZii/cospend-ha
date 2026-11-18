"""Mise à jour périodique des projets Cospend."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from aiocospend import (
    Bill,
    BillChanges,
    CospendAuthenticationError,
    CospendClient,
    CospendError,
    Project,
    ProjectBills,
    ProjectStatistics,
)

from .const import (
    CONF_FULL_RESYNC_HOURS,
    CONF_PROJECTS,
    DEFAULT_FULL_RESYNC_HOURS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_BILL_ADDED,
    EVENT_BILL_DELETED,
    EVENT_BILL_UPDATED,
)

_LOGGER = logging.getLogger(__name__)

type CospendConfigEntry = ConfigEntry[CospendCoordinator]


@dataclass(slots=True)
class ProjectData:
    """État d'un projet à un instant donné."""

    project: Project
    bills: Mapping[int, Bill]
    statistics: ProjectStatistics | None = None

    @property
    def last_bill(self) -> Bill | None:
        """Dépense la plus récente (par date, puis par identifiant)."""
        return max(self.bills.values(), key=lambda bill: (bill.timestamp, bill.id), default=None)


class CospendCoordinator(DataUpdateCoordinator[dict[str, ProjectData]]):
    """Lit les projets choisis et tient leurs dépenses à jour de façon incrémentale."""

    config_entry: CospendConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: CospendConfigEntry, client: CospendClient
    ) -> None:
        minutes = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(minutes=minutes),
        )
        self.client = client
        self._full_resync_seconds = (
            entry.options.get(CONF_FULL_RESYNC_HOURS, DEFAULT_FULL_RESYNC_HOURS) * 3600
        )
        self._stores: dict[str, ProjectBills] = {}
        self._statistics: dict[str, ProjectStatistics] = {}
        self._statistics_stale: set[str] = set()

    async def _async_update_data(self) -> dict[str, ProjectData]:
        try:
            projects = {project.id: project for project in await self.client.get_projects()}
            result: dict[str, ProjectData] = {}
            for project_id in self.config_entry.options.get(CONF_PROJECTS, []):
                project = projects.get(project_id)
                if project is None:
                    _LOGGER.warning(
                        "Le projet Cospend %s n'existe plus ou n'est plus accessible", project_id
                    )
                    continue
                result[project_id] = await self._async_update_project(project)
        except CospendAuthenticationError as err:
            raise ConfigEntryAuthFailed("Identifiants Cospend refusés") from err
        except CospendError as err:
            raise UpdateFailed(f"Erreur de communication avec Cospend : {err}") from err
        return result

    async def _async_update_project(self, project: Project) -> ProjectData:
        store = self._stores.setdefault(project.id, ProjectBills(project.id))
        changes = await store.sync(self.client, full_sync_max_age=self._full_resync_seconds)
        if changes.any:
            self._statistics_stale.add(project.id)
            if not changes.is_initial:
                self._fire_events(project, changes)
        if project.id in self._statistics_stale or project.id not in self._statistics:
            self._statistics[project.id] = await self.client.get_statistics(project.id)
            self._statistics_stale.discard(project.id)
        return ProjectData(project, store.bills, self._statistics[project.id])

    def _fire_events(self, project: Project, changes: BillChanges) -> None:
        for event, bills in (
            (EVENT_BILL_ADDED, changes.added),
            (EVENT_BILL_UPDATED, changes.updated),
            (EVENT_BILL_DELETED, changes.deleted),
        ):
            for bill in bills:
                self.hass.bus.async_fire(event, bill_event_data(project, bill))


def bill_event_data(project: Project, bill: Bill) -> dict[str, Any]:
    """Données d'un événement ``cospend_bill_*``."""
    payer = project.member(bill.payer_id)
    owers = [project.member(ower_id) for ower_id in bill.ower_ids]
    return {
        "project_id": project.id,
        "project_name": project.name,
        "bill_id": bill.id,
        "what": bill.what,
        "amount": bill.amount,
        "date": bill.date,
        "timestamp": bill.timestamp,
        "comment": bill.comment,
        "payer_id": bill.payer_id,
        "payer_name": payer.name if payer else None,
        "ower_ids": list(bill.ower_ids),
        "ower_names": [member.name for member in owers if member],
        "category_id": bill.category_id,
        "payment_mode_id": bill.payment_mode_id,
    }
