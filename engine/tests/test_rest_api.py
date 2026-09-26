"""The door contract over HTTP: the same RunView and DecisionResult every other door gets, behind a bearer token."""

import asyncio
import uuid

import httpx
import pytest

from contextrail.app_state import build_platform
from contextrail.main import create_app
from contextrail.settings import Settings

ANIL_SLACK, DANA_TEAMS, MEERA_EMAIL = "U0ANIL001", "00000000-0000-4000-8000-000000000050", "meera.iyer@northbeam.example"
ANIL_REQUEST = {"request_text": "Give Anil the same access as Rahul Mehta", "channel": "slack",
                "actor_external_id": ANIL_SLACK}


async def _start(client, **overrides) -> dict:
    r = await client.post("/v1/runs", json={**ANIL_REQUEST, **overrides})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _holds(view: dict) -> dict[str, dict]:
    return {row["approver_id"]: row for row in view["rows"] if row["state"] == "awaiting"}


@pytest.mark.parametrize("header", [None, "Bearer wrong-token", "Basic dXNlcjpwYXNz", "Bearer "])
async def test_runs_api_requires_the_engine_token(api, header):
    client, _ = api
    headers = {"Authorization": header} if header else {}
    client.headers.pop("Authorization")
    r = await client.get(f"/v1/runs/{uuid.uuid4()}", headers=headers)
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")


@pytest.mark.parametrize("configured", ["", "change-me"])
async def test_an_unset_or_placeholder_token_closes_the_api(rail, configured):
    runner, _ = rail
    settings = Settings(_env_file=None, engine_token=configured)
    app = create_app(settings, platform=build_platform(settings, runner=runner))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine.test") as client:
        r = await client.post("/v1/runs", json=ANIL_REQUEST, headers={"Authorization": f"Bearer {configured}"})
    assert r.status_code == 503 and "ENGINE_TOKEN" in r.json()["detail"]


async def test_start_run_returns_the_door_view_and_get_returns_the_same(api):
    client, _ = api
    r = await client.post("/v1/runs", json=ANIL_REQUEST)
    assert r.status_code == 201
    view = r.json()
    assert view["status"] == "awaiting_approval" and set(_holds(view)) == {"p-dana", "p-meera"}
    assert (view["counts"]["allow"], view["counts"]["hold"], view["counts"]["refuse"]) == (15, 2, 1)
    assert r.headers["location"] == f"/v1/runs/{view['run_id']}"
    again = await client.get(r.headers["location"])
    assert again.status_code == 200 and again.json() == view


async def test_requester_history_is_resolved_and_scoped_to_the_actor(api):
    client, _ = api
    own = await _start(client)
    mine = await client.post("/v1/runs/mine", json={"channel": "slack", "actor_external_id": ANIL_SLACK})
    other = await client.post("/v1/runs/mine", json={"channel": "email", "actor_external_id": "priya.r@contractor.northbeam.example"})
    assert mine.status_code == 200 and [run["run_id"] for run in mine.json()["runs"]] == [own["run_id"]]
    assert other.status_code == 200 and other.json()["runs"] == []


async def test_unknown_and_malformed_run_ids(api):
    client, _ = api
    missing = await client.get(f"/v1/runs/{uuid.uuid4()}")
    assert missing.status_code == 404 and missing.headers["content-type"].startswith("application/problem+json")
    assert (await client.get("/v1/runs/not-a-uuid")).status_code == 422


async def test_a_ticket_gets_one_run_and_the_sidebar_finds_it_by_ticket(api):
    client, platform = api
    ticket = {"channel": "freshservice", "source_ref": "4242", "actor_external_id": "fs-agent-7"}
    first = await client.post("/v1/runs", json={**ANIL_REQUEST, **ticket})
    second = await client.post("/v1/runs", json={**ANIL_REQUEST, **ticket})   # FDK backup trigger, same ticket
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["run_id"] == second.json()["run_id"]
    by_ticket = await client.get("/v1/runs/by-ticket/4242")
    assert by_ticket.status_code == 200 and by_ticket.json()["run_id"] == first.json()["run_id"]
    await _start(client, source_ref="4243")                                    # a Slack ref is not a ticket
    assert (await client.get("/v1/runs/by-ticket/4243")).status_code == 404
    async with platform.db.connection() as c:
        n = (await (await c.execute("select count(*) as n from runs where source_ref = '4242'")).fetchone())["n"]
    assert n == 1


