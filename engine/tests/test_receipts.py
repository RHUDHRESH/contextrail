"""Receipts: a short summary and the full JSON of a run, built only from stored facts, honest about tampering."""

import uuid

import psycopg
import pytest

from contextrail import repo
from contextrail.app_state import build_platform
from contextrail.jobs import PermanentJobError, Worker, handlers, load_handlers
from contextrail.receipts import build_receipt, receipt_build
from contextrail.settings import Settings

ANIL = "Give Anil the same access as Rahul Mehta"
DANA_TEAMS, MEERA_EMAIL = "00000000-0000-4000-8000-000000000050", "meera.iyer@northbeam.example"


@pytest.fixture
async def anil(rail):
    """The platform and Anil's run, finished its first pass (15 verified, 2 held, 1 refused)."""
    runner, _ = rail
    platform = build_platform(Settings(_env_file=None), runner=runner)
    view = await platform.door.start_run(ANIL, channel="slack", actor_external_id="U0ANIL001")
    return platform, view


async def _build(platform, run_id):
    return await build_receipt(platform.db, run_id, people=platform.door.people, modes=platform.modes)


async def _rows(platform, sql, *params):
    async with platform.db.connection() as c:
        return await (await c.execute(sql, params)).fetchall()


async def test_receipt_carries_every_action_decision_evidence_digest_audit_range_and_mode(anil):
    platform, view = anil
    r = await _build(platform, view.run_id)
    b = r.body
    run = (await _rows(platform, "select * from runs where id = %s", view.run_id))[0]
    assert r.created and b["run"]["status"] == "awaiting_approval" and b["run"]["request_text"] == ANIL
    assert (b["subject"]["source_id"], b["peer"]["source_id"]) == ("E-1042", "E-0007")
    assert len(b["actions"]) == 18 and all(a["verdict"] and a["rule_id"] and a["clause"] for a in b["actions"])
    assert all(a["verified_at"] for a in b["actions"] if a["state"] == "verified")
    refused = [a for a in b["actions"] if a["verdict"] == "REFUSE"]
    assert [(a["rule_id"], a["state"]) for a in refused] == [("POL-ACC-003", "refused")] and refused[0]["clause"]
    assert b["decisions"] == [] and b["tally"]["verified"] == 15
    evidence = {e["id"]: e for e in b["evidence"]}
    assert evidence["EV-slk_payments_admin_override"]["trust"] == "untrusted"
    assert b["capsule"] == {"digest": run["capsule_digest"], "seal_verified": True, "problem": None}
    seqs = [x["seq"] for x in await _rows(platform, "select seq from audit where run_id = %s and event not like "
                                                    "'receipt.%%' order by seq", view.run_id)]
    assert (b["audit"]["from_seq"], b["audit"]["to_seq"], b["audit"]["events"]) == (seqs[0], seqs[-1], len(seqs))
    assert b["chain"]["ok"] is True
    assert b["connectors"] == {"dodo": "FIXTURE", "entitlements": "FIXTURE", "freshservice": "FIXTURE",
                               "github": "FIXTURE", "hris": "FIXTURE",
                               "slack_corpus": "FIXTURE"}
    assert b["digest"] == r.digest and (r.audit_from, r.audit_to) == (seqs[0], seqs[-1])


async def test_the_summary_is_short_and_names_what_matters(anil):
    platform, view = anil
    s = (await _build(platform, view.run_id)).summary
    assert "awaiting approval" in s and "15 allowed" in s and "2 held" in s and "1 refused" in s
    assert "POL-ACC-003" in s and "Dana Osei" in s and "Meera Iyer" in s
    assert "FIXTURE" in s and "chain intact" in s and "seal verified" in s
    assert len(s.splitlines()) <= 16


async def test_the_receipt_is_stored_and_chained_and_an_unchanged_rebuild_is_a_no_op(anil):
    platform, view = anil
    first = await _build(platform, view.run_id)
    again = await _build(platform, view.run_id)
    assert not again.created and again.digest == first.digest
    stored = await _rows(platform, "select * from receipts where run_id = %s", view.run_id)
    assert stored[0]["summary"] == first.summary and stored[0]["body"]["digest"] == first.digest
    built = await _rows(platform, "select payload from audit where run_id = %s and event = 'receipt.built'",
                        view.run_id)
    assert [e["payload"]["digest"] for e in built] == [first.digest]


