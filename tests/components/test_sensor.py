"""Tests des capteurs, des événements et du cycle de vie de l'intégration."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from pytest_homeassistant_custom_component.common import async_capture_events

from aiocospend import CospendAuthenticationError, CospendConnectionError
from custom_components.cospend.const import (
    DOMAIN,
    EVENT_BILL_ADDED,
    EVENT_BILL_DELETED,
    EVENT_BILL_UPDATED,
)
from custom_components.cospend.sensor import currency_unit, sensor_unique_id

from .fake_client import FakeClient

PROJECT = "teste"
UTIL1, UTIL2, UTIL3 = 12, 13, 14  # membres du projet de test


def _state(hass: HomeAssistant, entry, key: str, subject: int | None = None):
    unique_id = sensor_unique_id(entry.entry_id, PROJECT, key, subject)
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    assert entity_id is not None, unique_id
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state


async def test_project_sensors(hass: HomeAssistant, init_integration) -> None:
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED
    assert _state(hass, entry, "bills_count").state == "6"
    assert float(_state(hass, entry, "total_spent").state) == 1850

    last = _state(hass, entry, "last_bill")
    assert last.state == "util2 → util1"  # la plus récente, à date égale la plus grande id
    assert last.attributes["bill_id"] == 38
    assert last.attributes["payer"] == "util2"
    assert last.attributes["owers"] == ["util1"]
    assert float(_state(hass, entry, "last_bill_amount").state) == 16.67


async def test_member_sensors_give_balance_paid_and_spent(
    hass: HomeAssistant, init_integration
) -> None:
    entry = init_integration
    assert float(_state(hass, entry, "member_balance", UTIL1).state) == 683.33
    assert float(_state(hass, entry, "member_balance", UTIL3).state) == -666.67
    assert float(_state(hass, entry, "member_paid", UTIL1).state) == 1250
    assert float(_state(hass, entry, "member_paid", UTIL3).state) == 0
    assert float(_state(hass, entry, "member_spent", UTIL1).state) == 566.67
    assert float(_state(hass, entry, "member_spent", UTIL2).state) == 616.67


async def test_category_sensors_feed_analysis_graphs(hass: HomeAssistant, init_integration) -> None:
    entry = init_integration
    assert float(_state(hass, entry, "category_total", 36).state) == 1250  # Bar/Fête
    assert float(_state(hass, entry, "category_total", 35).state) == 600  # Courses
    assert float(_state(hass, entry, "category_total", 37).state) == 0  # Loyer


async def test_payment_mode_sensors_are_disabled_by_default(
    hass: HomeAssistant, init_integration
) -> None:
    entry = init_integration
    unique_id = sensor_unique_id(entry.entry_id, PROJECT, "payment_mode_total", 16)
    registry_entry = er.async_get(hass).async_get(
        er.async_get(hass).async_get_entity_id("sensor", DOMAIN, unique_id)
    )
    assert registry_entry is not None
    assert registry_entry.disabled_by is RegistryEntryDisabler.INTEGRATION


async def test_month_spent_uses_the_current_month(
    hass: HomeAssistant, mock_config_entry, fake_client: FakeClient, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-11-20 12:00:00")
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.cospend.CospendClient", return_value=fake_client):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert float(_state(hass, mock_config_entry, "month_spent").state) == 1850

    freezer.move_to("2026-12-02 08:00:00")
    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert float(_state(hass, mock_config_entry, "month_spent").state) == 0


async def test_no_event_on_first_read_then_events_on_changes(
    hass: HomeAssistant, mock_config_entry, fake_client: FakeClient
) -> None:
    added = async_capture_events(hass, EVENT_BILL_ADDED)
    updated = async_capture_events(hass, EVENT_BILL_UPDATED)
    deleted = async_capture_events(hass, EVENT_BILL_DELETED)

    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.cospend.CospendClient", return_value=fake_client):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert not (added or updated or deleted)  # la première lecture sert de point de départ

    coordinator = mock_config_entry.runtime_data
    fake_client.simulate_add(100, what="Restaurant", amount=42.5, payer_id=UTIL1)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(added) == 1
    assert added[0].data["bill_id"] == 100
    assert added[0].data["what"] == "Restaurant"
    assert added[0].data["project_id"] == PROJECT
    assert added[0].data["payer_name"] == "util1"

    fake_client.simulate_update(100, amount=45.0)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert [e.data["amount"] for e in updated] == [45.0]

    fake_client.simulate_delete(100)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert [e.data["bill_id"] for e in deleted] == [100]
    assert len(added) == 1  # rien de plus


async def test_new_bill_updates_sensors(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    entry = init_integration
    fake_client.simulate_add(101, what="Cinéma", amount=18)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert _state(hass, entry, "bills_count").state == "7"
    assert _state(hass, entry, "last_bill").state == "Cinéma"
    assert fake_client.statistics_calls == 2  # lecture initiale, puis après le changement


async def test_statistics_are_not_refetched_without_changes(
    hass: HomeAssistant, init_integration, fake_client: FakeClient
) -> None:
    await init_integration.runtime_data.async_refresh()
    await init_integration.runtime_data.async_refresh()
    assert fake_client.statistics_calls == 1


async def test_authentication_failure_starts_reauth(
    hass: HomeAssistant, mock_config_entry, fake_client: FakeClient
) -> None:
    fake_client.error = CospendAuthenticationError("401")
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.cospend.CospendClient", return_value=fake_client):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_connection_failure_is_retried(
    hass: HomeAssistant, mock_config_entry, fake_client: FakeClient
) -> None:
    fake_client.error = CospendConnectionError("down")
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.cospend.CospendClient", return_value=fake_client):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_device_shows_the_project_name(hass: HomeAssistant, init_integration) -> None:
    """Le nom du projet (et non « Project ») s'affiche sous la fiche de l'appareil."""
    entry = init_integration
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, f"{entry.entry_id}_{PROJECT}")}
    )
    assert device is not None
    assert device.name == PROJECT
    assert device.model == PROJECT


async def test_unload(hass: HomeAssistant, init_integration) -> None:
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_diagnostics_hide_secrets(hass: HomeAssistant, init_integration) -> None:
    from custom_components.cospend.diagnostics import async_get_config_entry_diagnostics

    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    text = str(diagnostics)
    assert "secret" not in text and "cloud.example.org" not in text and "admin" not in text
    assert diagnostics["projects"][0]["bills_cached"] == 6
    assert diagnostics["last_update_success"] is True


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (None, (None, False)),
        ("", (None, False)),
        ("euro", ("EUR", True)),
        ("EUR", ("EUR", True)),
        ("€", ("EUR", True)),
        ("$", ("USD", True)),
        ("francs pacifiques", ("francs pacifiques", False)),
    ],
)
def test_currency_unit(name: str | None, expected: tuple[str | None, bool]) -> None:
    assert currency_unit(name) == expected
