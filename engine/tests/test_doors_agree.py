"""The doors agree (CLAUDE.md §18 test_doors_agree, P9, X6): every door renders the same RunView for a run.

Covered here: the MCP door against the Door's own RunView, for the same run, before and after a decision taken in
another door. Slack, Teams, email and voice renderings join this file when those doors merge.
"""

import pytest
from mcp import Client
from mcp_helpers import settings

from contextrail.agentic.knowledge import RuleIndex
from contextrail.fixtures import load
from contextrail.policy.loader import load_rules
from contextrail.surfaces.door import Door
from contextrail.surfaces.mcp_server import build_mcp_server
from contextrail.surfaces.mcp_tools import ContextRailTools

PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}


@pytest.fixture
async def door(rail):
    runner, deps = rail
    return Door(runner, people=PEOPLE, modes={n: c.mode for n, c in deps.registry.connectors.items()})


async def _mcp_table(door: Door, handle: dict) -> dict:
    srv = build_mcp_server(settings(), ContextRailTools(door=lambda: door, knowledge=lambda: RuleIndex(load_rules())))
    async with Client(srv, mode="legacy") as c:
        r = await c.call_tool("check_policy_and_permissions", {"capsule_handle": handle})
    assert not r.is_error, r.content
    return r.structured_content


def _same(mcp: dict, view) -> None:
    rest = view.model_dump(mode="json")
    assert mcp["rows"] == rest["rows"]            # verdict, lamp, rule, clause verbatim, approver, state, params
    assert mcp["counts"] == rest["counts"] and mcp["modes"] == rest["modes"] and mcp["replay"] == rest["replay"]
    assert mcp["capsule_handle"]["digest"] == rest["capsule_digest"]


async def test_mcp_verdict_table_equals_the_runview_every_door_renders(door):
    view = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                actor_external_id="U0ANIL001")
    handle = {"run_id": str(view.run_id), "digest": view.capsule_digest}
    _same(await _mcp_table(door, handle), await door.get_status(view.run_id))
    refused = [r for r in view.rows if r.verdict == "REFUSE"]
    assert refused and all(r.clause and r.struck_through for r in refused)


async def test_they_still_agree_after_a_decision_in_another_door(door):
    view = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                actor_external_id="U0ANIL001")
    hold = next(r for r in view.rows if r.approver_id == "p-dana")
    decided = await door.decide(view.run_id, hold.action_id, hold.params_hash, channel="teams",
                                actor_external_id="00000000-0000-4000-8000-000000000050", decision="approved")
    after = decided.view
    handle = {"run_id": str(after.run_id), "digest": after.capsule_digest}
    _same(await _mcp_table(door, handle), await door.get_status(after.run_id))
