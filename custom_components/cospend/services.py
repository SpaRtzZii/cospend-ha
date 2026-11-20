"""Services ``cospend.add_bill``, ``cospend.update_bill`` et ``cospend.delete_bill``."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from aiocospend import (
    CospendAuthenticationError,
    CospendError,
    CospendForbiddenError,
    CospendNotFoundError,
    ExpressionError,
    PartialWriteError,
    ResolutionError,
    SplitError,
    SplitMode,
    execute_creates,
    execute_deletes,
    execute_updates,
    is_transient,
    plan_add_bill,
    plan_delete_bill,
    plan_update_bill,
)
from aiocospend.const import REPEAT_CODES

from .const import DOMAIN
from .coordinator import CospendCoordinator, ProjectData
from .queue import (
    KIND_ADD,
    KIND_DELETE,
    KIND_UPDATE,
    STATUS_BLOCKED,
    QueuedOperation,
    async_flush,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_ADD_BILL = "add_bill"
SERVICE_UPDATE_BILL = "update_bill"
SERVICE_DELETE_BILL = "delete_bill"
SERVICE_RETRY_QUEUED = "retry_queued"
SERVICE_DISCARD_QUEUED = "discard_queued"

ATTR_PROJECT = "project"
ATTR_BILL_ID = "bill_id"
ATTR_TITLE = "title"
ATTR_AMOUNT = "amount"
ATTR_PAYER = "payer"
ATTR_OWERS = "owers"
ATTR_SPLIT_MODE = "split_mode"
ATTR_SHARES = "shares"
ATTR_CATEGORY = "category"
ATTR_PAYMENT_MODE = "payment_mode"
ATTR_DATE = "date"
ATTR_COMMENT = "comment"
ATTR_CURRENCY = "currency"
ATTR_EXCHANGE_RATE = "exchange_rate"
ATTR_REPEAT = "repeat"
ATTR_REPEAT_FREQUENCY = "repeat_frequency"
ATTR_REPEAT_UNTIL = "repeat_until"
ATTR_REPEAT_ALL_ACTIVE = "repeat_all_active"
ATTR_WHOLE_GROUP = "whole_group"
ATTR_OPERATION_ID = "operation_id"
ATTR_FORCE = "force"

_REF = vol.All(vol.Any(cv.string, int), vol.Coerce(str))
_NUMBER = vol.All(vol.Any(cv.string, int, float), vol.Coerce(str))


def _when(value: Any) -> datetime:
    """Date ou date et heure (fuseau de Home Assistant) ; une date seule prend l'heure actuelle."""
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value).strip()
        try:
            moment = cv.datetime(text)
        except vol.Invalid:
            day = cv.date(text)
            now = dt_util.now()
            moment = datetime.combine(day, now.timetz().replace(microsecond=0))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt_util.get_default_time_zone())
    return moment.replace(microsecond=0)


def _rate(value: Any) -> Decimal:
    try:
        rate = Decimal(str(value).replace(",", "."))
    except InvalidOperation as err:
        raise vol.Invalid("taux de change invalide") from err
    if not rate.is_finite() or rate <= 0:
        raise vol.Invalid("le taux de change doit être positif")
    return rate


def _repeat_until_or_clear(value: Any) -> str:
    """Date de fin de récurrence ; une chaîne vide la retire."""
    if value is None or str(value).strip() == "":
        return ""
    return cv.date(value).isoformat()


_ADD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROJECT): _REF,
        vol.Required(ATTR_TITLE): cv.string,
        vol.Required(ATTR_AMOUNT): _NUMBER,
        vol.Required(ATTR_PAYER): _REF,
        vol.Optional(ATTR_OWERS): vol.All(cv.ensure_list, [_REF]),
        vol.Optional(ATTR_SPLIT_MODE, default=SplitMode.EVEN.value): vol.In(
            [mode.value for mode in SplitMode]
        ),
        vol.Optional(ATTR_SHARES): {_REF: _NUMBER},
        vol.Optional(ATTR_CATEGORY): _REF,
        vol.Optional(ATTR_PAYMENT_MODE): _REF,
        vol.Optional(ATTR_DATE): _when,
        vol.Optional(ATTR_COMMENT, default=""): cv.string,
        vol.Optional(ATTR_CURRENCY): cv.string,
        vol.Optional(ATTR_EXCHANGE_RATE): _rate,
        vol.Optional(ATTR_REPEAT): vol.In(REPEAT_CODES),
        vol.Optional(ATTR_REPEAT_FREQUENCY): vol.All(vol.Coerce(int), vol.Range(min=1, max=999)),
        vol.Optional(ATTR_REPEAT_UNTIL): vol.All(cv.date, lambda d: d.isoformat()),
        vol.Optional(ATTR_REPEAT_ALL_ACTIVE): cv.boolean,
    }
)

_UPDATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROJECT): _REF,
        vol.Required(ATTR_BILL_ID): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_AMOUNT): _NUMBER,
        vol.Optional(ATTR_PAYER): _REF,
        vol.Optional(ATTR_OWERS): vol.All(cv.ensure_list, [_REF]),
        vol.Optional(ATTR_CATEGORY): _REF,
        vol.Optional(ATTR_PAYMENT_MODE): _REF,
        vol.Optional(ATTR_DATE): _when,
        vol.Optional(ATTR_COMMENT): cv.string,
        vol.Optional(ATTR_CURRENCY): cv.string,
        vol.Optional(ATTR_EXCHANGE_RATE): _rate,
        vol.Optional(ATTR_REPEAT): vol.In(REPEAT_CODES),
        vol.Optional(ATTR_REPEAT_FREQUENCY): vol.All(vol.Coerce(int), vol.Range(min=1, max=999)),
        vol.Optional(ATTR_REPEAT_UNTIL): _repeat_until_or_clear,
        vol.Optional(ATTR_REPEAT_ALL_ACTIVE): cv.boolean,
    }
)

_RETRY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_OPERATION_ID): cv.string,
        vol.Optional(ATTR_FORCE, default=False): cv.boolean,
    }
)

_DISCARD_SCHEMA = vol.Schema({vol.Required(ATTR_OPERATION_ID): cv.string})

_DELETE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROJECT): _REF,
        vol.Required(ATTR_BILL_ID): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_WHOLE_GROUP, default=True): cv.boolean,
    }
)


def _error(key: str, **placeholders: Any) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={k: str(v) for k, v in placeholders.items()},
    )


def _find_project(hass: HomeAssistant, ref: str) -> tuple[CospendCoordinator, ProjectData]:
    """Projet suivi dont l'identifiant (ou, à défaut, le nom) est ``ref``."""
    by_id: list[tuple[CospendCoordinator, ProjectData]] = []
    by_name: list[tuple[CospendCoordinator, ProjectData]] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        coordinator: CospendCoordinator = entry.runtime_data
        for project_id, data in (coordinator.data or {}).items():
            if project_id == ref:
                by_id.append((coordinator, data))
            elif data.project.name.casefold() == ref.casefold():
                by_name.append((coordinator, data))
    matches = by_id or by_name
    if not matches:
        raise _error("project_not_found", project=ref)
    if len(matches) > 1:
        raise _error("project_ambiguous", project=ref)
    return matches[0]


def _check_writable(data: ProjectData) -> None:
    if data.project.is_archived:
        raise _error("project_archived", project=data.project.name)
    if not data.project.can_write:
        raise _error("project_read_only", project=data.project.name)


def _plan(build: Callable[[], Any]) -> Any:
    """Calcule un plan (sans réseau) en traduisant les erreurs de saisie."""
    try:
        return build()
    except CospendNotFoundError as err:
        raise _error("bill_not_found", error=err) from err
    except (ResolutionError, SplitError, ExpressionError, ValueError) as err:
        raise _error("invalid_value", error=err) from err


def _response(
    project_id: str, bill_ids: list[int], op: QueuedOperation | None = None
) -> ServiceResponse:
    return {
        "project": project_id,
        "bill_ids": bill_ids,
        "queued": op is not None,
        "operation_id": op.id if op else None,
    }


async def _translate(
    hass: HomeAssistant, coordinator: CospendCoordinator, err: Exception
) -> HomeAssistantError:
    """Erreur de Cospend non passagère, traduite pour l'utilisateur."""
    if isinstance(err, CospendNotFoundError):
        return _error("bill_not_found", error=err)
    if isinstance(err, CospendAuthenticationError):
        coordinator.config_entry.async_start_reauth(hass)
        return HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed")
    if isinstance(err, CospendForbiddenError):
        return HomeAssistantError(translation_domain=DOMAIN, translation_key="forbidden")
    if isinstance(err, CospendError):
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="request_failed",
            translation_placeholders={"error": str(err)},
        )
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="request_failed",
        translation_placeholders={"error": str(err)},
    )


