"""Tests de la métadonnée de devise dans le commentaire."""

from __future__ import annotations

from decimal import Decimal as D

from aiocospend import ForeignAmount, join_comment, split_comment


def test_round_trip() -> None:
    foreign = ForeignAmount("USD", D("12.50"), D("0.92"))
    comment = join_comment("restaurant", foreign)
    assert comment == "restaurant #USD:12.5@0.92"
    assert split_comment(comment) == ("restaurant", foreign.__class__("USD", D("12.5"), D("0.92")))


def test_no_metadata() -> None:
    assert split_comment("simple") == ("simple", None)
    assert join_comment("simple", None) == "simple"


def test_replaces_existing_metadata() -> None:
    comment = join_comment("a #USD:1@2", ForeignAmount("GBP", D("3"), D("1.1")))
    assert comment == "a #GBP:3@1.1"


def test_metadata_alone() -> None:
    assert join_comment("", ForeignAmount("JPY", D("1000"), D("0.006"))) == "#JPY:1000@0.006"
    assert split_comment("#JPY:1000@0.006")[0] == ""


def test_names_with_spaces_and_symbols_and_decimal_commas() -> None:
    text, foreign = split_comment("repas #US Dollar:12,5@0,92")
    assert text == "repas"
    assert foreign == ForeignAmount("US Dollar", D("12.5"), D("0.92"))
    assert split_comment("#$:3@2")[1] == ForeignAmount("$", D("3"), D("2"))


def test_rate_one_writes_no_metadata() -> None:
    assert join_comment("a", ForeignAmount("EUR", D("5"), D("1"))) == "a"


def test_a_hash_in_the_comment_is_not_swallowed() -> None:
    text, foreign = split_comment("lot #12 #USD:5@2")
    assert (text, foreign) == ("lot #12", ForeignAmount("USD", D("5"), D("2")))
