"""Intégration Cospend pour Home Assistant (en développement : jalon M0)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Prépare l'intégration. Aucune fonctionnalité avant le jalon M2."""
    return True
