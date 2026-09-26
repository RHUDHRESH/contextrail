"""Freshservice approvals on a ticket (T126, CLAUDE.md §2 P0-4).

api.freshservice.com, Tickets > Approvals:
- POST /api/v2/tickets/[ticket_id]/approvals  {"approver_id", "approval_type", optional "email_content"} -> `approval`
- GET  /api/v2/tickets/[ticket_id]/approvals -> `approvals`;  GET .../approvals/[id] -> `approval`
- approval_type 1 everyone, 2 anyone, 3 majority, 4 first responder; status 0 requested, 1 approved, 2 rejected,
  3 cancelled.
Freshservice takes no idempotency key, so request_approval reads before it writes: a retried job finds the approval
the first attempt created instead of asking the approver twice.
"""

import httpx
import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import UnknownOutcome
from contextrail.connectors.freshservice import (
    ApprovalStatus,
    ApprovalType,
    FreshserviceClient,
    approval_status,
)

APPROVALS = "/api/v2/tickets/4412/approvals"


def approval(id: int, approver_id: int, status: int = 0, name: str | None = None) -> dict:
    names = {0: "requested", 1: "approved", 2: "rejected", 3: "cancelled"}
    return {"id": id, "approver_id": approver_id, "approval_type": 1,
            "approval_status": {"id": status, "name": name or names[status]}, "latest_remark": ""}


def client(tenant: FakeTenant) -> FreshserviceClient:
    return FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport)


def test_documented_values():
    assert [int(t) for t in ApprovalType] == [1, 2, 3, 4]
    assert {s.name: int(s) for s in ApprovalStatus} == {"REQUESTED": 0, "APPROVED": 1, "REJECTED": 2, "CANCELLED": 3}


async def test_create_approval_posts_the_documented_body():
    created = approval(7163764235, 7000000050)
    tenant = FakeTenant({("POST", APPROVALS): ok({"approval": created})})
    async with client(tenant) as fs:
        got = await fs.create_approval(4412, "7000000050", email_content="<p>GitHub read-only</p>")
    assert got == created
    assert tenant.body() == {"approver_id": 7000000050, "approval_type": 1, "email_content": "<p>GitHub read-only</p>"}


async def test_email_content_is_optional_and_the_type_can_be_chosen():
    tenant = FakeTenant({("POST", APPROVALS): ok({"approval": approval(1, 7)})})
    async with client(tenant) as fs:
        await fs.create_approval(4412, 7, approval_type=ApprovalType.ANYONE)
    assert tenant.body() == {"approver_id": 7, "approval_type": 2}


async def test_approval_state_is_read_from_the_list_and_by_id():
    tenant = FakeTenant({("GET", APPROVALS): ok({"approvals": [approval(1, 7, 1), approval(2, 8, 0)]}),
                         ("GET", f"{APPROVALS}/2"): ok({"approval": approval(2, 8, 3)})})
    async with client(tenant) as fs:
        listed = await fs.list_approvals(4412)
        one = await fs.get_approval(4412, 2)
    assert [approval_status(a) for a in listed] == [ApprovalStatus.APPROVED, ApprovalStatus.REQUESTED]
    assert approval_status(one) is ApprovalStatus.CANCELLED


def test_status_is_read_by_id_even_if_the_name_differs():
    assert approval_status(approval(1, 7, 2, name="Rejected by approver")) is ApprovalStatus.REJECTED


async def test_request_approval_reuses_a_live_approval_for_the_same_approver():
    existing = approval(11, 7000000050, 0)
    tenant = FakeTenant({("GET", APPROVALS): ok({"approvals": [approval(10, 7000000301, 1), existing]})})
    async with client(tenant) as fs:
        got, replayed = await fs.request_approval(4412, 7000000050)
    assert (got, replayed) == (existing, True)
    assert [r.method for r in tenant.requests] == ["GET"]  # nobody is asked twice


async def test_request_approval_asks_again_only_if_the_earlier_one_was_cancelled():
    created = approval(12, 7000000050, 0)
    tenant = FakeTenant({("GET", APPROVALS): ok({"approvals": [approval(11, 7000000050, 3)]}),
                         ("POST", APPROVALS): ok({"approval": created})})
    async with client(tenant) as fs:
        assert await fs.request_approval(4412, 7000000050) == (created, False)
    assert [r.method for r in tenant.requests] == ["GET", "POST"]


async def test_an_unknown_outcome_is_not_retried_and_the_next_attempt_reconciles_first():
    tenant = FakeTenant({("GET", APPROVALS): ok({"approvals": []}),
                         ("POST", APPROVALS): httpx.ReadTimeout("slow")})
    async with client(tenant) as fs:
        with pytest.raises(UnknownOutcome):
            await fs.request_approval(4412, 7000000050)
        # the timed-out POST had in fact landed; the retried job finds it and does not post again
        landed = approval(13, 7000000050, 0)
        tenant.routes[("GET", APPROVALS)] = ok({"approvals": [landed]})
        assert await fs.request_approval(4412, 7000000050) == (landed, True)
    assert [r.method for r in tenant.requests] == ["GET", "POST", "GET"]


async def test_approver_ids_are_validated_before_anything_is_sent():
    tenant = FakeTenant()
    async with client(tenant) as fs:
        with pytest.raises(ValueError):
            await fs.request_approval(4412, "dana@northbeam.example")
    assert tenant.requests == []
