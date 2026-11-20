"""Plan de remboursement calculé localement, à partir des soldes des membres.

Sert de repli quand le serveur Cospend ne répond pas : il donne un plan équivalent (chaque solde
est soldé) mais pas forcément identique à celui de Cospend.
"""

from __future__ import annotations

from collections.abc import Mapping

from .models import Transaction

# En dessous d'un demi-centime, un solde est considéré comme nul.
_EPSILON = 0.005


def suggest_settlement(balances: Mapping[int, float]) -> tuple[Transaction, ...]:
    """Remboursements qui soldent ``balances`` (positif : on lui doit, négatif : il doit).

    Algorithme glouton : le plus gros débiteur rembourse le plus gros créancier. Les montants
    sont calculés en centimes, donc exacts à 0,01 près, et la somme des soldes est supposée nulle
    (au centime d'arrondi près).
    """
    credit = {m: round(b * 100) for m, b in balances.items() if b > _EPSILON}
    debt = {m: round(-b * 100) for m, b in balances.items() if b < -_EPSILON}
    transactions: list[Transaction] = []
    while credit and debt:
        creditor = max(credit, key=lambda m: (credit[m], -m))
        debtor = max(debt, key=lambda m: (debt[m], -m))
        cents = min(credit[creditor], debt[debtor])
        if cents > 0:
            transactions.append(Transaction(debtor, creditor, cents / 100))
        credit[creditor] -= cents
        debt[debtor] -= cents
        if credit[creditor] <= 0:
            del credit[creditor]
        if debt[debtor] <= 0:
            del debt[debtor]
    return tuple(transactions)
