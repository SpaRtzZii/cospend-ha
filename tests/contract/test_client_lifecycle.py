"""Scénario complet du client contre un vrai serveur Nextcloud + Cospend.

Reprend les essais faits à la main sur un serveur Cospend 4.3.0 (création en formulaire,
montant négatif, modification partielle, lecture incrémentale, corbeille puis suppression
définitive). Un projet jetable est créé puis supprimé.

Exécuté seulement avec COSPEND_TEST_URL, COSPEND_TEST_USER et COSPEND_TEST_PASSWORD.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator

import aiohttp
import pytest

from aiocospend import CospendClient, CospendNotFoundError
from aiocospend.client import basic_auth_header
from aiocospend.const import API_VERSION, OCS_BASE_PATH

pytestmark = pytest.mark.contract

URL = os.environ.get("COSPEND_TEST_URL", "").rstrip("/")
USER = os.environ.get("COSPEND_TEST_USER", "")
PASSWORD = os.environ.get("COSPEND_TEST_PASSWORD", "")

if not (URL and USER and PASSWORD):
    pytest.skip("variables COSPEND_TEST_* absentes", allow_module_level=True)

HEADERS = {
    "OCS-APIRequest": "true",
    "Accept": "application/json",
    "Authorization": basic_auth_header(USER, PASSWORD),
}
API = f"{URL}{OCS_BASE_PATH}/{API_VERSION}"


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as s:
        yield s


@pytest.fixture
async def project_id(session: aiohttp.ClientSession) -> AsyncIterator[str]:
    """Projet jetable avec trois membres, supprimé en fin de test."""
    pid = f"ha-test-{int(time.time())}"
    async with session.post(f"{API}/projects", data={"id": pid, "name": pid}, headers=HEADERS) as r:
        assert r.status == 200, await r.text()
    for name in ("util1", "util2", "util3"):
        async with session.post(
            f"{API}/projects/{pid}/members", data={"name": name}, headers=HEADERS
        ) as r:
            assert r.status == 200, await r.text()
    try:
        yield pid
    finally:
        async with session.delete(f"{API}/projects/{pid}", headers=HEADERS) as r:
            await r.read()


@pytest.fixture
def client(session: aiohttp.ClientSession) -> CospendClient:
    return CospendClient(session, URL, USER, PASSWORD)


async def test_full_lifecycle(client: CospendClient, project_id: str) -> None:
    info = await client.check_connection()
    assert info.version

    project = await client.get_project(project_id)
    assert [m.name for m in project.members] == ["util1", "util2", "util3"]
    util1, util2, util3 = (m.id for m in project.members)
    assert project_id in [p.id for p in await client.get_projects()]

    now = int(time.time())
    today = time.strftime("%Y-%m-%d")

    # Création (répartition égale entre deux participants), puis lecture.
    bill_id = await client.create_bill(
        project_id,
        what="test",
        amount=20,
        payer_id=util1,
        payed_for=[util1, util2],
        timestamp=now,
        date=today,
        comment="avant",
    )
    bill = await client.get_bill(project_id, bill_id)
    assert (bill.amount, bill.what, bill.comment) == (20, "test", "avant")
    assert sorted(bill.ower_ids) == sorted([util1, util2])

    # Montant négatif accepté.
    negative_id = await client.create_bill(
        project_id,
        what="avoir",
        amount=-5,
        payer_id=util1,
        payed_for=[util1],
        timestamp=now,
        date=today,
    )
    assert (await client.get_bill(project_id, negative_id)).amount == -5

    # Lecture incrémentale : on attend une seconde pleine après le curseur.
    cursor = (await client.get_bills(project_id)).timestamp
    await asyncio.sleep(2)

    # Modification partielle : les autres champs sont conservés.
    assert await client.update_bill(project_id, bill_id, amount=30) == bill_id
    updated = await client.get_bill(project_id, bill_id)
    assert updated.amount == 30
    assert (updated.what, updated.comment, updated.payer_id) == ("test", "avant", util1)
    assert sorted(updated.ower_ids) == sorted([util1, util2])

    delta = await client.get_bills(project_id, last_changed=cursor)
    assert [b.id for b in delta.bills] == [bill_id]

    # Corbeille : la dépense disparaît de la liste incrémentale, on la repère par allBillIds.
    await asyncio.sleep(2)
    cursor = delta.timestamp
    await client.delete_bill(project_id, bill_id)
    delta = await client.get_bills(project_id, last_changed=cursor)
    assert bill_id not in [b.id for b in delta.bills]
    assert bill_id not in delta.all_bill_ids
    trash = await client.get_bills(project_id, deleted=True)
    assert [b.id for b in trash.bills] == [bill_id]

    # Seconde suppression : définitive.
    await client.delete_bill(project_id, bill_id)
    assert (await client.get_bills(project_id, deleted=True)).nb_bills == 0
    with pytest.raises(CospendNotFoundError):
        await client.get_bill(project_id, bill_id)


async def test_custom_split_group_and_analysis(client: CospendClient, project_id: str) -> None:
    """Répartition personnalisée : une dépense par participant, même horodatage."""
    project = await client.get_project(project_id)
    util1, util2, util3 = (m.id for m in project.members)
    now = int(time.time())
    today = time.strftime("%Y-%m-%d")

    ids = [
        await client.create_bill(
            project_id,
            what="testfact",
            amount=share,
            payer_id=util2,
            payed_for=[owner],
            timestamp=now,
            date=today,
        )
        for owner, share in ((util2, 200), (util1, 150), (util3, 250))
    ]
    page = await client.get_bills(project_id)
    group = [b for b in page.bills if b.id in ids]
    assert len(group) == 3
    assert len({b.timestamp for b in group}) == 1

    stats = await client.get_statistics(project_id)
    assert stats.months
    settlement = await client.get_settlement(project_id)
    assert settlement.transactions
