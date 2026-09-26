"""One outbound door message per (run, action, channel): an approval email, a ticket reply, a card (§0 rule 5).

The key is `canonical.door_send_key(run_id, action_id, channel)`; the `door_messages` row is the record that the
message went. The check, the send and the record happen under a transaction-scoped advisory lock on that key, so a
retried job or two racing workers send once. Nothing is recorded when the send raises, so a retry sends. If the
remote side accepts and the commit then fails, a retry sends again: at-least-once in that one window, because the
remote systems (SES, a Freshservice reply) take no idempotency key of their own.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from contextrail import repo
from contextrail.canonical import door_send_key
from contextrail.db import Database


async def send_once(db: Database, *, run_id: UUID, action_id: str, channel: str,
                    send: Callable[[str], Awaitable[dict]]) -> tuple[dict, bool]:
    """Call `send(key)` unless this message already went. Returns (stored ref, replayed)."""
    key = door_send_key(run_id, action_id, channel)
    async with db.transaction() as c:
        await c.execute("select pg_advisory_xact_lock(%s)", (int(key[:15], 16),))
        sent = [r for r in await repo.list_door_messages(c, run_id, action_id) if r["channel"] == channel]
        if sent:
            return sent[0]["ref"], True
        ref = {**await send(key), "idempotency_key": key}
        await repo.upsert_door_message(c, run_id, channel, ref, action_id=action_id)
    return ref, False
