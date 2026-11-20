"""Tests du client contre le faux serveur Cospend."""

from __future__ import annotations

import aiohttp
import pytest
from fake_server import API, FakeCospend

from aiocospend import (
    CospendAuthenticationError,
    CospendBadRequestError,
    CospendClient,
    CospendConnectionError,
    CospendMaintenanceError,
    CospendNotFoundError,
    CospendResponseError,
    CospendVersionError,
)

PROJECT = "teste"


def last_request(fake: FakeCospend, method: str):
    return next(r for r in reversed(fake.requests) if r.method == method)


# ---------------------------------------------------------------- connexion


async def test_check_connection(client: CospendClient) -> None:
    info = await client.check_connection()
    assert info.version == "4.3.0"
    assert not info.federation_enabled


async def test_check_connection_rejects_old_version(
    client: CospendClient, fake: FakeCospend
) -> None:
    fake.version = "1.5.0"
    with pytest.raises(CospendVersionError):
        await client.check_connection()


async def test_check_connection_without_cospend_app(
    client: CospendClient, fake: FakeCospend
) -> None:
    fake.cospend_installed = False
    with pytest.raises(CospendVersionError):
        await client.check_connection()


async def test_wrong_password(fake: FakeCospend, session: aiohttp.ClientSession) -> None:
    bad = CospendClient(session, fake.url, fake.username, "mauvais", timeout=5)
    with pytest.raises(CospendAuthenticationError) as caught:
        await bad.check_connection()
    assert caught.value.status == 401


async def test_maintenance(client: CospendClient, fake: FakeCospend) -> None:
    fake.maintenance = True
    with pytest.raises(CospendMaintenanceError):
        await client.get_projects()


async def test_unreachable_server(session: aiohttp.ClientSession) -> None:
    unreachable = CospendClient(session, "http://127.0.0.1:9", "u", "p", timeout=2)
    with pytest.raises(CospendConnectionError):
        await unreachable.get_projects()


async def test_non_json_response(fake: FakeCospend, session: aiohttp.ClientSession) -> None:
    # Une adresse qui ne répond pas en OCS (page HTML, mauvaise URL) est détectée.
    wrong = CospendClient(session, f"{fake.url}/html", fake.username, fake.password, timeout=5)
    with pytest.raises(CospendResponseError):
        await wrong.get_server_info()


async def test_base_url_is_normalized(fake: FakeCospend, session: aiohttp.ClientSession) -> None:
    messy = CospendClient(session, f"{fake.url}/index.php/apps/cospend/", "admin", "secret")
    assert messy.base_url == fake.url
    assert (await messy.get_projects())[0].id == PROJECT


# ---------------------------------------------------------------- projets


async def test_get_projects_and_project(client: CospendClient) -> None:
    projects = await client.get_projects()
    assert [p.id for p in projects] == [PROJECT]
    project = await client.get_project(PROJECT)
    assert len(project.members) == 3
    with pytest.raises(CospendNotFoundError):
        await client.get_project("inconnu")


# ---------------------------------------------------------------- dépenses : lecture


async def test_get_bills_page(client: CospendClient) -> None:
    page = await client.get_bills(PROJECT, reverse=True)
    assert page.nb_bills == 6
    assert [b.id for b in page.bills][:2] == [37, 38]  # le plus récent d'abord


async def test_get_bills_filters(client: CospendClient, fake: FakeCospend) -> None:
    page = await client.get_bills(PROJECT, payer_id=13, search_term="util2")
    assert [b.id for b in page.bills] == [38]  # « util2 → util1 », payé par util2
    page = await client.get_bills(PROJECT, payer_id=13, search_term="testfact")
    assert {b.id for b in page.bills} == {31, 32, 33}
    query = last_request(fake, "GET").query
    assert query == {"payerId": "13", "searchTerm": "testfact"}


async def test_iter_bills_paginates(client: CospendClient, fake: FakeCospend) -> None:
    ids = [b.id async for b in client.iter_bills(PROJECT, page_size=4)]
    assert sorted(ids) == [30, 31, 32, 33, 37, 38]
    pages = [r for r in fake.requests if r.path.endswith("/bills") and r.method == "GET"]
    assert [p.query["offset"] for p in pages] == ["0", "4"]


