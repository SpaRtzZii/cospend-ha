"""Tests des modèles sur des réponses réelles de Cospend 4.3.0 (jeux d'essai anonymisés)."""

import pytest
from fake_server import load_fixture

from aiocospend import (
    Bill,
    BillsPage,
    CospendResponseError,
    Project,
    ProjectStatistics,
    Settlement,
)


def test_project() -> None:
    project = Project.from_api(load_fixture("project.json"))
    assert project.id == "teste"
    assert [m.name for m in project.members] == ["util1", "util2", "util3"]
    assert project.members[0].color == (73, 154, 162)
    assert project.members[0].user_id is None
    assert project.access_level == 4
    assert project.can_write
    assert not project.is_archived
    assert project.currency_name is None
    assert {c.name for c in project.categories} >= {"Courses", "Restaurant"}
    assert [p.old_id for p in project.payment_modes][:2] == ["c", "b"]
    assert project.balance[12] == pytest.approx(683.333, abs=1e-3)
    assert project.member(13) is not None
    assert project.member(999) is None


def test_bills_page_keeps_server_semantics() -> None:
    page = BillsPage.from_api(load_fixture("bills_page.json"))
    assert page.nb_bills == 6
    assert page.all_bill_ids == (30, 31, 32, 33, 37, 38)
    assert page.timestamp == 1794779704
    reimbursement = next(b for b in page.bills if b.id == 37)
    assert reimbursement.category_id == -11
    assert reimbursement.what == "util3 → util1"
    assert reimbursement.ower_ids == (12,)
    assert reimbursement.project_id == "teste"


def test_custom_split_group_is_visible_in_raw_bills() -> None:
    page = BillsPage.from_api(load_fixture("bills_page.json"))
    group = [b for b in page.bills if b.what == "testfact"]
    assert len(group) == 3
    assert len({b.timestamp for b in group}) == 1
    assert sorted(b.ower_ids[0] for b in group) == [12, 13, 14]


def test_bill_without_project_id_in_incremental_listing() -> None:
    page = BillsPage.from_api(load_fixture("bills_lastchanged_page.json"))
    assert page.bills[0].project_id is None
    assert page.bills[0].comment == "apres"


def test_trash_page() -> None:
    page = BillsPage.from_api(load_fixture("trash_page.json"))
    assert page.bills[0].deleted is True
    assert page.bills[0].amount == -5


def test_single_bill() -> None:
    bill = Bill.from_api(load_fixture("bill.json"))
    assert bill.amount == 30
    assert bill.ower_ids == (12, 13)
    assert bill.payment_mode == "c"
    assert bill.payment_mode_id == 16


def test_statistics_ignores_localized_average_key() -> None:
    stats = ProjectStatistics.from_api(load_fixture("statistics.json"))
    assert stats.months == ("2026-11",)
    assert set(stats.monthly_paid) == {"2026-11"}  # « Moyenne par mois » est écartée
    assert stats.monthly_paid["2026-11"][0] == 1850  # la clé 0 est le total
    assert stats.category_stats == {36: 1250.0, 35: 600.0}
    assert set(stats.category_monthly[36]) == {"2026-11"}
    assert stats.category_member[35][13] == 600
    assert stats.stats[0].member.name == "util1"
    assert stats.stats[0].balance == pytest.approx(683.333, abs=1e-3)
    assert "membersPaidFor" in stats.raw


def test_settlement() -> None:
    settlement = Settlement.from_api(load_fixture("settlement.json"))
    assert [(t.from_member, t.to_member) for t in settlement.transactions] == [(14, 12), (13, 12)]
    assert settlement.transactions[0].amount == pytest.approx(666.6667, abs=1e-4)
    assert sum(settlement.balances.values()) == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (Bill, {"id": 1}),
        (BillsPage, {"bills": []}),
        (Project, {"name": "sans identifiant"}),
        (Settlement, {"transactions": [{"from": 1}]}),
    ],
)
def test_invalid_payloads_raise(model: type, data: dict) -> None:
    with pytest.raises(CospendResponseError):
        model.from_api(data)
