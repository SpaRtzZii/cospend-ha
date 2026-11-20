"""Services de gestion du projet : membres, catégories, modes de paiement et devises.

Ces opérations ne passent pas par la file d'attente hors ligne : elles modifient la structure du
projet, et rejouer plus tard un ajout ou une suppression pourrait créer des doublons ou viser un
autre élément. Si Cospend est injoignable, le service échoue simplement.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from aiocospend import (
    CospendClient,
    CospendConnectionError,
    CospendMaintenanceError,
    Project,
    ResolutionError,
    resolve_member,
)
from aiocospend.const import DEFAULT_COLOR
from aiocospend.writer import _match

from .const import DOMAIN
from .services import (
    _REF,
    ATTR_PROJECT,
    _check_writable,
    _error,
    _find_project,
    _fresh_project,
    _rate,
    _translate,
)

MAINTAINER_LEVEL = 3

ATTR_MEMBER = "member"
ATTR_CATEGORY = "category"
ATTR_PAYMENT_MODE = "payment_mode"
ATTR_CURRENCY = "currency"
ATTR_NAME = "name"
ATTR_NEW_NAME = "new_name"
ATTR_WEIGHT = "weight"
ATTR_COLOR = "color"
ATTR_ICON = "icon"
ATTR_ACTIVE = "active"
ATTR_RATE = "exchange_rate"

_COLOR = vol.All(cv.string, vol.Match(r"^#[0-9a-fA-F]{6}$"), str.lower)
_NAME = vol.All(cv.string, str.strip, vol.Length(min=1, max=100))
_WEIGHT = vol.All(vol.Coerce(float), vol.Range(min=0, max=1000))
_ICON = vol.All(cv.string, vol.Length(max=16))
_CODE = vol.All(cv.string, str.strip, vol.Length(min=1, max=20), vol.Match(r"^[^\s,]+$"))


class _MemberExists(Exception):
    """Un membre actif porte déjà ce nom."""


Handler = Callable[[ServiceCall], Awaitable[ServiceResponse]]


def _hex(rgb: tuple[int, int, int] | None) -> str | None:
    return None if rgb is None else "#{:02x}{:02x}{:02x}".format(*rgb)


def _check_maintainer(project: Project) -> None:
    if project.access_level < MAINTAINER_LEVEL:
        raise _error("needs_maintainer", project=project.name)


def _resolve(project: Project, kind: str, ref: str) -> int:
    """Identifiant de l'élément désigné par son nom (ou son identifiant)."""
    try:
        if kind == "member":
            return resolve_member(project, ref)
        if kind == "category":
            names = {c.id: c.name for c in project.categories}
            return _match(names, ref, "catégorie")
        if kind == "payment_mode":
            names = {p.id: p.name for p in project.payment_modes}
            return _match(names, ref, "mode de paiement")
        names = {c.id: c.name for c in project.currencies}
        return _match(names, ref, "devise")
    except ResolutionError as err:
        raise _error("invalid_value", error=err) from err


async def _manage(
    call: ServiceCall,
    kind: str | None,
    action: Callable[[CospendClient, str, Project, int | None], Awaitable[int | None]],
    extra: dict[str, Any] | None = None,
) -> ServiceResponse:
    """Résout le projet et l'élément visé, exécute l'appel puis rafraîchit les données."""
    hass, data = call.hass, call.data
    coordinator, project_data = _find_project(hass, data[ATTR_PROJECT])
    _check_writable(project_data)
    _check_maintainer(project_data.project)
    project_id = project_data.project.id
    project = (await _fresh_project(coordinator, project_id)).project
    item_id = _resolve(project, kind, data[kind]) if kind and kind in data else None
    try:
        new_id = await action(coordinator.client, project_id, project, item_id)
    except _MemberExists as err:
        raise _error("member_exists", name=str(err)) from err
    except ValueError as err:
        raise _error("invalid_value", error=err) from err
    except (CospendConnectionError, CospendMaintenanceError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="manage_unreachable"
        ) from err
    except Exception as err:  # noqa: BLE001 - traduite pour l'utilisateur
        raise await _translate(hass, coordinator, err) from err
    finally:
        # Même après une erreur, la requête a pu aboutir côté Nextcloud : on resynchronise.
        await coordinator.async_refresh()
    return {
        "project": project_id,
        "id": new_id if new_id is not None else item_id,
        **(extra or {}),
    }


