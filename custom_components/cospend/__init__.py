"""Intégration Cospend pour Home Assistant."""

from __future__ import annotations

from homeassistant.const import (
    CONF_PASSWORD,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from aiocospend import CospendClient

from .const import DOMAIN
from .coordinator import CospendConfigEntry, CospendCoordinator
from .services import async_setup_services

PLATFORMS = [Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Enregistre les services, indépendamment des entrées de configuration."""
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: CospendConfigEntry) -> bool:
    """Prépare une entrée : client, première lecture, plateformes."""
    session = async_get_clientsession(hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True))
    client = CospendClient(
        session,
        entry.data[CONF_URL],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = CospendCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CospendConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_update(hass: HomeAssistant, entry: CospendConfigEntry) -> None:
    """Recharge l'entrée quand les options changent (projets, intervalles)."""
    await hass.config_entries.async_reload(entry.entry_id)
