"""Répartition d'une dépense entre participants.

Cospend ne sait faire qu'une répartition égale (pondérée par les poids des membres). Pour une
répartition par montants ou par pourcentages, Cowspent crée **une dépense par participant** ;
nous faisons de même. Tous les calculs se font en centimes entiers, avec la méthode du plus
fort reste : la somme des parts est toujours égale au total.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

_CENT = Decimal("0.01")


class SplitError(ValueError):
    """Répartition impossible ou incohérente."""


class SplitMode(StrEnum):
    EVEN = "even"
    AMOUNTS = "amounts"
    PERCENT = "percent"


@dataclass(frozen=True, slots=True)
class SplitPart:
    """Une dépense à créer : ``amount`` payé pour ``ower_ids``."""

    ower_ids: tuple[int, ...]
    amount: Decimal


def to_cents(amount: Decimal) -> int:
    cents = amount / _CENT
    if cents != cents.to_integral_value():
        raise SplitError(f"montant à plus de 2 décimales : {amount}")
    return int(cents)


def from_cents(cents: int) -> Decimal:
    return (Decimal(cents) * _CENT).quantize(_CENT)


def allocate(total_cents: int, ratios: Sequence[Decimal]) -> list[int]:
    """Partage ``total_cents`` proportionnellement à ``ratios`` (plus fort reste)."""
    if not ratios or any(r < 0 for r in ratios):
        raise SplitError("proportions invalides")
    denominator = sum(ratios)
    if denominator <= 0:
        raise SplitError("la somme des proportions doit être positive")
    exact = [Decimal(total_cents) * r / denominator for r in ratios]
    base = [int(x.to_integral_value(rounding=ROUND_FLOOR)) for x in exact]
    remainder = total_cents - sum(base)
    order = sorted(range(len(ratios)), key=lambda i: (-(exact[i] - base[i]), i))
    for i in order[:remainder]:
        base[i] += 1
    return base


def compute_split(
    total: Decimal,
    mode: SplitMode,
    ower_ids: Sequence[int],
    values: Mapping[int, Decimal] | None = None,
) -> list[SplitPart]:
    """Calcule les dépenses à créer.

    * ``EVEN`` : une seule dépense pour tous les participants (le serveur répartit) ;
    * ``AMOUNTS`` : ``values`` donne le montant de chaque participant, leur somme doit être égale
      au total ; une dépense par participant ;
    * ``PERCENT`` : ``values`` donne le pourcentage de chacun (somme = 100) ; une dépense par
      participant, arrondie au centime sans jamais perdre ni créer de centime.
    """
    if total <= 0:
        raise SplitError("le montant doit être positif")
    ids = list(dict.fromkeys(ower_ids))
    if not ids:
        raise SplitError("au moins un participant est requis")
    if mode is SplitMode.EVEN:
        return [SplitPart(tuple(ids), total)]

    if not values:
        raise SplitError("les parts sont requises pour ce mode de répartition")
    if set(values) != set(ids):
        raise SplitError("les parts doivent correspondre exactement aux participants")
    total_cents = to_cents(total)

    if mode is SplitMode.AMOUNTS:
        cents = [to_cents(values[i]) for i in ids]
        if any(c < 0 for c in cents):
            raise SplitError("un montant ne peut pas être négatif")
        if sum(cents) != total_cents:
            raise SplitError(
                f"la somme des parts ({from_cents(sum(cents))}) "
                f"ne correspond pas au total ({total})"
            )
    else:
        percents = [values[i] for i in ids]
        if any(p < 0 for p in percents):
            raise SplitError("un pourcentage ne peut pas être négatif")
        if sum(percents) != Decimal(100):
            raise SplitError(f"la somme des pourcentages doit faire 100 (reçu {sum(percents)})")
        cents = allocate(total_cents, percents)

    return [SplitPart((i,), from_cents(c)) for i, c in zip(ids, cents, strict=True) if c > 0]
