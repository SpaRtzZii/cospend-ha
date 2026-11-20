"""API websocket utilisée par la carte Lovelace (lecture seule).

Les commandes renvoient des données déjà en mémoire dans le coordinateur, sauf
``cospend/settlement`` qui interroge Nextcloud (avec un calcul local de repli).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from aiocospend import (
    Bill,
    CospendError,
    GroupedBill,
    Project,
    group_bills,
    split_comment,
    suggest_settlement,
)

from .const import DOMAIN
from .coordinator import CospendCoordinator, ProjectData

DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100


def async_setup_websocket(hass: HomeAssistant) -> None:
    """Enregistre les commandes ``cospend/*``."""
    websocket_api.async_register_command(hass, ws_projects)
    websocket_api.async_register_command(hass, ws_bills)
    websocket_api.async_register_command(hass, ws_bill)
    websocket_api.async_register_command(hass, ws_settlement)
    websocket_api.async_register_command(hass, ws_subscribe)


# ---------------------------------------------------------------------- sérialisation


def _color(rgb: tuple[int, int, int] | None) -> str | None:
    return None if rgb is None else "#{:02x}{:02x}{:02x}".format(*rgb)


def _coordinators(hass: HomeAssistant) -> list[CospendCoordinator]:
    """Coordinateurs des entrées chargées."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


def _serialize_project(
    coordinator: CospendCoordinator, project_id: str, data: ProjectData
) -> dict[str, Any]:
    project = data.project
    return {
        "entry_id": coordinator.config_entry.entry_id,
        "id": project_id,
        "name": project.name,
        "currency": project.currency_name,
        "archived": project.is_archived,
        "can_write": project.can_write and not project.is_archived,
        "access_level": project.access_level,
        "total_spent": project.total_spent,
        "nb_bills": len(data.bills),
        "pending": len(coordinator.queue.for_project(project_id)),
        "available": coordinator.last_update_success,
        "members": [
            {
                "id": member.id,
                "name": member.name,
                "activated": member.activated,
                "weight": member.weight,
                "color": _color(member.color),
                "balance": project.balance.get(member.id, 0.0),
            }
            for member in project.members
        ],
        "categories": [
            {"id": c.id, "name": c.name, "icon": c.icon, "color": c.color}
            for c in project.categories
        ],
        "payment_modes": [
            {"id": p.id, "name": p.name, "icon": p.icon, "color": p.color}
            for p in project.payment_modes
        ],
        "currencies": [
            {"id": c.id, "name": c.name, "exchange_rate": c.exchange_rate}
            for c in project.currencies
        ],
    }


def _shares(group: GroupedBill, project: Project) -> list[dict[str, Any]]:
    """Part de chaque participant (en devise du projet)."""
    shares: dict[int, float] = {}
    if group.is_group:
        # Répartition personnalisée : une dépense par participant, la part est son montant.
        for bill in group.bills:
            shares[bill.ower_ids[0]] = round(shares.get(bill.ower_ids[0], 0.0) + bill.amount, 2)
    else:
        bill = group.first
        total_weight = sum(ower.weight for ower in bill.owers)
        for ower in bill.owers:
            part = bill.amount * ower.weight / total_weight if total_weight else 0.0
            shares[ower.id] = round(part, 2)
    return [
        {
            "member_id": member_id,
            "name": (member.name if (member := project.member(member_id)) else str(member_id)),
            "amount": amount,
        }
        for member_id, amount in shares.items()
    ]


def _serialize_bill(
    group: GroupedBill, project: Project, coordinator: CospendCoordinator, *, detail: bool
) -> dict[str, Any]:
    bill: Bill = group.first
    comment, foreign = split_comment(bill.comment)
    item: dict[str, Any] = {
        "ids": list(group.ids),
        "id": bill.id,
        "is_group": group.is_group,
        "what": bill.what,
        "amount": group.total,
        "date": bill.date,
        "timestamp": bill.timestamp,
        "payer_id": bill.payer_id,
        "ower_ids": list(group.ower_ids),
        "category_id": bill.category_id,
        "payment_mode_id": bill.payment_mode_id,
        "comment": comment,
        "repeat": bill.repeat,
        "foreign": (
            {
                "currency": foreign.code,
                "amount": float(foreign.amount),
                "rate": float(foreign.rate),
            }
            if foreign
            else None
        ),
        "pending": any(coordinator.queue.touches_bill(project.id, i) for i in group.ids),
    }
    if detail:
        item["shares"] = _shares(group, project)
        item["repeat_freq"] = bill.repeat_freq
        item["repeat_until"] = bill.repeat_until
        item["repeat_all_active"] = bool(bill.repeat_all_active)
        # Poids inégaux (créés par une autre application) : une modification les remet à égalité.
        item["uneven_weights"] = (
            not group.is_group and len({ower.weight for ower in bill.owers}) > 1
        )
    return item


def _matches(group: GroupedBill, project: Project, needle: str) -> bool:
    bill = group.first
    payer = project.member(bill.payer_id)
    haystack = " ".join(
        [bill.what, split_comment(bill.comment)[0], payer.name if payer else ""]
    ).casefold()
    return all(word in haystack for word in needle.casefold().split())


def _find(
    hass: HomeAssistant, project_id: str, entry_id: str | None
) -> tuple[CospendCoordinator, ProjectData] | None:
    for coordinator in _coordinators(hass):
        if entry_id and coordinator.config_entry.entry_id != entry_id:
            continue
        data = (coordinator.data or {}).get(project_id)
        if data is not None:
            return coordinator, data
    return None


_PROJECT_FIELDS = {
    vol.Required("project_id"): str,
    vol.Optional("entry_id"): str,
}


# ---------------------------------------------------------------------- commandes


@websocket_api.websocket_command({vol.Required("type"): "cospend/projects"})
@callback
def ws_projects(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Projets suivis, avec membres, soldes et listes de choix."""
    projects = [
        _serialize_project(coordinator, project_id, data)
        for coordinator in _coordinators(hass)
        for project_id, data in (coordinator.data or {}).items()
    ]
    connection.send_result(msg["id"], {"projects": projects})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "cospend/bills",
        **_PROJECT_FIELDS,
        vol.Optional("offset", default=0): vol.All(int, vol.Range(min=0)),
        vol.Optional("limit", default=DEFAULT_PAGE_SIZE): vol.All(
            int, vol.Range(min=1, max=MAX_PAGE_SIZE)
        ),
        vol.Optional("search", default=""): str,
    }
)
@callback
def ws_bills(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Page de dépenses (plus récentes d'abord), regroupées, avec recherche facultative."""
    found = _find(hass, msg["project_id"], msg.get("entry_id"))
    if found is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Projet introuvable")
        return
    coordinator, data = found
    groups = group_bills(data.bills.values())
    groups.sort(key=lambda g: (g.first.timestamp, g.first.id), reverse=True)
    if needle := msg["search"].strip():
        groups = [g for g in groups if _matches(g, data.project, needle)]
    offset, limit = msg["offset"], msg["limit"]
    page = groups[offset : offset + limit]
    connection.send_result(
        msg["id"],
        {
            "total": len(groups),
            "offset": offset,
            "has_more": offset + limit < len(groups),
            "items": [
                _serialize_bill(group, data.project, coordinator, detail=False) for group in page
            ],
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "cospend/bill",
        **_PROJECT_FIELDS,
        vol.Required("bill_id"): int,
    }
)
@callback
def ws_bill(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Détail d'une dépense (ou de son groupe) avec la part de chaque participant."""
    found = _find(hass, msg["project_id"], msg.get("entry_id"))
    if found is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Projet introuvable")
        return
    coordinator, data = found
    group = next(
        (g for g in group_bills(data.bills.values()) if msg["bill_id"] in g.ids),
        None,
    )
    if group is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Dépense introuvable")
        return
    connection.send_result(
        msg["id"], _serialize_bill(group, data.project, coordinator, detail=True)
    )


@websocket_api.websocket_command({vol.Required("type"): "cospend/settlement", **_PROJECT_FIELDS})
@websocket_api.async_response
async def ws_settlement(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Plan de remboursement : celui de Cospend, ou un calcul local si le serveur ne répond pas."""
    found = _find(hass, msg["project_id"], msg.get("entry_id"))
    if found is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Projet introuvable")
        return
    coordinator, data = found
    source = "server"
    try:
        plan = (await coordinator.client.get_settlement(data.project.id)).transactions
    except CospendError:
        source = "local"
        plan = suggest_settlement(data.project.balance)
    transactions = [
        {"from_id": t.from_member, "to_id": t.to_member, "amount": round(t.amount, 2)}
        for t in plan
        if round(t.amount, 2) > 0
    ]
    connection.send_result(
        msg["id"],
        {
            "source": source,
            "transactions": transactions,
            # Des opérations en attente ne sont pas encore dans les soldes du serveur.
            "pending": len(coordinator.queue.for_project(data.project.id)),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): "cospend/subscribe"})
@callback
def ws_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Prévient la carte à chaque mise à jour des données ou de la file d'attente."""
    unsubscribers: list[Callable[[], None]] = []

    @callback
    def _changed() -> None:
        connection.send_message(websocket_api.event_message(msg["id"], {"changed": True}))

    for coordinator in _coordinators(hass):
        unsubscribers.append(coordinator.async_add_listener(_changed))
        unsubscribers.append(coordinator.queue.async_add_listener(_changed))

    @callback
    def _unsubscribe() -> None:
        for unsubscribe in unsubscribers:
            unsubscribe()

    connection.subscriptions[msg["id"]] = _unsubscribe
    connection.send_result(msg["id"])
