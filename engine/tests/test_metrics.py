"""GET /v1/metrics: counts computed from the tables, never estimated."""

from decimal import Decimal

DANA_TEAMS, MEERA_EMAIL = "00000000-0000-4000-8000-000000000050", "meera.iyer@northbeam.example"


async def test_an_empty_engine_reports_zeros_not_guesses(api):
    client, _ = api
    m = (await client.get("/v1/metrics")).json()
    assert m["runs"]["total"] == 0 and m["verdicts"] == {"ALLOW": 0, "HOLD": 0, "REFUSE": 0}
    assert m["time_to_access_s"] == {"median": None, "count": 0}
    assert m["llm"] == {"calls": 0, "replay_calls": 0, "cost_usd_by_tier": {}} and m["decisions_by_door"] == {}


async def test_metrics_after_the_same_as_rahul_story(api):
    client, platform = api
    view = (await client.post("/v1/runs", json={"request_text": "Give Anil the same access as Rahul Mehta",
                                                 "channel": "slack", "actor_external_id": "U0ANIL001"})).json()
    await client.post("/v1/runs", json={"request_text": "Give Anil the same access as Rahul", "channel": "teams",
                                        "actor_external_id": "00000000-0000-4000-8000-000000001042"})
    holds = {r["approver_id"]: r for r in view["rows"] if r["state"] == "awaiting"}
    for who, channel, actor in (("p-dana", "teams", DANA_TEAMS), ("p-meera", "email", MEERA_EMAIL)):
        await client.post(f"/v1/runs/{view['run_id']}/decisions", json={
            "action_id": holds[who]["action_id"], "params_hash": holds[who]["params_hash"], "channel": channel,
            "actor_external_id": actor, "decision": "approved"})
    async with platform.db.transaction() as c:
        for tier, cost, replay in (("T1", "0.001200", False), ("T1", "0.000800", False), ("T4", "0", True)):
            await c.execute("insert into llm_calls (run_id, stage, model, tier, cost_usd, replay) "
                            "values (%s, 'discover', 'claude-haiku-4-5-20251001', %s, %s, %s)",
                            (view["run_id"], tier, cost, replay))
    r = await client.get("/v1/metrics")
    assert r.status_code == 200
    m = r.json()
    assert m["runs"] == {"total": 2, "by_status": {"needs_input": 1, "partial": 1},
                         "by_source": {"slack": 1, "teams": 1}}
    assert m["verdicts"] == {"ALLOW": 15, "HOLD": 2, "REFUSE": 1}
    assert m["time_to_access_s"]["count"] == 15 and m["time_to_access_s"]["median"] >= 0   # 13 allowed + 2 approved
    assert m["decisions_by_door"] == {"email": 1, "teams": 1}
    assert m["llm"]["calls"] == 3 and m["llm"]["replay_calls"] == 1
    assert {k: Decimal(v) for k, v in m["llm"]["cost_usd_by_tier"].items()} == {"T1": Decimal("0.002"),
                                                                                "T4": Decimal(0)}


async def test_metrics_need_the_token(api):
    client, _ = api
    client.headers.pop("Authorization")
    assert (await client.get("/v1/metrics")).status_code == 401
