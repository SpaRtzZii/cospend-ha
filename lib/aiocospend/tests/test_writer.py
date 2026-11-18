"""Tests de la création, modification et suppression de dépenses (faux serveur)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest
from fake_server import FakeCospend

from aiocospend import (
    CospendClient,
    CospendNotFoundError,
    PartialWriteError,
    Project,
    ResolutionError,
    SplitError,
    SplitMode,
    add_bill,
    delete_bill,
    update_bill,
)

PROJECT = "teste"
WHEN = datetime(2026, 11, 18, 21, 30, 5, tzinfo=UTC)
TS = int(WHEN.timestamp())


@pytest.fixture
def project() -> Project:
    raw = json.loads((Path(__file__).parent / "fixtures" / "project.json").read_text("utf-8"))
    return Project.from_api(raw.get("ocs", {}).get("data", raw))


def stored(fake: FakeCospend, bill_id: int) -> dict:
    return fake.bills[bill_id]


async def current_bills(client: CospendClient) -> dict:
    page = await client.get_bills(PROJECT)
    return {b.id: b for b in page.bills}


# --------------------------------------------------------------------- création


async def test_add_even_bill(client, fake, project) -> None:
    ids = await add_bill(
        client,
        project,
        what="Courses",
        amount="12,5 + 7.5",
        payer="util1",
        when=WHEN,
        category="courses",
        payment_mode="Liquide",
    )
    assert len(ids) == 1
    bill = stored(fake, ids[0])
    assert bill["amount"] == 20.0
    assert bill["payer_id"] == 12
    assert bill["owerIds"] == [12, 13, 14]  # tous les membres actifs
    assert bill["categoryid"] == 35
    assert (bill["paymentmodeid"], bill["paymentmode"]) == (17, "b")
    assert (bill["timestamp"], bill["date"]) == (TS, "2026-11-18")


async def test_add_custom_split_makes_one_bill_per_participant(client, fake, project) -> None:
    ids = await add_bill(
        client,
        project,
        what="Soirée",
        amount="600",
        payer=13,
        when=WHEN,
        owers=["util1", "util2", "util3"],
        mode=SplitMode.AMOUNTS,
        shares={"util1": "150", "util2": "200", "util3": "250"},
    )
    assert len(ids) == 3
    assert [stored(fake, i)["amount"] for i in ids] == [150.0, 200.0, 250.0]
    assert [stored(fake, i)["owerIds"] for i in ids] == [[12], [13], [14]]
    # même seconde, même titre, même commentaire : le regroupement strict les retrouve
    assert len({(stored(fake, i)["timestamp"], stored(fake, i)["what"]) for i in ids}) == 1


async def test_add_percent_split(client, fake, project) -> None:
    ids = await add_bill(
        client,
        project,
        what="Cadeau",
        amount="100",
        payer=12,
        when=WHEN,
        owers=[12, 13, 14],
        mode=SplitMode.PERCENT,
        shares={12: "33.33", 13: "33.33", 14: "33.34"},
    )
    assert sum(stored(fake, i)["amount"] for i in ids) == pytest.approx(100.0)


async def test_add_with_foreign_currency(client, fake, project) -> None:
    ids = await add_bill(
        client,
        project,
        what="Hôtel",
        amount="100",
        payer=12,
        when=WHEN,
        currency="USD",
        exchange_rate=D("0.92"),
        comment="nuit",
    )
    bill = stored(fake, ids[0])
    assert bill["amount"] == 92.0
    assert bill["comment"] == "nuit #USD:100@0.92"


async def test_add_with_unknown_currency_needs_a_rate(client, project) -> None:
    with pytest.raises(ResolutionError, match="devise inconnue"):
        await add_bill(client, project, what="x", amount="1", payer=12, when=WHEN, currency="XYZ")


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"payer": "inconnu"}, ResolutionError),
        ({"owers": ["util1", "nobody"]}, ResolutionError),
        ({"category": "nope"}, ResolutionError),
        ({"payment_mode": "nope"}, ResolutionError),
        ({"repeat": "zz"}, ResolutionError),
        ({"mode": SplitMode.AMOUNTS}, SplitError),
        ({"amount": "0"}, SplitError),
        ({"what": "  "}, ValueError),
    ],
)
async def test_add_rejects_bad_input_before_calling_the_server(
    client, fake, project, kwargs, error
) -> None:
    base = {"what": "x", "amount": "10", "payer": 12, "when": WHEN}
    before = len(fake.requests)
    with pytest.raises(error):
        await add_bill(client, project, **{**base, **kwargs})
    assert not [r for r in fake.requests[before:] if r.method == "POST"]


async def test_add_naive_datetime_is_rejected(client, project) -> None:
    with pytest.raises(ValueError, match="fuseau"):
        await add_bill(client, project, what="x", amount="1", payer=12, when=datetime(2026, 1, 1))


async def test_partial_failure_reports_what_was_created(client, fake, project, monkeypatch) -> None:
    real = client.create_bill
    calls = 0

    async def flaky(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("coupure")
        return await real(*args, **kwargs)

    monkeypatch.setattr(client, "create_bill", flaky)
    with pytest.raises(PartialWriteError) as info:
        await add_bill(
            client,
            project,
            what="x",
            amount="30",
            payer=12,
            when=WHEN,
            owers=[12, 13, 14],
            mode=SplitMode.PERCENT,
            shares={12: "50", 13: "25", 14: "25"},
        )
    assert len(info.value.done) == 1
    assert isinstance(info.value.cause, RuntimeError)
    assert calls == 2  # pas de nouvel essai, pas de rattrapage


async def test_first_failure_is_raised_as_is(client, project, monkeypatch) -> None:
    async def boom(*args, **kwargs):
        raise RuntimeError("non")

    monkeypatch.setattr(client, "create_bill", boom)
    with pytest.raises(RuntimeError):
        await add_bill(client, project, what="x", amount="1", payer=12, when=WHEN)


# ----------------------------------------------------------------- modification


async def test_update_single_bill(client, fake, project) -> None:
    bills = await current_bills(client)
    ids = await update_bill(
        client,
        project,
        bills,
        30,
        what="Renommée",
        amount="5,5",
        payer="util2",
        category="Loyer",
        payment_mode="Chèque",
        comment="ok",
    )
    assert ids == [30]
    bill = stored(fake, 30)
    assert (bill["what"], bill["amount"], bill["payer_id"]) == ("Renommée", 5.5, 13)
    assert (bill["categoryid"], bill["paymentmodeid"], bill["paymentmode"]) == (37, 18, "f")
    assert bill["comment"] == "ok"


async def test_update_sends_only_what_changed(client, fake, project) -> None:
    bills = await current_bills(client)
    await update_bill(client, project, bills, 30, comment="seul")
    request = next(r for r in reversed(fake.requests) if r.method == "PUT")
    assert request.form == {"comment": "seul"}


async def test_update_group_common_fields(client, fake, project) -> None:
    bills = await current_bills(client)
    ids = await update_bill(client, project, bills, 32, what="Groupe", category="Loyer")
    assert ids == [31, 32, 33]
    assert {stored(fake, i)["what"] for i in ids} == {"Groupe"}
    assert {stored(fake, i)["categoryid"] for i in ids} == {37}


async def test_update_group_split_is_refused(client, project) -> None:
    bills = await current_bills(client)
    with pytest.raises(SplitError, match="recrée"):
        await update_bill(client, project, bills, 31, amount="10")
    with pytest.raises(SplitError):
        await update_bill(client, project, bills, 31, owers=["util1"])


async def test_update_keeps_currency_tag_unless_the_amount_changes(client, fake, project) -> None:
    ids = await add_bill(
        client,
        project,
        what="Hôtel",
        amount="100",
        payer=12,
        when=WHEN,
        currency="USD",
        exchange_rate=D("0.92"),
    )
    bills = await current_bills(client)
    await update_bill(client, project, bills, ids[0], comment="nuit")
    assert stored(fake, ids[0])["comment"] == "nuit #USD:100@0.92"
    bills = await current_bills(client)  # état courant, comme le fait l'intégration
    await update_bill(client, project, bills, ids[0], amount="50")
    assert stored(fake, ids[0])["comment"] == "nuit"


async def test_update_unknown_bill_and_empty_update(client, project) -> None:
    bills = await current_bills(client)
    with pytest.raises(CospendNotFoundError):
        await update_bill(client, project, bills, 9999, what="x")
    with pytest.raises(ValueError, match="aucun champ"):
        await update_bill(client, project, bills, 30)


# ------------------------------------------------------------------ suppression


async def test_delete_single_bill_goes_to_trash(client, fake, project) -> None:
    bills = await current_bills(client)
    assert await delete_bill(client, PROJECT, bills, 30) == [30]
    assert stored(fake, 30)["deleted"] == 1


async def test_delete_whole_group(client, fake, project) -> None:
    bills = await current_bills(client)
    assert await delete_bill(client, PROJECT, bills, 32) == [31, 32, 33]
    assert all(stored(fake, i)["deleted"] == 1 for i in (31, 32, 33))


async def test_delete_only_one_bill_of_a_group(client, fake, project) -> None:
    bills = await current_bills(client)
    assert await delete_bill(client, PROJECT, bills, 32, whole_group=False) == [32]
    assert stored(fake, 31)["deleted"] == 0


async def test_delete_is_never_replayed(client, fake, project, monkeypatch) -> None:
    bills = await current_bills(client)
    real = client.delete_bill
    calls: list[int] = []

    async def flaky(project_id, bill_id, **kw):
        calls.append(bill_id)
        if len(calls) == 2:
            raise RuntimeError("coupure")
        return await real(project_id, bill_id, **kw)

    monkeypatch.setattr(client, "delete_bill", flaky)
    with pytest.raises(PartialWriteError) as info:
        await delete_bill(client, PROJECT, bills, 31)
    assert info.value.done == [31]
    assert calls == [31, 32]  # 33 n'est pas tenté, 32 n'est pas rejoué
    assert stored(fake, 31)["deleted"] == 1
    assert stored(fake, 33)["deleted"] == 0


async def test_delete_unknown_bill(client, project) -> None:
    with pytest.raises(CospendNotFoundError):
        await delete_bill(client, PROJECT, {}, 1)


async def test_foreign_currency_with_rate_one_is_a_plain_bill(client, fake, project) -> None:
    ids = await add_bill(
        client,
        project,
        what="x",
        amount="10",
        payer=12,
        when=WHEN,
        currency="EUR2",
        exchange_rate=D("1"),
        comment="c",
    )
    assert stored(fake, ids[0])["comment"] == "c"
    assert stored(fake, ids[0])["amount"] == 10.0
