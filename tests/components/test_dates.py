"""Date d'affichage d'une dépense : fuseau de Home Assistant, pas UTC."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.core import HomeAssistant

from aiocospend import Bill
from custom_components.cospend.dates import bill_local_date


def _bill(timestamp: int, date: str) -> Bill:
    return Bill.from_api(
        {
            "id": 1,
            "what": "x",
            "amount": 1,
            "timestamp": timestamp,
            "date": date,
            "payer_id": 1,
            "owers": [],
        }
    )


async def test_local_date_follows_home_assistant_timezone(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Paris")
    # 20/11 00:30 à Paris = 19/11 23:30 UTC : le serveur renvoie le 19, Cospend affiche le 20.
    stamp = int(datetime(2026, 11, 19, 23, 30, tzinfo=UTC).timestamp())
    assert bill_local_date(_bill(stamp, "2026-11-19")) == "2026-11-20"


async def test_local_date_without_timestamp_uses_server_date(hass: HomeAssistant) -> None:
    assert bill_local_date(_bill(0, "2026-11-19")) == "2026-11-19"
