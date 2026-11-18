"""Tests du regroupement strict des dépenses à répartition personnalisée."""

from __future__ import annotations

from dataclasses import replace

from aiocospend import Bill, Ower, find_group, group_bills


def make(bill_id: int, ower: int | tuple[int, ...] = 12, **kw) -> Bill:
    owers = (ower,) if isinstance(ower, int) else ower
    base = Bill(
        id=bill_id,
        what="testfact",
        amount=100.0,
        comment="",
        timestamp=1_794_777_105,
        date="2026-11-15",
        payer_id=13,
        owers=tuple(Ower(i, 1.0, f"u{i}", True) for i in owers),
        repeat="n",
        repeat_freq=1,
        repeat_until=None,
        repeat_all_active=0,
        payment_mode="c",
        payment_mode_id=16,
        category_id=35,
        deleted=False,
        last_changed=1,
    )
    return replace(base, **kw)


def test_three_matching_bills_make_one_group() -> None:
    groups = group_bills([make(31, 13), make(32, 12), make(33, 14)])
    assert len(groups) == 1
    assert groups[0].ids == (31, 32, 33)
    assert groups[0].is_group
    assert groups[0].total == 300.0
    assert groups[0].ower_ids == (13, 12, 14)


def test_a_single_bill_is_not_a_group() -> None:
    (group,) = group_bills([make(1)])
    assert not group.is_group


def test_any_difference_prevents_grouping() -> None:
    for change in (
        {"what": "autre"},
        {"timestamp": 1_794_777_106},
        {"payer_id": 12},
        {"category_id": 36},
        {"payment_mode_id": 17},
        {"comment": "x"},
        {"repeat": "m"},
        {"repeat_until": "2027-01-01"},
    ):
        groups = group_bills([make(1, 12), make(2, 13, **change)])
        assert [g.is_group for g in groups] == [False, False], change


def test_bills_with_several_owers_are_never_grouped() -> None:
    groups = group_bills([make(1, (12, 13)), make(2, 14)])
    assert [g.is_group for g in groups] == [False, False]


def test_same_ower_twice_is_not_grouped() -> None:
    groups = group_bills([make(1, 12), make(2, 12)])
    assert [g.is_group for g in groups] == [False, False]


def test_find_group() -> None:
    bills = [make(1, 12), make(2, 13), make(9, 12, what="seule")]
    assert find_group(bills, 2).ids == (1, 2)
    assert find_group(bills, 9).ids == (9,)
    assert find_group(bills, 404) is None
