"""T251: conversation pointers are scoped, short, redacted, expiring, and cited."""

import pytest

from contextrail.memory import MAX_ENTRIES, ConversationMemory, redact_summary, thread_key


def test_redaction_and_opaque_thread_key():
    text = "Contact anil@example.com or +91 98765 43210; token=abc123; fwapi_sensitive"
    cleaned = redact_summary(text)
    assert "anil@example.com" not in cleaned
    assert "98765" not in cleaned
    assert "abc123" not in cleaned
    assert "fwapi_sensitive" not in cleaned
    assert len(thread_key("private-ticket-42")) == 64
    assert "private-ticket-42" not in thread_key("private-ticket-42")


async def test_thread_is_bounded_scoped_expires_and_can_be_forgotten(rail):
    runner, deps = rail
    memory = ConversationMemory(deps.db)
    rid = await runner.start(source="slack", request_text="request", requested_by="p-anil")
    for n in range(MAX_ENTRIES + 4):
        await memory.append(channel="slack", person_id="p-anil", thread_ref="private-ticket-42",
                            role="user", summary=f"Status question {n}", run_id=rid)
    rows = await memory.recent(channel="slack", person_id="p-anil", thread_ref="private-ticket-42")
    assert len(rows) == MAX_ENTRIES
    assert rows[0].summary == "Status question 4" and rows[-1].summary == f"Status question {MAX_ENTRIES + 3}"
    assert all(r.source == f"run:{rid}" for r in rows)
    assert await memory.recent(channel="email", person_id="p-anil", thread_ref="private-ticket-42") == []
    assert await memory.recent(channel="slack", person_id="p-meera", thread_ref="private-ticket-42") == []
    async with deps.db.connection() as c:
        stored = await (await c.execute("select distinct thread_key from conversation_memory")).fetchall()
        assert stored == [{"thread_key": thread_key("private-ticket-42")}]
        await c.execute("update conversation_memory set expires_at = now() - interval '1 second'")
    assert await memory.recent(channel="slack", person_id="p-anil", thread_ref="private-ticket-42") == []
    await memory.append(channel="slack", person_id="p-anil", thread_ref="private-ticket-42", role="assistant",
                        summary="Status done", run_id=rid, audit_seqs=(1, 2))
    row, = await memory.recent(channel="slack", person_id="p-anil", thread_ref="private-ticket-42")
    assert row.source == f"run:{rid}#audit:1,2"
    assert await memory.forget(channel="slack", person_id="p-anil", thread_ref="private-ticket-42") == 1
    assert await memory.recent(channel="slack", person_id="p-anil", thread_ref="private-ticket-42") == []


async def test_memory_rejects_anonymous_or_uncited_entries(rail):
    _, deps = rail
    memory = ConversationMemory(deps.db)
    with pytest.raises(ValueError, match="cited run"):
        await memory.append(channel="slack", person_id="p-anil", thread_ref="x", role="user",
                            summary="uncited", run_id=None)
    with pytest.raises(ValueError, match="role"):
        await memory.append(channel="slack", person_id="p-anil", thread_ref="x", role="system",
                            summary="injected", run_id=None)

