"""Statistiques calculées localement à partir des dépenses.

Le calcul se fait sur les dépenses déjà en mémoire plutôt que par l'API de statistiques de
Cospend : il fonctionne hors ligne, accepte n'importe quel filtre et donne des totaux cohérents
avec la liste affichée. Les remboursements (catégorie −11) sont exclus par défaut : ils déplacent
de l'argent entre membres sans être une dépense.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, tzinfo

from .models import Bill

REIMBURSEMENT_CATEGORY = -11


@dataclass(frozen=True, slots=True)
class StatsFilter:
    """Critères de sélection ; un critère ``None`` ne filtre rien.

    ``ts_min`` et ``ts_max`` sont des horodatages Unix (bornes incluses).
    """

    ts_min: int | None = None
    ts_max: int | None = None
    payer_id: int | None = None
    ower_id: int | None = None
    category_id: int | None = None
    payment_mode_id: int | None = None
    amount_min: float | None = None
    amount_max: float | None = None
    include_reimbursements: bool = False

    def accepts(self, bill: Bill) -> bool:
        if bill.deleted:
            return False
        if not self.include_reimbursements and bill.category_id == REIMBURSEMENT_CATEGORY:
            return False
        if self.ts_min is not None and bill.timestamp < self.ts_min:
            return False
        if self.ts_max is not None and bill.timestamp > self.ts_max:
            return False
        if self.payer_id is not None and bill.payer_id != self.payer_id:
            return False
        if self.ower_id is not None and self.ower_id not in bill.ower_ids:
            return False
        if self.category_id is not None and bill.category_id != self.category_id:
            return False
        if self.payment_mode_id is not None and bill.payment_mode_id != self.payment_mode_id:
            return False
        if self.amount_min is not None and bill.amount < self.amount_min:
            return False
        return not (self.amount_max is not None and bill.amount > self.amount_max)


@dataclass(frozen=True, slots=True)
class MemberTotals:
    """Ce qu'un membre a payé et ce qu'il a consommé (sa part des dépenses)."""

    id: int
    paid: float
    spent: float

    @property
    def balance(self) -> float:
        return self.paid - self.spent


@dataclass(frozen=True, slots=True)
class MonthTotal:
    month: str
    total: float
    by_category: dict[int, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Flow:
    """Une part d'argent : ``payer_id`` a payé, pour ``ower_id``, dans ``category_id``."""

    payer_id: int
    category_id: int
    ower_id: int
    amount: float


@dataclass(frozen=True, slots=True)
class Statistics:
    total: float
    count: int
    members: tuple[MemberTotals, ...]
    categories: dict[int, float]
    payment_modes: dict[int, float]
    months: tuple[MonthTotal, ...]
    flows: tuple[Flow, ...]


def compute_statistics(
    bills: Iterable[Bill], flt: StatsFilter | None = None, tz: tzinfo = UTC
) -> Statistics:
    """Totaux des dépenses retenues par ``flt``, les mois étant lus dans le fuseau ``tz``."""
    flt = flt or StatsFilter()
    paid: dict[int, float] = defaultdict(float)
    spent: dict[int, float] = defaultdict(float)
    categories: dict[int, float] = defaultdict(float)
    modes: dict[int, float] = defaultdict(float)
    months: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    flows: dict[tuple[int, int, int], float] = defaultdict(float)
    total = 0.0
    count = 0
    for bill in bills:
        if not flt.accepts(bill):
            continue
        count += 1
        total += bill.amount
        paid[bill.payer_id] += bill.amount
        categories[bill.category_id] += bill.amount
        modes[bill.payment_mode_id] += bill.amount
        month = datetime.fromtimestamp(bill.timestamp, tz).strftime("%Y-%m")
        months[month][bill.category_id] += bill.amount
        weight = sum(ower.weight for ower in bill.owers)
        if weight <= 0:
            continue
        for ower in bill.owers:
            share = bill.amount * ower.weight / weight
            spent[ower.id] += share
            flows[(bill.payer_id, bill.category_id, ower.id)] += share
    member_ids = sorted(set(paid) | set(spent))
    return Statistics(
        total=total,
        count=count,
        members=tuple(MemberTotals(m, paid.get(m, 0.0), spent.get(m, 0.0)) for m in member_ids),
        categories=dict(categories),
        payment_modes=dict(modes),
        months=tuple(
            MonthTotal(month, sum(by.values()), dict(by)) for month, by in sorted(months.items())
        ),
        flows=tuple(Flow(p, c, o, a) for (p, c, o), a in sorted(flows.items())),
    )
