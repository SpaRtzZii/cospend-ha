"""Regroupement strict des dépenses issues d'une répartition personnalisée.

Cowspent émule la répartition par montants ou pourcentages avec une dépense par participant.
Pour les présenter (et les modifier ou supprimer) comme une seule dépense, on les regroupe selon
un critère volontairement strict : au moins deux dépenses ayant **toutes** les mêmes valeurs
pour le titre, la seconde, le payeur, la catégorie, le mode de paiement, le commentaire et la
récurrence, et chacune un seul participant, tous différents. Dans le doute, on ne regroupe pas.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import Bill


@dataclass(frozen=True, slots=True)
class GroupedBill:
    """Une ou plusieurs dépenses présentées comme une seule."""

    bills: tuple[Bill, ...]

    @property
    def is_group(self) -> bool:
        return len(self.bills) > 1

    @property
    def ids(self) -> tuple[int, ...]:
        return tuple(bill.id for bill in self.bills)

    @property
    def first(self) -> Bill:
        return self.bills[0]

    @property
    def total(self) -> float:
        return round(sum(bill.amount for bill in self.bills), 2)

    @property
    def ower_ids(self) -> tuple[int, ...]:
        seen: dict[int, None] = {}
        for bill in self.bills:
            seen.update(dict.fromkeys(bill.ower_ids))
        return tuple(seen)


def _key(bill: Bill) -> tuple:
    return (
        bill.what,
        bill.timestamp,
        bill.payer_id,
        bill.category_id,
        bill.payment_mode,
        bill.payment_mode_id,
        bill.comment,
        bill.repeat,
        bill.repeat_freq,
        bill.repeat_until,
        bill.repeat_all_active,
    )


def group_bills(bills: Iterable[Bill]) -> list[GroupedBill]:
    """Regroupe les dépenses (ordre d'apparition conservé, une entrée par groupe)."""
    buckets: dict[tuple, list[Bill]] = {}
    for bill in bills:
        buckets.setdefault(_key(bill), []).append(bill)

    groups: dict[int, GroupedBill] = {}
    for members in buckets.values():
        ower_ids = [bill.ower_ids for bill in members]
        groupable = (
            len(members) >= 2
            and all(len(ids) == 1 for ids in ower_ids)
            and len({ids[0] for ids in ower_ids}) == len(members)
        )
        if groupable:
            ordered = tuple(sorted(members, key=lambda b: b.id))
            groups[ordered[0].id] = GroupedBill(ordered)
        else:
            for bill in members:
                groups[bill.id] = GroupedBill((bill,))
    return [groups[key] for key in sorted(groups)]


def find_group(bills: Iterable[Bill], bill_id: int) -> GroupedBill | None:
    """Groupe contenant la dépense ``bill_id`` (ou ``None`` si elle est inconnue)."""
    for group in group_bills(bills):
        if bill_id in group.ids:
            return group
    return None
