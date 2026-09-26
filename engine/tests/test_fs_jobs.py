"""Freshservice job handlers (T126, CLAUDE.md §2 P0-4, §8 Approve, §13.0 step 5, D-015).

- handle_fs_approval_request consumes 'approval.dispatch' (rail/approve.py): one Freshservice approval per held
  action, from its named approver, on the run's ticket; stored in door_messages and audited.
- handle_fs_approval_mirror consumes 'fs.approval.mirror' (surfaces/door.py): the decision a door recorded becomes a
  private note on the ticket, read back, with the Freshservice approval's own state beside it.
The rail runs for real over PostgreSQL; Freshservice is the FIXTURE tenant, or a MockTransport tenant for LIVE.
"""

import json
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import TransientError
from contextrail.connectors.freshservice import FreshserviceConnector
from contextrail.connectors.registry import Registry
from contextrail.connectors.state import FixtureState
from contextrail.fixtures import load
from contextrail.settings import Settings
from contextrail.surfaces.door import Door
from contextrail.surfaces.freshservice import (
    handle_fs_approval_mirror,
    handle_fs_approval_request,
    request_fs_approvals,
)

DANA, MEERA, RAVI = 7000000050, 7000000301, 7000000002
PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}


async def _anil_run(runner, source: str = "freshservice", source_ref: str | None = "4412") -> UUID:
    rid = await runner.start(source=source, request_text="Give Anil the same access as Rahul Mehta",
                             source_ref=source_ref, requested_by="p-anil")
    assert await runner.run(rid) == "awaiting_approval"
    return rid


async def _rows(deps, sql: str, *params) -> list[dict]:
    async with deps.db.connection() as c:
        return await (await c.execute(sql, params)).fetchall()


async def _hold(deps, rid: UUID, approver: str) -> dict:
    return (await _rows(deps, "select * from actions where run_id = %s and approver = %s and state = 'awaiting'",
                        rid, approver))[0]


async def _events(deps, rid: UUID) -> list[str]:
    return [r["event"] for r in await _rows(deps, "select event from audit where run_id = %s order by seq", rid)]


async def _mirror_payloads(deps) -> list[dict]:
    return [r["payload"] for r in await _rows(deps, "select payload from jobs where kind = 'fs.approval.mirror'")]


# --- approvals for held actions -------------------------------------------------------------------------------

async def test_each_held_action_gets_an_approval_from_its_named_approver_on_the_ticket(rail):
    runner, deps = rail
    rid = await _anil_run(runner)
    results = await request_fs_approvals(deps, rid)
    assert [r["status"] for r in results] == ["requested", "requested"]
    assert {r["approver_id"] for r in results} == {DANA, MEERA}
    assert all(r["ticket_id"] == 4412 and r["mode"] == "FIXTURE" and r["fallback_reason"] is None for r in results)
    fs_side = (await deps.registry.get("freshservice").list_approvals(4412)).data
    assert sorted(a["approver_id"] for a in fs_side) == sorted([DANA, MEERA])
    stored = await _rows(deps, "select action_id, ref from door_messages where run_id = %s and channel = 'freshservice'",
                         rid)
    assert len(stored) == 2 and all(s["ref"]["approval_id"] and s["ref"]["mode"] == "FIXTURE" for s in stored)
    assert (await _events(deps, rid)).count("fs.approval.requested") == 2


async def test_the_approval_email_names_the_action_rule_and_clause(rail):
    runner, deps = rail
    rid = await _anil_run(runner)
    await request_fs_approvals(deps, rid)
    dana_hold = await _hold(deps, rid, "p-dana")
    email = next(a for a in (await deps.registry.get("freshservice").list_approvals(4412)).data
                 if a["approver_id"] == DANA)["email_content"]
    assert dana_hold["rule_id"] in email and "ContextRail" in email and str(rid) in email
    assert "<script" not in email


async def test_asking_again_changes_nothing(rail):
    runner, deps = rail
    rid = await _anil_run(runner)
    await request_fs_approvals(deps, rid)
    again = await request_fs_approvals(deps, rid)
    assert [r["status"] for r in again] == ["exists", "exists"]
    assert {r["approval_status"] for r in again} == {"requested"}  # the Freshservice state, kept apart from ours
    assert len((await deps.registry.get("freshservice").list_approvals(4412)).data) == 2


