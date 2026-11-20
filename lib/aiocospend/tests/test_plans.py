"""Tests des plans d'écriture (sans réseau) et de la détection de ce qui est déjà fait."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from test_grouping import make

from aiocospend import (
    CospendAuthenticationError,
    CospendBadRequestError,
    CospendConnectionError,
    CospendMaintenanceError,
    CospendServerError,
    CospendSSLError,
    Project,
    SplitMode,
    fields_applied,
    is_transient,
    plan_add_bill,
    plan_delete_bill,
    plan_update_bill,
    spec_matches_bill,
)

WHEN = datetime(2026, 11, 18, 21, 30, 5, tzinfo=UTC)


@pytest.fixture
def project() -> Project:
    raw = json.loads((Path(__file__).parent / "fixtures" / "project.json").read_text("utf-8"))
    return Project.from_api(raw.get("ocs", {}).get("data", raw))


def test_plan_is_json_serializable_and_ordered(project: Project) -> None:
    plan = plan_add_bill(
        project,
        what="Soirée",
        amount="100",
        payer="util1",
        when=WHEN,
        owers=[12, 13, 14],
        mode=SplitMode.PERCENT,
        shares={12: "50", 13: "30", 14: "20"},
        category="Restaurant",
    )
    assert json.loads(json.dumps(plan)) == plan
    assert [spec["amount"] for spec in plan] == ["50", "30", "20"]
    assert [spec["payed_for"] for spec in plan] == [[12], [13], [14]]
    assert {spec["timestamp"] for spec in plan} == {int(WHEN.timestamp())}
    assert {spec["comment"] for spec in plan} == {""}


def test_spec_matches_only_the_same_bill(project: Project) -> None:
    (spec,) = plan_add_bill(project, what="Pizza", amount="20", payer=12, when=WHEN)
    bill = make(
        50,
        (12, 13, 14),
        what="Pizza",
        amount=20.0,
        payer_id=12,
        timestamp=int(WHEN.timestamp()),
        comment="",
    )
    assert spec_matches_bill(spec, bill)
    for change in (
        {"what": "Autre"},
        {"amount": 21.0},
        {"payer_id": 13},
        {"timestamp": bill.timestamp + 1},
        {"comment": "x"},
    ):
        assert not spec_matches_bill(spec, replace(bill, **change))
    assert not spec_matches_bill(
        spec,
        make(51, 12, what="Pizza", amount=20.0, payer_id=12, timestamp=bill.timestamp, comment=""),
    )


def test_fields_applied() -> None:
    bill = make(1, 12, what="A", amount=10.0, category_id=35)
    assert fields_applied({"what": "A", "amount": "10", "category_id": 35}, bill)
    assert not fields_applied({"what": "B"}, bill)
    assert not fields_applied({"amount": "10.5"}, bill)
    assert fields_applied({}, bill)


def test_fields_applied_repeat() -> None:
    bill = replace(make(1, 12), repeat="m", repeat_freq=2, repeat_until=None, repeat_all_active=1)
    assert fields_applied(
        {"repeat": "m", "repeat_freq": 2, "repeat_until": "", "repeat_all_active": 1}, bill
    )
    assert not fields_applied({"repeat": "w"}, bill)
    assert not fields_applied({"repeat_until": "2027-01-31"}, bill)


def test_update_and_delete_plans(project: Project) -> None:
    bills = {b.id: b for b in (make(31, 13), make(32, 12), make(33, 14))}
    plan = plan_update_bill(project, bills, 32, what="Groupe")
    assert [bill_id for bill_id, _ in plan] == [31, 32, 33]
    assert all(fields == {"what": "Groupe"} for _, fields in plan)
    assert plan_delete_bill(bills, 32) == [31, 32, 33]
    assert plan_delete_bill(bills, 32, whole_group=False) == [32]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (CospendConnectionError("x"), True),
        (CospendMaintenanceError("x"), True),
        (CospendServerError("x"), True),
        (CospendSSLError("x"), False),
        (CospendAuthenticationError("x"), False),
        (CospendBadRequestError("x"), False),
        (ValueError("x"), False),
    ],
)
def test_is_transient(error: Exception, expected: bool) -> None:
    assert is_transient(error) is expected
