"""Création, modification et suppression de dépenses (logique de Cowspent).

Règles :

* une répartition égale = une seule dépense ; une répartition par montants ou pourcentages = une
  dépense par participant, toutes avec le même titre, la même seconde, le même commentaire…
  (voir ``grouping``) ;
* une opération sur plusieurs dépenses est séquentielle et **jamais rejouée** : si elle échoue en
  cours de route, ``PartialWriteError`` indique exactement ce qui a déjà été fait ;
* les suppressions vont à la corbeille (une seconde suppression serait définitive).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from .const import NO_CATEGORY_ID, NO_PAYMENT_MODE_ID, REPEAT_CODES, REPEAT_NONE
from .currency import ForeignAmount, join_comment, split_comment
from .exceptions import CospendError, CospendNotFoundError
from .expression import parse_amount
from .grouping import GroupedBill, find_group
from .models import Bill, Project
from .splits import SplitError, SplitMode, SplitPart, allocate, compute_split, from_cents, to_cents

if TYPE_CHECKING:
    from .client import CospendClient

_RATE = Decimal("0.000001")


class ResolutionError(ValueError):
    """Membre, catégorie, mode de paiement ou devise introuvable (ou ambigu)."""


class PartialWriteError(CospendError):
    """Une opération multiple s'est arrêtée en cours de route.

    ``done`` liste les identifiants déjà traités ; rien n'a été annulé ni rejoué.
    """

    def __init__(self, message: str, *, done: list[int], cause: Exception) -> None:
        super().__init__(message)
        self.done = done
        self.cause = cause


# --------------------------------------------------------------------- résolution


def _match(candidates: Mapping[int, str], ref: str | int, kind: str) -> int:
    text = str(ref).strip()
    by_name = [i for i, name in candidates.items() if name.casefold() == text.casefold()]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise ResolutionError(f"{kind} ambigu : « {text} » correspond à plusieurs éléments")
    if text.lstrip("-").isdigit() and int(text) in candidates:
        return int(text)
    raise ResolutionError(f"{kind} introuvable : « {text} »")


def resolve_member(project: Project, ref: str | int) -> int:
    return _match({m.id: m.name for m in project.members}, ref, "membre")


def resolve_category(project: Project, ref: str | int | None) -> int:
    if ref in (None, ""):
        return NO_CATEGORY_ID
    return _match({c.id: c.name for c in project.categories}, ref, "catégorie")


def resolve_payment_mode(project: Project, ref: str | int | None) -> tuple[int, str]:
    """Renvoie l'identifiant du mode de paiement et son ancien code d'une lettre."""
    if ref in (None, ""):
        return NO_PAYMENT_MODE_ID, "n"
    mode_id = _match({p.id: p.name for p in project.payment_modes}, ref, "mode de paiement")
    mode = next(p for p in project.payment_modes if p.id == mode_id)
    return mode_id, mode.old_id or "n"


def resolve_owers(project: Project, owers: list[str | int] | None) -> list[int]:
    """Participants : la liste donnée, ou tous les membres actifs."""
    if not owers:
        ids = [m.id for m in project.members if m.activated]
        if not ids:
            raise ResolutionError("le projet n'a aucun membre actif")
        return ids
    return list(dict.fromkeys(resolve_member(project, ref) for ref in owers))


def resolve_rate(project: Project, currency: str, rate: Decimal | None) -> Decimal | None:
    """Taux de la devise étrangère, ou ``None`` si c'est la devise du projet."""
    if project.currency_name and currency.casefold() == project.currency_name.casefold():
        return None
    if rate is not None:
        if rate <= 0:
            raise ResolutionError("le taux de change doit être positif")
        return rate
    for known in project.currencies:
        if known.name.casefold() == currency.casefold():
            return Decimal(str(known.exchange_rate)).quantize(_RATE).normalize()
    raise ResolutionError(f"devise inconnue : « {currency} » (indique un taux de change)")


def _repeat(repeat: str | None) -> str:
    code = repeat or REPEAT_NONE
    if code not in REPEAT_CODES:
        raise ResolutionError(f"récurrence invalide : « {code} »")
    return code


# ------------------------------------------------------------------------ création


def _stamp(when: datetime) -> tuple[int, str]:
    if when.tzinfo is None:
        raise ValueError("la date doit avoir un fuseau horaire")
    return int(when.timestamp()), when.date().isoformat()


