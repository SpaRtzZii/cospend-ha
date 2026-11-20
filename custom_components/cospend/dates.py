"""Date d'affichage d'une dépense."""

from __future__ import annotations

from homeassistant.util import dt as dt_util

from aiocospend import Bill


def bill_local_date(bill: Bill) -> str:
    """Jour de la dépense dans le fuseau de Home Assistant (AAAA-MM-JJ).

    Le serveur calcule son champ ``date`` en UTC, alors que l'interface de Cospend affiche
    l'horodatage dans le fuseau de l'utilisateur : une dépense saisie le 20 à 00h30 locale
    porte la date du 19 côté serveur. On part donc de l'horodatage, comme Cospend. Sans
    horodatage exploitable, on retombe sur la date du serveur.
    """
    if bill.timestamp > 0:
        try:
            return dt_util.as_local(dt_util.utc_from_timestamp(bill.timestamp)).date().isoformat()
        except (OverflowError, OSError, ValueError):
            pass
    return bill.date
