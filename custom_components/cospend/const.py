"""Constantes de l'intégration Cospend."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "cospend"
NAME: Final = "Cospend"

CONF_PROJECTS: Final = "projects"
CONF_FULL_RESYNC_HOURS: Final = "full_resync_hours"

DEFAULT_SCAN_INTERVAL: Final = 10  # minutes
MIN_SCAN_INTERVAL: Final = 1
MAX_SCAN_INTERVAL: Final = 1440

DEFAULT_FULL_RESYNC_HOURS: Final = 24
MIN_FULL_RESYNC_HOURS: Final = 1
MAX_FULL_RESYNC_HOURS: Final = 168

EVENT_BILL_ADDED: Final = f"{DOMAIN}_bill_added"
EVENT_BILL_UPDATED: Final = f"{DOMAIN}_bill_updated"
EVENT_BILL_DELETED: Final = f"{DOMAIN}_bill_deleted"
