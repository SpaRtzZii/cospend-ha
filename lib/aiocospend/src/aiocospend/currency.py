"""Métadonnée de devise étrangère dans le commentaire d'une dépense.

Cospend ne stocke qu'un montant dans la devise du projet. Cowspent garde le montant d'origine
dans le commentaire, sous la forme ``#NOM:MONTANT@TAUX`` (le montant enregistré est
``MONTANT × TAUX``), à la fin du commentaire et seulement si le taux n'est pas 1
(``EditBillViewModel.getFinalComment`` / ``initFromBill``). Le nom peut contenir des espaces et
des symboles ; les montants n'ont ni signe ni exposant et acceptent la virgule. Écart volontaire :
un nom de devise ne peut pas contenir ``#``, pour ne pas avaler un ``#`` du commentaire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .utils import format_amount

_PATTERN = re.compile(r"#(?P<code>[^:#]+):(?P<amount>[\d.,]+)@(?P<rate>[\d.,]+)")


@dataclass(frozen=True, slots=True)
class ForeignAmount:
    code: str
    amount: Decimal
    rate: Decimal


def split_comment(comment: str) -> tuple[str, ForeignAmount | None]:
    """Sépare le texte du commentaire de la métadonnée de devise éventuelle."""
    match = _PATTERN.search(comment)
    if match is None:
        return comment, None
    try:
        foreign = ForeignAmount(
            match["code"],
            Decimal(match["amount"].replace(",", ".")),
            Decimal(match["rate"].replace(",", ".")),
        )
    except InvalidOperation:
        return comment, None
    text = (comment[: match.start()] + comment[match.end() :]).strip()
    return text, foreign


def join_comment(comment: str, foreign: ForeignAmount | None) -> str:
    """Ajoute (ou remplace) la métadonnée de devise à la fin du commentaire."""
    text, _ = split_comment(comment)
    if foreign is None or foreign.rate == 1:
        return text
    tag = f"#{foreign.code}:{format_amount(foreign.amount)}@{format_amount(foreign.rate)}"
    return f"{text} {tag}".strip()