# ---------------------------------------------------------------- dépenses : écriture


async def test_create_bill_sends_every_field_as_form(
    client: CospendClient, fake: FakeCospend
) -> None:
    bill_id = await client.create_bill(
        PROJECT,
        what="test",
        amount=12.5,
        payer_id=12,
        payed_for=[12, 13],
        timestamp=1794780500,
        date="2026-11-15",
    )
    assert bill_id == 100
    form = last_request(fake, "POST").form
    assert form == {
        "date": "2026-11-15",
        "what": "test",
        "payer": "12",
        "amount": "12.5",
        "comment": "",
        "timestamp": "1794780500",
        "repeat": "n",
        "payedFor": "12,13",
        "paymentMode": "n",
        "categoryId": "0",
        "paymentModeId": "0",
    }
    bill = await client.get_bill(PROJECT, bill_id)
    assert bill.ower_ids == (12, 13)
    assert bill.amount == 12.5


async def test_create_negative_amount(client: CospendClient) -> None:
    bill_id = await client.create_bill(
        PROJECT,
        what="avoir",
        amount=-5,
        payer_id=12,
        payed_for=[12],
        timestamp=1794780500,
        date="2026-11-15",
    )
    assert (await client.get_bill(PROJECT, bill_id)).amount == -5


async def test_create_requires_a_participant(client: CospendClient) -> None:
    with pytest.raises(ValueError):
        await client.create_bill(
            PROJECT,
            what="x",
            amount=1,
            payer_id=12,
            payed_for=[],
            timestamp=1,
            date="2026-11-15",
        )


async def test_create_bad_request(client: CospendClient) -> None:
    with pytest.raises(CospendBadRequestError):
        await client.create_bill(
            PROJECT,
            what="x",
            amount=1,
            payer_id=12,
            payed_for=[99],  # membre inexistant : le faux serveur refuse
            timestamp=1,
            date="2026-11-15",
        )


async def test_partial_update_keeps_other_fields(client: CospendClient, fake: FakeCospend) -> None:
    before = await client.get_bill(PROJECT, 30)
    assert await client.update_bill(PROJECT, 30, amount=1300) == 30
    assert last_request(fake, "PUT").form == {"amount": "1300"}
    after = await client.get_bill(PROJECT, 30)
    assert after.amount == 1300
    assert (after.what, after.payer_id, after.ower_ids, after.category_id) == (
        before.what,
        before.payer_id,
        before.ower_ids,
        before.category_id,
    )


async def test_update_requires_a_change(client: CospendClient) -> None:
    with pytest.raises(ValueError):
        await client.update_bill(PROJECT, 30)


async def test_delete_goes_to_trash_then_is_permanent(
    client: CospendClient, fake: FakeCospend
) -> None:
    await client.delete_bill(PROJECT, 33)
    assert last_request(fake, "DELETE").query == {}  # défaut du serveur : corbeille
    trash = await client.get_bills(PROJECT, deleted=True)
    assert [b.id for b in trash.bills] == [33]
    assert 33 not in (await client.get_bills(PROJECT)).all_bill_ids

    await client.delete_bill(PROJECT, 33)  # seconde suppression : définitive
    assert (await client.get_bills(PROJECT, deleted=True)).nb_bills == 0
    with pytest.raises(CospendNotFoundError):
        await client.get_bill(PROJECT, 33)


async def test_permanent_delete_flag(client: CospendClient, fake: FakeCospend) -> None:
    await client.delete_bill(PROJECT, 31, move_to_trash=False)
    assert last_request(fake, "DELETE").query == {"moveToTrash": "false"}
    assert (await client.get_bills(PROJECT, deleted=True)).nb_bills == 0


# ---------------------------------------------------------------- lecture incrémentale


