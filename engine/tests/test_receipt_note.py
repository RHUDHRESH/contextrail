"""The receipt reaches the Freshservice ticket as a private note, once per receipt, labelled with its mode."""

import pytest

from contextrail import repo
from contextrail.app_state import build_platform
from contextrail.jobs import PermanentJobError, Worker, handlers, load_handlers
from contextrail.receipts import build_receipt, receipt_note
from contextrail.settings import Settings

ANIL = "Give Anil the same access as Rahul Mehta"
DANA_TEAMS, MEERA_EMAIL = "00000000-0000-4000-8000-000000000050", "meera.iyer@northbeam.example"


class FakeNotes:
    """Stands in for POST /api/v2/tickets/{id}/notes (the Freshservice connector, section I). Records, never sends."""

    mode = "FIXTURE"

    def __init__(self, failures: int = 0) -> None:
        self.notes: list[tuple[str, str]] = []
        self.failures = failures

    async def add_private_note(self, ticket_id: str, body: str) -> str:
        if self.failures:
            self.failures -= 1
            raise RuntimeError("freshservice 503")
        self.notes.append((ticket_id, body))
        return f"note-{len(self.notes)}"


@pytest.fixture
def platform(rail):
    runner, _ = rail
    p = build_platform(Settings(_env_file=None), runner=runner)
    p.notes = FakeNotes()
    load_handlers()
    return p


async def _drain(platform) -> list:
    worker, outs = Worker(platform.db, platform, retry_delay=lambda n: 0), []
    while (out := await worker.run_once()) is not None:
        outs.append(out)
    return outs


async def _rows(platform, sql, *params):
    async with platform.db.connection() as c:
        return await (await c.execute(sql, params)).fetchall()


async def _ticket_run(platform, ticket="4242"):
    # An email-created ticket (D-007) whose requester resolves: holds on a run with no attributable requester cannot
    # be approved at all (POL-SOD-001 fails closed), which would stop the story before its final receipt.
    return await platform.door.start_run(ANIL, channel="email", actor_external_id="anil.kumar@northbeam.example",
                                         source_ref=ticket)


def test_receipt_note_is_a_registered_handler():
    load_handlers()
    assert handlers.get("receipt.note") is receipt_note


async def test_a_ticket_run_gets_its_receipt_as_one_private_note(platform):
    view = await _ticket_run(platform)
    await _drain(platform)
    receipt = (await _rows(platform, "select * from receipts where run_id = %s", view.run_id))[0]
    assert platform.notes.notes == [("4242", receipt["summary"])] and receipt["fs_note_id"] == "note-1"
    noted = await _rows(platform, "select payload from audit where run_id = %s and event = 'receipt.noted'",
                        view.run_id)
    assert [n["payload"] for n in noted] == [{"digest": receipt["body"]["digest"], "ticket_id": "4242",
                                              "note_id": "note-1", "mode": "FIXTURE"}]
    async with platform.db.transaction() as c:   # a replayed note job posts nothing
        await repo.enqueue_job(c, "receipt.note", {"run_id": str(view.run_id), "digest": receipt["body"]["digest"]})
    await _drain(platform)
    assert len(platform.notes.notes) == 1


async def test_a_superseded_receipt_is_not_posted_the_current_one_is(platform):
    view = await _ticket_run(platform)
    old = await build_receipt(platform.db, view.run_id, people=platform.door.people, modes=platform.modes,
                              note=True)
    holds = {r.approver_id: r for r in view.rows if r.state == "awaiting"}
    r1 = await platform.door.decide(view.run_id, holds["p-dana"].action_id, holds["p-dana"].params_hash,
                                    channel="teams", actor_external_id=DANA_TEAMS, decision="approved")
    r2 = await platform.door.decide(view.run_id, holds["p-meera"].action_id, holds["p-meera"].params_hash,
                                    channel="email", actor_external_id=MEERA_EMAIL, decision="approved")
    assert (r1.outcome, r2.outcome, r2.view.status) == ("recorded", "recorded", "partial")
    await _drain(platform)
    assert len(platform.notes.notes) == 1 and "partial" in platform.notes.notes[0][1]
    assert old.digest[:12] not in platform.notes.notes[0][1]


async def test_a_failed_note_write_is_retried_and_posted_once(platform):
    platform.notes = FakeNotes(failures=1)
    view = await _ticket_run(platform)
    outs = await _drain(platform)
    assert [o.outcome for o in outs if o.kind == "receipt.note"] == ["retry", "done"]
    assert len(platform.notes.notes) == 1
    assert (await _rows(platform, "select fs_note_id from receipts where run_id = %s", view.run_id))[0][
        "fs_note_id"] == "note-1"


async def test_runs_without_a_ticket_or_without_a_notes_connector_queue_no_note(platform):
    await platform.door.start_run(ANIL, channel="slack", actor_external_id="U0ANIL001")   # no ticket
    platform.notes = None
    await _ticket_run(platform, "5151")                                                  # no connector
    await _drain(platform)
    assert await _rows(platform, "select 1 from jobs where kind = 'receipt.note'") == []
    assert len(await _rows(platform, "select 1 from receipts")) == 2


async def test_a_note_job_without_a_notes_connector_fails_permanently(platform):
    view = await _ticket_run(platform)
    platform.notes = None
    with pytest.raises(PermanentJobError, match="notes"):
        await receipt_note(platform, {"run_id": str(view.run_id), "digest": "0" * 64})