async def test_the_handler_consumes_the_dispatch_jobs_the_rail_enqueued(rail):
    runner, deps = rail
    rid = await _anil_run(runner)
    payloads = [r["payload"] for r in await _rows(deps, "select payload from jobs where kind = 'approval.dispatch'")]
    assert len(payloads) == 2
    out = [await handle_fs_approval_request(p, deps) for p in payloads]
    assert {o["status"] for o in out} == {"requested"} and {o["approver_id"] for o in out} == {DANA, MEERA}
    assert all(o["run_id"] == str(rid) for o in out)


async def test_a_mapped_freshservice_id_wins_over_an_email_lookup(rail):
    runner, deps = rail
    async with deps.db.connection() as c:
        await c.execute("update identity_map set fs_agent_id = %s where person_id = 'p-meera'", (str(RAVI),))
    rid = await _anil_run(runner)
    out = await handle_fs_approval_request({"run_id": str(rid), "action_id": (await _hold(deps, rid, "p-meera"))["id"]},
                                           deps)
    assert out["approver_id"] == RAVI


async def test_an_approver_freshservice_does_not_know_is_blocked_not_guessed(rail):
    runner, deps = rail
    async with deps.db.connection() as c:
        await c.execute("update identity_map set email = 'dana@elsewhere.example' where person_id = 'p-dana'")
    rid = await _anil_run(runner)
    out = await handle_fs_approval_request({"run_id": str(rid), "action_id": (await _hold(deps, rid, "p-dana"))["id"]},
                                           deps)
    assert out["status"] == "blocked" and "p-dana" in out["reason"]
    assert (await deps.registry.get("freshservice").list_approvals(4412)).data == []
    assert "fs.approval.blocked" in await _events(deps, rid)


async def test_a_run_without_a_ticket_or_an_action_that_is_not_waiting_is_skipped(rail):
    runner, deps = rail
    slack_run = await _anil_run(runner, source="slack", source_ref="1726900000.000100")
    out = await request_fs_approvals(deps, slack_run)
    assert {o["status"] for o in out} == {"skipped"} and "no Freshservice ticket" in out[0]["reason"]
    rid = await _anil_run(runner)
    allowed = (await _rows(deps, "select id from actions where run_id = %s and verdict = 'ALLOW' limit 1", rid))[0]
    out = await handle_fs_approval_request({"run_id": str(rid), "action_id": allowed["id"]}, deps)
    assert out["status"] == "skipped" and "not awaiting" in out["reason"]


# --- mirroring a decision -------------------------------------------------------------------------------------

async def _decided_by_meera(runner, deps) -> UUID:
    rid = await _anil_run(runner)
    await request_fs_approvals(deps, rid)
    hold = await _hold(deps, rid, "p-meera")
    door = Door(runner, people=PEOPLE, modes={n: c.mode for n, c in deps.registry.connectors.items()})
    r = await door.decide(rid, hold["id"], hold["params_hash"], channel="email",
                          actor_external_id="meera.iyer@northbeam.example", decision="approved")
    assert r.outcome == "recorded"
    return rid


async def test_a_decision_from_another_door_is_mirrored_as_a_private_note_and_read_back(rail):
    runner, deps = rail
    rid = await _decided_by_meera(runner, deps)
    [payload] = await _mirror_payloads(deps)
    out = await handle_fs_approval_mirror(payload, deps)
    assert (out["status"], out["ticket_id"], out["confirmed"], out["mode"]) == ("mirrored", 4412, True, "FIXTURE")
    assert out["fs_approval"]["status"] == "requested" and out["conflict"] is False
    [note] = [c for c in load_conversations(deps) if "cr-mirror:" in c["body"]]
    assert note["private"] is True
    for fragment in ("approved", "Meera Iyer", "email", "POL-ACC-005", "cannot mark"):
        assert fragment in note["body_text"], fragment
    assert "fs.approval.mirrored" in await _events(deps, rid)


