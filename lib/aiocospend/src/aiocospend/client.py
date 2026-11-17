"""Client asynchrone pour l'API OCS de Nextcloud Cospend.

Comportements relevés sur un serveur Cospend 4.3.0 (voir les jeux d'essai) :

* les écritures sont envoyées en **formulaire** (``application/x-www-form-urlencoded``) ;
* la création envoie **tous** les champs, comme l'application Cowspent ;
* une modification partielle ne touche que les champs envoyés ;
* une suppression envoie la dépense en corbeille ; **supprimer une dépense déjà en corbeille la
  supprime définitivement**. Ce client ne rejoue jamais une suppression de lui-même : l'appelant
  doit relire l'état de la dépense avant de réessayer.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import API_VERSION, CAPABILITIES_PATH, MIN_COSPEND_VERSION, OCS_BASE_PATH
from .exceptions import (
    CospendAuthenticationError,
    CospendBadRequestError,
    CospendConnectionError,
    CospendError,
    CospendForbiddenError,
    CospendMaintenanceError,
    CospendNotFoundError,
    CospendResponseError,
    CospendServerError,
    CospendSSLError,
    CospendVersionError,
)
from .models import (
    Bill,
    BillsPage,
    Project,
    ProjectStatistics,
    ServerInfo,
    Settlement,
)
from .utils import compare_versions, format_amount, normalize_url

DEFAULT_TIMEOUT = 30.0
DEFAULT_PAGE_SIZE = 50

type Amount = int | float | Decimal | str


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def basic_auth_header(username: str, password: str) -> str:
    """En-tête ``Authorization`` Basic (sans dépendre de l'API d'authentification d'aiohttp)."""
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"


def _clean(params: Mapping[str, Any]) -> dict[str, str]:
    """Retire les valeurs ``None`` et convertit tout en texte."""
    return {key: _query_value(value) for key, value in params.items() if value is not None}


class CospendClient:
    """Client de l'API Cospend d'un serveur Nextcloud.

    ``session`` est fournie par l'appelant (celle de Home Assistant en production). Les
    identifiants ne sont pas attachés à la session : ils sont envoyés à chaque requête.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._session = session
        self._base_url = normalize_url(base_url)
        self._authorization = basic_auth_header(username, password)
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    @property
    def base_url(self) -> str:
        return self._base_url

    # ------------------------------------------------------------------ requêtes

    def _api(self, path: str = "") -> str:
        return f"{OCS_BASE_PATH}/{API_VERSION}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        form: Mapping[str, Any] | None = None,
    ) -> Any:
        """Envoie une requête OCS et renvoie le contenu de ``ocs.data``."""
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                params=_clean(params) if params else None,
                data=_clean(form) if form is not None else None,
                headers={
                    "OCS-APIRequest": "true",
                    "Accept": "application/json",
                    "Authorization": self._authorization,
                },
                timeout=self._timeout,
            ) as response:
                status = response.status
                text = await response.text()
        except aiohttp.ClientSSLError as err:
            raise CospendSSLError(f"Certificat refusé : {err}") from err
        except TimeoutError as err:
            raise CospendConnectionError("Délai dépassé") from err
        except aiohttp.ClientError as err:
            raise CospendConnectionError(f"Connexion impossible : {err}") from err

        if status >= 400:
            raise self._error_for(status, text)
        try:
            payload = json.loads(text)
            return payload["ocs"]["data"]
        except (ValueError, KeyError, TypeError) as err:
            raise CospendResponseError(
                "Réponse inattendue (adresse du serveur incorrecte ?)", status=status
            ) from err

    @staticmethod
    def _error_for(status: int, text: str) -> CospendError:
        detail = f"HTTP {status}"
        if status == 401:
            return CospendAuthenticationError(f"{detail} : identifiants refusés", status=status)
        if status == 403:
            return CospendForbiddenError(f"{detail} : accès refusé", status=status)
        if status == 404:
            return CospendNotFoundError(f"{detail} : introuvable", status=status)
        if status == 400:
            return CospendBadRequestError(f"{detail} : requête refusée", status=status)
        if status == 503:
            return CospendMaintenanceError(f"{detail} : serveur en maintenance", status=status)
        if status >= 500:
            return CospendServerError(f"{detail} : erreur du serveur", status=status)
        return CospendError(f"{detail} : {text[:200]}", status=status)

    # ------------------------------------------------------------------ connexion

    async def get_server_info(self) -> ServerInfo:
        """Version de Cospend et état de la fédération (``capabilities``)."""
        data = await self._request("GET", CAPABILITIES_PATH)
        try:
            cospend = data["capabilities"]["cospend"]
            return ServerInfo(
                version=str(cospend["version"]),
                federation_enabled=bool(cospend.get("federation", {}).get("enabled", False)),
            )
        except (KeyError, TypeError) as err:
            raise CospendVersionError("L'application Cospend est absente ou désactivée") from err

    async def ping(self) -> None:
        """Vérifie que l'API Cospend répond avec ces identifiants."""
        await self._request("GET", self._api("/ping"))

    async def check_connection(self) -> ServerInfo:
        """Valide l'adresse, les identifiants et la version minimale de Cospend."""
        info = await self.get_server_info()
        try:
            too_old = compare_versions(info.version, MIN_COSPEND_VERSION) < 0
        except ValueError as err:
            raise CospendResponseError(f"Version illisible : {info.version!r}") from err
        if too_old:
            raise CospendVersionError(
                f"Cospend {info.version} est trop ancienne (minimum {MIN_COSPEND_VERSION})"
            )
        await self.ping()
        return info

    # ------------------------------------------------------------------ projets

    async def get_projects(self) -> list[Project]:
        """Projets du compte, avec membres, catégories, modes de paiement et soldes."""
        data = await self._request("GET", self._api("/projects"))
        if not isinstance(data, list):
            raise CospendResponseError("La liste des projets n'est pas une liste")
        return [Project.from_api(item) for item in data]

    async def get_project(self, project_id: str) -> Project:
        data = await self._request("GET", self._api(f"/projects/{quote(project_id, safe='')}"))
        return Project.from_api(data)

    # ------------------------------------------------------------------ dépenses

    def _bills_path(self, project_id: str, bill_id: int | None = None) -> str:
        path = self._api(f"/projects/{quote(project_id, safe='')}/bills")
        return path if bill_id is None else f"{path}/{bill_id}"

    async def get_bills(
        self,
        project_id: str,
        *,
        offset: int | None = None,
        limit: int | None = None,
        reverse: bool | None = None,
        payer_id: int | None = None,
        category_id: int | None = None,
        payment_mode_id: int | None = None,
        search_term: str | None = None,
        deleted: bool = False,
        last_changed: int | None = None,
    ) -> BillsPage:
        """Liste des dépenses.

        Avec ``last_changed``, seules les dépenses visibles modifiées depuis ce curseur sont
        renvoyées ; une dépense mise en corbeille n'est détectable que par son absence de
        ``all_bill_ids``. Avec ``deleted=True``, on obtient la corbeille.
        """
        data = await self._request(
            "GET",
            self._bills_path(project_id),
            params={
                "offset": offset,
                "limit": limit,
                "reverse": reverse,
                "payerId": payer_id,
                "categoryId": category_id,
                "paymentModeId": payment_mode_id,
                "searchTerm": search_term,
                "deleted": 1 if deleted else None,
                "lastChanged": last_changed,
            },
        )
        return BillsPage.from_api(data)

    async def iter_bills(
        self,
        project_id: str,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
        reverse: bool = True,
        **filters: Any,
    ) -> AsyncIterator[Bill]:
        """Parcourt toutes les dépenses, page par page (de la plus récente à la plus ancienne)."""
        offset = 0
        while True:
            page = await self.get_bills(
                project_id, offset=offset, limit=page_size, reverse=reverse, **filters
            )
            for bill in page.bills:
                yield bill
            offset += len(page.bills)
            if len(page.bills) < page_size:
                return

    async def get_bill(self, project_id: str, bill_id: int) -> Bill:
        data = await self._request("GET", self._bills_path(project_id, bill_id))
        return Bill.from_api(data)

    async def create_bill(
        self,
        project_id: str,
        *,
        what: str,
        amount: Amount,
        payer_id: int,
        payed_for: Sequence[int],
        timestamp: int,
        date: str,
        comment: str = "",
        category_id: int = 0,
        payment_mode_id: int = 0,
        payment_mode: str = "n",
        repeat: str = "n",
        repeat_freq: int | None = None,
        repeat_until: str | None = None,
        repeat_all_active: int | None = None,
    ) -> int:
        """Crée une dépense et renvoie son identifiant.

        Tous les champs sont envoyés, comme le fait Cowspent. ``date`` (AAAA-MM-JJ) et
        ``timestamp`` doivent être cohérents : l'appelant les calcule dans le même fuseau.
        """
        if not payed_for:
            raise ValueError("au moins un participant est requis")
        data = await self._request(
            "POST",
            self._bills_path(project_id),
            form={
                "date": date,
                "what": what,
                "payer": payer_id,
                "amount": format_amount(amount),
                "comment": comment,
                "timestamp": timestamp,
                "repeat": repeat,
                "payedFor": ",".join(str(i) for i in payed_for),
                "paymentMode": payment_mode,
                "categoryId": category_id,
                "paymentModeId": payment_mode_id,
                "repeatFreq": repeat_freq,
                "repeatUntil": repeat_until,
                "repeatAllActive": repeat_all_active,
            },
        )
        return self._bill_id(data)

    async def update_bill(
        self,
        project_id: str,
        bill_id: int,
        *,
        what: str | None = None,
        amount: Amount | None = None,
        payer_id: int | None = None,
        payed_for: Sequence[int] | None = None,
        timestamp: int | None = None,
        date: str | None = None,
        comment: str | None = None,
        category_id: int | None = None,
        payment_mode_id: int | None = None,
        payment_mode: str | None = None,
        repeat: str | None = None,
        repeat_freq: int | None = None,
        repeat_until: str | None = None,
        repeat_all_active: int | None = None,
    ) -> int:
        """Modifie une dépense : seuls les champs fournis sont envoyés (testé sur Cospend 4.3.0)."""
        form = {
            "what": what,
            "amount": format_amount(amount) if amount is not None else None,
            "payer": payer_id,
            "payedFor": ",".join(str(i) for i in payed_for) if payed_for is not None else None,
            "timestamp": timestamp,
            "date": date,
            "comment": comment,
            "categoryId": category_id,
            "paymentModeId": payment_mode_id,
            "paymentMode": payment_mode,
            "repeat": repeat,
            "repeatFreq": repeat_freq,
            "repeatUntil": repeat_until,
            "repeatAllActive": repeat_all_active,
        }
        if payed_for is not None and not payed_for:
            raise ValueError("au moins un participant est requis")
        if all(value is None for value in form.values()):
            raise ValueError("aucun champ à modifier")
        data = await self._request("PUT", self._bills_path(project_id, bill_id), form=form)
        return self._bill_id(data)

    async def delete_bill(
        self, project_id: str, bill_id: int, *, move_to_trash: bool = True
    ) -> None:
        """Supprime une dépense : corbeille par défaut, définitivement si déjà en corbeille.

        Ne jamais rejouer cet appel à l'aveugle (voir l'en-tête du module).
        """
        await self._request(
            "DELETE",
            self._bills_path(project_id, bill_id),
            params=None if move_to_trash else {"moveToTrash": False},
        )

    @staticmethod
    def _bill_id(data: Any) -> int:
        try:
            return int(data)
        except (TypeError, ValueError) as err:
            raise CospendResponseError(f"Identifiant de dépense attendu, reçu : {data!r}") from err

    # ------------------------------------------------------------------ analyse

    async def get_statistics(
        self,
        project_id: str,
        *,
        ts_min: int | None = None,
        ts_max: int | None = None,
        category_id: int | None = None,
        payment_mode_id: int | None = None,
        payer_id: int | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
        currency_id: int | None = None,
        show_disabled: bool | None = None,
    ) -> ProjectStatistics:
        data = await self._request(
            "GET",
            self._api(f"/projects/{quote(project_id, safe='')}/statistics"),
            params={
                "tsMin": ts_min,
                "tsMax": ts_max,
                "categoryId": category_id,
                "paymentModeId": payment_mode_id,
                "payerId": payer_id,
                "amountMin": amount_min,
                "amountMax": amount_max,
                "currencyId": currency_id,
                "showDisabled": show_disabled,
            },
        )
        return ProjectStatistics.from_api(data)

    async def get_settlement(
        self,
        project_id: str,
        *,
        centered_on: int | None = None,
        max_timestamp: int | None = None,
    ) -> Settlement:
        """Plan de remboursement du serveur (lecture seule)."""
        data = await self._request(
            "GET",
            self._api(f"/projects/{quote(project_id, safe='')}/settlement"),
            params={"centeredOn": centered_on, "maxTimestamp": max_timestamp},
        )
        return Settlement.from_api(data)
