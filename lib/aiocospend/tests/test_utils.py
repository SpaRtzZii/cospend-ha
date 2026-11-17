"""Tests des utilitaires."""

from decimal import Decimal

import pytest

from aiocospend import compare_versions, format_amount, normalize_url, parse_version


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("cloud.exemple.org", "https://cloud.exemple.org"),
        ("  https://cloud.exemple.org/  ", "https://cloud.exemple.org"),
        ("https://cloud.exemple.org/index.php/apps/cospend/p/teste", "https://cloud.exemple.org"),
        (
            "https://cloud.exemple.org/nextcloud/index.php/login",
            "https://cloud.exemple.org/nextcloud",
        ),
        ("https://cloud.exemple.org/nextcloud/", "https://cloud.exemple.org/nextcloud"),
        ("http://192.168.1.10:8080/status.php", "http://192.168.1.10:8080"),
        ("https://cloud.exemple.org/ocs/v2.php/apps/cospend", "https://cloud.exemple.org"),
        ("https://cloud.exemple.org?x=1#frag", "https://cloud.exemple.org"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "ftp://exemple.org", "https://"])
def test_normalize_url_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_url(raw)


def test_parse_version() -> None:
    assert parse_version("4.3.0") == (4, 3, 0)
    assert parse_version("4.3.0-beta.1") == (4, 3, 0)
    with pytest.raises(ValueError):
        parse_version("abc")


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [("4.3.0", "1.6.1", 1), ("1.6.1", "1.6.1", 0), ("1.6", "1.6.0", 0), ("1.5.9", "1.6.1", -1)],
)
def test_compare_versions(left: str, right: str, expected: int) -> None:
    assert compare_versions(left, right) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, "5"),
        (5.0, "5"),
        (5.5, "5.5"),
        (0.1, "0.1"),
        (-5, "-5"),
        (100, "100"),
        ("12.50", "12.5"),
        (Decimal("1E+2"), "100"),
        (666.67, "666.67"),
        (0, "0"),
    ],
)
def test_format_amount(value: int | float | str | Decimal, expected: str) -> None:
    assert format_amount(value) == expected


@pytest.mark.parametrize("value", ["abc", float("nan"), float("inf"), ""])
def test_format_amount_rejects(value: float | str) -> None:
    with pytest.raises(ValueError):
        format_amount(value)
