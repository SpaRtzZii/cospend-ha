"""File d'attente persistante des écritures, et rejeu quand Cospend redevient joignable.

Principes (voir aussi ``aiocospend.writer``) :

* une opération est un **plan** déjà calculé (noms résolus, répartition faite) : on la rejoue
  telle quelle, sans dépendre de l'état du projet au moment du rejeu ;
* l'ordre est conservé par projet : une opération ne passe jamais devant une plus ancienne ;
* aucune écriture n'est rejouée à l'aveugle : avant de recréer une dépense dont la création a
  pu aboutir sans réponse, on la cherche sur le serveur ; une modification déjà appliquée est
  ignorée ; une suppression d'une dépense déjà absente est ignorée ;
* un conflit (dépense modifiée ou supprimée ailleurs entre-temps) n'est jamais résolu en
  silence : l'opération est **bloquée**, signalée, et attend ``retry_queued`` ou ``discard_queued``.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store

from aiocospend import (
    CospendAuthenticationError,
    PartialWriteError,
    fields_applied,
    is_transient,
    spec_matches_bill,
)

from .const import (
    DOMAIN,
    EVENT_OPERATION_BLOCKED,
    EVENT_OPERATION_QUEUED,
    EVENT_OPERATION_SYNCED,
)

if TYPE_CHECKING:
    from .coordinator import CospendCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

KIND_ADD = "add"
KIND_UPDATE = "update"
KIND_DELETE = "delete"

STATUS_PENDING = "pending"
STATUS_BLOCKED = "blocked"

REASON_CONFLICT = "conflict"
REASON_BILL_MISSING = "bill_missing"
REASON_PROJECT_MISSING = "project_missing"
REASON_REQUEST_FAILED = "request_failed"


@dataclass
class QueuedOperation:
    """Une écriture en attente."""

    id: str
    kind: str
    project_id: str
    title: str
    plan: list[Any]
    created: str
    base: dict[str, int | None] = field(default_factory=dict)
    done: list[int] = field(default_factory=list)
    status: str = STATUS_PENDING
    attempts: int = 0
    ambiguous: bool = False
    force: bool = False
    reason: str | None = None
    error: str | None = None

    @classmethod
    def new(
        cls,
        kind: str,
        project_id: str,
        title: str,
        plan: list[Any],
        *,
        base: dict[str, int | None] | None = None,
        done: list[int] | None = None,
        ambiguous: bool = False,
    ) -> QueuedOperation:
        return cls(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            project_id=project_id,
            title=title,
            plan=plan,
            created=datetime.now(UTC).isoformat(timespec="seconds"),
            base=base or {},
            done=list(done or []),
            ambiguous=ambiguous,
        )

    @property
    def remaining(self) -> int:
        return len(self.plan) - len(self.done)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "project_id": self.project_id,
            "title": self.title,
            "plan": self.plan,
            "created": self.created,
            "base": self.base,
            "done": self.done,
            "status": self.status,
            "attempts": self.attempts,
            "ambiguous": self.ambiguous,
            "force": self.force,
            "reason": self.reason,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QueuedOperation:
        plan = data["plan"]
        if data["kind"] == KIND_UPDATE:
            plan = [(int(bill_id), fields) for bill_id, fields in plan]
        return cls(
            id=data["id"],
            kind=data["kind"],
            project_id=data["project_id"],
            title=data.get("title", ""),
            plan=plan,
            created=data["created"],
            base=dict(data.get("base") or {}),
            done=[int(i) for i in data.get("done", [])],
            status=data.get("status", STATUS_PENDING),
            attempts=int(data.get("attempts", 0)),
            ambiguous=bool(data.get("ambiguous", False)),
            force=bool(data.get("force", False)),
            reason=data.get("reason"),
            error=data.get("error"),
        )

    def summary(self) -> dict[str, Any]:
        """Version lisible, pour les attributs du capteur et les événements."""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "created": self.created,
            "attempts": self.attempts,
            "parts_done": len(self.done),
            "parts_total": len(self.plan),
            "reason": self.reason,
            "error": self.error,
        }


class OperationQueue:
    """Les écritures en attente d'une entrée de configuration, conservées sur disque."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.queue.{entry_id}"
        )
        self.operations: list[QueuedOperation] = []
        self.flushing = False
        self._listeners: list[Callable[[], None]] = []

    # ---------------------------------------------------------------- persistance

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        self.operations = []
        for raw in (stored or {}).get("operations", []):
            try:
                self.operations.append(QueuedOperation.from_dict(raw))
            except (KeyError, TypeError, ValueError):
                _LOGGER.warning("Opération en file d'attente illisible, ignorée : %s", raw)
        self._sync_issues()

    async def async_save(self) -> None:
        await self._store.async_save({"operations": [op.as_dict() for op in self.operations]})
        self._sync_issues()
        self._notify()

    async def async_remove_storage(self) -> None:
        await self._store.async_remove()
        for op in self.operations:
            ir.async_delete_issue(self._hass, DOMAIN, self._issue_id(op))

    # ------------------------------------------------------------------ écoute

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # ------------------------------------------------------------------ lecture

    def for_project(self, project_id: str) -> list[QueuedOperation]:
        return [op for op in self.operations if op.project_id == project_id]

    def get(self, operation_id: str) -> QueuedOperation | None:
        return next((op for op in self.operations if op.id == operation_id), None)

    def blocked(self) -> list[QueuedOperation]:
        return [op for op in self.operations if op.status == STATUS_BLOCKED]

    def touches_bill(self, project_id: str, bill_id: int) -> bool:
        """Une opération déjà en attente concerne-t-elle cette dépense ?"""
        for op in self.for_project(project_id):
            if op.kind == KIND_UPDATE and any(item[0] == bill_id for item in op.plan):
                return True
            if op.kind == KIND_DELETE and bill_id in op.plan:
                return True
        return False

    # -------------------------------------------------------------------- écriture

    async def async_enqueue(self, op: QueuedOperation) -> QueuedOperation:
        self.operations.append(op)
        await self.async_save()
        self._hass.bus.async_fire(EVENT_OPERATION_QUEUED, _event_data(op))
        return op

    async def async_discard(self, op: QueuedOperation) -> None:
        if op in self.operations:
            self.operations.remove(op)
        ir.async_delete_issue(self._hass, DOMAIN, self._issue_id(op))
        await self.async_save()

    async def async_retry(self, op: QueuedOperation, *, force: bool) -> None:
        op.status = STATUS_PENDING
        op.reason = None
        op.error = None
        op.force = force
        await self.async_save()

    # ---------------------------------------------------------- réparations (Repairs)

    def _issue_id(self, op: QueuedOperation) -> str:
        return f"blocked_{self._entry_id}_{op.id}"

    @callback
    def _sync_issues(self) -> None:
        wanted = {self._issue_id(op): op for op in self.blocked()}
        registry = ir.async_get(self._hass)
        prefix = f"blocked_{self._entry_id}_"
        for domain, issue_id in list(registry.issues):
            if domain == DOMAIN and issue_id.startswith(prefix) and issue_id not in wanted:
                ir.async_delete_issue(self._hass, DOMAIN, issue_id)
        for issue_id, op in wanted.items():
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                is_persistent=True,
                severity=ir.IssueSeverity.ERROR,
                translation_key=f"blocked_{op.reason or REASON_REQUEST_FAILED}",
                translation_placeholders={
                    "project": op.project_id,
                    "title": op.title,
                    "operation_id": op.id,
                    "error": op.error or "",
                },
            )


