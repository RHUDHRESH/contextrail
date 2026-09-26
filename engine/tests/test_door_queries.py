"""Personal questions resolve exact owned references; general questions cite curated knowledge."""

from contextrail import repo
from contextrail.fixtures import load
from contextrail.knowledge.okf import load_bundle
from contextrail.knowledge.rag import index_bundle
from contextrail.llm.question_agent import NO_SUPPORT, QuestionAnswer
from contextrail.policy.loader import load_rules
from contextrail.surfaces.door import Door
from contextrail.surfaces.read_tools import PlatformReadTools

ANIL = "U0ANIL001"
RAHUL = "U0RAHU007"


def _door(runner):
    people = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
    return Door(runner, people=people, modes={})


async def test_freshservice_requester_and_approver_ids_use_distinct_namespaces(rail):
    runner, deps = rail
    door = _door(runner)
    async with deps.db.transaction() as conn:
        await conn.execute("update identity_map set fs_requester_id = '42' where person_id = 'p-anil'")
        await conn.execute("update identity_map set fs_agent_id = '42' where person_id = 'p-meera'")
    assert (await door.resolve_actor("freshservice", "42"))["person_id"] == "p-anil"
    assert (await door.resolve_actor("freshservice", "42", for_approval=True))["person_id"] == "p-meera"
    assert (await door.resolve_actor("freshservice", "ANIL.KUMAR@NORTHBEAM.EXAMPLE"))["person_id"] == "p-anil"


async def test_named_status_lookup_uses_owned_run_instead_of_latest(rail):
    runner, deps = rail
    door = _door(runner)
    anil = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                actor_external_id=ANIL, source_ref="C1:123")
    priya = await door.start_run("Priya starts Monday, give her everything", channel="slack",
                                 actor_external_id=ANIL, source_ref="C1:124")
    assert anil.run_id != priya.run_id
    async with deps.db.transaction() as conn:
        await repo.upsert_door_message(conn, anil.run_id, "freshservice",
                                       {"status": "verified", "ticket_id": 4711, "mode": "FIXTURE"})

    for question in ("What's the update on Anil Kumar?", f"Status of run {anil.run_id}",
                     f"Status of run {str(anil.run_id)[:8]}", "What is the status of ticket 4711?",
                     f"Status of run {' '.join(anil.run_id.hex[:8].upper())}", "Update on 4711?"):
        answer = await door.answer_query(question, channel="slack", actor_external_id=ANIL)
        assert answer.run_id == anil.run_id, question
        assert answer.citations and answer.sources == [f"audit:{seq}" for seq in answer.citations]

    absent = await door.answer_query("What's the update on Nobody Example?", channel="slack",
                                     actor_external_id=ANIL)
    assert absent.run_id is None and "for that reference" in absent.text
    private = await door.answer_query(f"Status of run {anil.run_id}", channel="slack", actor_external_id=RAHUL)
    assert private.run_id is None and private.citations == []


async def test_repeated_subject_name_requires_a_specific_reference(rail):
    runner, _ = rail
    door = _door(runner)
    first = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                 actor_external_id=ANIL, source_ref="C1:123")
    await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                         actor_external_id=ANIL, source_ref="C1:124")
    ambiguous = await door.answer_query("What's the update on Anil Kumar?", channel="slack",
                                        actor_external_id=ANIL)
    assert ambiguous.run_id is None and "multiple requests" in ambiguous.text
    exact = await door.answer_query(f"Status of run {first.run_id}", channel="slack", actor_external_id=ANIL)
    assert exact.run_id == first.run_id


async def test_thread_memory_points_to_its_run_and_is_rechecked_for_ownership(rail):
    runner, _ = rail
    door = _door(runner)
    first = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                 actor_external_id=ANIL, source_ref="C1:123")
    await door.start_run("Priya starts Monday, give her everything", channel="slack",
                         actor_external_id=ANIL, source_ref="C1:124")
    await door.memory.append(channel="slack", person_id="p-anil", thread_ref="call-77", role="user",
                             summary="Follow up", run_id=first.run_id)
    answer = await door.answer_query("Any update on my request?", channel="slack", actor_external_id=ANIL,
                                     thread_ref="call-77")
    assert answer.run_id == first.run_id
    other = await door.answer_query("Any update on my request?", channel="slack", actor_external_id=RAHUL,
                                    thread_ref="call-77")
    assert other.run_id is None


async def test_door_links_request_and_question_to_authoritative_run_without_raw_text(rail):
    runner, deps = rail
    door = _door(runner)
    view = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                actor_external_id=ANIL, source_ref="C1:123.4")
    answer = await door.answer_query("What happened?", channel="slack", actor_external_id=ANIL,
                                     thread_ref="C1:123.4")
    assert answer.run_id == view.run_id and answer.citations
    why = await door.answer_query("Why was that refused?", channel="slack", actor_external_id=ANIL,
                                  thread_ref="C1:123.4")
    assert why.run_id == view.run_id and "Recorded reasons:" in why.text and "POL-ACC-003" in why.text
    async with deps.db.connection() as c:
        governed = await (await c.execute("select seq from audit where run_id = %s and event = 'stage.govern'",
                                          (view.run_id,))).fetchone()
    assert governed["seq"] in why.citations
    rows = await door.memory.recent(channel="slack", person_id="p-anil", thread_ref="C1:123.4")
    assert [r.role for r in rows] == ["user", "user", "assistant", "user", "assistant"]
    assert all("Anil" not in r.summary and "Rahul" not in r.summary for r in rows)
    assert rows[-1].audit_seqs == tuple(why.citations)
    unknown = await door.answer_query("status?", channel="slack", actor_external_id="U0UNKNOWN",
                                      thread_ref="C1:123.4")
    assert unknown.run_id is None and unknown.citations == []


async def test_general_question_has_curated_citation_for_unknown_actor_and_model_failure(rail):
    runner, deps = rail
    async with deps.db.transaction() as conn:
        await index_bundle(conn, load_bundle(), load_rules())
    door = _door(runner)
    door.read_tools = PlatformReadTools(door)

    class UnsupportedAgent:
        async def ask(self, *_args, **_kwargs):
            return QuestionAnswer(text=NO_SUPPORT, citations=[], tools_used=[], author="none")

    door.question_agent = UnsupportedAgent()
    answer = await door.answer_query("Can contractors get production credentials under POL-CTR-001?",
                                     channel="voice", actor_external_id=None)
    assert answer.run_id is None and answer.sources
    assert all(source.startswith("okf:") for source in answer.sources)
    assert "production" in answer.text.lower() or "POL-CTR-001" in answer.text