async def test_incremental_sync_detects_edits_and_deletions(
    client: CospendClient, fake: FakeCospend
) -> None:
    first = await client.get_bills(PROJECT)
    cursor = first.timestamp

    fake.tick()
    await client.update_bill(PROJECT, 31, amount=210)  # modification
    fake.tick()
    await client.delete_bill(PROJECT, 33)  # mise en corbeille
    fake.tick()
    created = await client.create_bill(  # création
        PROJECT, what="nouveau", amount=7, payer_id=12, payed_for=[12],
        timestamp=fake.clock, date="2026-11-15",
    )  # fmt: skip

    delta = await client.get_bills(PROJECT, last_changed=cursor)
    assert {b.id for b in delta.bills} == {31, created}  # 33 n'est pas renvoyée
    assert 33 not in delta.all_bill_ids  # on la détecte par son absence
    assert set(first.all_bill_ids) - set(delta.all_bill_ids) == {33}
    assert delta.timestamp >= cursor
    assert delta.nb_bills == 6  # total des dépenses visibles : 6 - 1 + 1


# ---------------------------------------------------------------- analyse


async def test_statistics_and_settlement(client: CospendClient, fake: FakeCospend) -> None:
    stats = await client.get_statistics(PROJECT, ts_min=1, category_id=35)
    assert stats.months == ("2026-11",)
    assert last_request(fake, "GET").query == {"tsMin": "1", "categoryId": "35"}
    settlement = await client.get_settlement(PROJECT, centered_on=12)
    assert len(settlement.transactions) == 2
    assert last_request(fake, "GET").query == {"centeredOn": "12"}


async def test_requests_carry_ocs_header_and_basic_auth(
    client: CospendClient, fake: FakeCospend
) -> None:
    await client.get_projects()
    assert last_request(fake, "GET").path == f"{API}/projects"


# ---------------------------------------------------------------- structure du projet


async def test_create_member_and_category(client: CospendClient, fake: FakeCospend) -> None:
    member = await client.create_member(PROJECT, "Zoé", weight=2, color="#112233")
    request = last_request(fake, "POST")
    assert request.path.endswith(f"/projects/{PROJECT}/members")
    assert request.form == {"name": "Zoé", "weight": "2", "active": "1", "color": "#112233"}
    category = await client.create_category(PROJECT, "Sport", icon="🎾")
    assert category == member + 1
    request = last_request(fake, "POST")
    assert request.path.endswith("/categories")
    assert request.form == {"name": "Sport", "icon": "🎾", "color": "#888888"}


async def test_update_member_sends_only_given_fields(
    client: CospendClient, fake: FakeCospend
) -> None:
    await client.update_member(PROJECT, 12, activated=False)
    request = last_request(fake, "PUT")
    assert request.path.endswith("/members/12")
    assert request.form == {"activated": "false"}
    await client.update_member(PROJECT, 12, name="Alice", weight=1.5)
    assert last_request(fake, "PUT").form == {"name": "Alice", "weight": "1.5"}
    with pytest.raises(ValueError):
        await client.update_member(PROJECT, 12)


async def test_payment_mode_and_currency_routes(client: CospendClient, fake: FakeCospend) -> None:
    await client.create_payment_mode(PROJECT, "Espèces", icon="💵", color="#00aa00")
    assert last_request(fake, "POST").path.endswith("/paymentmodes")
    await client.update_payment_mode(PROJECT, 17, name="Cash")
    assert last_request(fake, "PUT").path.endswith("/paymentmodes/17")
    await client.create_currency(PROJECT, "USD", 0.92)
    request = last_request(fake, "POST")
    assert request.path.endswith("/currencies")
    assert request.form == {"name": "USD", "rate": "0.92"}
    await client.update_currency(PROJECT, 1, rate=0.9)
    assert last_request(fake, "PUT").form == {"rate": "0.9"}


async def test_delete_items_and_unknown_project(client: CospendClient, fake: FakeCospend) -> None:
    await client.delete_category(PROJECT, 35)
    assert last_request(fake, "DELETE").path.endswith("/categories/35")
    await client.delete_currency(PROJECT, 1)
    assert last_request(fake, "DELETE").path.endswith("/currencies/1")
    with pytest.raises(CospendNotFoundError):
        await client.delete_member("autre", 1)
