"""Diagnostics : informations utiles au dépannage, sans données personnelles."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_URL, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CONF_PROJECTS
from .coordinator import CospendConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, CONF_URL, CONF_PROJECTS}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CospendConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(
            {"data": dict(entry.data), "options": dict(entry.options)}, TO_REDACT
        ),
        "last_update_success": coordinator.last_update_success,
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds() if coordinator.update_interval else None
        ),
        "projects": [
            {
                "bills_cached": len(data.bills),
                "members": len(data.project.members),
                "categories": len(data.project.categories),
                "payment_modes": len(data.project.payment_modes),
                "has_statistics": data.statistics is not None,
                "archived": data.project.is_archived,
                "access_level": data.project.access_level,
            }
            for data in (coordinator.data or {}).values()
        ],
    }