def _event_data(op: QueuedOperation, **extra: Any) -> dict[str, Any]:
    return {
        "operation_id": op.id,
        "kind": op.kind,
        "project_id": op.project_id,
        "title": op.title,
        "bill_ids": list(op.done),
        **extra,
    }


# ---------------------------------------------------------------------------- rejeu


async def async_flush(coordinator: CospendCoordinator) -> None:
    """Rejoue les opérations en attente, dans l'ordre, tant que Cospend répond."""
    queue = coordinator.queue
    if queue.flushing or not any(op.status == "pending" for op in queue.operations):
        return
    queue.flushing = True
    try:
        # Lecture récente (et test de joignabilité) avant toute écriture.
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            return
        progressed = False
        for project_id in dict.fromkeys(op.project_id for op in queue.operations):
            for op in queue.for_project(project_id):
                if op.status != STATUS_PENDING:
                    break  # un blocage garde l'ordre : on n'enchaîne pas derrière
                outcome = await _process(coordinator, op)
                if outcome == "done":
                    progressed = True
                    continue
                break
        if progressed:
            await coordinator.async_refresh()
    finally:
        queue.flushing = False


async def _block(
    coordinator: CospendCoordinator, op: QueuedOperation, reason: str, error: str = ""
) -> str:
    op.status = STATUS_BLOCKED
    op.reason = reason
    op.error = error or None
    await coordinator.queue.async_save()
    coordinator.hass.bus.async_fire(
        EVENT_OPERATION_BLOCKED, _event_data(op, reason=reason, error=error)
    )
    return "blocked"


