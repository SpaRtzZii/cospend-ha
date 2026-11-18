"""Tests du calcul de montants saisis comme expressions."""

from __future__ import annotations

from decimal import Decimal

import pytest

from aiocospend import ExpressionError, parse_amount


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12", "12.00"),
        ("12,5", "12.50"),
        ("12.5", "12.50"),
        ("1 + 2 * 3", "7.00"),
        ("(1 + 2) * 3", "9.00"),
        ("10 / 4", "2.50"),
        ("10 / 3", "3.33"),
        ("2 / 3", "0.67"),
        ("-5 + 10", "5.00"),
        ("2 × 3 ÷ 4", "1.50"),
        ("  7,25  ", "7.25"),
        ("0,005", "0.01"),
        ("((((2))))", "2.00"),
    ],
)
def test_expressions(text: str, expected: str) -> None:
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("value", [12, 12.5, Decimal("3.456")])
def test_numbers_are_rounded_to_cents(value) -> None:
    assert parse_amount(value) == Decimal(str(value)).quantize(Decimal("0.01"))


@pytest.mark.parametrize(
    "text",
    [
        "",
        "  ",
        "abc",
        "1 +",
        "(1 + 2",
        "1 + 2)",
        "1 / 0",
        "2 ** 3",
        "__import__('os')",
        "1;2",
        "1 2",
        "(" * 40 + "1" + ")" * 40,
        "9" * 300,
    ],
)
def test_invalid_expressions(text: str) -> None:
    with pytest.raises(ExpressionError):
        parse_amount(text)


def test_booleans_and_non_finite_are_rejected() -> None:
    with pytest.raises(ExpressionError):
        parse_amount(True)
    with pytest.raises(ExpressionError):
        parse_amount(float("nan"))
