"""Plan de remboursement local."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aiocospend import Project, ResolutionError, Transaction, resolve_category, suggest_settlement


def test_two_debtors_one_creditor() -> None:
    plan = suggest_settlement({12: 683.33, 13: -16.67, 14: -666.66})
    assert plan == (Transaction(14, 12, 666.66), Transaction(13, 12, 16.67))


def test_everything_is_settled() -> None:
    balances = {1: 50.0, 2: 30.0, 3: -45.5, 4: -34.5}
    plan = suggest_settlement(balances)
    net = {m: 0 for m in balances}
    for t in plan:
        net[t.from_member] -= t.amount
        net[t.to_member] += t.amount
    assert all(abs(net[m] - balances[m]) < 0.005 for m in balances)
    assert len(plan) <= len(balances) - 1


def test_balanced_project_needs_nothing() -> None:
    assert suggest_settlement({1: 0.0, 2: 0.001, 3: -0.002}) == ()
    assert suggest_settlement({}) == ()


def test_is_deterministic() -> None:
    balances = {1: 10.0, 2: 10.0, 3: -10.0, 4: -10.0}
    assert suggest_settlement(balances) == suggest_settlement(dict(reversed(balances.items())))


def test_reimbursement_category_is_accepted() -> None:
    raw = json.loads((Path(__file__).parent / "fixtures" / "project.json").read_text("utf-8"))
    project = Project.from_api(raw.get("ocs", {}).get("data", raw))
    assert resolve_category(project, -11) == -11
    assert resolve_category(project, "-11") == -11
    with pytest.raises(ResolutionError):
        resolve_category(project, -12)
