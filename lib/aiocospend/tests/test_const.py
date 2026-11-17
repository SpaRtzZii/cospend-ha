"""Tests de base du paquet aiocospend."""

import aiocospend
from aiocospend import const


def test_version_and_minimum() -> None:
    assert aiocospend.__version__ == "0.1.0"
    assert aiocospend.MIN_COSPEND_VERSION == "1.6.1"


def test_reimbursement_category_is_native_id() -> None:
    assert const.REIMBURSEMENT_CATEGORY_ID == -11


def test_repeat_codes_include_default() -> None:
    assert const.REPEAT_NONE in const.REPEAT_CODES
