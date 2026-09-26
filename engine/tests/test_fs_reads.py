"""Freshservice reads by ID (T124): ticket (with its source), requester, agent, and agent by exact email.

Request paths and response envelopes follow api.freshservice.com: View a Ticket (`ticket`), View a Requester
(`requester`), View an Agent (`agent`), List all Agents filtered by `email` (`agents`).
"""

import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import ConnectorError
from contextrail.connectors.freshservice import FreshserviceClient, source_name

TICKET = {"id": 4412, "subject": "Access request (ContextRail)", "requester_id": 5000001042,
          "requested_for_id": 5000001042, "source": 1, "type": "Service Request", "status": 2}


def client(tenant: FakeTenant) -> FreshserviceClient:
    return FreshserviceClient(DOMAIN, API_KEY, transport=tenant.transport)


async def test_get_ticket_by_id_returns_the_ticket_with_its_source():
    tenant = FakeTenant({("GET", "/api/v2/tickets/4412"): ok({"ticket": TICKET})})
    async with client(tenant) as fs:
        ticket = await fs.get_ticket("4412")
    assert ticket == TICKET
    assert tenant.requests[0].method == "GET" and tenant.requests[0].url.path == "/api/v2/tickets/4412"
    assert source_name(ticket) == "email"


@pytest.mark.parametrize("value,name", [(1, "email"), (2, "portal"), (3, "phone"), (4, "chat"),
                                        (5, "feedback_widget"), (10, "slack"), (15, "ms_teams"), (1001, "other")])
def test_ticket_sources_follow_the_documented_values(value, name):
    assert source_name({"source": value}) == name


async def test_get_requester_by_id():
    requester = {"id": 5000001042, "first_name": "Anil", "last_name": "Kumar",
                 "primary_email": "anil.kumar@northbeam.example", "active": True}
    tenant = FakeTenant({("GET", "/api/v2/requesters/5000001042"): ok({"requester": requester})})
    async with client(tenant) as fs:
        assert await fs.get_requester(5000001042) == requester


async def test_get_agent_by_id():
    agent = {"id": 7000000301, "first_name": "Meera", "last_name": "Iyer", "email": "meera.iyer@northbeam.example"}
    tenant = FakeTenant({("GET", "/api/v2/agents/7000000301"): ok({"agent": agent})})
    async with client(tenant) as fs:
        assert await fs.get_agent(7000000301) == agent


async def test_agents_by_email_filters_server_side_and_keeps_only_exact_matches():
    meera = {"id": 7000000301, "email": "Meera.Iyer@northbeam.example"}
    lookalike = {"id": 7000000999, "email": "meera.iyer2@northbeam.example"}
    tenant = FakeTenant({("GET", "/api/v2/agents"): ok({"agents": [meera, lookalike]})})
    async with client(tenant) as fs:
        found = await fs.find_agents_by_email("meera.iyer@northbeam.example")
    assert found == [meera]  # relevance is not identity (P1): only the exact address, case-insensitive
    assert tenant.requests[0].url.query == b"email=meera.iyer%40northbeam.example"  # docs: URL-encode filters


async def test_an_unknown_email_finds_nobody():
    tenant = FakeTenant({("GET", "/api/v2/agents"): ok({"agents": []})})
    async with client(tenant) as fs:
        assert await fs.find_agents_by_email("nobody@northbeam.example") == []


@pytest.mark.parametrize("bad", ["", "0", "-1", "12/../agents", "4412?x=1", "²", 3.5, None, True])
async def test_ids_must_be_positive_integers_before_they_reach_a_path(bad):
    tenant = FakeTenant()
    async with client(tenant) as fs:
        with pytest.raises((ValueError, TypeError)):
            await fs.get_ticket(bad)
    assert tenant.requests == []


async def test_a_response_without_the_documented_envelope_is_an_error_not_a_none():
    tenant = FakeTenant({("GET", "/api/v2/requesters/7"): ok({"user": {"id": 7}})})
    async with client(tenant) as fs:
        with pytest.raises(ConnectorError, match="requester"):
            await fs.get_requester(7)


async def test_a_missing_record_is_a_permanent_404():
    tenant = FakeTenant()  # every unrouted path answers 404
    async with client(tenant) as fs:
        with pytest.raises(ConnectorError) as e:
            await fs.get_ticket(99)
    assert e.value.status == 404
