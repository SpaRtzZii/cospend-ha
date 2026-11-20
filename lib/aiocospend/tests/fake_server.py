"""Faux serveur Nextcloud + Cospend pour les tests du client.

Il imite les comportements relevés sur un vrai Cospend 4.3.0 :
création en formulaire avec identifiant renvoyé, modification partielle conservant les champs
non envoyés, ``lastChanged`` qui ne renvoie pas les dépenses mises en corbeille, ``allBillIds``
limité à l'état demandé, suppression en corbeille puis suppression définitive à la seconde
suppression. Les 404 sur une dépense inconnue sont une hypothèse (non observée).
"""

from __future__ import annotations

import base64
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web

FIXTURES = Path(__file__).parent / "fixtures"
OCS = "/ocs/v2.php"
API = f"{OCS}/apps/cospend/api/v1"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@dataclass
class RecordedRequest:
    method: str
    path: str
    query: dict[str, str]
    form: dict[str, str]


@dataclass
class FakeCospend:
    username: str = "admin"
    password: str = "secret"
    version: str = "4.3.0"
    maintenance: bool = False
    cospend_installed: bool = True
    requests: list[RecordedRequest] = field(default_factory=list)
    clock: int = 1_794_780_000
    next_bill_id: int = 100
    next_item_id: int = 500
    url: str = ""
    _form: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.project: dict[str, Any] = load_fixture("project.json")
        page = load_fixture("bills_page.json")
        self.bills: dict[int, dict[str, Any]] = {b["id"]: copy.deepcopy(b) for b in page["bills"]}
        self.app = web.Application(middlewares=[self._middleware])
        self.app.router.add_get(f"{OCS}/cloud/capabilities", self._capabilities)
        self.app.router.add_get("/html/ocs/v2.php/cloud/capabilities", self._html)
        self.app.router.add_get(f"{API}/ping", self._ping)
        self.app.router.add_get(f"{API}/projects", self._projects)
        self.app.router.add_get(f"{API}/projects/{{pid}}", self._project)
        self.app.router.add_get(f"{API}/projects/{{pid}}/bills", self._list_bills)
        self.app.router.add_post(f"{API}/projects/{{pid}}/bills", self._create_bill)
        self.app.router.add_get(f"{API}/projects/{{pid}}/bills/{{bid}}", self._get_bill)
        self.app.router.add_put(f"{API}/projects/{{pid}}/bills/{{bid}}", self._update_bill)
        self.app.router.add_delete(f"{API}/projects/{{pid}}/bills/{{bid}}", self._delete_bill)
        for kind in ("members", "categories", "paymentmodes", "currencies"):
            self.app.router.add_post(f"{API}/projects/{{pid}}/{kind}", self._item_create)
            self.app.router.add_put(f"{API}/projects/{{pid}}/{kind}/{{iid}}", self._item_update)
            self.app.router.add_delete(f"{API}/projects/{{pid}}/{kind}/{{iid}}", self._item_delete)
        self.app.router.add_get(f"{API}/projects/{{pid}}/statistics", self._statistics)
        self.app.router.add_get(f"{API}/projects/{{pid}}/settlement", self._settlement)

    # --------------------------------------------------------------- utilitaires

    def tick(self, seconds: int = 10) -> int:
        self.clock += seconds
        return self.clock

    @staticmethod
    def _ok(data: Any) -> web.Response:
        meta = {"status": "ok", "statuscode": 200, "message": "OK"}
        return web.json_response({"ocs": {"meta": meta, "data": data}})

    @staticmethod
    def _fail(status: int) -> web.Response:
        meta = {"status": "failure", "statuscode": status, "message": ""}
        return web.json_response({"ocs": {"meta": meta, "data": []}}, status=status)

    @web.middleware
    async def _middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        form: dict[str, str] = {}
        if request.method in ("POST", "PUT"):
            form = {k: str(v) for k, v in (await request.post()).items()}
        self.requests.append(
            RecordedRequest(request.method, request.path, dict(request.query), form)
        )
        if self.maintenance:
            return self._fail(503)
        token = base64.b64encode(f"{self.username}:{self.password}".encode()).decode("ascii")
        if request.headers.get("Authorization") != f"Basic {token}":
            return self._fail(401)
        if request.headers.get("OCS-APIRequest") != "true":
            return self._fail(401)
        self._form = form
        return await handler(request)

    def _bill_out(self, bill: dict[str, Any], *, with_project: bool) -> dict[str, Any]:
        out = copy.deepcopy(bill)
        if not with_project:
            out.pop("projectid", None)
        return out

    def _owers(self, ids: list[int]) -> list[dict[str, Any]]:
        members = {m["id"]: m for m in self.project["members"]}
        return [
            {
                "id": i,
                "weight": members[i]["weight"],
                "name": members[i]["name"],
                "activated": members[i]["activated"],
            }
            for i in ids
        ]

    # --------------------------------------------------------------- routes

    async def _capabilities(self, request: web.Request) -> web.Response:
        caps: dict[str, Any] = {}
        if self.cospend_installed:
            caps["cospend"] = {"version": self.version, "federation": {"enabled": False}}
        return self._ok({"version": {"string": "32.0.0"}, "capabilities": caps})

    async def _html(self, request: web.Request) -> web.Response:
        return web.Response(text="<html>connexion</html>", content_type="text/html")

    async def _ping(self, request: web.Request) -> web.Response:
        return self._ok([])

    async def _projects(self, request: web.Request) -> web.Response:
        return self._ok([self.project])

    def _check_project(self, request: web.Request) -> web.Response | None:
        if request.match_info["pid"] != self.project["id"]:
            return self._fail(404)
        return None

    async def _project(self, request: web.Request) -> web.Response:
        return self._check_project(request) or self._ok(self.project)

    async def _list_bills(self, request: web.Request) -> web.Response:
        if (error := self._check_project(request)) is not None:
            return error
        q = request.query
        deleted = int(q.get("deleted", 0))
        matching = [b for b in self.bills.values() if b["deleted"] == deleted]
        selected = list(matching)
        if "lastChanged" in q:
            selected = [b for b in selected if b["lastchanged"] > int(q["lastChanged"])]
            selected.sort(key=lambda b: (b["timestamp"], b["id"]))
        else:
            if "payerId" in q:
                selected = [b for b in selected if b["payer_id"] == int(q["payerId"])]
            if "categoryId" in q:
                selected = [b for b in selected if b["categoryid"] == int(q["categoryId"])]
            if "searchTerm" in q:
                term = q["searchTerm"].lower()
                selected = [
                    b for b in selected if term in b["what"].lower() or term in b["comment"].lower()
                ]
            if q.get("reverse") == "true":
                selected.sort(key=lambda b: (-b["timestamp"], b["id"]))
            else:
                selected.sort(key=lambda b: (b["timestamp"], b["id"]))
            offset = int(q.get("offset", 0))
            limit = int(q["limit"]) if "limit" in q else None
            selected = selected[offset : offset + limit if limit is not None else None]
        with_project = deleted == 0 and "lastChanged" not in q
        return self._ok(
            {
                "nb_bills": len(matching),
                "bills": [self._bill_out(b, with_project=with_project) for b in selected],
                "allBillIds": sorted(b["id"] for b in matching),
                "timestamp": self.clock,
            }
        )

    def _find(self, request: web.Request) -> dict[str, Any] | None:
        return self.bills.get(int(request.match_info["bid"]))

    async def _get_bill(self, request: web.Request) -> web.Response:
        bill = self._find(request)
        return self._ok(self._bill_out(bill, with_project=True)) if bill else self._fail(404)

    async def _create_bill(self, request: web.Request) -> web.Response:
        if (error := self._check_project(request)) is not None:
            return error
        f = self._form
        try:
            payed_for = [int(i) for i in f["payedFor"].split(",")]
            timestamp = int(f["timestamp"]) if "timestamp" in f else self.clock
            bill = {
                "id": self.next_bill_id,
                "projectid": self.project["id"],
                "what": f["what"],
                "comment": f.get("comment", ""),
                "payer_id": int(f["payer"]),
                "timestamp": timestamp,
                "date": f["date"],
                "amount": float(f["amount"]),
                "repeat": f.get("repeat", "n"),
                "repeatallactive": int(f.get("repeatAllActive", 0)),
                "repeatuntil": f.get("repeatUntil"),
                "repeatfreq": int(f.get("repeatFreq", 1)),
                "categoryid": int(f.get("categoryId", 0)),
                "paymentmode": f.get("paymentMode", "n"),
                "paymentmodeid": int(f.get("paymentModeId", 0)),
                "deleted": 0,
                "lastchanged": self.clock,
                "owers": self._owers(payed_for),
                "owerIds": payed_for,
            }
        except (KeyError, ValueError):
            return self._fail(400)
        self.bills[bill["id"]] = bill
        self.next_bill_id += 1
        return self._ok(bill["id"])

    async def _update_bill(self, request: web.Request) -> web.Response:
        bill = self._find(request)
        if bill is None:
            return self._fail(404)
        f = self._form
        mapping = {
            "what": ("what", str),
            "comment": ("comment", str),
            "payer": ("payer_id", int),
            "timestamp": ("timestamp", int),
            "date": ("date", str),
            "amount": ("amount", float),
            "repeat": ("repeat", str),
            "repeatFreq": ("repeatfreq", int),
            "repeatUntil": ("repeatuntil", str),
            "repeatAllActive": ("repeatallactive", int),
            "categoryId": ("categoryid", int),
            "paymentMode": ("paymentmode", str),
            "paymentModeId": ("paymentmodeid", int),
        }
        try:
            for key, (field_name, cast) in mapping.items():
                if key in f:
                    bill[field_name] = cast(f[key])
            if "payedFor" in f:
                ids = [int(i) for i in f["payedFor"].split(",")]
                bill["owerIds"] = ids
                bill["owers"] = self._owers(ids)
        except ValueError:
            return self._fail(400)
        bill["lastchanged"] = self.clock
        return self._ok(bill["id"])

    async def _delete_bill(self, request: web.Request) -> web.Response:
        bill = self._find(request)
        if bill is None:
            return self._fail(404)
        to_trash = request.query.get("moveToTrash", "true") != "false"
        if bill["deleted"] == 0 and to_trash:
            bill["deleted"] = 1
            bill["lastchanged"] = self.clock
        else:
            del self.bills[bill["id"]]  # déjà en corbeille ou suppression définitive demandée
        return self._ok([])

    # Structure du projet : on enregistre seulement les requêtes ; le fond n'est pas simulé.
    async def _item_create(self, request: web.Request) -> web.Response:
        if (error := self._check_project(request)) is not None:
            return error
        self.next_item_id += 1
        return self._ok(self.next_item_id)

    async def _item_update(self, request: web.Request) -> web.Response:
        return self._check_project(request) or self._ok({})

    async def _item_delete(self, request: web.Request) -> web.Response:
        return self._check_project(request) or self._ok("OK")

    async def _statistics(self, request: web.Request) -> web.Response:
        return self._check_project(request) or self._ok(load_fixture("statistics.json"))

    async def _settlement(self, request: web.Request) -> web.Response:
        return self._check_project(request) or self._ok(load_fixture("settlement.json"))
