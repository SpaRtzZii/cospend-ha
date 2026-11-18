"""Tests du mode hors ligne : mise en file, rejeu sans doublon, conflits, persistance."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import async_capture_events

from aiocospend import CospendConnectionError, CospendForbiddenError
from custom_components.cospend.const import (
    DOMAIN,
    EVENT_OPERATION_BLOCKED,
    EVENT_OPERATION_QUEUED,
    EVENT_OPERATION_SYNCED,
)
from custom_components.cospend.queue import async_flush

from .fake_client import FakeClient

PROJECT = "teste"
DOWN = CospendConnectionError("hors ligne")


async def call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


async def go_offline(init_integration, fake: FakeClient) -> None:
    fake.error = DOWN
    await init_integration.runtime_data.async_refresh()
    assert not init_integration.runtime_data.last_update_success


async def go_online(init_integration, fake: FakeClient) -> None:
    fake.error = None
    fake.write_error = None
    await init_integration.runtime_data.async_refresh()


def pending(init_integration) -> list:
    return init_integration.runtime_data.queue.operations


def created(fake: FakeClient) -> list[dict]:
    return [kwargs for name, _, kwargs in fake.calls if name == "create_bill"]


async def test_add_while_offline_is_queued_then_sent(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    queued_events = async_capture_events(hass, EVENT_OPERATION_QUEUED)
    synced_events = async_capture_events(hass, EVENT_OPERATION_SYNCED)
    await go_offline(init_integration, fake_client)

    response = await call(hass, "add_bill", project=PROJECT, title="Pizza", amount="20", payer=12)
    assert response["queued"] is True
    assert response["bill_ids"] == []
    assert not created(fake_client)  # rien n'est tenté quand on sait Cospend injoignable
    assert len(pending(init_integration)) == 1
    await hass.async_block_till_done()
    assert len(queued_events) == 1

    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    await hass.async_block_till_done()
    assert len(created(fake_client)) == 1
    assert not pending(init_integration)
    assert [e.data["bill_ids"] for e in synced_events] == [[100]]


async def test_queue_sensor_counts_pending_operations(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "add_bill", project=PROJECT, title="A", amount="1", payer=12)
    await call(hass, "add_bill", project=PROJECT, title="B", amount="2", payer=12)
    await hass.async_block_till_done()
    state = hass.states.get("sensor.teste_pending_operations")
    assert state is not None and state.state == "2"
    assert [op["title"] for op in state.attributes["operations"]] == ["A", "B"]

    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.teste_pending_operations").state == "0"


async def test_order_is_kept(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    for title in ("un", "deux", "trois"):
        await call(hass, "add_bill", project=PROJECT, title=title, amount="1", payer=12)
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    assert [b["what"] for b in created(fake_client)] == ["un", "deux", "trois"]


async def test_nothing_overtakes_a_pending_operation(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "add_bill", project=PROJECT, title="un", amount="1", payer=12)
    await go_online(init_integration, fake_client)
    # Cospend répond de nouveau, mais la file n'a pas encore été vidée : la suite passe derrière.
    response = await call(hass, "add_bill", project=PROJECT, title="deux", amount="1", payer=12)
    assert response["queued"] is True
    assert not created(fake_client)
    await async_flush(init_integration.runtime_data)
    assert [b["what"] for b in created(fake_client)] == ["un", "deux"]


async def test_transient_error_during_a_direct_call_is_queued(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    fake_client.write_error = DOWN
    response = await call(hass, "add_bill", project=PROJECT, title="Pizza", amount="20", payer=12)
    assert response["queued"] is True
    (op,) = pending(init_integration)
    assert op.ambiguous  # la création a peut-être abouti sans réponse


async def test_replay_does_not_duplicate_a_bill_that_was_created_without_an_answer(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    """La création a abouti côté serveur mais la réponse s'est perdue : pas de doublon."""
    real = fake_client.create_bill

    async def lost_answer(project_id, **kwargs):
        await real(project_id, **kwargs)
        raise DOWN

    fake_client.create_bill = lost_answer
    response = await call(hass, "add_bill", project=PROJECT, title="Pizza", amount="20", payer=12)
    assert response["queued"] is True
    assert len(created(fake_client)) == 1  # elle est bien partie une fois

    fake_client.create_bill = real
    await async_flush(init_integration.runtime_data)
    assert len(created(fake_client)) == 1  # et n'est pas recréée
    assert not pending(init_integration)
    assert sum(b.what == "Pizza" for b in fake_client.bills.values()) == 1


