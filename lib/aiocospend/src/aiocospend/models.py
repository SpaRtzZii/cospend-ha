"""Modèles de données de l'API Cospend.

Les formats viennent de réponses réelles de Cospend 4.3.0 ; voir ``tests/fixtures``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .exceptions import CospendResponseError

_MONTH = re.compile(r"^\d{4}-\d{2}$")

# Niveaux d'accès supposés d'après le code de Cospend (4 = propriétaire est confirmé) :
# à valider par les tests de contrat avant de s'appuyer dessus.
ACCESS_LEVEL_PARTICIPANT = 2


def _as_dict(value: Any) -> dict[Any, Any]:
    """Normalise une table indexée par identifiant.

    Le serveur est en PHP : un tableau dont les clés sont 0, 1, 2… est sérialisé en **liste**
    JSON au lieu d'un objet. Cas réel : des dépenses sans catégorie donnent
    ``categoryStats == [600]`` au lieu de ``{"0": 600}``. Une liste est donc lue comme
    ``{0: v0, 1: v1, …}``.
    """
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, (list, tuple)):
        return dict(enumerate(value))
    return {}


def _invalid(kind: str, err: Exception) -> CospendResponseError:
    return CospendResponseError(f"{kind} invalide dans la réponse du serveur : {err!r}")


@dataclass(frozen=True, slots=True)
class Ower:
    """Participant à une dépense."""

    id: int
    weight: float
    name: str
    activated: bool

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Ower:
        try:
            return cls(
                id=int(data["id"]),
                weight=float(data.get("weight", 1)),
                name=str(data.get("name") or ""),
                activated=bool(data.get("activated", True)),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise _invalid("Participant", err) from err


@dataclass(frozen=True, slots=True)
class Bill:
    """Dépense. Les montants sont ceux du serveur (flottants, non arrondis)."""

    id: int
    what: str
    amount: float
    comment: str
    timestamp: int
    date: str
    payer_id: int
    owers: tuple[Ower, ...]
    repeat: str
    repeat_freq: int
    repeat_until: str | None
    repeat_all_active: int
    payment_mode: str
    payment_mode_id: int
    category_id: int
    deleted: bool
    last_changed: int
    project_id: str | None = None

    @property
    def ower_ids(self) -> tuple[int, ...]:
        return tuple(ower.id for ower in self.owers)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Bill:
        try:
            return cls(
                id=int(data["id"]),
                what=str(data.get("what") or ""),
                amount=float(data["amount"]),
                comment=str(data.get("comment") or ""),
                timestamp=int(data["timestamp"]),
                date=str(data.get("date") or ""),
                payer_id=int(data["payer_id"]),
                owers=tuple(Ower.from_api(o) for o in data.get("owers") or ()),
                repeat=str(data.get("repeat") or "n"),
                repeat_freq=int(data.get("repeatfreq") or 1),
                repeat_until=data.get("repeatuntil"),
                repeat_all_active=int(data.get("repeatallactive") or 0),
                payment_mode=str(data.get("paymentmode") or "n"),
                payment_mode_id=int(data.get("paymentmodeid") or 0),
                category_id=int(data.get("categoryid") or 0),
                deleted=bool(data.get("deleted", 0)),
                last_changed=int(data.get("lastchanged") or 0),
                project_id=data.get("projectid"),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise _invalid("Dépense", err) from err


@dataclass(frozen=True, slots=True)
class BillsPage:
    """Réponse de la liste des dépenses.

    ``nb_bills`` est le total des dépenses du projet pour l'état demandé (visibles ou en
    corbeille), pas le nombre de dépenses renvoyées. ``all_bill_ids`` liste les identifiants
    de cet état : une dépense mise en corbeille en disparaît. ``timestamp`` est l'heure du
    serveur, à réutiliser comme curseur ``last_changed`` du cycle suivant.
    """

    nb_bills: int
    bills: tuple[Bill, ...]
    all_bill_ids: tuple[int, ...]
    timestamp: int

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> BillsPage:
        try:
            return cls(
                nb_bills=int(data["nb_bills"]),
                bills=tuple(Bill.from_api(b) for b in data.get("bills") or ()),
                all_bill_ids=tuple(int(i) for i in data.get("allBillIds") or ()),
                timestamp=int(data["timestamp"]),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise _invalid("Liste de dépenses", err) from err


@dataclass(frozen=True, slots=True)
class Member:
    id: int
    name: str
    weight: float
    activated: bool
    last_changed: int
    user_id: str | None
    color: tuple[int, int, int] | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Member:
        try:
            color = data.get("color")
            return cls(
                id=int(data["id"]),
                name=str(data.get("name") or ""),
                weight=float(data.get("weight", 1)),
                activated=bool(data.get("activated", True)),
                last_changed=int(data.get("lastchanged") or 0),
                user_id=data.get("userid"),
                color=(int(color["r"]), int(color["g"]), int(color["b"])) if color else None,
            )
        except (KeyError, TypeError, ValueError) as err:
            raise _invalid("Membre", err) from err


@dataclass(frozen=True, slots=True)
class Category:
    id: int
    name: str
    color: str
    icon: str
    order: int

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Category:
        try:
            return cls(
                id=int(data["id"]),
                name=str(data.get("name") or ""),
                color=str(data.get("color") or ""),
                icon=str(data.get("icon") or ""),
                order=int(data.get("order") or 0),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise _invalid("Catégorie", err) from err


@dataclass(frozen=True, slots=True)
class PaymentMode:
    id: int
    name: str
    color: str
    icon: str
    order: int
    old_id: str | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> PaymentMode:
        try:
            return cls(
                id=int(data["id"]),
                name=str(data.get("name") or ""),
                color=str(data.get("color") or ""),
                icon=str(data.get("icon") or ""),
                order=int(data.get("order") or 0),
                old_id=data.get("old_id"),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise _invalid("Mode de paiement", err) from err


@dataclass(frozen=True, slots=True)
class Currency:
    id: int
    name: str
    exchange_rate: float

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Currency:
        try:
            return cls(
                id=int(data["id"]),
                name=str(data.get("name") or ""),
                exchange_rate=float(data["exchange_rate"]),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise _invalid("Devise", err) from err


@dataclass(frozen=True, slots=True)
class Share:
    """Partage d'un projet (type ``u`` utilisateur, ``l`` lien, etc.)."""

    id: int
    type: str
    access_level: int
    user_id: str | None
    name: str | None

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Share:
        try:
            return cls(
                id=int(data["id"]),
                type=str(data.get("type") or ""),
                access_level=int(data.get("accesslevel") or 0),
                user_id=data.get("userid"),
                name=data.get("name"),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise _invalid("Partage", err) from err


@dataclass(frozen=True, slots=True)
class Project:
    """Projet Cospend avec sa structure (la liste des projets renvoie déjà tout cela)."""

    id: str
    name: str
    owner_id: str | None
    currency_name: str | None
    archived_ts: int | None
    access_level: int
    last_changed: int
    nb_bills: int
    nb_trashbin_bills: int
    total_spent: float
    balance: Mapping[int, float]
    members: tuple[Member, ...]
    categories: tuple[Category, ...]
    payment_modes: tuple[PaymentMode, ...]
    currencies: tuple[Currency, ...]
    shares: tuple[Share, ...]
    deletion_disabled: bool = False

    @property
    def is_archived(self) -> bool:
        return self.archived_ts is not None

    @property
    def can_write(self) -> bool:
        """Écriture supposée possible (niveau ≥ 2). À valider par les tests de contrat."""
        return self.access_level >= ACCESS_LEVEL_PARTICIPANT

    def member(self, member_id: int) -> Member | None:
        return next((m for m in self.members if m.id == member_id), None)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Project:
        try:
            categories = sorted(
                (Category.from_api(c) for c in _as_dict(data.get("categories")).values()),
                key=lambda c: (c.order, c.id),
            )
            payment_modes = sorted(
                (PaymentMode.from_api(p) for p in _as_dict(data.get("paymentmodes")).values()),
                key=lambda p: (p.order, p.id),
            )
            archived = data.get("archived_ts")
            return cls(
                id=str(data["id"]),
                name=str(data.get("name") or data["id"]),
                owner_id=data.get("userid"),
                currency_name=data.get("currencyname"),
                archived_ts=int(archived) if archived is not None else None,
                access_level=int(data.get("myaccesslevel") or 0),
                last_changed=int(data.get("lastchanged") or 0),
                nb_bills=int(data.get("nb_bills") or 0),
                nb_trashbin_bills=int(data.get("nb_trashbin_bills") or 0),
                total_spent=float(data.get("total_spent") or 0),
                balance={int(k): float(v) for k, v in _as_dict(data.get("balance")).items()},
                members=tuple(Member.from_api(m) for m in data.get("members") or ()),
                categories=tuple(categories),
                payment_modes=tuple(payment_modes),
                currencies=tuple(Currency.from_api(c) for c in data.get("currencies") or ()),
                shares=tuple(Share.from_api(s) for s in data.get("shares") or ()),
                deletion_disabled=bool(data.get("deletiondisabled", False)),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            raise _invalid("Projet", err) from err


@dataclass(frozen=True, slots=True)
class MemberStats:
    balance: float
    filtered_balance: float
    paid: float
    spent: float
    member: Member


def _monthly_by_member(data: Mapping[str, Any] | None) -> dict[str, dict[int, float]]:
    """``{"2026-11": {"12": 1250, "0": 1850}}`` → ``{"2026-11": {12: 1250.0, 0: 1850.0}}``.

    Seules les clés au format AAAA-MM sont conservées : le serveur ajoute une entrée de
    moyenne dont le libellé est traduit (« Moyenne par mois ») et ne doit jamais servir de clé.
    """
    return {
        month: {int(k): float(v) for k, v in _as_dict(values).items()}
        for month, values in _as_dict(data).items()
        if _MONTH.match(str(month))
    }


def _monthly_by_key(data: Mapping[str, Any] | None) -> dict[int, dict[str, float]]:
    """``{"36": {"2026-11": 1250, "Moyenne par mois": 1250}}`` → ``{36: {"2026-11": 1250.0}}``."""
    return {
        int(key): {m: float(v) for m, v in _as_dict(values).items() if _MONTH.match(str(m))}
        for key, values in _as_dict(data).items()
    }


@dataclass(frozen=True, slots=True)
class ProjectStatistics:
    """Statistiques d'un projet. ``raw`` conserve la réponse complète du serveur."""

    stats: tuple[MemberStats, ...]
    months: tuple[str, ...]
    member_ids: tuple[int, ...]
    monthly_paid: Mapping[str, Mapping[int, float]]
    monthly_spent: Mapping[str, Mapping[int, float]]
    category_stats: Mapping[int, float]
    category_monthly: Mapping[int, Mapping[str, float]]
    category_member: Mapping[int, Mapping[int, float]]
    payment_mode_stats: Mapping[int, float]
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> ProjectStatistics:
        try:
            return cls(
                stats=tuple(
                    MemberStats(
                        balance=float(s["balance"]),
                        filtered_balance=float(s.get("filtered_balance", s["balance"])),
                        paid=float(s["paid"]),
                        spent=float(s["spent"]),
                        member=Member.from_api(s["member"]),
                    )
                    for s in data.get("stats") or ()
                ),
                months=tuple(str(m) for m in data.get("realMonths") or ()),
                member_ids=tuple(int(i) for i in data.get("memberIds") or ()),
                monthly_paid=_monthly_by_member(data.get("memberMonthlyPaidStats")),
                monthly_spent=_monthly_by_member(data.get("memberMonthlySpentStats")),
                category_stats={
                    int(k): float(v) for k, v in _as_dict(data.get("categoryStats")).items()
                },
                category_monthly=_monthly_by_key(data.get("categoryMonthlyStats")),
                category_member={
                    int(cat): {int(m): float(v) for m, v in _as_dict(per).items()}
                    for cat, per in _as_dict(data.get("categoryMemberStats")).items()
                },
                payment_mode_stats={
                    int(k): float(v) for k, v in _as_dict(data.get("paymentModeStats")).items()
                },
                raw=data,
            )
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            raise _invalid("Statistiques", err) from err


@dataclass(frozen=True, slots=True)
class Transaction:
    """Remboursement proposé : ``from_member`` doit ``amount`` à ``to_member``."""

    from_member: int
    to_member: int
    amount: float


@dataclass(frozen=True, slots=True)
class Settlement:
    """Plan de remboursement du serveur. Montants non arrondis (flottants)."""

    transactions: tuple[Transaction, ...]
    balances: Mapping[int, float]

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Settlement:
        try:
            return cls(
                transactions=tuple(
                    Transaction(int(t["from"]), int(t["to"]), float(t["amount"]))
                    for t in data.get("transactions") or ()
                ),
                balances={int(k): float(v) for k, v in _as_dict(data.get("balances")).items()},
            )
        except (KeyError, TypeError, ValueError, AttributeError) as err:
            raise _invalid("Plan de remboursement", err) from err


@dataclass(frozen=True, slots=True)
class ServerInfo:
    """Informations sur le serveur Cospend."""

    version: str
    federation_enabled: bool = False
