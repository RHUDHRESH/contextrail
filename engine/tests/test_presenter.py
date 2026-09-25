from contextrail import repo
from contextrail.fixtures import load
from contextrail.surfaces.presenter import build_view

PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}


async def _view(deps, rid):
    async with deps.db.connection() as c:
        run, actions = await repo.get_run(c, rid), await repo.list_actions(c, rid)
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    return build_view(run, actions, people=PEOPLE, modes=modes)


async def test_run_view_for_same_as_rahul(rail):
    runner, deps = rail
    rid = await runner.start(source="slack", request_text="Give Anil the same access as Rahul Mehta",
                             requested_by="p-anil")
    await runner.run(rid)
    v = await _view(deps, rid)
    assert (v.status, v.subject, v.peer, len(v.rows)) == ("awaiting_approval", "Anil Kumar", "Rahul Mehta", 18)
    assert [r.lamp for r in v.rows] == ["✅"] * 15 + ["🟠"] * 2 + ["⛔"]
    assert all(r.verified for r in v.rows[:15])
    holds = v.rows[15:17]
    assert [h.approver_name for h in holds] == ["Dana Osei", "Meera Iyer"]
    assert all(h.explanation.startswith("Held for") and h.explainer == "template" for h in holds)
    refused = v.rows[17]
    assert refused.struck_through and refused.rule_id == "POL-ACC-003" and "senior engineers" in refused.clause
    assert refused.label == "AWS payments-prod AdministratorAccess"
    assert v.counts == {"allow": 15, "hold": 2, "refuse": 1, "verified": 15, "awaiting": 2, "failed": 0}
    assert set(v.modes.values()) == {"FIXTURE"} and all(r.connector_mode == "FIXTURE" for r in v.rows)


async def test_view_is_a_pure_function_of_stored_state(rail):
    runner, deps = rail
    rid = await runner.start(source="slack", request_text="Give Anil the same access as Rahul Mehta")
    await runner.run(rid)
    assert (await _view(deps, rid)) == (await _view(deps, rid))  # any door asking gets the identical view
