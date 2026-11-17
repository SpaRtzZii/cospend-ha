"""Utilitaires : adresse du serveur, versions, formatage des montants."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

# Segments qu'un utilisateur colle souvent à la fin de l'adresse de son Nextcloud.
_CUT_MARKERS = ("/index.php", "/apps/", "/ocs/", "/status.php", "/login", "/remote.php")


def normalize_url(url: str) -> str:
    """Normalise l'adresse d'un Nextcloud.

    Ajoute ``https://`` si aucun schéma n'est donné, retire la requête, le fragment, le slash
    final et tout ce qui suit ``/index.php``, ``/apps/``, ``/ocs/``, etc. Conserve un
    éventuel sous-dossier (``https://exemple.org/nextcloud``).
    """
    raw = url.strip()
    if not raw:
        raise ValueError("adresse vide")
    if "://" not in raw:
        raw = f"https://{raw}"
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"adresse invalide : {url!r}")
    path = parts.path
    for marker in _CUT_MARKERS:
        index = path.find(marker if marker.endswith("/") else marker)
        if index != -1:
            path = path[:index]
    path = path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


def parse_version(version: str) -> tuple[int, ...]:
    """Convertit ``"4.3.0"`` (ou ``"4.3.0-beta.1"``) en ``(4, 3, 0)``."""
    numbers = re.match(r"^\s*(\d+(?:\.\d+)*)", version)
    if not numbers:
        raise ValueError(f"version illisible : {version!r}")
    return tuple(int(part) for part in numbers.group(1).split("."))


def compare_versions(left: str, right: str) -> int:
    """Renvoie -1, 0 ou 1 selon que ``left`` est inférieure, égale ou supérieure à ``right``."""
    a, b = parse_version(left), parse_version(right)
    size = max(len(a), len(b))
    a += (0,) * (size - len(a))
    b += (0,) * (size - len(b))
    return (a > b) - (a < b)


def format_amount(value: int | float | Decimal | str) -> str:
    """Formate un montant pour l'API (point décimal, sans exposant ni zéros inutiles).

    Les flottants passent par leur représentation la plus courte (``0.1`` donne ``"0.1"``).
    """
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except InvalidOperation as err:
        raise ValueError(f"montant invalide : {value!r}") from err
    if not number.is_finite():
        raise ValueError(f"montant invalide : {value!r}")
    text = format(number.normalize(), "f")
    return "0" if text in ("-0", "") else text