def load_conversations(deps) -> list[dict]:
    return deps.registry.get("freshservice").fixture_state.load()["conversations"]["4412"]


async def test_mirroring_twice_leaves_one_note(rail):
    runner, deps = rail
    await _decided_by_meera(runner, deps)
    [payload] = await _mirror_payloads(deps)
    first = await handle_fs_approval_mirror(payload, deps)
    second = await handle_fs_approval_mirror(payload, deps)
    assert (first["replayed"], second["replayed"]) == (False, True) and first["note_id"] == second["note_id"]
    assert sum("cr-mirror:" in c["body"] for c in load_conversations(deps)) == 1


async def test_a_freshservice_state_that_disagrees_is_flagged_and_the_first_decision_stands(rail):
    runner, deps = rail
    rid = await _decided_by_meera(runner, deps)
    state = deps.registry.get("freshservice").fixture_state

    def reject_meeras(doc):
        for a in doc["approvals"]["4412"]:
            if a["approver_id"] == MEERA:
                a["approval_status"] = {"id": 2, "name": "rejected"}

    await state.mutate(reject_meeras)
    out = await handle_fs_approval_mirror((await _mirror_payloads(deps))[0], deps)
    assert out["conflict"] is True and out["fs_approval"]["status"] == "rejected"
    note = next(c for c in load_conversations(deps) if "cr-mirror:" in c["body"])
    assert "rejected" in note["body_text"] and "first decision" in note["body_text"]
    assert (await _rows(deps, "select decision from approvals where run_id = %s", rid))[0]["decision"] == "approved"


async def test_nothing_to_mirror_is_skipped(rail):
    runner, deps = rail
    rid = await _anil_run(runner)
    hold = await _hold(deps, rid, "p-dana")
    out = await handle_fs_approval_mirror({"run_id": str(rid), "action_id": hold["id"]}, deps)
    assert out["status"] == "skipped" and "no decision" in out["reason"]
    async with deps.db.transaction() as c:
        await c.execute("insert into approvals (run_id, action_id, params_hash, approver, decision, channel) "
                        "values (%s, %s, %s, 'p-dana', 'approved', 'freshservice')", (rid, hold["id"], hold["params_hash"]))
    out = await handle_fs_approval_mirror({"run_id": str(rid), "action_id": hold["id"]}, deps)
    assert out["status"] == "skipped" and "in Freshservice" in out["reason"]


# --- LIVE: the same handler against a (mock) tenant -----------------------------------------------------------

