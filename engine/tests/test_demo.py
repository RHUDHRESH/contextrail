"""The scripted demo (checklist T221, partial). Every outcome an audience sees is produced by the real rail over the
FIXTURE data; these tests pin what the rail does for each scenario, and that docs/DEMO_DATA.md is exactly what the
demo writes from a real run (so the document cannot drift from the rail)."""

import asyncio
from pathlib import Path

from contextrail import demo
from contextrail.fixtures import load

SCENARIOS = {s.key: s for s in demo.SCENARIOS}
DOC = Path(__file__).resolve().parents[2] / "docs" / "DEMO_DATA.md"
KEY_BY_LABEL = {t["label"]: k for k, t in load("entitlements")["catalog"].items()}


async def _run(rail, key):
    runner, _ = rail
    return await demo.run_scenario(demo.door_for(runner), SCENARIOS[key])


def _rows(outcome):
    return {KEY_BY_LABEL[r.label]: r for r in outcome.view.rows}


async def test_same_as_rahul_is_13_2_1_plus_two_revokes(rail):
    o = await _run(rail, "same-as-rahul")
    assert o.status == "awaiting_approval"
    assert o.grants == {"ALLOW": 13, "HOLD": 2, "REFUSE": 1}
    assert [(r.verdict, r.rule_id, r.state) for r in o.revokes] == [("ALLOW", "POL-OFF-001", "verified")] * 2
    rows = _rows(o)
    assert {r.approver_name for r in rows.values() if r.verdict == "HOLD"} == {"Dana Osei", "Meera Iyer"}
    admin = rows["aws-payments-prod-admin"]
    assert (admin.verdict, admin.rule_id, admin.struck_through) == ("REFUSE", "POL-ACC-003", True)


async def test_ambiguous_rahul_asks_which_one_instead_of_guessing(rail):
    o = await _run(rail, "ambiguous-rahul")
    assert o.status == "needs_input" and o.view.rows == []
    assert o.message == "Which Rahul? Rahul Mehta (payments), Rahul Verma (risk-analytics)"
    assert {c["source_id"] for c in o.view.needs[0]["candidates"]} == {"E-0007", "E-0415"}


async def test_contractor_onboarding_holds_the_sow_repo_and_refuses_production_credentials(rail):
    o = await _run(rail, "contractor-onboarding")
    rows = _rows(o)
    assert o.status == "awaiting_approval" and len(rows) == 3
    assert (rows["slack-general"].verdict, rows["slack-general"].state) == ("ALLOW", "verified")
    repo = rows["gh-perception-sdk-read"]
    assert (repo.verdict, repo.rule_id, repo.approver_name) == ("HOLD", "POL-ACC-004", "Dana Osei")
    prod = rows["aws-perception-prod-credentials"]
    assert (prod.verdict, prod.rule_id) == ("REFUSE", "POL-CTR-001")
    assert "never receive production credentials" in prod.clause


async def test_transfer_mirrors_the_new_team_and_revokes_the_old_one(rail):
    o = await _run(rail, "team-transfer")
    assert o.status == "done" and o.grants == {"ALLOW": 5}
    assert [KEY_BY_LABEL[r.label] for r in o.revokes] == ["looker-risk-dashboards", "slack-risk-analytics"]
    assert all(r.state == "verified" for r in o.view.rows)
    assert _rows(o)["gh-analytics-dbt-read"].rule_id == "POL-ACC-001"  # in her new role's baseline


async def test_a_senior_engineers_production_admin_is_held_for_security_not_refused(rail):
    o = await _run(rail, "senior-admin")
    rows = _rows(o)
    assert o.status == "awaiting_approval" and o.grants == {"ALLOW": 1, "HOLD": 1}
    admin = rows["aws-platform-prod-admin"]
    assert (admin.verdict, admin.rule_id, admin.approver_name) == ("HOLD", "POL-ACC-003", "Dana Osei")
    assert rows["pagerduty-platform-responder"].state == "verified"


async def test_analytics_hire_gets_raw_pii_under_written_rule(rail):
    o = await _run(rail, "raw-pii")
    rows = _rows(o)
    assert o.status == "done" and o.grants == {"ALLOW": 10}
    raw = rows["snowflake-raw-pii"]
    assert (raw.verdict, raw.rule_id, raw.state) == ("ALLOW", "POL-DAT-001", "verified")
    assert rows["snowflake-analytics-masked"].state == "verified"
    assert all(r.state == "verified" for r in rows.values() if r.verdict == "ALLOW")


async def test_a_paid_seat_is_held_for_the_manager(rail):
    o = await _run(rail, "paid-seat")
    rows = _rows(o)
    assert o.status == "awaiting_approval" and o.grants == {"ALLOW": 1, "HOLD": 1}
    seat = rows["figma-professional-seat"]
    assert (seat.verdict, seat.rule_id, seat.approver_name) == ("HOLD", "POL-ACC-005", "Meera Iyer")
    assert rows["gh-payments-web-read"].state == "verified"


async def test_a_question_is_routed_to_receipts_not_run(rail):
    o = await _run(rail, "question")
    assert o.status == "done" and o.view.rows == []
    assert o.message == "This is a question; answered from receipts."


async def test_the_script_runs_every_scenario_in_order_and_writes_the_committed_document(migrated_db, tmp_path, capsys):
    out = tmp_path / "DEMO_DATA.md"
    assert await asyncio.to_thread(demo.main, ["demo", migrated_db, "--state-dir", str(tmp_path / "state"),
                                             "--markdown", str(out)]) == 0
    printed = capsys.readouterr().out
    statuses = [line.split()[2] for line in printed.splitlines() if line[:2].strip().isdigit()]
    assert statuses == ["awaiting_approval", "needs_input", "awaiting_approval", "done", "awaiting_approval",
                        "done", "awaiting_approval", "done"]
    assert DOC.read_text(encoding="utf-8") == out.read_text(encoding="utf-8"), (
        "docs/DEMO_DATA.md is stale: regenerate it with python -m contextrail.demo --embedded-postgres "
        "--markdown ../docs/DEMO_DATA.md")
