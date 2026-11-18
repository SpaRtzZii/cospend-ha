"""Création, modification et suppression de dépenses (logique de Cowspent).

Règles :

* une répartition égale = une seule dépense ; une répartition par montants ou pourcentages = une
  dépense par participant, toutes avec le même titre, la même seconde, le même commentaire…
  (voir ``grouping``) ;
* une opération sur plusieurs dépenses est séquentielle et **jamais rejouée** : si elle échoue en
  cours de route, ``PartialWriteError`` indique exactement ce qui a déjà été fait ;
* les suppressions vont à la corbeille (une seconde suppression serait définitive) ;
* chaque opération se décompose en un **plan** (calculé sans réseau, sérialisable en JSON) et une
  **exécution** : c'est ce qui permet à l'intégration de mettre un plan en file d'attente quand
  Cospend est injoignable, puis de le rejouer sans doublon (``spec_matches_bill`` et
  ``fields_applied`` détectent ce qui a déjà été fait).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .const import NO_CATEGORY_ID, NO_PAYMENT_MODE_ID, REPEAT_CODES, REPEAT_NONE
from .currency import ForeignAmount, join_comment, split_comment
from .exceptions import (
    CospendConnectionError,
    CospendError,
    CospendMaintenanceError,
    CospendNotFoundError,
    CospendServerError,
    CospendSSLError,
)
from .expression import parse_amount
from .grouping import GroupedBill, find_group
from .models import Bill, Project
from .splits import SplitError, SplitMode, SplitPart, allocate, compute_split, from_cents, to_cents
from .utils import format_amount

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


# ------------------------------------------------------------------ classification


def is_transient(error: BaseException) -> bool:
    """Erreur passagère (réseau, maintenance, 5xx) : l'opération peut être rejouée plus tard.

    Les erreurs de certificat, d'authentification, de droits ou de requête ne le sont pas.
    """
    if isinstance(error, CospendSSLError):
        return False
    return isinstance(error, CospendConnectionError | CospendMaintenanceError | CospendServerError)


# ------------------------------------------------------------------------ création


def _stamp(when: datetime) -> tuple[int, str]:
    if when.tzinfo is None:
        raise ValueError("la date doit avoir un fuseau horaire")
    return int(when.timestamp()), when.date().isoformat()


def plan_add_bill(
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
) -> list[dict[str, Any]]:
    """Calcule les dépenses à créer (arguments de ``create_bill``, sérialisables en JSON)."""
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

    return [
        {
            "what": what.strip(),
            "amount": format_amount(part.amount),
            "payer_id": payer_id,
            "payed_for": list(part.ower_ids),
            "timestamp": timestamp,
            "date": date,
            "comment": full_comment,
            "category_id": category_id,
            "payment_mode_id": mode_id,
            "payment_mode": mode_code,
            "repeat": repeat_code,
            "repeat_freq": repeat_freq,
            "repeat_until": repeat_until,
            "repeat_all_active": repeat_all_active,
        }
        for part in parts
    ]


async def _run_steps(items: Sequence[Any], step, label: str) -> list[int]:
    """Exécute ``step(item)`` en séquence ; en cas d'échec, signale ce qui est déjà fait."""
    done: list[int] = []
    for item in items:
        try:
            done.append(await step(item))
        except Exception as err:
            if not done:
                raise
            raise PartialWriteError(
                f"{len(done)} dépense(s) sur {len(items)} {label} avant l'échec : {done}",
                done=done,
                cause=err,
            ) from err
    return done


async def execute_creates(
    client: CospendClient, project_id: str, specs: Sequence[Mapping[str, Any]]
) -> list[int]:
    """Crée les dépenses d'un plan, dans l'ordre, sans jamais rejouer."""

    async def step(spec: Mapping[str, Any]) -> int:
        return await client.create_bill(project_id, **spec)

    return await _run_steps(specs, step, "créée(s)")


async def add_bill(client: CospendClient, project: Project, **kwargs: Any) -> list[int]:
    """Crée une dépense (ou plusieurs, pour une répartition personnalisée) et renvoie les ids."""
    return await execute_creates(client, project.id, plan_add_bill(project, **kwargs))


# ------------------------------------------------------------------ modification


def _locate(bills: Mapping[int, Bill], bill_id: int) -> GroupedBill:
    group = find_group(bills.values(), bill_id)
    if group is None:
        raise CospendNotFoundError(f"dépense {bill_id} inconnue")
    return group


