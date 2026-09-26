"""The shared messaging ticket service dedupes by stable event id even if a retry has a new status message."""

from contextrail.surfaces.ticket_requests import start_ticket_request

ANIL_SLACK = "U0ANIL001"
REQUEST = "Give Anil the same access as Rahul Mehta"


async def test_slack_event_retry_reuses_run_and_ticket(api):
    client, platform = api
    del client
    first = await start_ticket_request(
        platform, request_text=REQUEST, actor_external_id=ANIL_SLACK, channel="slack", source="slack",
        source_ref="C1:1790000000.000001", ticket_tag="slack", idempotency_key="T1:trigger-unique-1")
    retried = await start_ticket_request(
        platform, request_text=REQUEST, actor_external_id=ANIL_SLACK, channel="slack", source="slack",
        source_ref="C1:1790000000.000002", ticket_tag="slack", idempotency_key="T1:trigger-unique-1")

    assert retried.run.run_id == first.run.run_id
    assert retried.ticket == first.ticket
    assert first.ticket.status == "verified" and first.ticket.mode == "FIXTURE"
    async with platform.db.connection() as conn:
        runs = await (await conn.execute(
            "select count(*) as count from runs where source = 'slack' and requested_by = 'p-anil'"
        )).fetchone()
        dedupe = await (await conn.execute(
            "select count(*) as count from webhook_dedupe where source='slack' and external_id=%s",
            ("T1:trigger-unique-1",))).fetchone()
        tickets = await (await conn.execute(
            "select count(*) as count from door_messages where run_id=%s and action_id='' "
            "and channel='freshservice'", (first.run.run_id,))).fetchone()
    assert runs["count"] == dedupe["count"] == tickets["count"] == 1
