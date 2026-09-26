"""SES connector (CLAUDE.md §12, checklist T230): sesv2 send_email in ap-south-1, one email per (run, action),
LIVE only when configured, otherwise a FIXTURE outbox that says so. No network: botocore's Stubber answers."""

import asyncio
import email
import email.policy
import time

import boto3
import pytest
from botocore.stub import Stubber

from contextrail import repo
from contextrail.canonical import door_send_key
from contextrail.connectors.base import ConnectorError, TransientError
from contextrail.connectors.ses import OutboundEmail, SesConnector, make_client
from contextrail.db import Database
from contextrail.settings import Settings

FROM = "approvals@mail.contextrail.app"
MSG = OutboundEmail(to="meera.iyer@northbeam.example", subject="Approval needed · Slack seat",
                    text="Approve or refuse.", html="<p>Approve or refuse.</p>")


def live_settings(**kw) -> Settings:
    return Settings(_env_file=None, ses_from_address=FROM, **kw)


def stubbed_client():
    client = boto3.client("sesv2", region_name="ap-south-1", aws_access_key_id="testing",
                          aws_secret_access_key="testing")  # obviously fake; the Stubber intercepts every call
    return client, Stubber(client)


def expected_params(run_id, action_id="A16", **extra) -> dict:
    key = door_send_key(run_id, action_id, "email")
    return {
        "FromEmailAddress": FROM,
        "Destination": {"ToAddresses": ["meera.iyer@northbeam.example"]},
        "Content": {"Simple": {
            "Subject": {"Data": "Approval needed · Slack seat", "Charset": "UTF-8"},
            "Body": {"Text": {"Data": "Approve or refuse.", "Charset": "UTF-8"},
                     "Html": {"Data": "<p>Approve or refuse.</p>", "Charset": "UTF-8"}},
            "Headers": [{"Name": "X-ContextRail-Idempotency-Key", "Value": key}],
        }},
        "EmailTags": [{"Name": "contextrail_run", "Value": str(run_id)},
                      {"Name": "contextrail_action", "Value": action_id},
                      {"Name": "contextrail_door", "Value": "email"}],
        **extra,
    }


@pytest.fixture
async def db(migrated_db):
    async with Database(migrated_db) as d:
        yield d


async def new_run(db) -> object:
    async with db.transaction() as c:
        return (await repo.create_run(c, source="slack", request_text="same as Rahul"))["id"]


async def email_rows(db, run_id):
    async with db.connection() as c:
        return [r for r in await repo.list_door_messages(c, run_id, "A16") if r["channel"] == "email"]


# --- mode is honest ---------------------------------------------------------------------------------------

def test_unconfigured_is_fixture():
    assert SesConnector(Settings(_env_file=None, ses_from_address="")).mode == "FIXTURE"


def test_the_env_example_placeholder_sender_is_not_live():
    # .env.example ships "contextrail@yourdomain.example": a reserved domain can never be a verified SES identity.
    s = Settings(_env_file=None, ses_from_address="contextrail@yourdomain.example")
    assert s.ses_configured and SesConnector(s).mode == "FIXTURE"


def test_a_real_sender_is_live():
    client, _ = stubbed_client()
    assert SesConnector(live_settings(), client=client).mode == "LIVE"


def test_the_client_is_sesv2_in_the_configured_region():
    client = make_client(live_settings())
    assert (client.meta.service_model.service_name, client.meta.region_name) == ("sesv2", "ap-south-1")


# --- LIVE: the exact sesv2 SendEmail request, once --------------------------------------------------------

async def test_live_send_uses_the_sesv2_request_shape_and_records_the_message(db):
    rid = await new_run(db)
    client, stub = stubbed_client()
    stub.add_response("send_email", {"MessageId": "0109-abc"}, expected_params(rid))
    with stub:
        out = await SesConnector(live_settings(), client=client).send(db, run_id=rid, action_id="A16", message=MSG)
    stub.assert_no_pending_responses()
    assert (out.mode, out.message_id, out.replayed) == ("LIVE", "0109-abc", False)
    (row,) = await email_rows(db, rid)
    assert row["ref"] == {"mode": "LIVE", "message_id": "0109-abc", "to": MSG.to,
                          "idempotency_key": door_send_key(rid, "A16", "email"), "outbox": None}