def plan_update_bill(
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
) -> list[tuple[int, dict[str, Any]]]:
    """Calcule les modifications (identifiant, champs), un couple par dépense concernée.

    Pour un groupe, les champs communs sont appliqués à toutes ses dépenses ; le montant et
    les participants d'un groupe ne sont pas modifiables (supprimer puis recréer).
    """
    group = _locate(bills, bill_id)
    if group.is_group and (amount is not None or owers is not None):
        raise SplitError(
            "le montant et les participants d'une dépense à répartition personnalisée ne "
            "peuvent pas être modifiés : supprime-la puis recrée-la"
        )

    fields: dict[str, Any] = {}
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
        fields["amount"] = format_amount(value)
    if not fields and comment is None:
        raise ValueError("aucun champ à modifier")

    plan: list[tuple[int, dict[str, Any]]] = []
    for bill in group.bills:
        bill_fields = dict(fields)
        if comment is not None or "amount" in fields:
            text, foreign = split_comment(bill.comment)
            if "amount" in fields:
                foreign = None  # la métadonnée de devise serait périmée
            if comment is not None:
                text = comment
            bill_fields["comment"] = join_comment(text, foreign)
        plan.append((bill.id, bill_fields))
    return plan


async def execute_updates(
    client: CospendClient, project_id: str, plan: Sequence[tuple[int, Mapping[str, Any]]]
) -> list[int]:
    async def step(item: tuple[int, Mapping[str, Any]]) -> int:
        bill_id, fields = item
        await client.update_bill(project_id, bill_id, **fields)
        return bill_id

    return await _run_steps(plan, step, "modifiée(s)")


async def update_bill(
    client: CospendClient,
    project: Project,
    bills: Mapping[int, Bill],
    bill_id: int,
    **kwargs: Any,
) -> list[int]:
    """Modifie une dépense ; pour un groupe, les champs communs sont appliqués à toutes."""
    plan = plan_update_bill(project, bills, bill_id, **kwargs)
    return await execute_updates(client, project.id, plan)


# ------------------------------------------------------------------- suppression


def plan_delete_bill(
    bills: Mapping[int, Bill], bill_id: int, *, whole_group: bool = True
) -> list[int]:
    """Identifiants à mettre à la corbeille : la dépense, ou tout son groupe."""
    group = _locate(bills, bill_id)
    return list(group.ids) if whole_group else [bill_id]


async def execute_deletes(
    client: CospendClient, project_id: str, bill_ids: Sequence[int]
) -> list[int]:
    """Met à la corbeille, une fois chacune. Jamais rejoué."""

    async def step(bill_id: int) -> int:
        await client.delete_bill(project_id, bill_id)
        return bill_id

    return await _run_steps(bill_ids, step, "supprimée(s)")


async def delete_bill(
    client: CospendClient,
    project_id: str,
    bills: Mapping[int, Bill],
    bill_id: int,
    *,
    whole_group: bool = True,
) -> list[int]:
    """Met à la corbeille une dépense, ou tout son groupe. Jamais rejoué."""
    return await execute_deletes(
        client, project_id, plan_delete_bill(bills, bill_id, whole_group=whole_group)
    )


# ------------------------------------------------- détection de ce qui est déjà fait


def _same_amount(left: float, right: str | float) -> bool:
    return abs(float(left) - float(right)) < 0.005


def spec_matches_bill(spec: Mapping[str, Any], bill: Bill) -> bool:
    """La dépense du serveur est-elle celle que ce plan de création produirait ?

    Sert à ne pas recréer une dépense dont la création a abouti sans que la réponse nous soit
    parvenue (délai dépassé, coupure) : titre, seconde, payeur, montant, participants et
    commentaire doivent tous correspondre.
    """
    return (
        bill.what == spec["what"]
        and bill.timestamp == spec["timestamp"]
        and bill.payer_id == spec["payer_id"]
        and _same_amount(bill.amount, spec["amount"])
        and set(bill.ower_ids) == set(spec["payed_for"])
        and bill.comment == spec["comment"]
    )


def fields_applied(fields: Mapping[str, Any], bill: Bill) -> bool:
    """Tous les champs d'une modification sont-ils déjà ceux de la dépense du serveur ?"""
    checks = {
        "what": lambda v: bill.what == v,
        "payer_id": lambda v: bill.payer_id == v,
        "timestamp": lambda v: bill.timestamp == v,
        "date": lambda v: bill.date == v,
        "category_id": lambda v: bill.category_id == v,
        "payment_mode_id": lambda v: bill.payment_mode_id == v,
        "payment_mode": lambda v: bill.payment_mode == v,
        "payed_for": lambda v: set(bill.ower_ids) == set(v),
        "amount": lambda v: _same_amount(bill.amount, v),
        "comment": lambda v: bill.comment == v,
    }
    return all(checks[key](value) for key, value in fields.items() if key in checks)
