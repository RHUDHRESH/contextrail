"""Plain Freshservice incident ticket writes are workspace-scoped and uncertainty-safe."""

import httpx
import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import UnknownOutcome
from contextrail.connectors.freshservice import FreshserviceClient


async def test_direct_ticket_includes_configured_workspace_and_exact_contents():
    tenant = FakeTenant({("POST", "/api/v2/tickets"): ok({"ticket": {"id": 812}}, status=201)})
    async with FreshserviceClient(DOMAIN, API_KEY, workspace_id=12, transport=tenant.transport) as fs:
        ticket = await fs.create_incident_ticket(email="requester@example.com", subject="Demo request",
                                                 description="Please provision access.")
    assert ticket["id"] == 812
    assert tenant.body() == {"email": "requester@example.com", "subject": "Demo request",
                             "description": "Please provision access.", "priority": 1, "status": 2,
                             "workspace_id": 12}


@pytest.mark.parametrize("response", [httpx.ReadTimeout("slow"), httpx.Response(502)])
async def test_uncertain_ticket_write_is_not_retried(response):
    tenant = FakeTenant({("POST", "/api/v2/tickets"): response})
    async with FreshserviceClient(DOMAIN, API_KEY, workspace_id=12, transport=tenant.transport) as fs:
        with pytest.raises(UnknownOutcome):
            await fs.create_incident_ticket(email="requester@example.com", subject="Demo request",
                                             description="Please provision access.")
    assert len(tenant.requests) == 1