async def _perform(
    hass: HomeAssistant,
    coordinator: CospendCoordinator,
    project_id: str,
    *,
    kind: str,
    title: str,
    plan: list[Any],
    base: dict[str, int | None] | None,
    execute: Callable[[list[Any]], Awaitable[list[int]]],
) -> ServiceResponse:
    """Exécute un plan, ou le met en file d'attente si Cospend est injoignable."""
    queue = coordinator.queue

    async def enqueue(done: list[int], ambiguous: bool) -> ServiceResponse:
        op = QueuedOperation.new(
            kind, project_id, title, plan, base=base, done=done, ambiguous=ambiguous
        )
        await queue.async_enqueue(op)
        return _response(project_id, list(done), op)

    # Ordre conservé : rien ne passe devant une opération déjà en attente, et inutile
    # d'attendre un délai dépassé quand la dernière lecture a déjà échoué.
    if queue.for_project(project_id) or not coordinator.last_update_success:
        return await enqueue([], ambiguous=False)

    try:
        ids = await execute(plan)
    except PartialWriteError as err:
        if is_transient(err.cause):
            return await enqueue(list(err.done), ambiguous=True)
        await coordinator.async_refresh()
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="partial_write",
            translation_placeholders={
                "done": ", ".join(map(str, err.done)),
                "error": str(err.cause),
            },
        ) from err
    except Exception as err:  # noqa: BLE001 - traduite ci-dessous
        if is_transient(err):
            return await enqueue([], ambiguous=True)
        raise await _translate(hass, coordinator, err) from err
    await coordinator.async_refresh()
    return _response(project_id, ids)


async def _async_add_bill(call: ServiceCall) -> ServiceResponse:
    hass, data = call.hass, call.data
    coordinator, project_data = _find_project(hass, data[ATTR_PROJECT])
    _check_writable(project_data)
    project = project_data.project
    when = data.get(ATTR_DATE) or dt_util.now().replace(microsecond=0)

    plan = _plan(
        lambda: plan_add_bill(
            project,
            what=data[ATTR_TITLE],
            amount=data[ATTR_AMOUNT],
            payer=data[ATTR_PAYER],
            when=when,
            owers=data.get(ATTR_OWERS),
            mode=SplitMode(data[ATTR_SPLIT_MODE]),
            shares=data.get(ATTR_SHARES),
            comment=data[ATTR_COMMENT],
            category=data.get(ATTR_CATEGORY),
            payment_mode=data.get(ATTR_PAYMENT_MODE),
            currency=data.get(ATTR_CURRENCY),
            exchange_rate=data.get(ATTR_EXCHANGE_RATE),
            repeat=data.get(ATTR_REPEAT),
            repeat_freq=data.get(ATTR_REPEAT_FREQUENCY),
            repeat_until=data.get(ATTR_REPEAT_UNTIL),
            repeat_all_active=(
                int(data[ATTR_REPEAT_ALL_ACTIVE]) if ATTR_REPEAT_ALL_ACTIVE in data else None
            ),
        )
    )
    return await _perform(
        hass,
        coordinator,
        project.id,
        kind=KIND_ADD,
        title=data[ATTR_TITLE],
        plan=plan,
        base=None,
        execute=lambda specs: execute_creates(coordinator.client, project.id, specs),
    )


async def _fresh_project(coordinator: CospendCoordinator, project_id: str) -> ProjectData:
    """État le plus récent possible (l'ancien si Cospend est injoignable)."""
    if coordinator.last_update_success:
        await coordinator.async_refresh()
    return coordinator.data[project_id]


def _bases(
    coordinator: CospendCoordinator, project_data: ProjectData, bill_ids: list[int]
) -> dict[str, int | None]:
    """Dernière modification de chaque dépense visée.

    ``None`` quand une opération déjà en attente vise cette dépense (opérations enchaînées).
    """
    project_id = project_data.project.id
    return {
        str(bill_id): (
            None
            if coordinator.queue.touches_bill(project_id, bill_id)
            else project_data.bills[bill_id].last_changed
        )
        for bill_id in bill_ids
        if bill_id in project_data.bills
    }


