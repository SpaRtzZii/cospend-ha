"""Fixtures communes : faux serveur Cospend et client branché dessus."""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from fake_server import FakeCospend

from aiocospend import CospendClient


@pytest.fixture(autouse=True)
def _allow_local_sockets(request: pytest.FixtureRequest) -> None:
    """Autorise les sockets locaux si pytest-socket est présent (ex. avec Home Assistant)."""
    try:
        request.getfixturevalue("socket_enabled")
    except pytest.FixtureLookupError:
        pass


@pytest.fixture
async def fake() -> AsyncIterator[FakeCospend]:
    fake_cospend = FakeCospend()
    server = TestServer(fake_cospend.app)
    await server.start_server()
    fake_cospend.url = str(server.make_url("")).rstrip("/")
    try:
        yield fake_cospend
    finally:
        await server.close()


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client_session:
        yield client_session


@pytest.fixture
def client(fake: FakeCospend, session: aiohttp.ClientSession) -> CospendClient:
    return CospendClient(session, fake.url, fake.username, fake.password, timeout=5)
