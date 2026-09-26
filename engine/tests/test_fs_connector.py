"""LIVE flag per call path and the labelled FIXTURE fallback (T138, CLAUDE.md §0 rule 4, D-004).

The connector is LIVE only when FS_DOMAIN and FS_API_KEY are set. Every result says which system actually
answered: FIXTURE when unconfigured, and FIXTURE with a `fallback_reason` (plus a warning log) when a tenant call
failed. A write whose outcome is unknown is never "fixed" by writing to the fixture instead.
"""

import json

import httpx
import pytest
from _fs_mock import API_KEY, DOMAIN, FakeTenant, ok

from contextrail.connectors.base import Connector, ConnectorError, TransientError, UnknownOutcome
from contextrail.connectors.freshservice import FreshserviceConnector, source_name
from contextrail.connectors.registry import build_registry
from contextrail.connectors.state import FixtureState
from contextrail.fixtures import load
from contextrail.logs import configure_logging
from contextrail.models import Action
from contextrail.settings import Settings

ANIL, MEERA, DANA = 5000001042, 7000000301, 7000000050
LIVE = Settings(_env_file=None, fs_domain=DOMAIN, fs_api_key=API_KEY)


def fixture_conn(tmp_path) -> FreshserviceConnector:
    return FreshserviceConnector(None, state=FixtureState("freshservice", directory=tmp_path))


def live_conn(tmp_path, tenant: FakeTenant) -> FreshserviceConnector:
    return FreshserviceConnector(LIVE, state=FixtureState("freshservice", directory=tmp_path),
                                 transport=tenant.transport)


# --- the mode -------------------------------------------------------------------------------------------------

def test_mode_is_live_only_when_freshservice_is_configured(tmp_path):
    st = FixtureState("freshservice", directory=tmp_path)
    assert FreshserviceConnector(None, state=st).mode == "FIXTURE"
    assert FreshserviceConnector(Settings(_env_file=None, fs_domain=DOMAIN), state=st).mode == "FIXTURE"
    assert FreshserviceConnector(LIVE, state=st).mode == "LIVE"


def test_it_is_a_connector_but_not_an_action_target(tmp_path):
    conn = fixture_conn(tmp_path)
    assert isinstance(conn, Connector) and conn.name == "freshservice"


async def test_actions_are_not_written_through_freshservice(tmp_path):
    conn = fixture_conn(tmp_path)
    a = Action.create("A1", "grant", {"entitlement": "jira-pay", "subject_id": "E-1042"})
    with pytest.raises(ConnectorError):
        await conn.write(a, "k")
    with pytest.raises(ConnectorError):
        await conn.verify(a)


def test_the_registry_carries_freshservice_with_its_honest_mode(tmp_path):
    assert build_registry(tmp_path).get("freshservice").mode == "FIXTURE"
    assert build_registry(tmp_path, settings=Settings(_env_file=None)).get("freshservice").mode == "FIXTURE"
    assert build_registry(tmp_path, settings=LIVE).get("freshservice").mode == "LIVE"


# --- FIXTURE: unconfigured ------------------------------------------------------------------------------------

async def test_unconfigured_reads_come_from_the_fixture_and_say_so(tmp_path):
    conn = fixture_conn(tmp_path)
    t = await conn.get_ticket(4412)
    assert (t.mode, t.fallback_reason) == ("FIXTURE", None)
    assert t.data["requester_id"] == ANIL and source_name(t.data) == "portal"
    r = await conn.get_requester(t.data["requester_id"])
    assert (r.mode, r.data["primary_email"]) == ("FIXTURE", "anil.kumar@northbeam.example")
    assert (await conn.read({"ticket_id": 4412}))["mode"] == "FIXTURE"


async def test_fixture_agents_by_id_and_by_exact_email(tmp_path):
    conn = fixture_conn(tmp_path)
    by_mail = await conn.find_agents_by_email("Meera.Iyer@northbeam.example")
    assert [a["id"] for a in by_mail.data] == [MEERA] and by_mail.mode == "FIXTURE"
    assert (await conn.get_agent(MEERA)).data["email"] == "meera.iyer@northbeam.example"
    assert (await conn.find_agents_by_email("anil.kumar@northbeam.example")).data == []  # a requester, not an agent


async def test_fixture_catalog_has_the_access_request_item(tmp_path):
    item = await fixture_conn(tmp_path).access_request_item()
    assert item.mode == "FIXTURE" and item.data["name"] == "Access request (ContextRail)"


async def test_fixture_approvals_and_notes_really_change_state_and_read_back(tmp_path):
    conn = fixture_conn(tmp_path)
    first = await conn.request_approval(4412, DANA, email_content="<p>GitHub read-only</p>")
    again = await conn.request_approval(4412, DANA)
    assert (first.mode, first.status, first.replayed) == ("FIXTURE", "requested", False)
    assert (again.approval_id, again.replayed) == (first.approval_id, True)
    note = await conn.add_private_note(4412, "<p>Receipt: 13 verified</p>", "cr-ref:0123456789abcdef")
    assert (note.mode, note.confirmed, note.replayed) == ("FIXTURE", True, False)
    # a new process (new connector, same state directory) sees the same approval and note
    later = fixture_conn(tmp_path)
    assert (await later.get_approval(4412, first.approval_id)).approver_id == DANA
    assert (await later.add_private_note(4412, "<p>Receipt</p>", "cr-ref:0123456789abcdef")).replayed