async def test_configuration_set_is_passed_when_set(db):
    rid = await new_run(db)
    client, stub = stubbed_client()
    stub.add_response("send_email", {"MessageId": "m-1"}, expected_params(rid, ConfigurationSetName="cr-events"))
    with stub:
        await SesConnector(live_settings(ses_configuration_set="cr-events"), client=client).send(
            db, run_id=rid, action_id="A16", message=MSG)
    stub.assert_no_pending_responses()


async def test_a_second_send_for_the_same_action_is_a_replay_not_a_second_email(db):
    rid = await new_run(db)
    client, stub = stubbed_client()
    stub.add_response("send_email", {"MessageId": "m-1"}, expected_params(rid))  # exactly one response queued
    ses = SesConnector(live_settings(), client=client)
    with stub:
        first = await ses.send(db, run_id=rid, action_id="A16", message=MSG)
        again = await ses.send(db, run_id=rid, action_id="A16", message=MSG)  # a retried job
    assert (first.replayed, again.replayed, again.message_id) == (False, True, "m-1")
    assert len(await email_rows(db, rid)) == 1


class SlowClient:
    """SES taking its time: without the lock, every racing worker would reach send_email during the wait."""

    def __init__(self) -> None:
        self.calls = 0

    def send_email(self, **params):
        self.calls += 1
        time.sleep(0.3)
        return {"MessageId": f"m-{self.calls}"}


async def test_concurrent_sends_for_the_same_action_send_once(db):
    rid = await new_run(db)

    async def hold_a_connection():
        async with db.connection() as c:
            await c.execute("select pg_sleep(0.05)")

    await asyncio.gather(*[hold_a_connection() for _ in range(4)])  # warm the pool so the race is real
    client = SlowClient()
    ses = SesConnector(live_settings(), client=client)
    outs = await asyncio.gather(*[ses.send(db, run_id=rid, action_id="A16", message=MSG) for _ in range(3)])
    assert client.calls == 1
    assert sorted(o.replayed for o in outs) == [False, True, True] and {o.message_id for o in outs} == {"m-1"}


@pytest.mark.parametrize(("code", "status", "error"), [
    ("TooManyRequestsException", 429, TransientError),
    ("InternalFailure", 500, TransientError),
    ("MessageRejected", 400, ConnectorError),
])
async def test_ses_errors_are_classified_and_nothing_is_recorded(db, code, status, error):
    rid = await new_run(db)
    client, stub = stubbed_client()
    stub.add_client_error("send_email", service_error_code=code, http_status_code=status)
    with stub, pytest.raises(error):
        await SesConnector(live_settings(), client=client).send(db, run_id=rid, action_id="A16", message=MSG)
    assert await email_rows(db, rid) == []  # a retry will send; nothing claims it was delivered


# --- FIXTURE: written to a local outbox, labelled, and still once ------------------------------------------

async def test_fixture_writes_the_rendered_email_to_the_outbox(db, tmp_path):
    rid = await new_run(db)
    ses = SesConnector(Settings(_env_file=None, ses_from_address=""), outbox_dir=tmp_path)
    out = await ses.send(db, run_id=rid, action_id="A16", message=MSG)
    assert out.mode == "FIXTURE" and out.message_id.startswith("fixture-") and not out.replayed
    files = list(tmp_path.glob("*.eml"))
    assert [str(f) for f in files] == [out.outbox_path]
    parsed = email.message_from_bytes(files[0].read_bytes(), policy=email.policy.default)
    assert (parsed["To"], parsed["Subject"], parsed["X-ContextRail-Mode"]) == (MSG.to, MSG.subject, "FIXTURE")
    assert parsed.get_body(("plain",)).get_content().strip() == MSG.text
    assert parsed.get_body(("html",)).get_content().strip() == MSG.html
    (row,) = await email_rows(db, rid)
    assert row["ref"]["mode"] == "FIXTURE" and row["ref"]["outbox"] == out.outbox_path


async def test_fixture_resend_is_a_replay(db, tmp_path):
    rid = await new_run(db)
    ses = SesConnector(Settings(_env_file=None, ses_from_address=""), outbox_dir=tmp_path)
    await ses.send(db, run_id=rid, action_id="A16", message=MSG)
    again = await ses.send(db, run_id=rid, action_id="A16", message=MSG)
    assert again.replayed and len(list(tmp_path.glob("*.eml"))) == 1
