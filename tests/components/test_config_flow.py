"""Tests du flux de configuration."""

from __future__ import annotations

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from aiocospend import (
    CospendAuthenticationError,
    CospendConnectionError,
    CospendError,
    CospendResponseError,
    CospendSSLError,
    CospendVersionError,
)
from custom_components.cospend.const import CONF_FULL_RESYNC_HOURS, CONF_PROJECTS, DOMAIN

from .fake_client import FakeClient

USER_INPUT = {
    CONF_URL: "cloud.example.org/",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_VERIFY_SSL: True,
}


async def _start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
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


async def test_reconfigure_keeps_the_same_account(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry, mock_setup_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_URL: "https://cloud.example.org/"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_rejects_another_account(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry, mock_setup_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reconfigure_flow(hass)
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
    }


async def test_options_flow_cannot_connect(
    hass: HomeAssistant, mock_flow_client: FakeClient, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    mock_flow_client.error = CospendConnectionError("down")
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"
