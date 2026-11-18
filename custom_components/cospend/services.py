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
    add_bill,
    delete_bill,
    update_bill,
)
from aiocospend.const import REPEAT_CODES

from .const import DOMAIN
from .coordinator import CospendCoordinator, ProjectData

_LOGGER = logging.getLogger(__name__)

SERVICE_ADD_BILL = "add_bill"
SERVICE_UPDATE_BILL = "update_bill"
SERVICE_DELETE_BILL = "delete_bill"

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
    }
)

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


async def _run(
    hass: HomeAssistant,
    coordinator: CospendCoordinator,
    action: Callable[[], Awaitable[list[int]]],
) -> list[int]:
    """Exécute l'écriture, traduit les erreurs, puis relit le projet (événements compris)."""
    try:
        return await action()
    except (ResolutionError, SplitError, ExpressionError, ValueError) as err:
        raise _error("invalid_value", error=err) from err
    except CospendNotFoundError as err:
        raise _error("bill_not_found", error=err) from err
    except PartialWriteError as err:
        await coordinator.async_refresh()
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="partial_write",
            translation_placeholders={
                "done": ", ".join(map(str, err.done)),
                "error": str(err.cause),
            },
        ) from err
    except CospendAuthenticationError as err:
        coordinator.config_entry.async_start_reauth(hass)
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed") from err
    except CospendForbiddenError as err:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="forbidden") from err
    except CospendError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="request_failed",
            translation_placeholders={"error": str(err)},
        ) from err


def _response(project_id: str, bill_ids: list[int]) -> ServiceResponse:
    return {"project": project_id, "bill_ids": bill_ids}


async def _async_add_bill(call: ServiceCall) -> ServiceResponse:
    hass, data = call.hass, call.data
    coordinator, project_data = _find_project(hass, data[ATTR_PROJECT])
    _check_writable(project_data)
    project = project_data.project
    when = data.get(ATTR_DATE) or dt_util.now().replace(microsecond=0)

    ids = await _run(
        hass,
        coordinator,
        lambda: add_bill(
            coordinator.client,
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
        ),
    )
    await coordinator.async_refresh()
    return _response(project.id, ids)


async def _async_update_bill(call: ServiceCall) -> ServiceResponse:
    hass, data = call.hass, call.data
    coordinator, project_data = _find_project(hass, data[ATTR_PROJECT])
    _check_writable(project_data)
    await coordinator.async_refresh()  # état le plus récent avant de regrouper
    project_data = coordinator.data[project_data.project.id]

    ids = await _run(
        hass,
        coordinator,
        lambda: update_bill(
            coordinator.client,
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
        ),
    )
    await coordinator.async_refresh()
    return _response(project_data.project.id, ids)


async def _async_delete_bill(call: ServiceCall) -> ServiceResponse:
    hass, data = call.hass, call.data
    coordinator, project_data = _find_project(hass, data[ATTR_PROJECT])
    _check_writable(project_data)
    await coordinator.async_refresh()
    project_data = coordinator.data[project_data.project.id]

    ids = await _run(
        hass,
        coordinator,
        lambda: delete_bill(
            coordinator.client,
            project_data.project.id,
            project_data.bills,
            data[ATTR_BILL_ID],
            whole_group=data[ATTR_WHOLE_GROUP],
        ),
    )
    await coordinator.async_refresh()
    return _response(project_data.project.id, ids)


def async_setup_services(hass: HomeAssistant) -> None:
    """Enregistre les services (une seule fois, au démarrage de l'intégration)."""
    for name, handler, schema in (
        (SERVICE_ADD_BILL, _async_add_bill, _ADD_SCHEMA),
        (SERVICE_UPDATE_BILL, _async_update_bill, _UPDATE_SCHEMA),
        (SERVICE_DELETE_BILL, _async_delete_bill, _DELETE_SCHEMA),
    ):
        hass.services.async_register(
            DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.OPTIONAL
        )
