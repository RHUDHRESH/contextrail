import asyncio
import uuid

from contextrail.rail.events import EventBus


async def test_events_are_sequenced_and_fanned_out_to_sse_and_doors():
    bus, rid, seen = EventBus(), uuid.uuid4(), []

    async def door(e):
        seen.append((e.seq, e.stage))

    bus.on_run(rid, door)
    q = bus.subscribe(rid)
    await bus.emit(rid, "discover", "running", "Discovering who this is about")
    await bus.emit(rid, "govern", "running", "Govern: 13 allowed, 2 held, 1 refused",
                   counts={"allow": 13, "hold": 2, "refuse": 1})
    got = [q.get_nowait(), q.get_nowait()]
    assert [e.seq for e in got] == [0, 1] and got[1].counts["refuse"] == 1
    assert seen == [(0, "discover"), (1, "govern")]


async def test_late_subscriber_gets_history_first():
    bus, rid = EventBus(), uuid.uuid4()
    await bus.emit(rid, "discover", "running", "a")
    q = bus.subscribe(rid)
    await bus.emit(rid, "compile", "running", "b")
    assert [q.get_nowait().message, q.get_nowait().message] == ["a", "b"]


async def test_a_failing_or_slow_door_never_blocks_the_rail():
    bus, rid, ok = EventBus(callback_timeout_s=0.05), uuid.uuid4(), []

    async def broken(e):
        raise RuntimeError("slack 500")

    async def slow(e):
        await asyncio.sleep(5)

    async def fine(e):
        ok.append(e.seq)

    for cb in (broken, slow, fine):
        bus.on_run(rid, cb)
    await asyncio.wait_for(bus.emit(rid, "execute", "running", "x"), timeout=1)
    assert ok == [0]


async def test_runs_are_isolated_and_messages_are_capped():
    bus, a, b = EventBus(), uuid.uuid4(), uuid.uuid4()
    qa = bus.subscribe(a)
    await bus.emit(b, "discover", "running", "other run")
    e = await bus.emit(a, "discover", "running", "x" * 500)
    assert qa.qsize() == 1 and len(e.message) == 280 and e.seq == 0
