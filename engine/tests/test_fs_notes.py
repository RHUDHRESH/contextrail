"""Private notes on a ticket (T127, CLAUDE.md §2 P0-7): post the receipt, then re-fetch to confirm it exists.

api.freshservice.com, Conversations: POST /api/v2/tickets/[ticket_id]/notes {"body" (HTML, required), "private"
(default true)} -> `conversation`; GET /api/v2/tickets/[id]/conversations -> `conversations` (paginated, 30 per page).
There is no idempotency key, so every note carries a marker: a retry that finds the marker does not post again.
"""

import httpx
import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import UnknownOutcome
from contextrail.connectors.freshservice import FreshserviceClient

NOTES = ("POST", "/api/v2/tickets/4412/notes")
CONVS = ("GET", "/api/v2/tickets/4412/conversations")
MARKER = "cr-ref:9f3ae1c04b7d2a55"


def conv(id: int, text: str, private: bool = True) -> dict:
    return {"id": id, "body": f"<div>{text}</div>", "body_text": text, "private": private, "ticket_id": 4412}


class Ticket:
    """A ticket whose conversation list really grows when a note is posted."""

    def __init__(self, existing: list[dict] | None = None, *, drop_posts: bool = False) -> None:
        self.convs = list(existing or [])
        self.drop_posts = drop_posts

    def post(self, request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        note = {"id": 9000 + len(self.convs), "body": body["body"], "body_text": body["body"],
                "private": body.get("private", True), "ticket_id": 4412}
        if not self.drop_posts:  # the lying system acknowledges and keeps nothing
            self.convs.append(note)
        return ok({"conversation": note}, status=201)

    def get(self, request: httpx.Request) -> httpx.Response:
        page, size = int(request.url.params.get("page", 1)), int(request.url.params.get("per_page", 30))
        chunk = self.convs[(page - 1) * size: page * size]
        more = {"link": '<https://x/>; rel="next"'} if page * size < len(self.convs) else {}
        return ok({"conversations": chunk}, headers=more)


def tenant_for(t: Ticket) -> FakeTenant:
    return FakeTenant({NOTES: t.post, CONVS: t.get})


def client(tenant: FakeTenant) -> FreshserviceClient:
    return FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport)


async def test_create_note_posts_a_private_note():
    tenant = FakeTenant({NOTES: ok({"conversation": conv(1, "hi")}, status=201)})
    async with client(tenant) as fs:
        assert (await fs.create_note(4412, "<p>hi</p>"))["id"] == 1
    assert tenant.body() == {"body": "<p>hi</p>", "private": True}


async def test_a_receipt_note_is_posted_once_and_confirmed_by_reading_it_back():
    t = Ticket([conv(1, "Is this still a problem", private=False)])
    tenant = tenant_for(t)
    async with client(tenant) as fs:
        out = await fs.add_private_note(4412, "<p>Receipt: 13 verified</p>", MARKER)
    assert (out.replayed, out.confirmed) == (False, True)
    assert out.note["private"] is True and MARKER in out.note["body"]
    assert [r.method for r in tenant.requests] == ["GET", "POST", "GET"]


async def test_a_note_that_is_already_there_is_not_posted_again():
    t = Ticket([conv(1, "old"), conv(2, f"Receipt: 13 verified ref {MARKER}")])
    tenant = tenant_for(t)
    async with client(tenant) as fs:
        out = await fs.add_private_note(4412, "<p>Receipt: 13 verified</p>", MARKER)
    assert (out.replayed, out.confirmed, out.note["id"]) == (True, True, 2)
    assert [r.method for r in tenant.requests] == ["GET"]


async def test_a_201_whose_note_cannot_be_read_back_is_not_confirmed():
    t = Ticket(drop_posts=True)
    async with client(tenant_for(t)) as fs:
        out = await fs.add_private_note(4412, "<p>Receipt</p>", MARKER)
    assert (out.replayed, out.confirmed) == (False, False)  # a 200 is not done (P3)


async def test_the_marker_is_found_on_a_later_page():
    t = Ticket([conv(i, f"chatter {i}") for i in range(1, 31)] + [conv(31, f"Receipt ref {MARKER}")])
    tenant = tenant_for(t)
    async with client(tenant) as fs:
        out = await fs.add_private_note(4412, "<p>Receipt</p>", MARKER)
    assert out.replayed and out.note["id"] == 31
    assert [dict(r.url.params)["page"] for r in tenant.requests] == ["1", "2"]


async def test_an_unknown_outcome_is_raised_and_the_retry_finds_the_note_instead_of_posting():
    t = Ticket()

    def post_then_time_out(request: httpx.Request) -> httpx.Response:
        t.post(request)
        raise httpx.ReadTimeout("slow")

    tenant = FakeTenant({NOTES: post_then_time_out, CONVS: t.get})
    async with client(tenant) as fs:
        with pytest.raises(UnknownOutcome):
            await fs.add_private_note(4412, "<p>Receipt</p>", MARKER)
        out = await fs.add_private_note(4412, "<p>Receipt</p>", MARKER)
    assert (out.replayed, out.confirmed) == (True, True)
    assert sum(r.method == "POST" for r in tenant.requests) == 1 and len(t.convs) == 1


@pytest.mark.parametrize("bad", ["", "has space", "<b>x</b>", "a" * 81])
async def test_markers_are_plain_tokens(bad):
    tenant = FakeTenant()
    async with client(tenant) as fs:
        with pytest.raises(ValueError):
            await fs.add_private_note(4412, "<p>x</p>", bad)
    assert tenant.requests == []