async def test_fixture_unknown_records_are_404s(tmp_path):
    with pytest.raises(ConnectorError) as e:
        await fixture_conn(tmp_path).get_ticket(999999)
    assert e.value.status == 404


# --- LIVE, and the fallback when a tenant call fails ----------------------------------------------------------

async def test_live_results_say_live(tmp_path):
    tenant = FakeTenant({("GET", "/api/v2/tickets/77"): ok({"ticket": {"id": 77, "source": 1}})})
    conn = live_conn(tmp_path, tenant)
    t = await conn.get_ticket(77)
    assert (t.mode, t.fallback_reason, t.data["id"]) == ("LIVE", None, 77)
    assert tenant.requests[0].headers["authorization"].startswith("Basic ")


async def test_a_failing_tenant_read_falls_back_to_the_fixture_labelled_and_logged(tmp_path, capsys):
    configure_logging("INFO", json=True)
    tenant = FakeTenant({("GET", "/api/v2/tickets/4412"): httpx.Response(503)})
    t = await live_conn(tmp_path, tenant).get_ticket(4412)
    assert t.mode == "FIXTURE" and "503" in t.fallback_reason
    assert t.data["requester_id"] == ANIL
    lines = [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]
    warn = [x for x in lines if x.get("event") == "freshservice.fixture_fallback"]
    assert warn and warn[0]["level"] == "warning" and warn[0]["op"] == "get_ticket"
    assert API_KEY not in json.dumps(lines)


@pytest.mark.parametrize(("answer", "error"), [(ok({"description": "no"}, status=403), ConnectorError),
                                               (httpx.Response(503), TransientError)])
async def test_a_failing_tenant_write_is_raised_and_never_redone_on_the_fixture(tmp_path, answer, error):
    """A write the tenant did not take cannot be stood in for by the fixture: the ticket would never show it, and
    a stored fixture id would stop the real one from ever being requested (split brain). Reads still fall back."""
    tenant = FakeTenant({("GET", "/api/v2/tickets/4412/approvals"): ok({"approvals": []}),
                         ("POST", "/api/v2/tickets/4412/approvals"): answer})
    with pytest.raises(error):
        await live_conn(tmp_path, tenant).request_approval(4412, DANA)
    assert (await fixture_conn(tmp_path).list_approvals(4412)).data == []
    note_tenant = FakeTenant({("GET", "/api/v2/tickets/4412/conversations"): ok({"conversations": []}),
                              ("POST", "/api/v2/tickets/4412/notes"): answer})
    with pytest.raises(error):
        await live_conn(tmp_path, note_tenant).add_private_note(4412, "<p>x</p>", "cr-ref:0123456789abcdef")


async def test_an_unknown_write_outcome_is_raised_not_papered_over_by_the_fixture(tmp_path):
    tenant = FakeTenant({("GET", "/api/v2/tickets/4412/approvals"): ok({"approvals": []}),
                         ("POST", "/api/v2/tickets/4412/approvals"): httpx.ReadTimeout("slow")})
    conn = live_conn(tmp_path, tenant)
    with pytest.raises(UnknownOutcome):
        await conn.request_approval(4412, DANA)
    assert (await fixture_conn(tmp_path).list_approvals(4412)).data == []  # the fixture was not written


async def test_when_both_fail_the_error_names_both(tmp_path):
    tenant = FakeTenant({("GET", "/api/v2/tickets/999999"): httpx.Response(500)})
    with pytest.raises(ConnectorError) as e:
        await live_conn(tmp_path, tenant).get_ticket(999999)
    assert "500" in str(e.value) and "fixture" in str(e.value) and "404" in str(e.value)


async def test_bad_ids_are_refused_before_any_call_in_any_mode(tmp_path):
    tenant = FakeTenant()
    with pytest.raises((ValueError, TypeError)):
        await live_conn(tmp_path, tenant).get_ticket("4412/../agents")
    assert tenant.requests == []


# --- the fixture file itself ----------------------------------------------------------------------------------

def test_fixture_people_are_the_identity_fixture_people():
    fs, ident = load("freshservice"), load("identity")
    assert fs["_meta"]["mode"] == "FIXTURE"
    people = {p["email"]: p for p in ident["people"]}
    requesters = {r["primary_email"]: r for r in fs["requesters"].values()}
    agents = {a["email"]: a for a in fs["agents"].values()}
    assert set(requesters) | set(agents) == set(people)
    assert set(agents) == {e for e, p in people.items() if p["can_approve"]}  # every approver can approve in FS
    for email, rec in {**requesters, **agents}.items():
        assert f"{rec['first_name']} {rec['last_name']}" == people[email]["display_name"]
    for key, rec in {**fs["requesters"], **fs["agents"]}.items():
        assert str(rec["id"]) == key


def test_fixture_ticket_4412_is_anils_access_request():
    fs = load("freshservice")
    t = fs["tickets"]["4412"]
    assert t["id"] == 4412 and t["type"] == "Service Request" and t["subject"] == "Access request (ContextRail)"
    assert fs["requesters"][str(t["requester_id"])]["primary_email"] == "anil.kumar@northbeam.example"
    assert t["requested_for_id"] == t["requester_id"]
    assert "same access as Rahul" in t["description_text"]
