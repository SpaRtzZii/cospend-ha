"""Tests du flux de configuration."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_USER
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
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from aiocospend import (
    CospendAuthenticationError,
    CospendBadRequestError,
    CospendConnectionError,
    CospendError,
    CospendResponseError,
    CospendSSLError,
    CospendVersionError,
)
from custom_components.cospend.config_flow import InvalidHostError, build_local_url
from custom_components.cospend.const import (
    CONF_FULL_RESYNC_HOURS,
    CONF_MANAGE_ADMIN_ONLY,
    CONF_PROJECTS,
    DOMAIN,
)

from .fake_client import FakeClient

USER_INPUT = {
    CONF_URL: "cloud.example.org/",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_VERIFY_SSL: True,
}


LOCAL_INPUT = {
    CONF_HOST: "192.168.1.20",
    CONF_PORT: 8080,
    CONF_SSL: False,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_VERIFY_SSL: False,
}


async def _start(hass: HomeAssistant, choice: str = "web"):
    """Ouvre l'assistant et choisit le mode de connexion (``web`` ou ``local``)."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "user"
    assert result["menu_options"] == ["web", "local"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": choice}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == choice
    return result


async def test_full_flow(hass: HomeAssistant, mock_flow_client, mock_setup_entry) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "projects"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROJECTS: ["teste"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "admin @ cloud.example.org"
    assert result["data"][CONF_URL] == "https://cloud.example.org"  # adresse normalisée
    assert result["options"][CONF_PROJECTS] == ["teste"]
    assert result["result"].unique_id == "https://cloud.example.org|admin"


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (CospendAuthenticationError("401"), "invalid_auth"),
        (CospendConnectionError("down"), "cannot_connect"),
        (CospendSSLError("cert"), "ssl_error"),
        (CospendVersionError("old"), "unsupported_version"),
        (CospendBadRequestError("400", status=400), "untrusted_domain"),
        (CospendResponseError("html"), "invalid_response"),
        (CospendError("autre"), "unknown"),
    ],
)
async def test_connection_errors_then_recovery(
    hass: HomeAssistant,
    mock_flow_client: FakeClient,
    mock_setup_entry,
    error: CospendError,
    key: str,
) -> None:
    mock_flow_client.error = error
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}

    mock_flow_client.error = None
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["step_id"] == "projects"


def test_build_local_url() -> None:
    assert build_local_url("192.168.1.20", 8080, False) == "http://192.168.1.20:8080"
    assert build_local_url(" 10.0.0.5 ", 443.0, True) == "https://10.0.0.5:443"
    assert build_local_url("nas.local", 80, False) == "http://nas.local:80"
    assert build_local_url("fd00::1", 8080, False) == "http://[fd00::1]:8080"
    assert build_local_url("[fd00::1]", 8080, False) == "http://[fd00::1]:8080"


@pytest.mark.parametrize(
    ("host", "port"),
    [
        ("", 80),
        ("http://192.168.1.20", 80),
        ("192.168.1.20/nextcloud", 80),
        ("a b", 80),
        ("192.168.1.20", 0),
        ("192.168.1.20", 70000),
    ],
)
def test_build_local_url_rejects_garbage(host: str, port: int) -> None:
    with pytest.raises(InvalidHostError):
        build_local_url(host, port, False)


async def test_local_flow(hass: HomeAssistant, mock_flow_client, mock_setup_entry) -> None:
    result = await _start(hass, "local")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOCAL_INPUT)
    assert result["step_id"] == "projects"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROJECTS: ["teste"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "admin @ 192.168.1.20:8080"
    assert result["data"][CONF_URL] == "http://192.168.1.20:8080"
    assert result["data"][CONF_VERIFY_SSL] is False
    assert result["result"].unique_id == "http://192.168.1.20:8080|admin"


async def test_local_invalid_host_then_recovery(
    hass: HomeAssistant, mock_flow_client, mock_setup_entry
) -> None:
    result = await _start(hass, "local")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**LOCAL_INPUT, CONF_HOST: "http://192.168.1.20"}
    )
    assert result["errors"] == {"base": "invalid_host"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOCAL_INPUT)
    assert result["step_id"] == "projects"


async def test_invalid_url(hass: HomeAssistant, mock_flow_client: FakeClient) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_URL: "ftp://exemple"}
    )
    assert result["errors"] == {"base": "invalid_url"}


async def test_no_project_selected(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_setup_entry
) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_PROJECTS: []})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_projects"}


async def test_already_configured(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry, mock_setup_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    mock_flow_client.error = CospendAuthenticationError("401")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "mauvais"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    mock_flow_client.error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "nouveau"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "nouveau"


async def _reconfigure(hass, entry, choice: str):
    result = await entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["reconfigure_web", "reconfigure_local"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": f"reconfigure_{choice}"}
    )
    assert result["type"] is FlowResultType.FORM
    return result


async def test_reconfigure_web_keeps_the_same_account(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry, mock_setup_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await _reconfigure(hass, mock_config_entry, "web")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_URL: "https://cloud.example.org/"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_from_web_address_to_local_ip(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry, mock_setup_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await _reconfigure(hass, mock_config_entry, "local")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], LOCAL_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data[CONF_URL] == "http://192.168.1.20:8080"
    assert mock_config_entry.unique_id == "http://192.168.1.20:8080|admin"
    assert mock_config_entry.title == "admin @ 192.168.1.20:8080"
    assert mock_config_entry.options[CONF_PROJECTS] == ["teste"]  # projets conservés


async def test_reconfigure_local_form_is_prefilled(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await _reconfigure(hass, mock_config_entry, "local")
    schema = {str(key): key.description for key in result["data_schema"].schema}
    assert schema[CONF_HOST] == {"suggested_value": "cloud.example.org"}
    assert schema[CONF_PORT] == {"suggested_value": 443}
    assert schema[CONF_SSL] == {"suggested_value": True}


async def test_reconfigure_rejects_another_account(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry, mock_setup_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await _reconfigure(hass, mock_config_entry, "web")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_USERNAME: "quelquun-d-autre"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"


async def test_options_flow(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_PROJECTS: ["teste"], CONF_SCAN_INTERVAL: 5, CONF_FULL_RESYNC_HOURS: 12},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_PROJECTS: ["teste"],
        CONF_SCAN_INTERVAL: 5,
        CONF_FULL_RESYNC_HOURS: 12,
        CONF_MANAGE_ADMIN_ONLY: False,
    }


async def test_options_flow_cannot_connect(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    mock_flow_client.error = CospendConnectionError("down")
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
