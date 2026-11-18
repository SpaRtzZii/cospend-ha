"""Capteurs Cospend : totaux, soldes et répartitions pour suivre et analyser un projet."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .coordinator import CospendConfigEntry, CospendCoordinator, ProjectData
from .entity import CospendEntity

PARALLEL_UPDATES = 0

# Codes ISO 4217 pour lesquels la classe « monétaire » de Home Assistant est utilisée.
_ISO_CURRENCIES = frozenset(
    "EUR USD GBP CHF CAD AUD NZD JPY CNY SEK NOK DKK PLN CZK HUF RON BGN HRK ISK TRY BRL MXN "
    "INR KRW SGD HKD ZAR".split()
)
_CURRENCY_ALIASES = {
    "euro": "EUR",
    "euros": "EUR",
    "€": "EUR",
    "dollar": "USD",
    "dollars": "USD",
    "$": "USD",
    "livre": "GBP",
    "pound": "GBP",
    "£": "GBP",
    "franc suisse": "CHF",
    "yen": "JPY",
    "¥": "JPY",
}


def currency_unit(name: str | None) -> tuple[str | None, bool]:
    """Unité d'affichage d'un montant et indication « code ISO reconnu ».

    Cospend stocke la devise du projet en texte libre (« euro », « EUR », vide…).
    """
    if not name or not name.strip():
        return None, False
    text = name.strip()
    code = _CURRENCY_ALIASES.get(text.lower(), text.upper())
    if code in _ISO_CURRENCIES:
        return code, True
    return text, False


# Noms des éléments sans identifiant propre dans Cospend, selon la langue de Home Assistant.
_BUILTIN_NAMES = {
    "fr": {"category": {0: "Sans catégorie", -11: "Remboursement"}, "payment_mode": {0: "Aucun"}},
    "en": {"category": {0: "No category", -11: "Reimbursement"}, "payment_mode": {0: "None"}},
}


def _builtin_name(kind: str, item_id: int, language: str) -> str:
    names = _BUILTIN_NAMES.get(language.split("-")[0], _BUILTIN_NAMES["en"])[kind]
    return names.get(item_id, f"#{item_id}")


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


@dataclass(frozen=True, kw_only=True)
class CospendSensorDescription(SensorEntityDescription):
    """Description d'un capteur : comment lire sa valeur dans les données du projet."""

    value_fn: Callable[[ProjectData, int | None], StateType]
    attrs_fn: Callable[[ProjectData], dict[str, Any]] | None = None
    monetary: bool = False
    placeholder: str | None = None


def _member_stat(data: ProjectData, member_id: int | None, field: str) -> float | None:
    if data.statistics is None:
        return None
    for stat in data.statistics.stats:
        if stat.member.id == member_id:
            return _rounded(getattr(stat, field))
    return 0.0


def _month_spent(data: ProjectData, _: int | None) -> float | None:
    if data.statistics is None:
        return None
    return _rounded(data.statistics.paid_in(dt_util.now().strftime("%Y-%m")))


def _last_bill_title(data: ProjectData, _: int | None) -> str | None:
    bill = data.last_bill
    return bill.what if bill else None


def _last_bill_amount(data: ProjectData, _: int | None) -> float | None:
    bill = data.last_bill
    return _rounded(bill.amount) if bill else None


def _last_bill_attributes(data: ProjectData) -> dict[str, Any]:
    bill = data.last_bill
    if bill is None:
        return {}
    payer = data.project.member(bill.payer_id)
    owers = [m.name for m in (data.project.member(i) for i in bill.ower_ids) if m]
    return {
        "bill_id": bill.id,
        "date": bill.date,
        "amount": bill.amount,
        "payer": payer.name if payer else None,
        "owers": owers,
        "category_id": bill.category_id,
        "payment_mode_id": bill.payment_mode_id,
        "comment": bill.comment,
    }


PROJECT_SENSORS: tuple[CospendSensorDescription, ...] = (
    CospendSensorDescription(
        key="bills_count",
        translation_key="bills_count",
        icon="mdi:receipt-text",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data, _: data.project.nb_bills,
    ),
    CospendSensorDescription(
        key="total_spent",
        translation_key="total_spent",
        icon="mdi:cash-multiple",
        monetary=True,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data, _: _rounded(data.project.total_spent),
    ),
    CospendSensorDescription(
        key="month_spent",
        translation_key="month_spent",
        icon="mdi:calendar-month",
        monetary=True,
        state_class=SensorStateClass.TOTAL,
        value_fn=_month_spent,
    ),
    CospendSensorDescription(
        key="last_bill",
        translation_key="last_bill",
        icon="mdi:receipt-text-clock",
        value_fn=_last_bill_title,
        attrs_fn=_last_bill_attributes,
    ),
    CospendSensorDescription(
        key="last_bill_amount",
        translation_key="last_bill_amount",
        icon="mdi:cash",
        monetary=True,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_last_bill_amount,
    ),
)

MEMBER_SENSORS: tuple[CospendSensorDescription, ...] = (
    CospendSensorDescription(
        key="member_balance",
        translation_key="member_balance",
        placeholder="member",
        icon="mdi:scale-balance",
        monetary=True,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data, member_id: _rounded(data.project.balance.get(member_id or 0, 0.0)),
    ),
    CospendSensorDescription(
        key="member_paid",
        translation_key="member_paid",
        placeholder="member",
        icon="mdi:cash-plus",
        monetary=True,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data, member_id: _member_stat(data, member_id, "paid"),
    ),
    CospendSensorDescription(
        key="member_spent",
        translation_key="member_spent",
        placeholder="member",
        icon="mdi:cash-minus",
        monetary=True,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda data, member_id: _member_stat(data, member_id, "spent"),
    ),
)