class LiveTicket:
    def __init__(self, keep_notes: bool = True) -> None:
        self.convs: list[dict] = []
        self.keep = keep_notes

    def post(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        note = {"id": 555 + len(self.convs), "body": body["body"], "body_text": body["body"],
                "private": body["private"]}
        if self.keep:
            self.convs.append(note)
        return ok({"conversation": note}, status=201)

    def get(self, request: httpx.Request) -> httpx.Response:
        return ok({"conversations": self.convs})


def live_ctx(deps, tmp_path, tenant: FakeTenant) -> SimpleNamespace:
    live = Settings(_env_file=None, fs_domain=DOMAIN, fs_api_key=API_KEY)
    conn = FreshserviceConnector(live, state=FixtureState("freshservice", directory=tmp_path / "fs"),
                                 transport=tenant.transport)
    return SimpleNamespace(db=deps.db, registry=Registry({**deps.registry.connectors, "freshservice": conn}))


async def _decided_without_fs_approval(runner, deps) -> UUID:
    rid = await _anil_run(runner)
    hold = await _hold(deps, rid, "p-meera")
    door = Door(runner, people=PEOPLE, modes={})
    await door.decide(rid, hold["id"], hold["params_hash"], channel="email",
                      actor_external_id="meera.iyer@northbeam.example", decision="refused", reason="not needed")
    return rid


async def test_live_mirror_posts_a_private_note_to_the_tenant_and_says_live(rail, tmp_path):
    runner, deps = rail
    await _decided_without_fs_approval(runner, deps)
    ticket = LiveTicket()
    tenant = FakeTenant({("POST", "/api/v2/tickets/4412/notes"): ticket.post,
                         ("GET", "/api/v2/tickets/4412/conversations"): ticket.get})
    out = await handle_fs_approval_mirror((await _mirror_payloads(deps))[0], live_ctx(deps, tmp_path, tenant))
    assert (out["mode"], out["fallback_reason"], out["confirmed"], out["fs_approval"]) == ("LIVE", None, True, None)
    post = next(r for r in tenant.requests if r.method == "POST")
    body = json.loads(post.content)
    assert body["private"] is True and "refused" in body["body"] and "cr-mirror:" in body["body"]


async def test_a_tenant_lookup_that_fell_back_is_retried_not_blocked(rail, tmp_path):
    """The fixture's answer to a LIVE agent lookup (0 matches) is not a fact about the tenant."""
    runner, deps = rail
    rid = await _anil_run(runner)
    tenant = FakeTenant({("GET", "/api/v2/agents"): httpx.Response(503)})
    hold = await _hold(deps, rid, "p-dana")
    with pytest.raises(TransientError, match="p-dana"):
        await handle_fs_approval_request({"run_id": str(rid), "action_id": hold["id"]}, live_ctx(deps, tmp_path, tenant))
    assert "fs.approval.blocked" not in await _events(deps, rid)
    assert await _rows(deps, "select * from door_messages where run_id = %s", rid) == []


async def test_an_approval_made_in_fixture_mode_is_requested_again_once_live(rail, tmp_path):
    runner, deps = rail
    rid = await _anil_run(runner)
    await request_fs_approvals(deps, rid)  # FIXTURE: the tenant was not configured yet
    hold = await _hold(deps, rid, "p-dana")
    dana = {"id": 8123, "email": "dana.osei@northbeam.example"}
    live_approval = {"id": 99, "approver_id": 8123, "approval_status": {"id": 0, "name": "requested"}}
    tenant = FakeTenant({("GET", "/api/v2/agents"): ok({"agents": [dana]}),
                         ("GET", "/api/v2/tickets/4412/approvals"): ok({"approvals": []}),
                         ("POST", "/api/v2/tickets/4412/approvals"): ok({"approval": live_approval})})
    out = await handle_fs_approval_request({"run_id": str(rid), "action_id": hold["id"]},
                                           live_ctx(deps, tmp_path, tenant))
    assert (out["status"], out["mode"], out["approval_id"]) == ("requested", "LIVE", 99)
    [row] = await _rows(deps, "select ref from door_messages where run_id = %s and action_id = %s", rid, hold["id"])
    assert (row["ref"]["mode"], row["ref"]["approval_id"]) == ("LIVE", 99)


async def test_a_mirror_never_reads_a_fixture_approval_id_against_the_tenant(rail, tmp_path):
    runner, deps = rail
    rid = await _decided_by_meera(runner, deps)  # the approval was requested in FIXTURE mode
    ticket = LiveTicket()
    tenant = FakeTenant({("POST", "/api/v2/tickets/4412/notes"): ticket.post,
                         ("GET", "/api/v2/tickets/4412/conversations"): ticket.get})
    out = await handle_fs_approval_mirror((await _mirror_payloads(deps))[0], live_ctx(deps, tmp_path, tenant))
    assert out["mode"] == "LIVE" and out["fs_approval"]["status"] == "unavailable"
    assert not any("/approvals" in r.url.path for r in tenant.requests)  # no GET of a foreign id
    assert out["conflict"] is False and "fs.approval.mirrored" in await _events(deps, rid)


async def test_a_mirror_note_that_does_not_read_back_fails_the_job_for_a_retry(rail, tmp_path):
    runner, deps = rail
    rid = await _decided_without_fs_approval(runner, deps)
    ticket = LiveTicket(keep_notes=False)  # acknowledges with 201, keeps nothing
    tenant = FakeTenant({("POST", "/api/v2/tickets/4412/notes"): ticket.post,
                         ("GET", "/api/v2/tickets/4412/conversations"): ticket.get})
    with pytest.raises(TransientError, match="not visible"):
        await handle_fs_approval_mirror((await _mirror_payloads(deps))[0], live_ctx(deps, tmp_path, tenant))
    assert "fs.approval.mirrored" not in await _events(deps, rid)
