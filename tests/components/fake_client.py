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

from aiocospend import Bill, BillsPage, Project, ProjectStatistics, ServerInfo

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

    # ------------------------------------------------------------ scénarios de test

    def add_bill(self, bill_id: int, **changes: Any) -> Bill:
        self.clock += 10
        template = next(iter(self.bills.values()))
        bill = replace(
            template, id=bill_id, last_changed=self.clock, timestamp=self.clock, **changes
        )
        self.bills[bill_id] = bill
        return bill

    def update_bill(self, bill_id: int, **changes: Any) -> Bill:
        self.clock += 10
        bill = replace(self.bills[bill_id], last_changed=self.clock, **changes)
        self.bills[bill_id] = bill
        return bill

    def delete_bill(self, bill_id: int) -> None:
        self.clock += 10
        del self.bills[bill_id]
