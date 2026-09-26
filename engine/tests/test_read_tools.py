"""Personal read tools enforce ownership and return source citations from stored records."""

from contextrail.fixtures import load
from contextrail.knowledge.okf import load_bundle
from contextrail.knowledge.rag import index_bundle
from contextrail.policy.loader import load_rules
from contextrail.surfaces.door import Door
from contextrail.surfaces.read_tools import PlatformReadTools


async def test_run_status_and_my_runs_are_scoped_to_the_requester(rail):
    runner, _ = rail
    people = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
    door = Door(runner, people=people, modes={})
    view = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                actor_external_id="U0ANIL001")
    reads = PlatformReadTools(door)

    allowed = await reads.run_status(view.run_id, actor_id="p-anil")
    denied = await reads.run_status(view.run_id, actor_id="p-rahul")
    own_list = await reads.my_runs(5, actor_id="p-anil")
    other_list = await reads.my_runs(5, actor_id="p-rahul")

    assert allowed.supported and str(view.run_id) in allowed.text
    assert all(citation.startswith("audit:") for citation in allowed.citations)
    assert not denied.supported and denied.citations == []
    assert own_list.supported and str(view.run_id) in own_list.text
    assert not other_list.supported


async def test_knowledge_answer_cites_indexed_okf_chunks(rail):
    runner, deps = rail
    async with deps.db.transaction() as conn:
        await index_bundle(conn, load_bundle(), load_rules())
    reads = PlatformReadTools(Door(runner, people={}, modes={}))
    found = await reads.search_knowledge("POL-CTR-001 contractor production credentials", actor_id=None)
    assert found.supported
    assert any(citation.startswith("okf:") for citation in found.citations)
    assert "POL-CTR-001" in found.text or "production" in found.text.lower()