def _register(hass: HomeAssistant, name: str, schema: dict[Any, Any], handler: Handler) -> None:
    hass.services.async_register(
        DOMAIN,
        name,
        handler,
        schema=vol.Schema({vol.Required(ATTR_PROJECT): _REF, **schema}),
        supports_response=SupportsResponse.OPTIONAL,
    )


# ------------------------------------------------------------------ membres


async def _add_member(call: ServiceCall) -> ServiceResponse:
    d = call.data
    extra: dict[str, Any] = {"reactivated": False}

    async def run(client, pid, project, _):  # type: ignore[no-untyped-def]
        wanted = d[ATTR_NAME].casefold()
        existing = next((m for m in project.members if m.name.casefold() == wanted), None)
        if existing is None:
            return await client.create_member(
                pid,
                d[ATTR_NAME],
                weight=d.get(ATTR_WEIGHT, 1.0),
                color=d.get(ATTR_COLOR),
                activated=d.get(ATTR_ACTIVE, True),
            )
        if existing.activated:
            raise _MemberExists(existing.name)
        # Un membre désactivé garde son nom : on le réactive au lieu d'échouer.
        await client.update_member(
            pid,
            existing.id,
            name=existing.name,
            weight=d.get(ATTR_WEIGHT, existing.weight),
            color=d.get(ATTR_COLOR, _hex(existing.color)),
            activated=True,
        )
        extra["reactivated"] = True
        return existing.id

    return await _manage(call, None, run, extra)


async def _update_member(call: ServiceCall) -> ServiceResponse:
    d = call.data

    async def run(client, pid, project, item):  # type: ignore[no-untyped-def]
        # Cospend remplace le membre en entier : un champ absent est remis à zéro (la couleur
        # change au hasard). On renvoie donc l'état actuel complété par les changements.
        current = project.member(item)
        await client.update_member(
            pid,
            item,
            name=d.get(ATTR_NEW_NAME, current.name),
            weight=d.get(ATTR_WEIGHT, current.weight),
            color=d.get(ATTR_COLOR, _hex(current.color)),
            activated=d.get(ATTR_ACTIVE, current.activated),
        )

    return await _manage(call, ATTR_MEMBER, run)


async def _delete_member(call: ServiceCall) -> ServiceResponse:
    async def run(client, pid, project, item):  # type: ignore[no-untyped-def]
        await client.delete_member(pid, item)

    return await _manage(call, ATTR_MEMBER, run)


# ------------------------------------------------- catégories et modes de paiement


def _labelled(kind: str, attr: str) -> tuple[Handler, Handler, Handler]:
    """Trois services (ajout, modification, suppression) pour une catégorie ou un mode."""

    async def add(call: ServiceCall) -> ServiceResponse:
        d = call.data

        async def run(client, pid, project, _):  # type: ignore[no-untyped-def]
            create = client.create_category if kind == "category" else client.create_payment_mode
            return await create(
                pid, d[ATTR_NAME], icon=d.get(ATTR_ICON, ""), color=d.get(ATTR_COLOR, DEFAULT_COLOR)
            )

        return await _manage(call, None, run)

    async def update(call: ServiceCall) -> ServiceResponse:
        d = call.data

        async def run(client, pid, project, item):  # type: ignore[no-untyped-def]
            change = client.update_category if kind == "category" else client.update_payment_mode
            items = project.categories if kind == "category" else project.payment_modes
            current = next(i for i in items if i.id == item)
            # Cospend exige nom, icône et couleur à chaque modification.
            await change(
                pid,
                item,
                name=d.get(ATTR_NEW_NAME, current.name),
                icon=d.get(ATTR_ICON, current.icon or ""),
                color=d.get(ATTR_COLOR, current.color or DEFAULT_COLOR),
            )

        return await _manage(call, attr, run)

    async def delete(call: ServiceCall) -> ServiceResponse:
        async def run(client, pid, project, item):  # type: ignore[no-untyped-def]
            remove = client.delete_category if kind == "category" else client.delete_payment_mode
            await remove(pid, item)

        return await _manage(call, attr, run)

    return add, update, delete


