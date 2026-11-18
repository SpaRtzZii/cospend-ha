"""Calcul d'un montant saisi comme expression (``12,5 + 3*2``), sans ``eval``.

Opérateurs : ``+ - * /``, parenthèses, moins unaire. La virgule et le point sont acceptés comme
séparateur décimal. Le résultat est arrondi à 2 décimales (demi vers le haut).
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, DivisionByZero, InvalidOperation

_TOKEN = re.compile(r"\s*(?:(\d+(?:[.,]\d+)?|[.,]\d+)|(.))")
_MAX_LENGTH = 200
_MAX_DEPTH = 32
_CENT = Decimal("0.01")


class ExpressionError(ValueError):
    """Expression de montant invalide."""


def _tokens(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    position = 0
    text = text.strip()
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None or match.end() == position:
            break
        number, other = match.groups()
        if number is not None:
            out.append(("num", number.replace(",", ".")))
        elif other in "+-*/()":
            out.append(("op", other))
        elif other == "×":
            out.append(("op", "*"))
        elif other == "÷":
            out.append(("op", "/"))
        elif not other.isspace():
            raise ExpressionError(f"caractère inattendu : {other!r}")
        position = match.end()
    return out


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._index = 0
        self._depth = 0

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _take(self) -> tuple[str, str]:
        token = self._tokens[self._index]
        self._index += 1
        return token

    def parse(self) -> Decimal:
        value = self._expression()
        if self._peek() is not None:
            raise ExpressionError("expression incomplète ou mal formée")
        return value

    def _expression(self) -> Decimal:
        value = self._term()
        while (token := self._peek()) and token in (("op", "+"), ("op", "-")):
            self._take()
            right = self._term()
            value = value + right if token[1] == "+" else value - right
        return value

    def _term(self) -> Decimal:
        value = self._factor()
        while (token := self._peek()) and token in (("op", "*"), ("op", "/")):
            self._take()
            right = self._factor()
            if token[1] == "*":
                value *= right
            else:
                if right == 0:
                    raise ExpressionError("division par zéro")
                value /= right
        return value

    def _factor(self) -> Decimal:
        token = self._peek()
        if token is None:
            raise ExpressionError("expression incomplète")
        if token == ("op", "-"):
            self._take()
            return -self._factor()
        if token == ("op", "+"):
            self._take()
            return self._factor()
        if token[0] == "num":
            self._take()
            return Decimal(token[1])
        if token == ("op", "("):
            self._take()
            self._depth += 1
            if self._depth > _MAX_DEPTH:
                raise ExpressionError("parenthèses trop imbriquées")
            value = self._expression()
            if self._peek() != ("op", ")"):
                raise ExpressionError("parenthèse fermante manquante")
            self._take()
            self._depth -= 1
            return value
        raise ExpressionError(f"élément inattendu : {token[1]!r}")


def parse_amount(value: str | int | float | Decimal) -> Decimal:
    """Évalue un montant (nombre ou expression) et l'arrondit au centime."""
    if isinstance(value, bool):
        raise ExpressionError("montant invalide")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int | float):
        result = Decimal(str(value))
    else:
        text = str(value)
        if not text.strip():
            raise ExpressionError("montant vide")
        if len(text) > _MAX_LENGTH:
            raise ExpressionError("expression trop longue")
        try:
            result = _Parser(_tokens(text)).parse()
        except (InvalidOperation, DivisionByZero) as err:
            raise ExpressionError("expression invalide") from err
    if not result.is_finite():
        raise ExpressionError("montant invalide")
    return result.quantize(_CENT, rounding=ROUND_HALF_UP)
