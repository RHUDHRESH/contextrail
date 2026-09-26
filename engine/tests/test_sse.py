"""GET /v1/runs/{id}/events: history first, then live StageEvents; heartbeat; ends on a terminal status."""

import asyncio
import json
import uuid

import pytest

from contextrail.rail.events import EventBus
from contextrail.surfaces.sse import stage_events

DANA_TEAMS, MEERA_EMAIL = "00000000-0000-4000-8000-000000000050", "meera.iyer@northbeam.example"


def status_of(value: str):
    box = {"status": value}

    async def load() -> str:
        return box["status"]

    load.box = box
    return load


async def test_history_first_then_live_then_end_on_a_terminal_event():
    bus, rid = EventBus(), uuid.uuid4()
    await bus.emit(rid, "discover", "running", "Found Anil")
    await bus.emit(rid, "compile", "running", "Case file sealed")
    gen = stage_events(bus, rid, status_of("running"), heartbeat_s=5)
    history = [await anext(gen), await anext(gen)]
    assert [(e.event, e.id, e.data.stage) for e in history] == [("stage", "0", "discover"), ("stage", "1", "compile")]
    live = asyncio.create_task(anext(gen))
    await asyncio.sleep(0.01)
    assert not live.done()                                   # nothing new yet: the stream waits
    await bus.emit(rid, "govern", "running", "Govern: 13 allowed, 2 held, 1 refused")
    assert (await asyncio.wait_for(live, 1)).data.seq == 2   # delivered live
    await bus.emit(rid, "finalize", "partial", "partial: 17 verified")
    final, end = await anext(gen), await anext(gen)
    assert (final.data.status, end.event, json.loads(json.dumps(end.data))) == (
        "partial", "end", {"run_id": str(rid), "status": "partial"})
    with pytest.raises(StopAsyncIteration):
        await anext(gen)
    assert not bus._queues[rid]                              # unsubscribed: no leaked queue


async def test_heartbeat_while_waiting_and_end_when_the_database_says_finished():
    bus, rid, load = EventBus(), uuid.uuid4(), status_of("awaiting_approval")
    gen = stage_events(bus, rid, load, heartbeat_s=0.01)
    assert (await anext(gen)).comment == "keep-alive"
    load.box["status"] = "done"                              # finished in another process (e.g. the worker)
    end = await anext(gen)
    assert (end.event, end.data["status"]) == ("end", "done")


async def test_last_event_id_skips_what_the_client_already_has():
    bus, rid = EventBus(), uuid.uuid4()
    for stage in ("discover", "compile", "govern"):
        await bus.emit(rid, stage, "running", stage)
    gen = stage_events(bus, rid, status_of("running"), heartbeat_s=5, after_seq=1)
    assert (await anext(gen)).id == "2"
    await gen.aclose()
    assert not bus._queues[rid]


async def test_a_run_finished_elsewhere_ends_at_once():
    gen = stage_events(EventBus(), uuid.uuid4(), status_of("partial"), heartbeat_s=5)
    assert (await anext(gen)).event == "end"


# --- over HTTP -------------------------------------------------------------------------------------------------

def parse(body: str) -> list[dict]:
    frames = []
    for block in body.strip().split("\n\n"):
        frame = {}
        for line in block.splitlines():
            key, _, value = line.partition(": ")
            frame[key or "comment"] = value
        frames.append(frame)
    return [f for f in frames if "comment" not in f]


async def _approve_both(client, view):
    holds = {r["approver_id"]: r for r in view["rows"] if r["state"] == "awaiting"}
    for who, channel, actor in (("p-dana", "teams", DANA_TEAMS), ("p-meera", "email", MEERA_EMAIL)):
        r = await client.post(f"/v1/runs/{view['run_id']}/decisions", json={
            "action_id": holds[who]["action_id"], "params_hash": holds[who]["params_hash"], "channel": channel,
            "actor_external_id": actor, "decision": "approved"})
        assert r.json()["outcome"] == "recorded"


async def _start(client):
    r = await client.post("/v1/runs", json={"request_text": "Give Anil the same access as Rahul Mehta",
                                             "channel": "slack", "actor_external_id": "U0ANIL001"})
    return r.json()


async def test_events_need_the_token_and_an_existing_run(api):
    client, _ = api
    assert (await client.get(f"/v1/runs/{uuid.uuid4()}/events")).status_code == 404
    client.headers.pop("Authorization")
    assert (await client.get(f"/v1/runs/{uuid.uuid4()}/events")).status_code == 401


async def test_the_whole_story_streams_in_order_and_the_stream_ends(api):
    client, _ = api
    view = await _start(client)
    await _approve_both(client, view)
    r = await client.get(f"/v1/runs/{view['run_id']}/events")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    frames = parse(r.text)
    stages = [json.loads(f["data"]) for f in frames if f.get("event") == "stage"]
    assert [s["seq"] for s in stages] == list(range(19))       # first pass 9, then 5 per resume
    assert stages[0]["stage"] == "discover" and (stages[-1]["stage"], stages[-1]["status"]) == ("finalize", "partial")
    assert [f["id"] for f in frames if f.get("event") == "stage"] == [str(s["seq"]) for s in stages]
    assert frames[-1]["event"] == "end" and json.loads(frames[-1]["data"])["status"] == "partial"
    resumed = await client.get(f"/v1/runs/{view['run_id']}/events", headers={"Last-Event-ID": "16"})
    assert [f.get("id") for f in parse(resumed.text)] == ["17", "18", None]      # then 'end', which has no id


async def test_a_client_watching_an_awaiting_run_sees_the_decisions_land_live(api):
    client, platform = api
    view = await _start(client)
    rid = uuid.UUID(view["run_id"])
    watching = asyncio.create_task(client.get(f"/v1/runs/{rid}/events"))
    for _ in range(200):                                      # wait until the stream has subscribed
        if platform.events._queues[rid]:
            break
        await asyncio.sleep(0.01)
    assert platform.events._queues[rid]
    await _approve_both(client, view)
    r = await asyncio.wait_for(watching, 30)
    stages = [json.loads(f["data"]) for f in parse(r.text) if f.get("event") == "stage"]
    assert [s["seq"] for s in stages] == list(range(19)) and stages[-1]["status"] == "partial"
