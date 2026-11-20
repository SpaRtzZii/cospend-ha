"""Statistiques locales : filtres, parts, mois, flux."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from aiocospend import Bill, StatsFilter, compute_statistics


def ts(year: int, month: int, day: int, hour: int = 12) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp())


def bill(
    id_: int,
    amount: float,
    payer: int,
    owers: dict[int, float],
    *,
    category: int = 0,
    mode: int = 0,
    timestamp: int | None = None,
    deleted: bool = False,
) -> Bill:
    return Bill.from_api(
        {
            "id": id_,
            "what": f"b{id_}",
            "amount": amount,
            "timestamp": timestamp or ts(2026, 11, 10),
            "date": "2026-11-10",
            "payer_id": payer,
            "owers": [{"id": m, "weight": w, "name": str(m)} for m, w in owers.items()],
            "categoryid": category,
            "paymentmodeid": mode,
            "deleted": int(deleted),
        }
    )


BILLS = [
    bill(1, 30, 1, {1: 1, 2: 1, 3: 1}, category=5, mode=2),
    bill(2, 20, 2, {1: 1, 2: 3}, category=6, timestamp=ts(2026, 10, 3)),
    bill(3, 10, 1, {2: 1}, category=-11),
    bill(4, 99, 1, {1: 1}, deleted=True),
]


def test_totals_exclude_reimbursements_and_deleted() -> None:
    stats = compute_statistics(BILLS)
    assert stats.count == 2
    assert stats.total == 50
    assert stats.categories == {5: 30, 6: 20}
    assert stats.payment_modes == {2: 30, 0: 20}


def test_member_paid_and_spent_use_weights() -> None:
    stats = compute_statistics(BILLS)
    by_id = {m.id: m for m in stats.members}
    assert by_id[1].paid == 30
    assert by_id[2].paid == 20
    assert by_id[1].spent == pytest.approx(10 + 5)
    assert by_id[2].spent == pytest.approx(10 + 15)
    assert by_id[3].spent == pytest.approx(10)
    assert sum(m.balance for m in stats.members) == pytest.approx(0)


def test_include_reimbursements() -> None:
    stats = compute_statistics(BILLS, StatsFilter(include_reimbursements=True))
    assert stats.count == 3
    assert stats.categories[-11] == 10


def test_filters() -> None:
    assert compute_statistics(BILLS, StatsFilter(payer_id=2)).total == 20
    assert compute_statistics(BILLS, StatsFilter(ower_id=3)).total == 30
    assert compute_statistics(BILLS, StatsFilter(category_id=6)).total == 20
    assert compute_statistics(BILLS, StatsFilter(payment_mode_id=2)).total == 30
    assert compute_statistics(BILLS, StatsFilter(amount_min=25)).total == 30
    assert compute_statistics(BILLS, StatsFilter(amount_max=25)).total == 20
    assert compute_statistics(BILLS, StatsFilter(ts_min=ts(2026, 11, 1))).total == 30
    assert compute_statistics(BILLS, StatsFilter(ts_max=ts(2026, 10, 31))).total == 20


def test_months_sorted_with_category_breakdown() -> None:
    stats = compute_statistics(BILLS)
    assert [m.month for m in stats.months] == ["2026-10", "2026-11"]
    assert stats.months[0].by_category == {6: 20}
    assert stats.months[1].total == 30


def test_month_is_read_in_given_timezone() -> None:
    # 31/10 23:30 UTC est déjà le 1er novembre à Paris.
    late = bill(1, 10, 1, {1: 1}, timestamp=ts(2026, 10, 31, 23) + 1800)
    assert compute_statistics([late]).months[0].month == "2026-10"
    paris = compute_statistics([late], tz=ZoneInfo("Europe/Paris"))
    assert paris.months[0].month == "2026-11"


def test_flows_add_up_to_total() -> None:
    stats = compute_statistics(BILLS)
    assert sum(f.amount for f in stats.flows) == pytest.approx(stats.total)
    assert any(f.payer_id == 2 and f.category_id == 6 and f.ower_id == 2 for f in stats.flows)


def test_bill_without_owers_counts_as_paid_only() -> None:
    stats = compute_statistics([bill(1, 12, 1, {})])
    assert stats.total == 12
    assert stats.flows == ()
    assert stats.members[0].spent == 0


def test_empty() -> None:
    stats = compute_statistics([])
    assert stats.total == 0 and stats.count == 0 and stats.months == ()
