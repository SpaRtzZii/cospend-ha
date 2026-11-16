"""Test de fumée de l'intégration : elle se charge sans erreur."""

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.cospend.const import DOMAIN


async def test_setup(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, DOMAIN, {})
