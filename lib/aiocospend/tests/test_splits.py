"""Tests de la répartition entre participants."""

from __future__ import annotations

from decimal import Decimal as D

import pytest

from aiocospend import SplitError, SplitMode, compute_split
from aiocospend.splits import allocate


def test_even_is_a_single_bill() -> None:
    parts = compute_split(D("30"), SplitMode.EVEN, [12, 13, 14, 12])
    assert [(p.ower_ids, p.amount) for p in parts] == [((12, 13, 14), D("30"))]


def test_amounts_make_one_bill_per_participant() -> None:
    parts = compute_split(
        D("600"), SplitMode.AMOUNTS, [12, 13, 14], {12: D("150"), 13: D("200"), 14: D("250")}
    )
    assert [(p.ower_ids, p.amount) for p in parts] == [
        ((12,), D("150.00")),
        ((13,), D("200.00")),
        ((14,), D("250.00")),
    ]


def test_amounts_must_add_up() -> None:
    with pytest.raises(SplitError, match="ne correspond pas"):
        compute_split(D("100"), SplitMode.AMOUNTS, [12, 13], {12: D("60"), 13: D("30")})


def test_percent_never_loses_a_cent() -> None:
    parts = compute_split(
        D("100"), SplitMode.PERCENT, [12, 13, 14], {12: D("33.33"), 13: D("33.33"), 14: D("33.34")}
    )
    assert sum(p.amount for p in parts) == D("100.00")
    assert [p.amount for p in parts] == [D("33.33"), D("33.33"), D("33.34")]


def test_percent_must_make_100() -> None:
    with pytest.raises(SplitError, match="100"):
        compute_split(D("10"), SplitMode.PERCENT, [12, 13], {12: D("50"), 13: D("40")})


def test_zero_share_is_dropped() -> None:
    parts = compute_split(D("10"), SplitMode.PERCENT, [12, 13], {12: D("100"), 13: D("0")})
    assert [(p.ower_ids, p.amount) for p in parts] == [((12,), D("10.00"))]


def test_shares_must_match_participants() -> None:
    with pytest.raises(SplitError, match="correspondre"):
        compute_split(D("10"), SplitMode.AMOUNTS, [12, 13], {12: D("10")})
    with pytest.raises(SplitError, match="requises"):
        compute_split(D("10"), SplitMode.PERCENT, [12, 13], None)


@pytest.mark.parametrize("total", [D("0"), D("-1")])
def test_total_must_be_positive(total: D) -> None:
    with pytest.raises(SplitError):
        compute_split(total, SplitMode.EVEN, [12])


def test_no_participant() -> None:
    with pytest.raises(SplitError):
        compute_split(D("1"), SplitMode.EVEN, [])


@pytest.mark.parametrize(
    ("total", "ratios", "expected"),
    [
        (100, [D(1), D(1), D(1)], [34, 33, 33]),
        (1, [D(1), D(1)], [1, 0]),
        (10, [D(0), D(1)], [0, 10]),
        (1000, [D("0.1"), D("0.2"), D("0.7")], [100, 200, 700]),
    ],
)
def test_allocate(total: int, ratios: list[D], expected: list[int]) -> None:
    result = allocate(total, ratios)
    assert result == expected
    assert sum(result) == total


def test_allocate_always_sums_to_total() -> None:
    for total in range(0, 200, 7):
        ratios = [D(3), D(5), D(11), D(1)]
        assert sum(allocate(total, ratios)) == total