async def test_a_never_attempted_operation_is_not_mistaken_for_an_existing_bill(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    """Deux appels identiques dans la même seconde ne se confondent pas."""
    when = "2026-11-18 21:30:00"
    data = {"project": PROJECT, "title": "Pizza", "amount": "20", "payer": 12, "date": when}
    first = await call(hass, "add_bill", **data)
    assert first["queued"] is False
    await go_offline(init_integration, fake_client)
    second = await call(hass, "add_bill", **data)
    assert second["queued"] is True
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    assert len(created(fake_client)) == 2


async def test_partial_custom_split_is_resumed_where_it_stopped(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    real = fake_client.create_bill
    count = 0

    async def flaky(project_id, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise DOWN
        return await real(project_id, **kwargs)

    fake_client.create_bill = flaky
    response = await call(
        hass,
        "add_bill",
        project=PROJECT,
        title="Soirée",
        amount="100",
        payer=12,
        split_mode="percent",
        owers=[12, 13, 14],
        shares={12: 50, 13: 30, 14: 20},
    )
    assert response["queued"] is True
    assert response["bill_ids"] == [100]  # la première part est faite
    (op,) = pending(init_integration)
    assert (len(op.done), len(op.plan)) == (1, 3)

    fake_client.create_bill = real
    await async_flush(init_integration.runtime_data)
    parts = [b for b in fake_client.bills.values() if b.what == "Soirée"]
    assert sorted(b.amount for b in parts) == [20.0, 30.0, 50.0]  # exactement 3, pas 4


async def test_update_is_queued_and_applied(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    response = await call(hass, "update_bill", project=PROJECT, bill_id=30, title="Renommée")
    assert response["queued"] is True
    assert fake_client.bills[30].what != "Renommée"
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    assert fake_client.bills[30].what == "Renommée"


async def test_update_conflict_is_blocked_not_applied(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    blocked_events = async_capture_events(hass, EVENT_OPERATION_BLOCKED)
    await go_offline(init_integration, fake_client)
    await call(hass, "update_bill", project=PROJECT, bill_id=30, title="Ma version")
    fake_client.simulate_update(30, what="Version d'un autre")  # modifiée ailleurs
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    await hass.async_block_till_done()

    assert fake_client.bills[30].what == "Version d'un autre"  # rien d'écrasé en silence
    (op,) = pending(init_integration)
    assert (op.status, op.reason) == ("blocked", "conflict")
    assert [e.data["reason"] for e in blocked_events] == ["conflict"]
    assert any(issue_id.startswith("blocked_") for _, issue_id in ir.async_get(hass).issues)


async def test_blocked_operation_can_be_forced_or_discarded(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "update_bill", project=PROJECT, bill_id=30, title="Ma version")
    fake_client.simulate_update(30, what="Version d'un autre")
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    (op,) = pending(init_integration)

    result = await call(hass, "retry_queued", operation_id=op.id, force=True)
    assert result == {"retried": [op.id]}
    assert fake_client.bills[30].what == "Ma version"
    assert not pending(init_integration)
    assert not [i for _, i in ir.async_get(hass).issues if i.startswith("blocked_")]


async def test_discard_removes_the_operation_and_the_issue(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "update_bill", project=PROJECT, bill_id=30, title="Ma version")
    fake_client.simulate_update(30, what="Version d'un autre")
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    (op,) = pending(init_integration)

    result = await call(hass, "discard_queued", operation_id=op.id)
    assert result["discarded"] == op.id
    assert not pending(init_integration)
    assert fake_client.bills[30].what == "Version d'un autre"
    assert not [i for _, i in ir.async_get(hass).issues if i.startswith("blocked_")]


async def test_a_blocked_operation_keeps_the_ones_behind_it_waiting(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "update_bill", project=PROJECT, bill_id=30, title="Ma version")
    await call(hass, "add_bill", project=PROJECT, title="Après", amount="1", payer=12)
    fake_client.simulate_update(30, what="Autre")
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    assert not created(fake_client)
    assert [op.status for op in pending(init_integration)] == ["blocked", "pending"]


async def test_replaying_an_update_already_applied_is_a_no_op(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "update_bill", project=PROJECT, bill_id=30, title="Renommée")
    fake_client.simulate_update(30, what="Renommée")  # appliquée entre-temps (réponse perdue)
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    assert not pending(init_integration)
    assert not [c for c in fake_client.calls if c[0] == "update_bill"]


async def test_delete_is_queued_and_never_sent_twice(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "delete_bill", project=PROJECT, bill_id=30)
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    assert 30 not in fake_client.bills
    assert [c[1] for c in fake_client.calls if c[0] == "delete_bill"] == [(PROJECT, 30)]


async def test_delete_of_a_bill_already_gone_is_not_replayed(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "delete_bill", project=PROJECT, bill_id=30)
    fake_client.simulate_delete(30)  # supprimée ailleurs entre-temps
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    assert not pending(init_integration)
    assert not [
        c for c in fake_client.calls if c[0] == "delete_bill"
    ]  # jamais de seconde suppression


async def test_chained_operations_on_the_same_bill_do_not_conflict_with_each_other(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "update_bill", project=PROJECT, bill_id=30, title="Première")
    await call(hass, "update_bill", project=PROJECT, bill_id=30, comment="Seconde")
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    assert not pending(init_integration)
    assert fake_client.bills[30].what == "Première"
    assert fake_client.bills[30].comment == "Seconde"


async def test_non_transient_error_is_raised_not_queued(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    from homeassistant.exceptions import HomeAssistantError

    fake_client.write_error = CospendForbiddenError("403", status=403)
    with pytest.raises(HomeAssistantError):
        await call(hass, "add_bill", project=PROJECT, title="x", amount="1", payer=12)
    assert not pending(init_integration)


async def test_invalid_input_is_never_queued(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    from homeassistant.exceptions import ServiceValidationError

    await go_offline(init_integration, fake_client)
    with pytest.raises(ServiceValidationError):
        await call(hass, "add_bill", project=PROJECT, title="x", amount="1", payer="inconnu")
    assert not pending(init_integration)


async def test_rejected_replay_blocks_the_operation(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "add_bill", project=PROJECT, title="x", amount="1", payer=12)
    await go_online(init_integration, fake_client)
    fake_client.write_error = CospendForbiddenError("403", status=403)
    await async_flush(init_integration.runtime_data)
    (op,) = pending(init_integration)
    assert (op.status, op.reason) == ("blocked", "request_failed")


async def test_still_offline_keeps_the_operation_pending(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "add_bill", project=PROJECT, title="x", amount="1", payer=12)
    await async_flush(init_integration.runtime_data)
    (op,) = pending(init_integration)
    assert op.status == "pending"
    assert not created(fake_client)


async def test_queue_survives_a_restart(
    hass: HomeAssistant, init_integration, fake_client: FakeClient, mock_config_entry
) -> None:
    from unittest.mock import patch

    await go_offline(init_integration, fake_client)
    await call(hass, "add_bill", project=PROJECT, title="Survivante", amount="5", payer=12)
    await hass.async_block_till_done()

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    fake_client.error = None
    with patch("custom_components.cospend.CospendClient", return_value=fake_client):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    # au redémarrage, la file est relue puis rejouée sans intervention
    assert [b["what"] for b in created(fake_client)] == ["Survivante"]
    assert not mock_config_entry.runtime_data.queue.operations


async def test_removing_the_entry_removes_its_queue(
    hass: HomeAssistant, init_integration, fake_client: FakeClient, mock_config_entry
) -> None:
    await go_offline(init_integration, fake_client)
    await call(hass, "update_bill", project=PROJECT, bill_id=30, title="Ma version")
    fake_client.simulate_update(30, what="Autre")
    await go_online(init_integration, fake_client)
    await async_flush(init_integration.runtime_data)
    assert [i for _, i in ir.async_get(hass).issues if i.startswith("blocked_")]

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert not [i for _, i in ir.async_get(hass).issues if i.startswith("blocked_")]


async def test_unknown_operation_id(hass: HomeAssistant, init_integration) -> None:
    from homeassistant.exceptions import ServiceValidationError

    with pytest.raises(ServiceValidationError):
        await call(hass, "discard_queued", operation_id="nope")
    with pytest.raises(ServiceValidationError):
        await call(hass, "retry_queued", operation_id="nope")
