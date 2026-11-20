"""Tests des services de gestion : membres, catégories, modes de paiement et devises."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from voluptuous import Invalid

from aiocospend import CospendForbiddenError
from custom_components.cospend.const import DOMAIN

from .fake_client import FakeClient

PROJECT = "teste"


async def call(hass: HomeAssistant, service: str, **data):
    return await hass.services.async_call(
        DOMAIN, service, {"project": PROJECT, **data}, blocking=True, return_response=True
    )


def writes(fake: FakeClient) -> list[tuple[str, tuple, dict]]:
    return fake.calls


async def test_services_are_registered(hass: HomeAssistant) -> None:
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    for kind in ("member", "category", "payment_mode", "currency"):
        for action in ("add", "update", "delete"):
            assert hass.services.has_service(DOMAIN, f"{action}_{kind}")


async def test_add_member(hass: HomeAssistant, init_integration, fake_client: FakeClient) -> None:
    response = await call(hass, "add_member", name="  Zoé ", weight=2, color="#AABBCC")
    assert response == {"project": PROJECT, "id": 77, "reactivated": False}
    ((name, args, kwargs),) = writes(fake_client)
    assert (name, args) == ("create_member", (PROJECT, "Zoé"))
    assert kwargs == {"weight": 2.0, "color": "#aabbcc", "activated": True}


async def test_update_member_resolves_the_name(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    response = await call(hass, "update_member", member="UTIL2", new_name="Bob", active=False)
    assert response["id"] == 13
    ((name, args, kwargs),) = writes(fake_client)
    assert (name, args) == ("update_member", (PROJECT, 13))
    assert kwargs == {"name": "Bob", "weight": None, "color": None, "activated": False}


async def test_update_member_by_id(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await call(hass, "update_member", member="12", weight=3)
    assert writes(fake_client)[0][1] == (PROJECT, 12)


async def test_delete_member(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await call(hass, "delete_member", member="util3")
    assert writes(fake_client)[0][:2] == ("delete_member", (PROJECT, 14))


async def test_unknown_member_is_refused(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    with pytest.raises(ServiceValidationError) as info:
        await call(hass, "delete_member", member="personne")
    assert info.value.translation_key == "invalid_value"
    assert not writes(fake_client)


async def test_categories_and_payment_modes(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await call(hass, "add_category", name="Sport", icon="🎾", color="#112233")
    await call(hass, "update_category", category="courses", new_name="Alimentation")
    await call(hass, "delete_category", category="Loyer")
    await call(hass, "add_payment_mode", name="Espèces")
    await call(hass, "update_payment_mode", payment_mode="Liquide", color="#00ff00")
    await call(hass, "delete_payment_mode", payment_mode="Chèque")
    calls = writes(fake_client)
    assert [c[0] for c in calls] == [
        "create_category",
        "update_category",
        "delete_category",
        "create_payment_mode",
        "update_payment_mode",
        "delete_payment_mode",
    ]
    assert calls[0][2] == {"icon": "🎾", "color": "#112233"}
    assert calls[1][1] == (PROJECT, 35)
    assert calls[2][1] == (PROJECT, 37)
    assert calls[3][2] == {"icon": "", "color": "#888888"}  # couleur par défaut exigée par Cospend
    assert calls[4][1] == (PROJECT, 17)
    assert calls[5][1] == (PROJECT, 18)


async def test_currencies(hass: HomeAssistant, init_integration, fake_client: FakeClient) -> None:
    await call(hass, "add_currency", name="USD", exchange_rate="0,92")
    assert writes(fake_client)[0][1:] == ((PROJECT, "USD", Decimal("0.92")), {})
    with pytest.raises(Invalid):
        await call(hass, "add_currency", name="USD", exchange_rate=0)


async def test_update_and_delete_currency(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    fake_client.project = replace(
        fake_client.project,
        currencies=(*fake_client.project.currencies, _currency(5, "USD", 0.9)),
    )
    await init_integration.runtime_data.async_refresh()
    await call(hass, "update_currency", currency="usd", exchange_rate=0.95)
    await call(hass, "delete_currency", currency="USD")
    calls = writes(fake_client)
    assert calls[0][:2] == ("update_currency", (PROJECT, 5))
    assert calls[0][2]["rate"] == Decimal("0.95")
    assert calls[1][:2] == ("delete_currency", (PROJECT, 5))


def _currency(currency_id: int, name: str, rate: float):
    from aiocospend import Currency

    return Currency(currency_id, name, rate)


async def test_needs_maintainer_level(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    fake_client.project = replace(fake_client.project, access_level=2)
    await init_integration.runtime_data.async_refresh()
    with pytest.raises(ServiceValidationError) as info:
        await call(hass, "add_member", name="Zoé")
    assert info.value.translation_key == "needs_maintainer"
    assert not writes(fake_client)


async def test_invalid_color_is_refused(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    with pytest.raises(Invalid):
        await call(hass, "add_category", name="Sport", color="rouge")


async def test_server_refusal_is_translated(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    fake_client.write_error = CospendForbiddenError("non")
    with pytest.raises(HomeAssistantError) as info:
        await call(hass, "add_member", name="Zoé")
    assert info.value.translation_key == "forbidden"


async def test_add_member_reactivates_a_disabled_one(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    members = fake_client.project.members
    disabled = replace(members[0], activated=False)
    fake_client.project = replace(fake_client.project, members=(disabled, *members[1:]))
    await init_integration.runtime_data.async_refresh()
    response = await call(hass, "add_member", name=members[0].name.upper(), weight=2)
    assert response == {"project": PROJECT, "id": members[0].id, "reactivated": True}
    ((name, args, kwargs),) = writes(fake_client)
    assert (name, args) == ("update_member", (PROJECT, members[0].id))
    assert kwargs == {"weight": 2.0, "color": None, "activated": True}


async def test_add_member_refuses_an_active_name(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    with pytest.raises(ServiceValidationError) as info:
        await call(hass, "add_member", name="util1")
    assert info.value.translation_key == "member_exists"
    assert not writes(fake_client)


async def test_data_is_refreshed_even_when_the_request_fails(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    refreshes = 0
    coordinator = init_integration.runtime_data
    original = coordinator.async_refresh

    async def counting() -> None:
        nonlocal refreshes
        refreshes += 1
        await original()

    coordinator.async_refresh = counting
    fake_client.write_error = CospendForbiddenError("non")
    before = refreshes
    with pytest.raises(HomeAssistantError):
        await call(hass, "add_member", name="Zoé")
    assert refreshes - before >= 2  # une fois avant l'appel, une fois après l'échec
