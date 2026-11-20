"""Tests des services add_bill, update_bill et delete_bill."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import async_capture_events

from aiocospend import CospendAuthenticationError, CospendForbiddenError
from custom_components.cospend.const import (
    DOMAIN,
    EVENT_BILL_ADDED,
    EVENT_BILL_DELETED,
    EVENT_BILL_UPDATED,
)

from .fake_client import FakeClient

PROJECT = "teste"


async def call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, data, blocking=True, return_response=True
    )


def created(fake: FakeClient) -> list[dict]:
    return [kwargs for name, _, kwargs in fake.calls if name == "create_bill"]


async def test_services_are_registered_without_an_entry(hass: HomeAssistant) -> None:
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    for service in ("add_bill", "update_bill", "delete_bill"):
        assert hass.services.has_service(DOMAIN, service)


async def test_add_bill(hass: HomeAssistant, init_integration, fake_client: FakeClient) -> None:
    events = async_capture_events(hass, EVENT_BILL_ADDED)
    response = await call(
        hass,
        "add_bill",
        project=PROJECT,
        title="Pizza",
        amount="12,5 + 7.5",
        payer="util1",
        category="courses",
        payment_mode="Liquide",
        date="2026-11-18 21:30:00",
    )
    (bill,) = created(fake_client)
    assert response["project"] == PROJECT
    assert response["bill_ids"] == [100]
    assert (bill["what"], float(bill["amount"]), bill["payer_id"]) == ("Pizza", 20.0, 12)
    assert tuple(bill["payed_for"]) == (12, 13, 14)
    assert (bill["category_id"], bill["payment_mode_id"], bill["payment_mode"]) == (35, 17, "b")
    assert bill["date"] == "2026-11-18"
    # la relecture qui suit l'écriture déclenche l'événement
    await hass.async_block_till_done()
    assert [e.data["bill_id"] for e in events] == [100]


async def test_add_bill_updates_sensors(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await call(hass, "add_bill", project=PROJECT, title="Pizza", amount=20, payer=12)
    state = hass.states.get("sensor.teste_number_of_bills")
    assert state is not None
    assert state.state == "7"


async def test_add_bill_with_custom_split(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    response = await call(
        hass,
        "add_bill",
        project=PROJECT,
        title="Soirée",
        amount="100",
        payer="util1",
        split_mode="percent",
        owers=["util1", "util2", "util3"],
        shares={"util1": 50, "util2": 25, "util3": 25},
    )
    assert response["bill_ids"] == [100, 101, 102]
    assert [float(b["amount"]) for b in created(fake_client)] == [50.0, 25.0, 25.0]
    assert len({b["timestamp"] for b in created(fake_client)}) == 1


async def test_add_bill_with_foreign_currency(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await call(
        hass,
        "add_bill",
        project=PROJECT,
        title="Hôtel",
        amount="100",
        payer=12,
        currency="USD",
        exchange_rate=0.92,
        comment="nuit",
    )
    (bill,) = created(fake_client)
    assert float(bill["amount"]) == 92.0
    assert bill["comment"] == "nuit #USD:100@0.92"


async def test_project_can_be_given_by_name(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await call(hass, "add_bill", project="TESTE", title="x", amount=1, payer=12)
    assert len(created(fake_client)) == 1


@pytest.mark.parametrize(
    ("data", "key"),
    [
        ({"project": "inconnu"}, "project_not_found"),
        ({"payer": "personne"}, "invalid_value"),
        ({"amount": "1 +"}, "invalid_value"),
        ({"split_mode": "percent"}, "invalid_value"),
        ({"category": "nope"}, "invalid_value"),
    ],
)
async def test_add_bill_rejects_invalid_input(
    hass: HomeAssistant, init_integration, fake_client: FakeClient, data, key
) -> None:
    base = {"project": PROJECT, "title": "x", "amount": "10", "payer": 12}
    with pytest.raises(ServiceValidationError) as info:
        await call(hass, "add_bill", **{**base, **data})
    assert info.value.translation_key == key
    assert not fake_client.calls


async def test_schema_rejects_bad_split_mode(hass: HomeAssistant, init_integration) -> None:
    import voluptuous as vol

    with pytest.raises(vol.Invalid):
        await call(
            hass, "add_bill", project=PROJECT, title="x", amount=1, payer=12, split_mode="zzz"
        )


async def test_archived_and_read_only_projects_are_refused(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    from dataclasses import replace

    base = {"project": PROJECT, "title": "x", "amount": "10", "payer": 12}
    fake_client.project = replace(fake_client.project, access_level=1)
    coordinator = init_integration.runtime_data
    await coordinator.async_refresh()
    with pytest.raises(ServiceValidationError) as info:
        await call(hass, "add_bill", **base)
    assert info.value.translation_key == "project_read_only"

    fake_client.project = replace(fake_client.project, access_level=4, archived_ts=1)
    await coordinator.async_refresh()
    with pytest.raises(ServiceValidationError) as info:
        await call(hass, "add_bill", **base)
    assert info.value.translation_key == "project_archived"
    assert not fake_client.calls


async def test_update_bill(hass: HomeAssistant, init_integration, fake_client: FakeClient) -> None:
    events = async_capture_events(hass, EVENT_BILL_UPDATED)
    response = await call(
        hass,
        "update_bill",
        project=PROJECT,
        bill_id=30,
        title="Renommée",
        amount="5,5",
        payer="util2",
    )
    assert response["bill_ids"] == [30]
    assert fake_client.bills[30].what == "Renommée"
    assert fake_client.bills[30].amount == 5.5
    assert fake_client.bills[30].payer_id == 13
    await hass.async_block_till_done()
    assert [e.data["bill_id"] for e in events] == [30]


async def test_update_group_applies_common_fields(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    response = await call(hass, "update_bill", project=PROJECT, bill_id=32, title="Groupe")
    assert response["bill_ids"] == [31, 32, 33]
    assert {fake_client.bills[i].what for i in (31, 32, 33)} == {"Groupe"}


async def test_update_group_split_is_refused(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    with pytest.raises(ServiceValidationError) as info:
        await call(hass, "update_bill", project=PROJECT, bill_id=31, amount="10")
    assert info.value.translation_key == "invalid_value"
    assert not [c for c in fake_client.calls if c[0] == "update_bill"]


async def test_update_unknown_bill(hass: HomeAssistant, init_integration) -> None:
    with pytest.raises(ServiceValidationError) as info:
        await call(hass, "update_bill", project=PROJECT, bill_id=9999, title="x")
    assert info.value.translation_key == "bill_not_found"


async def test_delete_bill(hass: HomeAssistant, init_integration, fake_client: FakeClient) -> None:
    events = async_capture_events(hass, EVENT_BILL_DELETED)
    response = await call(hass, "delete_bill", project=PROJECT, bill_id=30)
    assert response["bill_ids"] == [30]
    assert 30 not in fake_client.bills
    await hass.async_block_till_done()
    assert [e.data["bill_id"] for e in events] == [30]


async def test_delete_whole_group_or_one_part(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    response = await call(hass, "delete_bill", project=PROJECT, bill_id=31, whole_group=False)
    assert response["bill_ids"] == [31]
    assert {32, 33} <= set(fake_client.bills)
    response = await call(hass, "delete_bill", project=PROJECT, bill_id=32)
    assert response["bill_ids"] == [32, 33]


async def test_authentication_error_starts_reauth(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    fake_client.write_error = CospendAuthenticationError("401", status=401)
    with pytest.raises(HomeAssistantError) as info:
        await call(hass, "add_bill", project=PROJECT, title="x", amount=1, payer=12)
    assert info.value.translation_key == "auth_failed"
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_forbidden_error(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    fake_client.write_error = CospendForbiddenError("403", status=403)
    with pytest.raises(HomeAssistantError) as info:
        await call(hass, "delete_bill", project=PROJECT, bill_id=30)
    assert info.value.translation_key == "forbidden"


async def test_partial_failure_is_reported_and_state_refreshed(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    real = fake_client.create_bill
    count = 0

    async def flaky(project_id, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("coupure")
        return await real(project_id, **kwargs)

    with patch.object(fake_client, "create_bill", flaky), pytest.raises(HomeAssistantError) as info:
        await call(
            hass,
            "add_bill",
            project=PROJECT,
            title="Soirée",
            amount="100",
            payer=12,
            split_mode="amounts",
            owers=[12, 13],
            shares={"util1": 60, "util2": 40},
        )
    assert info.value.translation_key == "partial_write"
    assert info.value.translation_placeholders["done"] == "100"
    assert count == 2  # jamais rejoué
    assert 100 in fake_client.bills
    assert hass.states.get("sensor.teste_number_of_bills").state == "7"


def test_date_helpers() -> None:
    from custom_components.cospend.services import _when

    assert _when("2026-11-18 21:30:00").hour == 21
    assert _when("2026-11-18").date().isoformat() == "2026-11-18"
    assert _when(datetime(2026, 1, 1, tzinfo=UTC)).tzinfo is not None


async def test_add_bill_as_the_card_sends_it(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    """La carte envoie des identifiants (en texte), une date seule et une expression."""
    response = await call(
        hass,
        "add_bill",
        project=PROJECT,
        title="Essence",
        amount="12,5 + 7",
        payer="13",
        owers=["12", "13"],
        split_mode="even",
        category="35",
        comment="",
        date="2026-11-20",
    )
    (bill,) = created(fake_client)
    assert response["bill_ids"] == [100]
    assert (float(bill["amount"]), bill["payer_id"]) == (19.5, 13)
    assert tuple(bill["payed_for"]) == (12, 13)
    assert (bill["category_id"], bill["payment_mode_id"]) == (35, 0)
    assert bill["date"] == "2026-11-20"
