"""Fixtures des tests de l'intégration (nécessite pytest-homeassistant-custom-component)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.cospend.const import CONF_FULL_RESYNC_HOURS, CONF_PROJECTS, DOMAIN

from .fake_client import FakeClient


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Autorise le chargement de custom_components/ dans les tests Home Assistant."""
    yield


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="admin @ cloud.example.org",
        unique_id="https://cloud.example.org|admin",
        data={
            CONF_URL: "https://cloud.example.org",
            CONF_USERNAME: "admin",
            CONF_PASSWORD: "secret",
            CONF_VERIFY_SSL: True,
        },
        options={CONF_PROJECTS: ["teste"], CONF_SCAN_INTERVAL: 10, CONF_FULL_RESYNC_HOURS: 24},
    )


@pytest.fixture
def mock_flow_client(fake_client: FakeClient):
    """Remplace le client utilisé par le flux de configuration."""
    with patch("custom_components.cospend.config_flow.CospendClient", return_value=fake_client):
        yield fake_client


@pytest.fixture
def mock_setup_entry():
    """Évite de charger vraiment l'intégration à la fin d'un flux de configuration."""
    with patch("custom_components.cospend.async_setup_entry", return_value=True) as mocked:
        yield mocked


@pytest.fixture
async def init_integration(hass, mock_config_entry, fake_client) -> MockConfigEntry:
    """Intégration chargée avec le faux client."""
    mock_config_entry.add_to_hass(hass)
    with patch("custom_components.cospend.CospendClient", return_value=fake_client):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    return mock_config_entry
