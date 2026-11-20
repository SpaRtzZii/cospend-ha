"""Intégration Cospend pour Home Assistant."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
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
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from aiocospend import CospendClient

from .const import DOMAIN, FLUSH_INTERVAL_SECONDS
from .coordinator import CospendConfigEntry, CospendCoordinator
from .queue import OperationQueue, async_flush
from .services import async_setup_services
from .websocket import async_setup_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]
CARD_URL = f"/{DOMAIN}_static/cospend-card.js"
CARD_FILE = Path(__file__).parent / "www" / "cospend-card.js"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Enregistre les services, indépendamment des entrées de configuration."""
    async_setup_services(hass)
    async_setup_websocket(hass)
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Sert la carte Lovelace et la charge dans le navigateur (aucune ressource à ajouter)."""
    if not CARD_FILE.is_file():
        _LOGGER.debug("Carte Lovelace absente (%s) : version de développement", CARD_FILE)
        return
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_FILE), cache_headers=False)]
    )
    try:
        add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    except KeyError:
        # Pas d'interface web (frontend absent) : l'intégration fonctionne sans la carte.
        _LOGGER.debug("Le frontend n'est pas chargé : la carte Cospend n'est pas injectée")


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
    await coordinator.queue.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))

    async def _flush(_: datetime | None = None) -> None:
        await async_flush(coordinator)

    # Rejeu des écritures en attente : au démarrage, puis toutes les minutes.
    entry.async_create_background_task(hass, _flush(), f"{DOMAIN} flush {entry.entry_id}")
    entry.async_on_unload(
        async_track_time_interval(hass, _flush, timedelta(seconds=FLUSH_INTERVAL_SECONDS))
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: CospendConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_update(hass: HomeAssistant, entry: CospendConfigEntry) -> None:
    """Recharge l'entrée quand les options changent (projets, intervalles)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: CospendConfigEntry) -> None:
    """Supprime la file d'attente enregistrée quand l'entrée est retirée."""
    queue = OperationQueue(hass, entry.entry_id)
    await queue.async_load()
    await queue.async_remove_storage()