async def _async_update_bill(call: ServiceCall) -> ServiceResponse:
    hass, data = call.hass, call.data
    coordinator, project_data = _find_project(hass, data[ATTR_PROJECT])
    _check_writable(project_data)
    project_data = await _fresh_project(coordinator, project_data.project.id)

    plan = _plan(
        lambda: plan_update_bill(
            project_data.project,
            project_data.bills,
            data[ATTR_BILL_ID],
            what=data.get(ATTR_TITLE),
            amount=data.get(ATTR_AMOUNT),
            payer=data.get(ATTR_PAYER),
            owers=data.get(ATTR_OWERS),
            when=data.get(ATTR_DATE),
            comment=data.get(ATTR_COMMENT),
            category=data.get(ATTR_CATEGORY),
            payment_mode=data.get(ATTR_PAYMENT_MODE),
            currency=data.get(ATTR_CURRENCY),
            exchange_rate=data.get(ATTR_EXCHANGE_RATE),
            repeat=data.get(ATTR_REPEAT),
            repeat_freq=data.get(ATTR_REPEAT_FREQUENCY),
            repeat_until=data.get(ATTR_REPEAT_UNTIL),
            repeat_all_active=(
                int(data[ATTR_REPEAT_ALL_ACTIVE]) if ATTR_REPEAT_ALL_ACTIVE in data else None
            ),
        )
    )
    project_id = project_data.project.id
    first = project_data.bills[plan[0][0]]
    return await _perform(
        hass,
        coordinator,
        project_id,
        kind=KIND_UPDATE,
        title=data.get(ATTR_TITLE) or first.what,
        plan=[[bill_id, fields] for bill_id, fields in plan],
        base=_bases(coordinator, project_data, [bill_id for bill_id, _ in plan]),
        execute=lambda items: execute_updates(coordinator.client, project_id, items),
    )


async def _async_delete_bill(call: ServiceCall) -> ServiceResponse:
    hass, data = call.hass, call.data
    coordinator, project_data = _find_project(hass, data[ATTR_PROJECT])
    _check_writable(project_data)
    project_data = await _fresh_project(coordinator, project_data.project.id)

    ids = _plan(
        lambda: plan_delete_bill(
            project_data.bills, data[ATTR_BILL_ID], whole_group=data[ATTR_WHOLE_GROUP]
        )
    )
    project_id = project_data.project.id
    return await _perform(
        hass,
        coordinator,
        project_id,
        kind=KIND_DELETE,
        title=project_data.bills[ids[0]].what,
        plan=ids,
        base=_bases(coordinator, project_data, ids),
        execute=lambda items: execute_deletes(coordinator.client, project_id, items),
    )


def _queues(hass: HomeAssistant) -> list[CospendCoordinator]:
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]


async def _async_retry_queued(call: ServiceCall) -> ServiceResponse:
    """Remet des opérations bloquées en attente (avec ``force``, sans contrôle de conflit)."""
    operation_id = call.data.get(ATTR_OPERATION_ID)
    force = call.data[ATTR_FORCE]
    retried: list[str] = []
    for coordinator in _queues(call.hass):
        for op in list(coordinator.queue.operations):
            if op.status != STATUS_BLOCKED or operation_id not in (None, op.id):
                continue
            await coordinator.queue.async_retry(op, force=force)
            retried.append(op.id)
    if operation_id and not retried:
        raise _error("operation_not_found", operation=operation_id)
    for coordinator in _queues(call.hass):
        await async_flush(coordinator)
    return {"retried": retried}


async def _async_discard_queued(call: ServiceCall) -> ServiceResponse:
    """Abandonne une opération en attente ou bloquée (rien n'est annulé sur Cospend)."""
    operation_id = call.data[ATTR_OPERATION_ID]
    for coordinator in _queues(call.hass):
        op = coordinator.queue.get(operation_id)
        if op is not None:
            await coordinator.queue.async_discard(op)
            return {"discarded": op.id, "bill_ids_already_done": list(op.done)}
    raise _error("operation_not_found", operation=operation_id)


def async_setup_services(hass: HomeAssistant) -> None:
    """Enregistre les services (une seule fois, au démarrage de l'intégration)."""
    for name, handler, schema in (
        (SERVICE_ADD_BILL, _async_add_bill, _ADD_SCHEMA),
        (SERVICE_UPDATE_BILL, _async_update_bill, _UPDATE_SCHEMA),
        (SERVICE_DELETE_BILL, _async_delete_bill, _DELETE_SCHEMA),
        (SERVICE_RETRY_QUEUED, _async_retry_queued, _RETRY_SCHEMA),
        (SERVICE_DISCARD_QUEUED, _async_discard_queued, _DISCARD_SCHEMA),
    ):
        hass.services.async_register(
            DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL
        )