async def test_a_new_outcome_gets_a_new_receipt_with_who_decided_where(anil):
    platform, view = anil
    first = await _build(platform, view.run_id)
    holds = {r.approver_id: r for r in view.rows if r.state == "awaiting"}
    await platform.door.decide(view.run_id, holds["p-dana"].action_id, holds["p-dana"].params_hash,
                               channel="teams", actor_external_id=DANA_TEAMS, decision="approved")
    await platform.door.decide(view.run_id, holds["p-meera"].action_id, holds["p-meera"].params_hash,
                               channel="email", actor_external_id=MEERA_EMAIL, decision="approved")
    second = await _build(platform, view.run_id)
    assert second.created and second.digest != first.digest and second.body["run"]["status"] == "partial"
    decisions = {d["approver"]: d for d in second.body["decisions"]}
    assert (decisions["p-dana"]["channel"], decisions["p-meera"]["channel"]) == ("teams", "email")
    assert all(d["decided_at"] and d["decision"] == "approved" for d in decisions.values())
    assert "approved by Dana Osei via teams" in second.summary and "17 verified" in second.summary


async def test_a_broken_audit_chain_is_reported_not_hidden(anil, migrated_db):
    platform, view = anil
    with psycopg.connect(migrated_db, autocommit=True) as c:
        seq = c.execute("select min(seq) from audit where run_id = %s", (view.run_id,)).fetchone()[0]
        c.execute("alter table audit disable trigger audit_no_update")
        c.execute("update audit set payload = '{\"forged\": true}' where seq = %s", (seq,))
        c.execute("alter table audit enable trigger audit_no_update")
    r = await _build(platform, view.run_id)
    assert r.body["chain"]["ok"] is False and r.body["chain"]["first_broken_seq"] == seq
    assert f"chain BROKEN at seq {seq}" in r.summary


async def test_a_tampered_capsule_is_reported(anil, migrated_db):
    platform, view = anil
    with psycopg.connect(migrated_db, autocommit=True) as c:
        c.execute("""update runs set capsule = jsonb_set(capsule, '{constraints}', '["forged"]') where id = %s""",
                  (view.run_id,))
    r = await _build(platform, view.run_id)
    assert r.body["capsule"]["seal_verified"] is False and "digest" in r.body["capsule"]["problem"]
    assert "seal BROKEN" in r.summary


async def test_receipt_build_jobs_from_finalize_are_run_by_the_worker(anil):
    platform, view = anil
    assert "receipt.build" in load_handlers() and handlers.get("receipt.build") is receipt_build
    out = await Worker(platform.db, platform).run_once()
    while out is not None and out.kind != "receipt.build":   # approval.dispatch has no handler here: not claimed
        out = await Worker(platform.db, platform).run_once()
    assert out.outcome == "done"
    assert len(await _rows(platform, "select 1 from receipts where run_id = %s", view.run_id)) == 1


async def test_a_receipt_job_for_no_run_fails_permanently(anil):
    platform, _ = anil
    with pytest.raises(PermanentJobError):
        await receipt_build(platform, {"run_id": str(uuid.uuid4())})
    with pytest.raises(PermanentJobError):
        await receipt_build(platform, {"run_id": "nope"})


async def test_a_run_without_actions_still_gets_an_honest_receipt(rail):
    runner, _ = rail
    platform = build_platform(Settings(_env_file=None), runner=runner)
    rid = await runner.start(source="slack", request_text="What happened to my access request?")
    await runner.run(rid)
    r = await _build(platform, rid)
    assert r.body["actions"] == [] and r.body["subject"] is None
    assert r.body["capsule"] == {"digest": None, "seal_verified": None, "problem": "no case file was compiled"}
    async with platform.db.transaction() as c:  # keep repo import honest: the run row is untouched by a receipt
        assert (await repo.get_run(c, rid))["status"] == "done"