async def add_bill(
    client: CospendClient,
    project: Project,
    *,
    what: str,
    amount: str | int | float | Decimal,
    payer: str | int,
    when: datetime,
    owers: list[str | int] | None = None,
    mode: SplitMode = SplitMode.EVEN,
    shares: Mapping[str | int, str | int | float | Decimal] | None = None,
    comment: str = "",
    category: str | int | None = None,
    payment_mode: str | int | None = None,
    currency: str | None = None,
    exchange_rate: Decimal | None = None,
    repeat: str | None = None,
    repeat_freq: int | None = None,
    repeat_until: str | None = None,
    repeat_all_active: int | None = None,
) -> list[int]:
    """Crée une dépense (ou plusieurs, pour une répartition personnalisée) et renvoie les ids."""
    if not what.strip():
        raise ValueError("le titre est requis")
    total = parse_amount(amount)
    payer_id = resolve_member(project, payer)
    ower_ids = resolve_owers(project, owers)
    category_id = resolve_category(project, category)
    mode_id, mode_code = resolve_payment_mode(project, payment_mode)
    repeat_code = _repeat(repeat)
    timestamp, date = _stamp(when)

    values: dict[int, Decimal] | None = None
    if mode is not SplitMode.EVEN:
        if not shares:
            raise SplitError("les parts sont requises pour cette répartition")
        values = {resolve_member(project, ref): parse_amount(v) for ref, v in shares.items()}

    parts = compute_split(total, mode, ower_ids, values)

    foreign: ForeignAmount | None = None
    if currency:
        rate = resolve_rate(project, currency.strip(), exchange_rate)
        if rate is not None and rate != 1:
            foreign = ForeignAmount(currency.strip(), total, rate)
            main_total = (total * rate).quantize(Decimal("0.01"))
            if main_total <= 0:
                raise SplitError("le montant converti est nul")
            cents = allocate(to_cents(main_total), [p.amount for p in parts])
            parts = [
                SplitPart(p.ower_ids, from_cents(c))
                for p, c in zip(parts, cents, strict=True)
                if c > 0
            ]
    full_comment = join_comment(comment, foreign)

    created: list[int] = []
    for part in parts:
        try:
            bill_id = await client.create_bill(
                project.id,
                what=what.strip(),
                amount=part.amount,
                payer_id=payer_id,
                payed_for=part.ower_ids,
                timestamp=timestamp,
                date=date,
                comment=full_comment,
                category_id=category_id,
                payment_mode_id=mode_id,
                payment_mode=mode_code,
                repeat=repeat_code,
                repeat_freq=repeat_freq,
                repeat_until=repeat_until,
                repeat_all_active=repeat_all_active,
            )
        except Exception as err:
            if not created:
                raise
            raise PartialWriteError(
                f"{len(created)} dépense(s) sur {len(parts)} créée(s) avant l'échec : {created}",
                done=created,
                cause=err,
            ) from err
        created.append(bill_id)
    return created


# ------------------------------------------------------------------ modification


def _locate(bills: Mapping[int, Bill], bill_id: int) -> GroupedBill:
    group = find_group(bills.values(), bill_id)
    if group is None:
        raise CospendNotFoundError(f"dépense {bill_id} inconnue")
    return group


async def update_bill(
    client: CospendClient,
    project: Project,
    bills: Mapping[int, Bill],
    bill_id: int,
    *,
    what: str | None = None,
    amount: str | int | float | Decimal | None = None,
    payer: str | int | None = None,
    owers: list[str | int] | None = None,
    when: datetime | None = None,
    comment: str | None = None,
    category: str | int | None = None,
    payment_mode: str | int | None = None,
) -> list[int]:
    """Modifie une dépense ; pour un groupe, les champs communs sont appliqués à toutes.

    Le montant et les participants d'un groupe ne sont pas modifiables (supprime et recrée).
    """
    group = _locate(bills, bill_id)
    changes_split = amount is not None or owers is not None
    if group.is_group and changes_split:
        raise SplitError(
            "le montant et les participants d'une dépense à répartition personnalisée ne "
            "peuvent pas être modifiés : supprime-la puis recrée-la"
        )

    fields: dict[str, object] = {}
    if what is not None:
        if not what.strip():
            raise ValueError("le titre ne peut pas être vide")
        fields["what"] = what.strip()
    if payer is not None:
        fields["payer_id"] = resolve_member(project, payer)
    if when is not None:
        fields["timestamp"], fields["date"] = _stamp(when)
    if category is not None:
        fields["category_id"] = resolve_category(project, category)
    if payment_mode is not None:
        fields["payment_mode_id"], fields["payment_mode"] = resolve_payment_mode(
            project, payment_mode
        )
    if owers is not None:
        fields["payed_for"] = resolve_owers(project, owers)
    if amount is not None:
        value = parse_amount(amount)
        if value <= 0:
            raise SplitError("le montant doit être positif")
        fields["amount"] = value
    if not fields and comment is None:
        raise ValueError("aucun champ à modifier")

    updated: list[int] = []
    for bill in group.bills:
        bill_fields = dict(fields)
        if comment is not None or "amount" in fields:
            text, foreign = split_comment(bill.comment)
            if "amount" in fields:
                foreign = None  # la métadonnée de devise serait périmée
            if comment is not None:
                text = comment
            bill_fields["comment"] = join_comment(text, foreign)
        try:
            await client.update_bill(project.id, bill.id, **bill_fields)
        except Exception as err:
            if not updated:
                raise
            raise PartialWriteError(
                f"{len(updated)} dépense(s) sur {len(group.bills)} modifiée(s) avant l'échec",
                done=updated,
                cause=err,
            ) from err
        updated.append(bill.id)
    return updated


# ------------------------------------------------------------------- suppression


async def delete_bill(
    client: CospendClient,
    project_id: str,
    bills: Mapping[int, Bill],
    bill_id: int,
    *,
    whole_group: bool = True,
) -> list[int]:
    """Met à la corbeille une dépense, ou tout son groupe. Jamais rejoué."""
    group = _locate(bills, bill_id)
    targets = list(group.ids) if whole_group else [bill_id]
    deleted: list[int] = []
    for target in targets:
        try:
            await client.delete_bill(project_id, target)
        except Exception as err:
            if not deleted:
                raise
            raise PartialWriteError(
                f"{len(deleted)} dépense(s) sur {len(targets)} supprimée(s) avant l'échec",
                done=deleted,
                cause=err,
            ) from err
        deleted.append(target)
    return deleted