async def _process(coordinator: CospendCoordinator, op: QueuedOperation) -> str:
    """Traite une opération. Renvoie ``done``, ``retry`` (plus tard) ou ``blocked``."""
    queue = coordinator.queue
    data = (coordinator.data or {}).get(op.project_id)
    if data is None:
        return await _block(coordinator, op, REASON_PROJECT_MISSING)
    op.attempts += 1
    try:
        outcome = await _replay(coordinator, op, data.bills)
    except PartialWriteError as err:
        op.done.extend(err.done)
        outcome = await _on_error(coordinator, op, err.cause)
    except Exception as err:  # noqa: BLE001 - classée juste après
        outcome = await _on_error(coordinator, op, err)
    if outcome == "done":
        await queue.async_discard(op)
        coordinator.hass.bus.async_fire(EVENT_OPERATION_SYNCED, _event_data(op))
    elif outcome == "retry":
        await queue.async_save()
    return outcome


async def _on_error(coordinator: CospendCoordinator, op: QueuedOperation, err: Exception) -> str:
    if is_transient(err):
        op.error = str(err) or type(err).__name__
        op.ambiguous = True  # l'écriture en cours a peut-être abouti sans réponse
        return "retry"
    if isinstance(err, CospendAuthenticationError):
        op.error = str(err)
        coordinator.config_entry.async_start_reauth(coordinator.hass)
        return "retry"
    _LOGGER.warning("Opération %s bloquée : %s", op.id, err)
    return await _block(coordinator, op, REASON_REQUEST_FAILED, str(err) or type(err).__name__)


async def _replay(coordinator: CospendCoordinator, op: QueuedOperation, bills: Any) -> str:
    client = coordinator.client
    queue = coordinator.queue
    project_id = op.project_id

    if op.kind == KIND_ADD:
        claimed = {bill_id for other in queue.operations for bill_id in other.done}
        while len(op.done) < len(op.plan):
            spec = op.plan[len(op.done)]
            if op.ambiguous:
                match = next(
                    (
                        bill
                        for bill in bills.values()
                        if bill.id not in claimed and spec_matches_bill(spec, bill)
                    ),
                    None,
                )
                if match is not None:  # la création avait abouti : ne pas recréer
                    op.done.append(match.id)
                    claimed.add(match.id)
                    continue
            new_id = await client.create_bill(project_id, **spec)
            op.done.append(new_id)
            claimed.add(new_id)
            await queue.async_save()
        return "done"

    if op.kind == KIND_UPDATE:
        for bill_id, fields in op.plan[len(op.done) :]:
            bill = bills.get(bill_id)
            if bill is None:
                return await _block(coordinator, op, REASON_BILL_MISSING, str(bill_id))
            if fields_applied(fields, bill):
                op.done.append(bill_id)
                continue
            if _conflict(op, bill_id, bill.last_changed):
                return await _block(coordinator, op, REASON_CONFLICT, str(bill_id))
            await client.update_bill(project_id, bill_id, **fields)
            op.done.append(bill_id)
            await queue.async_save()
        return "done"

    for bill_id in op.plan[len(op.done) :]:
        bill = bills.get(bill_id)
        if bill is None:  # déjà absente (supprimée ici ou ailleurs) : jamais de seconde suppression
            op.done.append(bill_id)
            continue
        if _conflict(op, bill_id, bill.last_changed):
            return await _block(coordinator, op, REASON_CONFLICT, str(bill_id))
        await client.delete_bill(project_id, bill_id)
        op.done.append(bill_id)
        await queue.async_save()
    return "done"


def _conflict(op: QueuedOperation, bill_id: int, last_changed: int) -> bool:
    """La dépense a-t-elle changé depuis la mise en file ? (``None`` : enchaîné, non vérifié)"""
    if op.force:
        return False
    base = op.base.get(str(bill_id))
    return base is not None and base != last_changed
