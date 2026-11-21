"""Copie locale des projets et de leurs dépenses, pour démarrer quand Nextcloud est injoignable.

La copie est écrite après chaque lecture réussie. Au lancement de Home Assistant, si Cospend ne
répond pas, l'intégration repart de cette copie : les capteurs, la carte et la liste des dépenses
sont disponibles en lecture (les écritures sont mises en file d'attente) jusqu'au retour du serveur.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from aiocospend import (
    Bill,
    Category,
    Currency,
    Member,
    Ower,
    PaymentMode,
    Project,
    ProjectStatistics,
    Share,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY_SECONDS = 30


def project_to_dict(project: Project) -> dict[str, Any]:
    """Projet sous forme JSON (les clés de ``balance`` deviennent des chaînes)."""
    data = asdict(project)
    data["balance"] = {str(key): value for key, value in project.balance.items()}
    return data


def project_from_dict(data: Mapping[str, Any]) -> Project:
    """Inverse de :func:`project_to_dict`."""

    def member(item: Mapping[str, Any]) -> Member:
        color = item.get("color")
        return Member(**{**item, "color": tuple(color) if color else None})

    return Project(
        **{
            **data,
            "balance": {int(key): float(value) for key, value in data["balance"].items()},
            "members": tuple(member(item) for item in data["members"]),
            "categories": tuple(Category(**item) for item in data["categories"]),
            "payment_modes": tuple(PaymentMode(**item) for item in data["payment_modes"]),
            "currencies": tuple(Currency(**item) for item in data["currencies"]),
            "shares": tuple(Share(**item) for item in data["shares"]),
        }
    )


def bill_to_dict(bill: Bill) -> dict[str, Any]:
    return asdict(bill)


def bill_from_dict(data: Mapping[str, Any]) -> Bill:
    return Bill(**{**data, "owers": tuple(Ower(**item) for item in data["owers"])})


class ProjectCache:
    """Lecture et écriture de la copie locale d'une entrée de configuration."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.cache"
        )
        self._last_saved = ""

    async def async_load(
        self,
    ) -> dict[str, tuple[Project, list[Bill], ProjectStatistics | None]]:
        """Projets de la copie ; une copie illisible est ignorée (jamais bloquante)."""
        stored = await self._store.async_load()
        result: dict[str, tuple[Project, list[Bill], ProjectStatistics | None]] = {}
        if not stored:
            return result
        for project_id, item in (stored.get("projects") or {}).items():
            try:
                project = project_from_dict(item["project"])
                bills = [bill_from_dict(bill) for bill in item["bills"]]
                raw = item.get("statistics")
                statistics = ProjectStatistics.from_api(raw) if raw else None
            except Exception:  # noqa: BLE001 - une copie abîmée ne doit jamais empêcher le démarrage
                _LOGGER.warning("Copie locale du projet Cospend %s illisible : ignorée", project_id)
                continue
            result[project_id] = (project, bills, statistics)
        return result

    def schedule_save(
        self,
        data: Mapping[str, tuple[Project, Mapping[int, Bill], ProjectStatistics | None]],
    ) -> None:
        """Programme l'écriture, sauf si rien n'a changé depuis la précédente."""
        payload = {
            "projects": {
                project_id: {
                    "project": project_to_dict(project),
                    "bills": [bill_to_dict(bill) for bill in bills.values()],
                    "statistics": dict(statistics.raw) if statistics else None,
                }
                for project_id, (project, bills, statistics) in data.items()
            }
        }
        try:
            signature = json.dumps(payload, sort_keys=True, default=str)
        except (TypeError, ValueError):
            _LOGGER.debug("Copie locale non sérialisable : ignorée", exc_info=True)
            return
        if signature == self._last_saved:
            return
        self._last_saved = signature
        self._store.async_delay_save(lambda: payload, SAVE_DELAY_SECONDS)

    async def async_remove(self) -> None:
        await self._store.async_remove()
