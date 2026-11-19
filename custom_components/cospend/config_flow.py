"""Configuration par l'interface : connexion, choix des projets, options."""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SSL,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from aiocospend import (
    CospendAuthenticationError,
    CospendBadRequestError,
    CospendClient,
    CospendConnectionError,
    CospendError,
    CospendMaintenanceError,
    CospendResponseError,
    CospendServerError,
    CospendSSLError,
    CospendVersionError,
    Project,
    normalize_url,
)

from .const import (
    CONF_FULL_RESYNC_HOURS,
    CONF_PROJECTS,
    DEFAULT_FULL_RESYNC_HOURS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_FULL_RESYNC_HOURS,
    MAX_SCAN_INTERVAL,
    MIN_FULL_RESYNC_HOURS,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

_USERNAME = TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username"))
_PASSWORD = TextSelector(
    TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
)
DEFAULT_LOCAL_PORT = 8080

# Choix 1 : adresse web (http ou https, éventuellement derrière un reverse proxy).
WEB_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
        vol.Required(CONF_USERNAME): _USERNAME,
        vol.Required(CONF_PASSWORD): _PASSWORD,
        vol.Required(CONF_VERIFY_SSL, default=True): BooleanSelector(),
    }
)
# Choix 2 : adresse IP (ou nom d'hôte) et port du réseau local.
LOCAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        vol.Required(CONF_PORT, default=DEFAULT_LOCAL_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_SSL, default=False): BooleanSelector(),
        vol.Required(CONF_USERNAME): _USERNAME,
        vol.Required(CONF_PASSWORD): _PASSWORD,
        vol.Required(CONF_VERIFY_SSL, default=False): BooleanSelector(),
    }
)
_HOSTNAME = re.compile(
    r"^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$"
)


class InvalidHostError(ValueError):
    """L'adresse IP ou le nom d'hôte saisi n'est pas valide."""


def build_local_url(host: str, port: int | float, use_ssl: bool) -> str:
    """Construit l'adresse du serveur à partir d'une IP (ou d'un nom d'hôte) et d'un port."""
    host = host.strip().removeprefix("[").removesuffix("]")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if not _HOSTNAME.match(host):
            raise InvalidHostError(host) from None
        netloc_host = host
    else:
        netloc_host = f"[{address}]" if address.version == 6 else str(address)
    port = int(port)
    if not 1 <= port <= 65535:
        raise InvalidHostError(str(port))
    return normalize_url(f"{'https' if use_ssl else 'http'}://{netloc_host}:{port}")


def _local_defaults(url: str) -> dict[str, Any]:
    """Valeurs proposées dans le formulaire « IP + port » à partir d'une adresse enregistrée."""
    parts = urlsplit(url)
    use_ssl = parts.scheme == "https"
    return {
        CONF_HOST: parts.hostname or "",
        CONF_PORT: parts.port or (443 if use_ssl else 80),
        CONF_SSL: use_ssl,
    }


REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD, autocomplete="current-password")
        )
    }
)


def _error_key(err: CospendError) -> str:
    """Traduit une erreur du client en clé d'erreur du formulaire."""
    if isinstance(err, CospendAuthenticationError):
        return "invalid_auth"
    if isinstance(err, CospendSSLError):
        return "ssl_error"
    if isinstance(err, CospendConnectionError | CospendMaintenanceError | CospendServerError):
        return "cannot_connect"
    if isinstance(err, CospendBadRequestError):
        # Nextcloud répond 400 quand l'adresse n'est pas dans ``trusted_domains``.
        return "untrusted_domain"
    if isinstance(err, CospendVersionError):
        return "unsupported_version"
    if isinstance(err, CospendResponseError):
        return "invalid_response"
    return "unknown"


def _unique_id(url: str, username: str) -> str:
    return f"{url}|{username.lower()}"


def _project_options(projects: list[Project]) -> list[SelectOptionDict]:
    return [
        SelectOptionDict(
            value=project.id,
            label=f"{project.name} (archived)" if project.is_archived else project.name,
        )
        for project in projects
    ]


def _options_schema(
    projects: list[Project], defaults: Mapping[str, Any], *, with_intervals: bool
) -> vol.Schema:
    selected = defaults.get(CONF_PROJECTS) or [p.id for p in projects if not p.is_archived]
    schema: dict[Any, Any] = {
        vol.Required(CONF_PROJECTS, default=selected): SelectSelector(
            SelectSelectorConfig(
                options=_project_options(projects),
                multiple=True,
                mode=SelectSelectorMode.LIST,
            )
        )
    }
    if with_intervals:
        schema[
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        ] = NumberSelector(
            NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL,
                max=MAX_SCAN_INTERVAL,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        )
        schema[
            vol.Required(
                CONF_FULL_RESYNC_HOURS,
                default=defaults.get(CONF_FULL_RESYNC_HOURS, DEFAULT_FULL_RESYNC_HOURS),
            )
        ] = NumberSelector(
            NumberSelectorConfig(
                min=MIN_FULL_RESYNC_HOURS,
                max=MAX_FULL_RESYNC_HOURS,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="h",
            )
        )
    return vol.Schema(schema)


class CospendConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ajout d'un compte Nextcloud puis choix des projets Cospend."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._projects: list[Project] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CospendOptionsFlow:
        return CospendOptionsFlow()

    async def _async_fetch_projects(
        self, url: str, username: str, password: str, verify_ssl: bool
    ) -> list[Project]:
        client = CospendClient(
            async_get_clientsession(self.hass, verify_ssl=verify_ssl), url, username, password
        )
        await client.check_connection()
        return await client.get_projects()

    async def _async_validate(
        self, url: str, username: str, password: str, verify_ssl: bool
    ) -> str | None:
        """Renvoie une clé d'erreur, ou None si la connexion fonctionne."""
        try:
            self._projects = await self._async_fetch_projects(url, username, password, verify_ssl)
        except CospendError as err:
            _LOGGER.debug("Connexion à Cospend impossible : %s", err)
            return _error_key(err)
        except Exception:
            _LOGGER.exception("Erreur inattendue pendant la connexion à Cospend")
            return "unknown"
        return None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="user", menu_options=["web", "local"])

    def _read_form(self, user_input: dict[str, Any], *, local: bool) -> tuple[str, str]:
        """Adresse normalisée et identifiant saisis ; lève ValueError si l'adresse est invalide."""
        if local:
            url = build_local_url(
                user_input[CONF_HOST], user_input[CONF_PORT], user_input.get(CONF_SSL, False)
            )
        else:
            url = normalize_url(user_input[CONF_URL])
        return url, user_input[CONF_USERNAME].strip()

    async def _async_connection_step(
        self, step_id: str, user_input: dict[str, Any] | None, *, local: bool
    ) -> ConfigFlowResult:
        schema = LOCAL_SCHEMA if local else WEB_SCHEMA
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url, username = self._read_form(user_input, local=local)
            except InvalidHostError:
                errors["base"] = "invalid_host"
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                password = user_input[CONF_PASSWORD]
                verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
                if error := await self._async_validate(url, username, password, verify_ssl):
                    errors["base"] = error
                else:
                    await self.async_set_unique_id(_unique_id(url, username))
                    self._abort_if_unique_id_configured()
                    self._data = {
                        CONF_URL: url,
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_VERIFY_SSL: verify_ssl,
                    }
                    return await self.async_step_projects()
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def async_step_web(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_connection_step("web", user_input, local=False)

    async def async_step_local(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._async_connection_step("local", user_input, local=True)

    async def async_step_projects(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self._projects:
            return self.async_abort(reason="no_projects_on_server")
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_PROJECTS]:
                errors["base"] = "no_projects"
            else:
                host = urlsplit(self._data[CONF_URL]).netloc
                return self.async_create_entry(
                    title=f"{self._data[CONF_USERNAME]} @ {host}",
                    data=self._data,
                    options={
                        CONF_PROJECTS: user_input[CONF_PROJECTS],
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                        CONF_FULL_RESYNC_HOURS: DEFAULT_FULL_RESYNC_HOURS,
                    },
                )
        return self.async_show_form(
            step_id="projects",
            data_schema=_options_schema(self._projects, {}, with_intervals=False),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._async_validate(
                entry.data[CONF_URL],
                entry.data[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                entry.data.get(CONF_VERIFY_SSL, True),
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )
            errors["base"] = error
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="reconfigure", menu_options=["reconfigure_web", "reconfigure_local"]
        )

    async def _async_reconfigure_step(
        self, step_id: str, user_input: dict[str, Any] | None, *, local: bool
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        schema = LOCAL_SCHEMA if local else WEB_SCHEMA
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                url, username = self._read_form(user_input, local=local)
            except InvalidHostError:
                errors["base"] = "invalid_host"
            except ValueError:
                errors["base"] = "invalid_url"
            else:
                # Le compte doit rester le même ; l'adresse, elle, peut changer de forme
                # (nom de domaine, puis IP locale, et inversement).
                if username.lower() != entry.data[CONF_USERNAME].lower():
                    return self.async_abort(reason="wrong_account")
                verify_ssl = user_input.get(CONF_VERIFY_SSL, True)
                error = await self._async_validate(
                    url, username, user_input[CONF_PASSWORD], verify_ssl
                )
                if error is None:
                    unique_id = _unique_id(url, username)
                    if any(
                        other.unique_id == unique_id and other.entry_id != entry.entry_id
                        for other in self._async_current_entries(include_ignore=False)
                    ):
                        return self.async_abort(reason="already_configured")
                    return self.async_update_reload_and_abort(
                        entry,
                        unique_id=unique_id,
                        title=f"{username} @ {urlsplit(url).netloc}",
                        data_updates={
                            CONF_URL: url,
                            CONF_USERNAME: username,
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_VERIFY_SSL: verify_ssl,
                        },
                    )
                errors["base"] = error
        suggested = user_input or (
            {**_local_defaults(entry.data[CONF_URL])} if local else {CONF_URL: entry.data[CONF_URL]}
        )
        if user_input is None:
            suggested = {
                **suggested,
                CONF_USERNAME: entry.data[CONF_USERNAME],
                CONF_VERIFY_SSL: entry.data.get(CONF_VERIFY_SSL, True),
            }
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
        )

    async def async_step_reconfigure_web(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_reconfigure_step("reconfigure_web", user_input, local=False)

    async def async_step_reconfigure_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_reconfigure_step("reconfigure_local", user_input, local=True)


class CospendOptionsFlow(OptionsFlow):
    """Modification des projets suivis et des intervalles de lecture."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        client = CospendClient(
            async_get_clientsession(self.hass, verify_ssl=entry.data.get(CONF_VERIFY_SSL, True)),
            entry.data[CONF_URL],
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
        try:
            projects = await client.get_projects()
        except CospendError:
            return self.async_abort(reason="cannot_connect")

        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_PROJECTS]:
                errors["base"] = "no_projects"
            else:
                return self.async_create_entry(
                    data={
                        CONF_PROJECTS: user_input[CONF_PROJECTS],
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                        CONF_FULL_RESYNC_HOURS: int(user_input[CONF_FULL_RESYNC_HOURS]),
                    }
                )
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(projects, user_input or entry.options, with_intervals=True),
            errors=errors,
        )
