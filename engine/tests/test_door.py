"""The door contract: every door's request, decision and question goes through these checks."""

import psycopg
import pytest

from contextrail.fixtures import load
from contextrail.surfaces.door import Door

PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
ANIL_SLACK, DANA_TEAMS, MEERA_EMAIL, RAHUL_SLACK = "U0ANIL001", "00000000-0000-4000-8000-000000000050", \
    "Meera.Iyer@northbeam.example", "U0RAHU007"


@pytest.fixture
async def door(rail):
    runner, deps = rail
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    return Door(runner, people=PEOPLE, modes=modes), deps


async def _anil_run(door):
    view = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                actor_external_id=ANIL_SLACK)
    holds = {r.approver_id: r for r in view.rows if r.state == "awaiting"}
    return view, holds


async def test_start_run_resolves_the_requester_and_returns_the_view(door):
    d, _ = door
    view, holds = await _anil_run(d)
    assert view.status == "awaiting_approval" and set(holds) == {"p-dana", "p-meera"}


async def test_named_approvers_decide_from_different_doors_and_the_run_completes(door):
    d, deps = door
    view, holds = await _anil_run(d)
    r1 = await d.decide(view.run_id, holds["p-dana"].action_id, holds["p-dana"].params_hash, channel="teams",
                        actor_external_id=DANA_TEAMS, decision="approved")
    assert r1.outcome == "recorded" and r1.view.status == "awaiting_approval"
    r2 = await d.decide(view.run_id, holds["p-meera"].action_id, holds["p-meera"].params_hash, channel="email",
                        actor_external_id=MEERA_EMAIL, decision="approved")   # case-insensitive email match
    assert r2.outcome == "recorded" and r2.view.status == "partial"          # partial: the refusal stands
    assert r2.view.counts["verified"] == 17 and r2.view.counts["refuse"] == 1
    async with deps.db.connection() as c:
        jobs = [r["kind"] for r in await (await c.execute("select kind from jobs order by id")).fetchall()]
    assert jobs.count("fs.approval.mirror") == 2 and jobs.count("door.update") == 2


async def test_first_decision_wins_and_later_doors_are_told_who(door):
    d, _ = door
    view, holds = await _anil_run(d)
    h = holds["p-dana"]
    await d.decide(view.run_id, h.action_id, h.params_hash, channel="teams", actor_external_id=DANA_TEAMS,
                   decision="approved")
    again = await d.decide(view.run_id, h.action_id, h.params_hash, channel="slack", actor_external_id="U0DANA050",
                           decision="refused")
    assert (again.outcome, again.decided_by, again.decided_channel) == ("already_decided", "p-dana", "teams")


@pytest.mark.parametrize(("channel", "actor", "fragment"), [
    ("slack", RAHUL_SLACK, "only Dana Osei can decide"),     # not the named approver
    ("slack", "U0NOBODY", "unknown identity"),               # not in the identity map
])
async def test_wrong_people_are_rejected(door, channel, actor, fragment):
    d, _ = door
    view, holds = await _anil_run(d)
    h = holds["p-dana"]
    r = await d.decide(view.run_id, h.action_id, h.params_hash, channel=channel, actor_external_id=actor,
                       decision="approved")
    assert r.outcome == "rejected" and fragment in r.reason


async def test_stale_card_is_rejected(door):
    d, _ = door
    view, holds = await _anil_run(d)
    h = holds["p-dana"]
    r = await d.decide(view.run_id, h.action_id, "f" * 64, channel="teams", actor_external_id=DANA_TEAMS,
                       decision="approved")
    assert r.outcome == "rejected" and "out of date" in r.reason


async def test_separation_of_duties_is_enforced_at_decision_time(door, migrated_db):
    d, _ = door
    view, holds = await _anil_run(d)
    with psycopg.connect(migrated_db, autocommit=True) as c:  # suppose Dana turns out to be the requester
        c.execute("update runs set requested_by = 'p-dana' where id = %s", (view.run_id,))
    h = holds["p-dana"]
    r = await d.decide(view.run_id, h.action_id, h.params_hash, channel="teams", actor_external_id=DANA_TEAMS,
                       decision="approved")
    assert (r.outcome, r.rule_id) == ("rejected", "POL-SOD-001") and "void" in r.reason


async def test_refusing_a_hold_is_final(door):
    d, _ = door
    view, holds = await _anil_run(d)
    h = holds["p-meera"]
    r = await d.decide(view.run_id, h.action_id, h.params_hash, channel="email", actor_external_id=MEERA_EMAIL,
                       decision="refused", reason="no budget this quarter")
    row = next(x for x in r.view.rows if x.action_id == h.action_id)
    assert row.state == "refused"


async def test_candidate_pick_through_the_door(door):
    d, _ = door
    view = await d.start_run("Give Anil the same access as Rahul", channel="slack", actor_external_id=ANIL_SLACK)
    assert view.status == "needs_input" and {c["source_id"] for c in view.needs[0]["candidates"]} == {"E-0007", "E-0415"}
    done = await d.pick_candidate(view.run_id, "peer", "E-0007")
    assert done.status == "awaiting_approval" and done.peer == "Rahul Mehta"


async def test_answer_query_from_stored_facts_with_citations(door):
    d, _ = door
    await _anil_run(d)
    a = await d.answer_query("What happened to my request?", channel="slack", actor_external_id=ANIL_SLACK)
    assert "15 done and verified" in a.text and "Dana Osei" in a.text and "Meera Iyer" in a.text
    assert "POL-ACC-003" in a.text and a.citations
