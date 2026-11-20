"""Faux client Cospend en mémoire : teste l'intégration sans réseau.

Il rejoue les jeux d'essai du client (réponses réelles de Cospend 4.3.0) et imite la lecture
incrémentale : ``last_changed`` ne renvoie que les dépenses modifiées, ``all_bill_ids`` liste
les dépenses visibles.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from aiocospend import Bill, BillsPage, Ower, Project, ProjectStatistics, ServerInfo

FIXTURES = Path(__file__).resolve().parents[2] / "lib" / "aiocospend" / "tests" / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeClient:
    base_url = "https://cloud.example.org"

    def __init__(self) -> None:
        self.project = Project.from_api(load("project.json"))
        self.bills: dict[int, Bill] = {
            bill.id: bill for bill in BillsPage.from_api(load("bills_page.json")).bills
        }
        self.statistics = ProjectStatistics.from_api(load("statistics.json"))
        self.clock = 1_794_780_000
        self.error: Exception | None = None
        self.statistics_calls = 0
        self.calls: list[tuple[str, tuple, dict]] = []
        self.write_error: Exception | None = None

    def _check(self) -> None:
        if self.error is not None:
            raise self.error

    async def check_connection(self) -> ServerInfo:
        self._check()
        return ServerInfo("4.3.0")

    async def get_projects(self) -> list[Project]:
        self._check()
        return [replace(self.project, nb_bills=len(self.bills))]

    async def get_bills(
        self,
        project_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
        reverse: bool | None = None,
        last_changed: int | None = None,
        **_: Any,
    ) -> BillsPage:
        self._check()
        ordered = sorted(
            self.bills.values(),
            key=lambda b: (-b.timestamp, b.id) if reverse else (b.timestamp, b.id),
        )
        if last_changed is not None:
            selected = [bill for bill in ordered if bill.last_changed > last_changed]
        else:
            start = offset or 0
            selected = ordered[start : start + limit] if limit else ordered[start:]
        return BillsPage(
            nb_bills=len(ordered),
            bills=tuple(selected),
            all_bill_ids=tuple(sorted(self.bills)),
            timestamp=self.clock,
        )

    async def get_statistics(self, project_id: str, **_: Any) -> ProjectStatistics:
        self._check()
        self.statistics_calls += 1
        return self.statistics

    # --------------------------------------------------------- écritures du client

    def _record_write(self, name: str, args: tuple, kwargs: dict) -> None:
        if self.write_error is not None:
            raise self.write_error
        self.calls.append((name, args, kwargs))
        self.clock += 10

    def _owers(self, ids) -> tuple[Ower, ...]:
        return tuple(
            Ower(m.id, m.weight, m.name, m.activated) for m in self.project.members if m.id in ids
        )

    async def create_bill(self, project_id: str, **kwargs: Any) -> int:
        self._record_write("create_bill", (project_id,), kwargs)
        template = next(iter(self.bills.values()))
        bill_id = max(max(self.bills, default=0), 99) + 1
        self.bills[bill_id] = replace(
            template,
            id=bill_id,
            what=kwargs["what"],
            amount=float(kwargs["amount"]),
            comment=kwargs.get("comment", ""),
            timestamp=kwargs["timestamp"],
            date=kwargs["date"],
            payer_id=kwargs["payer_id"],
            owers=self._owers(kwargs["payed_for"]),
            category_id=kwargs.get("category_id", 0),
            payment_mode_id=kwargs.get("payment_mode_id", 0),
            payment_mode=kwargs.get("payment_mode", "n"),
            last_changed=self.clock,
        )
        return bill_id

    async def update_bill(self, project_id: str, bill_id: int, **kwargs: Any) -> int:
        self._record_write("update_bill", (project_id, bill_id), kwargs)
        bill = self.bills[bill_id]
        changes = {k: v for k, v in kwargs.items() if v is not None and k != "payed_for"}
        if "amount" in changes:
            changes["amount"] = float(changes["amount"])
        if kwargs.get("payed_for") is not None:
            changes["owers"] = self._owers(kwargs["payed_for"])
        self.bills[bill_id] = replace(bill, last_changed=self.clock, **changes)
        return bill_id

    async def delete_bill(self, project_id: str, bill_id: int, **kwargs: Any) -> None:
        self._record_write("delete_bill", (project_id, bill_id), kwargs)
        del self.bills[bill_id]

    def __getattr__(self, name: str) -> Any:
        """Appels de structure (membres, catégories…) : enregistrés tels quels."""
        if name.startswith(("create_", "update_", "delete_")):

            async def record(*args: Any, **kwargs: Any) -> int | None:
                self._record_write(name, args, kwargs)
                return 77 if name.startswith("create_") else None

            return record
        raise AttributeError(name)

    # ------------------------------------------------------------ scénarios de test

    def simulate_add(self, bill_id: int, **changes: Any) -> Bill:
        self.clock += 10
        template = next(iter(self.bills.values()))
        bill = replace(
            template, id=bill_id, last_changed=self.clock, timestamp=self.clock, **changes
        )
        self.bills[bill_id] = bill
        return bill

    def simulate_update(self, bill_id: int, **changes: Any) -> Bill:
        self.clock += 10
        bill = replace(self.bills[bill_id], last_changed=self.clock, **changes)
        self.bills[bill_id] = bill
        return bill

    def simulate_delete(self, bill_id: int) -> None:
        self.clock += 10
        del self.bills[bill_id]
