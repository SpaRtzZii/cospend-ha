"""Copie locale : l'intégration démarre même si Cospend est injoignable."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from aiocospend import CospendConnectionError
from custom_components.cospend.cache import (
    bill_from_dict,
    bill_to_dict,
    project_from_dict,
    project_to_dict,
)

from .fake_client import FakeClient

PROJECT = "teste"


def test_project_and_bills_survive_a_json_round_trip(fake_client: FakeClient) -> None:
    import json

    project = fake_client.project
    assert project_from_dict(json.loads(json.dumps(project_to_dict(project)))) == project
    for bill in fake_client.bills.values():
        assert bill_from_dict(json.loads(json.dumps(bill_to_dict(bill)))) == bill


async def _start(hass, entry, client) -> None:
    with patch("custom_components.cospend.CospendClient", return_value=client):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_starts_from_the_copy_when_cospend_is_down(
    hass: HomeAssistant,
    mock_config_entry,
    fake_client: FakeClient,
    freezer: FrozenDateTimeFactory,
) -> None:
    mock_config_entry.add_to_hass(hass)
    await _start(hass, mock_config_entry, fake_client)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    expected_bills = len(mock_config_entry.runtime_data.data[PROJECT].bills)
    assert expected_bills > 0

    # La copie est écrite peu après la lecture.
    freezer.tick(timedelta(seconds=40))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Redémarrage de Home Assistant alors que Nextcloud est éteint.
    fake_client.error = CospendConnectionError("down")
    await _start(hass, mock_config_entry, fake_client)
    assert mock_config_entry.state is ConfigEntryState.LOADED
    coordinator = mock_config_entry.runtime_data
    assert coordinator.restored is True
    assert coordinator.last_update_success is False
    data = coordinator.data[PROJECT]
    assert data.project == fake_client.project or data.project.id == PROJECT
    assert len(data.bills) == expected_bills

    # Nextcloud revient : la prochaine minute remplace la copie par les données du serveur.
    fake_client.error = None
    freezer.tick(timedelta(seconds=70))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert coordinator.restored is False
    assert coordinator.last_update_success is True
    assert len(coordinator.data[PROJECT].bills) == expected_bills


async def test_without_a_copy_the_setup_is_retried(
    hass: HomeAssistant, mock_config_entry, fake_client: FakeClient
) -> None:
    fake_client.error = CospendConnectionError("down")
    mock_config_entry.add_to_hass(hass)
    await _start(hass, mock_config_entry, fake_client)
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_removing_the_entry_removes_the_copy(hass: HomeAssistant, init_integration) -> None:
    await hass.config_entries.async_remove(init_integration.entry_id)
    await hass.async_block_till_done()
