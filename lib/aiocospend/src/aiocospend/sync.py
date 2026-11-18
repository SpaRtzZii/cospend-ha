"""Cache des dépenses d'un projet et synchronisation incrémentale.

Principe, validé sur Cospend 4.3.0 :

* la première lecture (ou une resynchronisation complète) parcourt toutes les dépenses par pages ;
* ensuite, ``last_changed`` ne renvoie que les dépenses modifiées depuis le curseur ;
* une dépense mise en corbeille n'est pas renvoyée : on la détecte par son absence de
  ``all_bill_ids``, à comparer au cache ;
* le curseur est l'heure du serveur renvoyée par la lecture, avec un recouvrement de quelques
  secondes (la limite exacte de ``last_changed`` n'est pas connue). La fusion est idempotente :
  une dépense relue à l'identique ne produit aucun changement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .client import CospendClient
from .models import Bill

DEFAULT_OVERLAP = 2
DEFAULT_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class BillChanges:
    """Différences constatées par une synchronisation.

    ``is_initial`` vaut ``True`` pour la toute première lecture : tout y est « ajouté », ce qui
    ne doit pas déclencher d'événements.
    """

    added: tuple[Bill, ...] = ()
    updated: tuple[Bill, ...] = ()
    deleted: tuple[Bill, ...] = ()
    is_initial: bool = False
    full: bool = False

    @property
    def any(self) -> bool:
        return bool(self.added or self.updated or self.deleted)


class ProjectBills:
    """Dépenses d'un projet gardées en mémoire, tenues à jour de façon incrémentale."""

    def __init__(
        self,
        project_id: str,
        *,
        overlap: int = DEFAULT_OVERLAP,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        self.project_id = project_id
        self.bills: dict[int, Bill] = {}
        self.cursor: int | None = None
        self.last_full_sync: float | None = None
        self._overlap = overlap
        self._page_size = page_size

    @property
    def synced(self) -> bool:
        return self.cursor is not None

    def full_sync_due(self, max_age: float, *, now: float | None = None) -> bool:
        """Vrai si aucune lecture complète n'a eu lieu ou si elle date de plus de ``max_age`` s."""
        if self.last_full_sync is None:
            return True
        current = time.monotonic() if now is None else now
        return current - self.last_full_sync >= max_age

    async def sync(
        self, client: CospendClient, *, full_sync_max_age: float | None = None
    ) -> BillChanges:
        """Lecture complète si nécessaire, incrémentale sinon."""
        if not self.synced or (
            full_sync_max_age is not None and self.full_sync_due(full_sync_max_age)
        ):
            return await self.full_sync(client)
        return await self.incremental_sync(client)

    async def full_sync(self, client: CospendClient) -> BillChanges:
        """Relit toutes les dépenses, page par page."""
        first = await client.get_bills(
            self.project_id, offset=0, limit=self._page_size, reverse=True
        )
        fetched = {bill.id: bill for bill in first.bills}
        offset = len(first.bills)
        while first.bills and offset < first.nb_bills:
            page = await client.get_bills(
                self.project_id, offset=offset, limit=self._page_size, reverse=True
            )
            if not page.bills:
                break
            fetched.update({bill.id: bill for bill in page.bills})
            offset += len(page.bills)
        initial = not self.synced
        changes = self._apply(fetched, set(fetched), initial=initial, full=True)
        self.cursor = first.timestamp
        self.last_full_sync = time.monotonic()
        return changes

    async def incremental_sync(self, client: CospendClient) -> BillChanges:
        """Ne lit que les dépenses modifiées depuis le curseur."""
        if self.cursor is None:
            raise RuntimeError("synchronisation complète requise avant la lecture incrémentale")
        page = await client.get_bills(
            self.project_id, last_changed=max(self.cursor - self._overlap, 0)
        )
        changes = self._apply(
            {bill.id: bill for bill in page.bills},
            set(page.all_bill_ids),
            initial=False,
            full=False,
        )
        self.cursor = page.timestamp
        return changes

    def _apply(
        self,
        changed: dict[int, Bill],
        alive_ids: set[int],
        *,
        initial: bool,
        full: bool,
    ) -> BillChanges:
        added: list[Bill] = []
        updated: list[Bill] = []
        for bill in changed.values():
            known = self.bills.get(bill.id)
            if known is None:
                added.append(bill)
            elif known != bill:
                updated.append(bill)
            self.bills[bill.id] = bill
        deleted = [
            self.bills.pop(bill_id) for bill_id in [i for i in self.bills if i not in alive_ids]
        ]
        return BillChanges(
            added=tuple(sorted(added, key=lambda b: b.id)),
            updated=tuple(sorted(updated, key=lambda b: b.id)),
            deleted=tuple(sorted(deleted, key=lambda b: b.id)),
            is_initial=initial,
            full=full,
        )
