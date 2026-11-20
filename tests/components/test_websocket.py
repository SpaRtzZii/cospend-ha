"""Tests de l'API websocket de la carte."""

from __future__ import annotations

from dataclasses import replace

from homeassistant.core import HomeAssistant

from aiocospend import Ower

from .fake_client import FakeClient


async def _call(client, payload: dict):
    await client.send_json_auto_id(payload)
    return await client.receive_json()


async def test_projects(hass: HomeAssistant, init_integration, hass_ws_client) -> None:
    client = await hass_ws_client(hass)
    response = await _call(client, {"type": "cospend/projects"})
    assert response["success"]
    (project,) = response["result"]["projects"]
    assert project["id"] == "teste"
    assert project["entry_id"] == init_integration.entry_id
    assert project["can_write"] is True
    assert project["pending"] == 0
    assert {m["name"] for m in project["members"]} == {"util1", "util2", "util3"}
    assert all("balance" in m for m in project["members"])
    assert project["members"][0]["color"].startswith("#")
    assert any(c["name"] == "Courses" for c in project["categories"])


async def test_bills_are_sorted_and_paginated(
    hass: HomeAssistant, init_integration, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    full = (await _call(client, {"type": "cospend/bills", "project_id": "teste"}))["result"]
    stamps = [item["timestamp"] for item in full["items"]]
    assert stamps == sorted(stamps, reverse=True)
    assert full["total"] == len(full["items"]) > 1
    assert full["has_more"] is False

    first = (await _call(client, {"type": "cospend/bills", "project_id": "teste", "limit": 1}))[
        "result"
    ]
    assert first["has_more"] is True
    assert [i["id"] for i in first["items"]] == [full["items"][0]["id"]]
    second = (
        await _call(
            client, {"type": "cospend/bills", "project_id": "teste", "limit": 1, "offset": 1}
        )
    )["result"]
    assert second["items"][0]["id"] == full["items"][1]["id"]


async def test_search(hass: HomeAssistant, init_integration, hass_ws_client) -> None:
    client = await hass_ws_client(hass)
    everything = (await _call(client, {"type": "cospend/bills", "project_id": "teste"}))["result"]
    title = everything["items"][0]["what"]
    result = (
        await _call(
            client,
            {"type": "cospend/bills", "project_id": "teste", "search": title.upper()},
        )
    )["result"]
    assert result["total"] >= 1
    assert all(title.casefold() in item["what"].casefold() for item in result["items"])
    nothing = (
        await _call(
            client, {"type": "cospend/bills", "project_id": "teste", "search": "zzz-introuvable"}
        )
    )["result"]
    assert nothing["total"] == 0 and nothing["items"] == []


async def test_custom_split_is_grouped_and_detailed(
    hass: HomeAssistant, init_integration, fake_client: FakeClient, hass_ws_client
) -> None:
    template = next(iter(fake_client.bills.values()))
    members = fake_client.project.members
    for offset, (member, amount) in enumerate(zip(members, (10.0, 20.0, 30.0), strict=True)):
        fake_client.bills[200 + offset] = replace(
            template,
            id=200 + offset,
            what="Resto",
            amount=amount,
            comment="soirée #USD:11@0.9",
            timestamp=template.timestamp + 5000,
            payer_id=members[0].id,
            owers=(Ower(member.id, 1.0, member.name, True),),
            last_changed=fake_client.clock + 1,
        )
    fake_client.clock += 10
    await init_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    listing = (await _call(client, {"type": "cospend/bills", "project_id": "teste"}))["result"]
    group = listing["items"][0]
    assert group["is_group"] is True
    assert group["ids"] == [200, 201, 202]
    assert group["amount"] == 60.0
    assert group["comment"] == "soirée"  # métadonnée de devise retirée
    assert group["foreign"] == {"currency": "USD", "amount": 11.0, "rate": 0.9}
    assert len(group["ower_ids"]) == 3

    detail = (await _call(client, {"type": "cospend/bill", "project_id": "teste", "bill_id": 201}))[
        "result"
    ]
    assert detail["ids"] == [200, 201, 202]
    assert sorted(share["amount"] for share in detail["shares"]) == [10.0, 20.0, 30.0]


async def test_even_split_shares(
    hass: HomeAssistant, init_integration, fake_client: FakeClient, hass_ws_client
) -> None:
    template = next(iter(fake_client.bills.values()))
    members = fake_client.project.members
    fake_client.bills[300] = replace(
        template,
        id=300,
        amount=90.0,
        owers=tuple(Ower(m.id, 1.0, m.name, True) for m in members),
        last_changed=fake_client.clock + 1,
    )
    fake_client.clock += 10
    await init_integration.runtime_data.async_refresh()

    client = await hass_ws_client(hass)
    detail = (await _call(client, {"type": "cospend/bill", "project_id": "teste", "bill_id": 300}))[
        "result"
    ]
    assert [share["amount"] for share in detail["shares"]] == [30.0, 30.0, 30.0]
    assert detail["uneven_weights"] is False
    assert detail["repeat_all_active"] is False


async def test_unknown_project_and_bill(
    hass: HomeAssistant, init_integration, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    response = await _call(client, {"type": "cospend/bills", "project_id": "nope"})
    assert response["success"] is False and response["error"]["code"] == "not_found"
    response = await _call(
        client, {"type": "cospend/bill", "project_id": "teste", "bill_id": 999999}
    )
    assert response["success"] is False and response["error"]["code"] == "not_found"


async def test_subscribe_notifies_on_refresh(
    hass: HomeAssistant, init_integration, fake_client: FakeClient, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "cospend/subscribe"})
    assert (await client.receive_json())["success"]

    fake_client.simulate_add(500, what="Nouvelle")
    await init_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()
    event = await client.receive_json()
    assert event["type"] == "event"
    assert event["event"] == {"changed": True}


async def test_card_is_registered_when_built(hass: HomeAssistant, tmp_path) -> None:
    from unittest.mock import AsyncMock, patch

    import custom_components.cospend as integration

    card = tmp_path / "cospend-card.js"
    card.write_text("// carte", encoding="utf-8")
    hass.http = AsyncMock()
    with (
        patch.object(integration, "CARD_FILE", card),
        patch.object(integration, "add_extra_js_url") as add_url,
    ):
        await integration._async_register_card(hass)
    (paths,) = hass.http.async_register_static_paths.call_args.args
    assert paths[0].url_path == integration.CARD_URL
    assert paths[0].path == str(card)
    assert add_url.call_args.args[1].startswith(f"{integration.CARD_URL}?v=")


async def test_card_is_skipped_when_not_built(hass: HomeAssistant, tmp_path) -> None:
    from unittest.mock import AsyncMock, patch

    import custom_components.cospend as integration

    hass.http = AsyncMock()
    with patch.object(integration, "CARD_FILE", tmp_path / "absent.js"):
        await integration._async_register_card(hass)
    hass.http.async_register_static_paths.assert_not_called()


async def test_card_registration_survives_a_missing_frontend(hass: HomeAssistant, tmp_path) -> None:
    from unittest.mock import AsyncMock, patch

    import custom_components.cospend as integration

    card = tmp_path / "cospend-card.js"
    card.write_text("// carte", encoding="utf-8")
    hass.http = AsyncMock()
    with (
        patch.object(integration, "CARD_FILE", card),
        patch.object(integration, "add_extra_js_url", side_effect=KeyError("frontend")),
    ):
        await integration._async_register_card(hass)  # ne doit pas lever


async def test_uneven_weights_are_reported(
    hass: HomeAssistant, init_integration, fake_client: FakeClient, hass_ws_client
) -> None:
    template = next(iter(fake_client.bills.values()))
    members = fake_client.project.members
    fake_client.bills[310] = replace(
        template,
        id=310,
        amount=90.0,
        owers=(
            Ower(members[0].id, 2.0, members[0].name, True),
            Ower(members[1].id, 1.0, members[1].name, True),
        ),
        last_changed=fake_client.clock + 1,
    )
    fake_client.clock += 10
    await init_integration.runtime_data.async_refresh()
    client = await hass_ws_client(hass)
    detail = (await _call(client, {"type": "cospend/bill", "project_id": "teste", "bill_id": 310}))[
        "result"
    ]
    assert detail["uneven_weights"] is True
    assert [share["amount"] for share in detail["shares"]] == [60.0, 30.0]


async def test_settlement_from_the_server(
    hass: HomeAssistant, init_integration, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    response = await _call(client, {"type": "cospend/settlement", "project_id": "teste"})
    assert response["success"]
    result = response["result"]
    assert result["source"] == "server"
    assert result["pending"] == 0
    assert result["transactions"] == [
        {"from_id": 14, "to_id": 12, "amount": 666.67},
        {"from_id": 13, "to_id": 12, "amount": 16.67},
    ]


async def test_settlement_falls_back_to_a_local_plan(
    hass: HomeAssistant, init_integration, hass_ws_client, fake_client: FakeClient
) -> None:
    from aiocospend import CospendConnectionError

    fake_client.settlement_error = CospendConnectionError("hors ligne")
    client = await hass_ws_client(hass)
    result = (await _call(client, {"type": "cospend/settlement", "project_id": "teste"}))["result"]
    assert result["source"] == "local"
    assert result["transactions"]
    assert all(t["amount"] > 0 and t["from_id"] != t["to_id"] for t in result["transactions"])


async def test_settlement_unknown_project(
    hass: HomeAssistant, init_integration, hass_ws_client
) -> None:
    client = await hass_ws_client(hass)
    response = await _call(client, {"type": "cospend/settlement", "project_id": "autre"})
    assert not response["success"]
    assert response["error"]["code"] == "not_found"
