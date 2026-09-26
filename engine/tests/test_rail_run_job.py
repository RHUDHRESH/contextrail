"""'rail.run' jobs: a ticket gets one run, stuck or approved runs continue, finished ones are left alone."""

import uuid

import pytest

from contextrail import repo
from contextrail.app_state import build_platform
from contextrail.intake import TicketRequest, rail_run
from contextrail.jobs import PermanentJobError, handlers
from contextrail.settings import Settings

ANIL = "Give Anil the same access as Rahul Mehta"


class FakeTickets:
    """Stands in for the Freshservice ticket read (connector in section I)."""

    mode = "FIXTURE"

    def __init__(self, requests: dict[str, TicketRequest]) -> None:
        self.requests, self.reads = requests, []

    async def ticket_request(self, ticket_id: str) -> TicketRequest:
        self.reads.append(ticket_id)
        return self.requests[ticket_id]


@pytest.fixture
def platform(rail):
    runner, _ = rail
    return build_platform(Settings(_env_file=None), runner=runner)


async def _rows(platform, sql, *params) -> list[dict]:
    async with platform.db.connection() as c:
        return await (await c.execute(sql, params)).fetchall()


async def _events(platform, run_id) -> list[str]:
    return [r["event"] for r in await _rows(platform, "select event from audit where run_id = %s order by seq", run_id)]


def test_rail_run_is_a_registered_handler():
    assert handlers.get("rail.run") is rail_run


async def test_a_ticket_job_starts_one_run_and_a_duplicate_changes_nothing(platform):
    platform.tickets = FakeTickets({"4242": TicketRequest(ticket_id="4242", text=ANIL)})
    await rail_run(platform, {"ticket_id": 4242, "source": "freshservice"})
    await rail_run(platform, {"ticket_id": "4242"})
    runs = await _rows(platform, "select * from runs")
    assert [(r["source"], r["source_ref"], r["status"]) for r in runs] == [("freshservice", "4242", "awaiting_approval")]
    assert platform.tickets.reads == ["4242"]
    assert (await _events(platform, runs[0]["id"])).count("stage.finalize") == 1


async def test_a_run_job_runs_a_run_that_was_created_but_never_run(platform):
    rid = await platform.runner.start(source="freshservice", request_text=ANIL, source_ref="77")
    await rail_run(platform, {"run_id": str(rid)})
    assert (await _rows(platform, "select status from runs where id = %s", rid))[0]["status"] == "awaiting_approval"


async def test_a_stuck_ticket_run_is_continued_without_reading_the_ticket_again(platform):
    platform.tickets = FakeTickets({})
    rid = await platform.runner.start(source="email", request_text=ANIL, source_ref="88")   # crashed before running
    await rail_run(platform, {"ticket_id": "88", "source": "email"})
    assert (await _rows(platform, "select status from runs where id = %s", rid))[0]["status"] == "awaiting_approval"
    assert platform.tickets.reads == []


async def test_a_run_job_resumes_an_approved_run_then_leaves_the_finished_run_alone(platform):
    rid = await platform.runner.start(source="slack", request_text=ANIL, requested_by="p-anil")
    await platform.runner.run(rid)
    undecided = await _events(platform, rid)
    await rail_run(platform, {"run_id": str(rid)})              # nobody has decided yet: nothing to resume
    assert await _events(platform, rid) == undecided
    async with platform.db.transaction() as c:
        for a in await repo.list_actions(c, rid):
            if a["state"] == "awaiting":
                await repo.record_approval(c, rid, a["id"], params_hash=a["params_hash"], approver=a["approver"],
                                           decision="approved", channel="freshservice")
    await rail_run(platform, {"run_id": str(rid)})
    assert (await _rows(platform, "select status from runs where id = %s", rid))[0]["status"] == "partial"
    before = await _events(platform, rid)
    await rail_run(platform, {"run_id": str(rid)})
    assert await _events(platform, rid) == before


async def test_a_run_waiting_for_input_is_left_for_the_requester(platform):
    rid = await platform.runner.start(source="slack", request_text="Give Anil the same access as Rahul")
    await platform.runner.run(rid)
    before = await _events(platform, rid)
    await rail_run(platform, {"run_id": str(rid)})
    assert await _events(platform, rid) == before


@pytest.mark.parametrize("payload", [
    {},                                                       # neither
    {"run_id": str(uuid.uuid4()), "ticket_id": "1"},          # both
    {"run_id": "not-a-uuid"},
    {"ticket_id": "1", "source": "slack"},                    # not a ticket-backed source
    {"run_id": str(uuid.uuid4())},                            # no such run
])
async def test_bad_payloads_fail_permanently(platform, payload):
    with pytest.raises(PermanentJobError):
        await rail_run(platform, payload)


async def test_a_ticket_job_needs_a_ticket_reader(platform):
    assert platform.tickets is None
    with pytest.raises(PermanentJobError, match="ticket reader"):
        await rail_run(platform, {"ticket_id": "9"})