CATEGORY_SENSOR = CospendSensorDescription(
    key="category_total",
    translation_key="category_total",
    placeholder="category",
    icon="mdi:shape",
    monetary=True,
    state_class=SensorStateClass.TOTAL,
    value_fn=lambda data, category_id: (
        None
        if data.statistics is None
        else _rounded(data.statistics.category_stats.get(category_id or 0, 0.0))
    ),
)

PAYMENT_MODE_SENSOR = CospendSensorDescription(
    key="payment_mode_total",
    translation_key="payment_mode_total",
    placeholder="payment_mode",
    icon="mdi:credit-card",
    monetary=True,
    state_class=SensorStateClass.TOTAL,
    entity_registry_enabled_default=False,
    value_fn=lambda data, mode_id: (
        None
        if data.statistics is None
        else _rounded(data.statistics.payment_mode_stats.get(mode_id or 0, 0.0))
    ),
)


def planned_sensors(
    data: ProjectData, language: str
) -> Iterator[tuple[CospendSensorDescription, int | None, str | None]]:
    """Capteurs attendus pour un projet : (description, identifiant, nom de l'élément)."""
    for description in PROJECT_SENSORS:
        yield description, None, None
    for member in data.project.members:
        for description in MEMBER_SENSORS:
            yield description, member.id, member.name

    category_names = {c.id: c.name for c in data.project.categories}
    extra_categories = set(data.statistics.category_stats) if data.statistics else set()
    for category_id in [*category_names, *sorted(extra_categories - set(category_names))]:
        name = category_names.get(category_id) or _builtin_name("category", category_id, language)
        yield CATEGORY_SENSOR, category_id, name

    mode_names = {m.id: m.name for m in data.project.payment_modes}
    extra_modes = set(data.statistics.payment_mode_stats) if data.statistics else set()
    for mode_id in [*mode_names, *sorted(extra_modes - set(mode_names))]:
        name = mode_names.get(mode_id) or _builtin_name("payment_mode", mode_id, language)
        yield PAYMENT_MODE_SENSOR, mode_id, name


def sensor_unique_id(entry_id: str, project_id: str, key: str, subject_id: int | None) -> str:
    suffix = "" if subject_id is None else f"_{subject_id}"
    return f"{entry_id}_{project_id}_{key}{suffix}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CospendConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crée les capteurs, puis ajoute ceux des membres ou catégories qui apparaissent ensuite."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new_sensors() -> None:
        new: list[CospendSensor] = []
        for project_id, data in coordinator.data.items():
            for description, subject_id, subject_name in planned_sensors(
                data, hass.config.language
            ):
                unique_id = sensor_unique_id(
                    entry.entry_id, project_id, description.key, subject_id
                )
                if unique_id in known:
                    continue
                known.add(unique_id)
                new.append(
                    CospendSensor(
                        coordinator, project_id, description, unique_id, subject_id, subject_name
                    )
                )
        if new:
            async_add_entities(new)

    _add_new_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_sensors))

    async_add_entities(
        CospendQueueSensor(coordinator, project_id) for project_id in coordinator.data
    )


class CospendSensor(CospendEntity, SensorEntity):
    """Capteur d'un projet, d'un membre, d'une catégorie ou d'un mode de paiement."""

    entity_description: CospendSensorDescription

    def __init__(
        self,
        coordinator: CospendCoordinator,
        project_id: str,
        description: CospendSensorDescription,
        unique_id: str,
        subject_id: int | None,
        subject_name: str | None,
    ) -> None:
        super().__init__(coordinator, project_id)
        self.entity_description = description
        self._subject_id = subject_id
        self._attr_unique_id = unique_id
        if description.placeholder and subject_name is not None:
            self._attr_translation_placeholders = {description.placeholder: subject_name}
        if description.monetary:
            unit, is_iso = currency_unit(coordinator.data[project_id].project.currency_name)
            self._attr_native_unit_of_measurement = unit
            self._attr_suggested_display_precision = 2
            if is_iso:
                self._attr_device_class = SensorDeviceClass.MONETARY

    @property
    def native_value(self) -> StateType:
        data = self.project_data
        if data is None:
            return None
        return self.entity_description.value_fn(data, self._subject_id)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self.project_data
        attrs_fn = self.entity_description.attrs_fn
        if data is None or attrs_fn is None:
            return None
        return attrs_fn(data)


class CospendQueueSensor(CospendEntity, SensorEntity):
    """Nombre d'écritures en attente d'envoi (Cospend injoignable) ou bloquées, par projet."""

    _attr_translation_key = "pending_operations"
    _attr_icon = "mdi:cloud-upload-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: CospendCoordinator, project_id: str) -> None:
        super().__init__(coordinator, project_id)
        self._attr_unique_id = sensor_unique_id(
            coordinator.config_entry.entry_id, project_id, "pending_operations", None
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Doit réagir à la file elle-même, y compris quand Cospend ne répond plus.
        self.async_on_remove(self.coordinator.queue.async_add_listener(self.async_write_ha_state))

    @property
    def available(self) -> bool:
        return self.project_data is not None

    @property
    def native_value(self) -> int:
        return len(self.coordinator.queue.for_project(self._project_id))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        operations = self.coordinator.queue.for_project(self._project_id)
        return {
            "blocked": sum(op.status == "blocked" for op in operations),
            "operations": [op.summary() for op in operations],
        }
