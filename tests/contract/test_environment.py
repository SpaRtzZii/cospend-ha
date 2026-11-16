"""Vérifie que le serveur de test (Nextcloud + Cospend) est prêt.

Exécuté seulement avec les variables d'environnement :
COSPEND_TEST_URL, COSPEND_TEST_USER, COSPEND_TEST_PASSWORD.
"""

from __future__ import annotations

import os

import aiohttp
import pytest

from aiocospend.const import (
    API_VERSION,
    CAPABILITIES_PATH,
    MIN_COSPEND_VERSION,
    OCS_BASE_PATH,
)

pytestmark = pytest.mark.contract

URL = os.environ.get("COSPEND_TEST_URL", "").rstrip("/")
USER = os.environ.get("COSPEND_TEST_USER", "")
PASSWORD = os.environ.get("COSPEND_TEST_PASSWORD", "")

if not (URL and USER and PASSWORD):
    pytest.skip("variables COSPEND_TEST_* absentes", allow_module_level=True)

HEADERS = {"OCS-APIRequest": "true", "Accept": "application/json"}


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


@pytest.fixture
async def session():
    async with aiohttp.ClientSession(auth=aiohttp.BasicAuth(USER, PASSWORD)) as s:
        yield s


async def test_cospend_capabilities(session: aiohttp.ClientSession) -> None:
    async with session.get(f"{URL}{CAPABILITIES_PATH}", headers=HEADERS) as response:
        assert response.status == 200
        payload = await response.json()
    version = payload["ocs"]["data"]["capabilities"]["cospend"]["version"]
    assert _version_tuple(version) >= _version_tuple(MIN_COSPEND_VERSION)


async def test_projects_endpoint(session: aiohttp.ClientSession) -> None:
    url = f"{URL}{OCS_BASE_PATH}/{API_VERSION}/projects"
    async with session.get(url, headers=HEADERS) as response:
        assert response.status == 200
        payload = await response.json()
    assert isinstance(payload["ocs"]["data"], list)