# ------------------------------------------------------------------ devises


async def _add_currency(call: ServiceCall) -> ServiceResponse:
    d = call.data

    async def run(client, pid, project, _):  # type: ignore[no-untyped-def]
        return await client.create_currency(pid, d[ATTR_NAME], d[ATTR_RATE])

    return await _manage(call, None, run)


async def _update_currency(call: ServiceCall) -> ServiceResponse:
    d = call.data

    async def run(client, pid, project, item):  # type: ignore[no-untyped-def]
        current = next(c for c in project.currencies if c.id == item)
        await client.update_currency(
            pid,
            item,
            name=d.get(ATTR_NEW_NAME, current.name),
            rate=d.get(ATTR_RATE, current.exchange_rate),
        )

    return await _manage(call, ATTR_CURRENCY, run)


async def _delete_currency(call: ServiceCall) -> ServiceResponse:
    async def run(client, pid, project, item):  # type: ignore[no-untyped-def]
        await client.delete_currency(pid, item)

    return await _manage(call, ATTR_CURRENCY, run)


def async_setup_manage_services(hass: HomeAssistant) -> None:
    """Enregistre les services de gestion de la structure d'un projet."""
    member_edit = {
        vol.Optional(ATTR_NEW_NAME): _NAME,
        vol.Optional(ATTR_WEIGHT): _WEIGHT,
        vol.Optional(ATTR_COLOR): _COLOR,
        vol.Optional(ATTR_ACTIVE): cv.boolean,
    }
    _register(
        hass,
        "add_member",
        {
            vol.Required(ATTR_NAME): _NAME,
            vol.Optional(ATTR_WEIGHT): _WEIGHT,
            vol.Optional(ATTR_COLOR): _COLOR,
            vol.Optional(ATTR_ACTIVE): cv.boolean,
        },
        _add_member,
    )
    _register(
        hass, "update_member", {vol.Required(ATTR_MEMBER): _REF, **member_edit}, _update_member
    )
    _register(hass, "delete_member", {vol.Required(ATTR_MEMBER): _REF}, _delete_member)

    for kind, attr in (("category", ATTR_CATEGORY), ("payment_mode", ATTR_PAYMENT_MODE)):
        add, update, delete = _labelled(kind, attr)
        _register(
            hass,
            f"add_{kind}",
            {
                vol.Required(ATTR_NAME): _NAME,
                vol.Optional(ATTR_ICON): _ICON,
                vol.Optional(ATTR_COLOR): _COLOR,
            },
            add,
        )
        _register(
            hass,
            f"update_{kind}",
            {
                vol.Required(attr): _REF,
                vol.Optional(ATTR_NEW_NAME): _NAME,
                vol.Optional(ATTR_ICON): _ICON,
                vol.Optional(ATTR_COLOR): _COLOR,
            },
            update,
        )
        _register(hass, f"delete_{kind}", {vol.Required(attr): _REF}, delete)

    _register(
        hass,
        "add_currency",
        {vol.Required(ATTR_NAME): _CODE, vol.Required(ATTR_RATE): _rate},
        _add_currency,
    )
    _register(
        hass,
        "update_currency",
        {
            vol.Required(ATTR_CURRENCY): _REF,
            vol.Optional(ATTR_NEW_NAME): _CODE,
            vol.Optional(ATTR_RATE): _rate,
        },
        _update_currency,
    )
    _register(hass, "delete_currency", {vol.Required(ATTR_CURRENCY): _REF}, _delete_currency)