async def test_simultaneous_starts_for_one_ticket_still_make_one_run(api):
    client, platform = api
    ticket = {**ANIL_REQUEST, "channel": "freshservice", "source_ref": "5151", "actor_external_id": "fs-agent-7"}
    responses = await asyncio.gather(*(client.post("/v1/runs", json=ticket) for _ in range(3)))
    assert sorted(r.status_code for r in responses) == [200, 200, 201]
    assert len({r.json()["run_id"] for r in responses}) == 1
    async with platform.db.connection() as c:
        n = (await (await c.execute("select count(*) as n from runs where source_ref = '5151'")).fetchone())["n"]
    assert n == 1


async def test_pick_resolves_needs_input_and_is_refused_once_the_run_moved_on(api):
    client, _ = api
    view = await _start(client, request_text="Give Anil the same access as Rahul")
    assert view["status"] == "needs_input"
    assert {c["source_id"] for c in view["needs"][0]["candidates"]} == {"E-0007", "E-0415"}
    picked = await client.post(f"/v1/runs/{view['run_id']}/pick", json={"role": "peer", "source_id": "E-0007"})
    assert picked.status_code == 200 and picked.json()["status"] == "awaiting_approval"
    assert picked.json()["peer"] == "Rahul Mehta"
    again = await client.post(f"/v1/runs/{view['run_id']}/pick", json={"role": "peer", "source_id": "E-0415"})
    assert again.status_code == 409
    missing = await client.post(f"/v1/runs/{uuid.uuid4()}/pick", json={"role": "peer", "source_id": "E-0007"})
    assert missing.status_code == 404


async def test_a_double_clicked_candidate_runs_the_rail_once(api):
    client, platform = api
    view = await _start(client, request_text="Give Anil the same access as Rahul")
    url = f"/v1/runs/{view['run_id']}/pick"
    responses = await asyncio.gather(*(client.post(url, json={"role": "peer", "source_id": "E-0007"})
                                       for _ in range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    async with platform.db.connection() as c:
        n = (await (await c.execute("select count(*) as n from audit where run_id = %s and event = 'stage.compile'",
                                    (view["run_id"],))).fetchone())["n"]
    assert n == 1


async def test_decisions_go_through_the_door_first_one_wins(api):
    client, _ = api
    view = await _start(client)
    dana, meera = _holds(view)["p-dana"], _holds(view)["p-meera"]
    url = f"/v1/runs/{view['run_id']}/decisions"

    def body(row, channel, actor, decision="approved"):
        return {"action_id": row["action_id"], "params_hash": row["params_hash"], "channel": channel,
                "actor_external_id": actor, "decision": decision}

    r1 = (await client.post(url, json=body(dana, "teams", DANA_TEAMS))).json()
    assert r1["outcome"] == "recorded" and r1["view"]["status"] == "awaiting_approval"
    late = (await client.post(url, json=body(dana, "slack", "U0DANA050", "refused"))).json()
    assert (late["outcome"], late["decided_by"], late["decided_channel"]) == ("already_decided", "p-dana", "teams")
    wrong = (await client.post(url, json=body(meera, "slack", ANIL_SLACK))).json()
    assert wrong["outcome"] == "rejected" and "only Meera Iyer can decide" in wrong["reason"]
    r2 = (await client.post(url, json=body(meera, "email", MEERA_EMAIL))).json()
    assert r2["outcome"] == "recorded" and r2["view"]["status"] == "partial" and r2["view"]["counts"]["verified"] == 17


async def test_decision_bodies_are_validated_at_the_boundary(api):
    client, _ = api
    view = await _start(client)
    row = _holds(view)["p-dana"]
    ok = {"action_id": row["action_id"], "params_hash": row["params_hash"], "channel": "teams",
          "actor_external_id": DANA_TEAMS, "decision": "approved"}
    for bad in ({"params_hash": "not-a-hash"}, {"decision": "maybe"}, {"channel": "fax"}):
        r = await client.post(f"/v1/runs/{view['run_id']}/decisions", json={**ok, **bad})
        assert r.status_code == 422, bad
