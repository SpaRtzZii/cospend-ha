"""Tests du cache de dépenses et de la synchronisation incrémentale."""

from __future__ import annotations

import pytest
from fake_server import FakeCospend

from aiocospend import CospendClient, ProjectBills
from aiocospend.models import ProjectStatistics

PROJECT = "teste"


async def create(client: CospendClient, fake: FakeCospend, what: str = "nouveau") -> int:
    return await client.create_bill(
        PROJECT,
        what=what,
        amount=7,
        payer_id=12,
        payed_for=[12],
        timestamp=fake.clock,
        date="2026-11-15",
    )


async def test_first_sync_is_initial_and_reads_everything(
    client: CospendClient, fake: FakeCospend
) -> None:
    store = ProjectBills(PROJECT)
    changes = await store.sync(client)
    assert changes.is_initial and changes.full
    assert len(changes.added) == 6
    assert sorted(store.bills) == [30, 31, 32, 33, 37, 38]
    assert store.cursor == fake.clock
    assert store.synced


async def test_incremental_without_change_is_quiet(
    client: CospendClient, fake: FakeCospend
) -> None:
    store = ProjectBills(PROJECT)
    await store.sync(client)
    fake.tick(1)  # reste dans la fenêtre de recouvrement : tout est relu, rien ne change
    changes = await store.sync(client)
    assert not changes.any
    assert not changes.is_initial and not changes.full


async def test_incremental_detects_add_update_delete(
    client: CospendClient, fake: FakeCospend
) -> None:
    store = ProjectBills(PROJECT)
    await store.sync(client)

    fake.tick(10)
    await client.update_bill(PROJECT, 31, amount=210)
    fake.tick(10)
    await client.delete_bill(PROJECT, 33)
    fake.tick(10)
    new_id = await create(client, fake)

    changes = await store.sync(client)
    assert [b.id for b in changes.added] == [new_id]
    assert [b.id for b in changes.updated] == [31]
    assert changes.updated[0].amount == 210
    assert [b.id for b in changes.deleted] == [33]
    assert 33 not in store.bills and new_id in store.bills

    assert not (await store.sync(client)).any  # rien de plus au cycle suivant


async def test_full_sync_is_paginated(client: CospendClient, fake: FakeCospend) -> None:
    store = ProjectBills(PROJECT, page_size=2)
    await store.sync(client)
    pages = [
        r.query["offset"] for r in fake.requests if r.path.endswith("/bills") and r.method == "GET"
    ]
    assert pages == ["0", "2", "4"]
    assert len(store.bills) == 6


async def test_full_resync_catches_changes_missed_by_incremental(
    client: CospendClient, fake: FakeCospend
) -> None:
    store = ProjectBills(PROJECT)
    await store.sync(client)
    # modification sans mise à jour de lastchanged : invisible pour la lecture incrémentale
    fake.bills[30]["amount"] = 1300.0
    fake.tick(1)
    assert not (await store.sync(client)).any

    changes = await store.sync(client, full_sync_max_age=0)
    assert changes.full and not changes.is_initial
    assert [b.id for b in changes.updated] == [30]


async def test_incremental_detects_deletion_without_new_modification_time(
    client: CospendClient, fake: FakeCospend
) -> None:
    store = ProjectBills(PROJECT)
    await store.sync(client)
    fake.bills[32]["deleted"] = 1  # mise en corbeille : repérée par all_bill_ids
    fake.tick(1)
    changes = await store.sync(client)
    assert [b.id for b in changes.deleted] == [32]
    assert not changes.full


async def test_sync_chooses_incremental_when_full_is_not_due(
    client: CospendClient, fake: FakeCospend
) -> None:
    store = ProjectBills(PROJECT)
    await store.sync(client, full_sync_max_age=3600)
    assert not (await store.sync(client, full_sync_max_age=3600)).full
    assert store.full_sync_due(3600, now=store.last_full_sync + 4000)
    assert not store.full_sync_due(3600, now=store.last_full_sync + 10)


async def test_incremental_requires_a_first_full_sync(client: CospendClient) -> None:
    with pytest.raises(RuntimeError):
        await ProjectBills(PROJECT).incremental_sync(client)


async def test_bill_equality_ignores_project_id(client: CospendClient) -> None:
    """La liste complète renvoie project_id, la liste incrémentale non : même dépense."""
    full = (await client.get_bills(PROJECT)).bills[0]
    partial = (await client.get_bills(PROJECT, last_changed=0)).bills
    same = next(b for b in partial if b.id == full.id)
    assert full.project_id == PROJECT and same.project_id is None
    assert full == same


def test_statistics_monthly_helpers() -> None:
    from fake_server import load_fixture

    stats = ProjectStatistics.from_api(load_fixture("statistics.json"))
    assert stats.paid_in("2026-11") == 1850
    assert stats.paid_in("2026-11", 12) == 1250
    assert stats.spent_in("2026-11", 14) == pytest.approx(666.6667, abs=1e-3)
    assert stats.paid_in("2025-01") == 0.0
