"""SES bounces and complaints via SNS (CLAUDE.md §12, §16, checklist T237): POST /v1/webhooks/ses accepts only
messages whose SNS signature verifies against a certificate fetched from an SNS host, for the one configured topic.
No network: a locally generated key pair signs the messages and stands in for the SNS certificate."""

import base64
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from contextrail.connectors.ses import SesConnector
from contextrail.fixtures import load
from contextrail.main import create_app
from contextrail.settings import Settings
from contextrail.surfaces.decision_link import LinkSigner
from contextrail.surfaces.door import Door
from contextrail.surfaces.email import EmailDoorContext, handle_approval_dispatch_email
from contextrail.surfaces.ses_webhook import string_to_sign

TOPIC = "arn:aws:sns:ap-south-1:111122223333:contextrail-ses-events"   # fictional account
CERT_URL = "https://sns.ap-south-1.amazonaws.com/SimpleNotificationService-0000000000000000000000.pem"
PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_cert(key, *, days=1) -> bytes:
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
    now = datetime.now(UTC)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=2))
            .not_valid_after(now + timedelta(days=days)).sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM)


PEM = make_cert(KEY)


def signed(msg: dict, *, key=KEY, version="2") -> dict:
    msg = {"SignatureVersion": version, "SigningCertURL": CERT_URL, **msg}
    algorithm = hashes.SHA256() if version == "2" else hashes.SHA1()
    msg["Signature"] = base64.b64encode(key.sign(string_to_sign(msg), padding.PKCS1v15(), algorithm)).decode()
    return msg


def notification(event: dict, *, message_id="sns-1", topic=TOPIC, **extra) -> dict:
    return {"Type": "Notification", "MessageId": message_id, "TopicArn": topic, "Message": json.dumps(event),
            "Timestamp": "2026-09-26T10:00:00.000Z", **extra}


def bounce(ses_message_id: str) -> dict:
    return {"notificationType": "Bounce",
            "mail": {"messageId": ses_message_id, "destination": ["meera.iyer@northbeam.example"]},
            "bounce": {"bounceType": "Permanent", "bounceSubType": "General",
                       "bouncedRecipients": [{"emailAddress": "meera.iyer@northbeam.example"}]}}


# --- the string to sign, exactly as the SNS docs define it -----------------------------------------------------

def test_string_to_sign_for_a_notification_with_and_without_subject():
    msg = {"Type": "Notification", "MessageId": "m1", "TopicArn": "arn:t", "Message": "hello\nworld",
           "Timestamp": "2019-01-31T04:37:04.321Z", "Signature": "ignored", "SigningCertURL": "ignored"}
    assert string_to_sign(msg) == (b"Message\nhello\nworld\nMessageId\nm1\nTimestamp\n2019-01-31T04:37:04.321Z\n"
                                   b"TopicArn\narn:t\nType\nNotification\n")
    assert string_to_sign({**msg, "Subject": "s"}).startswith(b"Message\nhello\nworld\nMessageId\nm1\nSubject\ns\n")


def test_string_to_sign_for_a_subscription_confirmation():
    msg = {"Type": "SubscriptionConfirmation", "MessageId": "m2", "TopicArn": "arn:t", "Message": "confirm",
           "Timestamp": "t", "Token": "tok", "SubscribeURL": "https://sns.ap-south-1.amazonaws.com/?x=1"}
    assert string_to_sign(msg) == (b"Message\nconfirm\nMessageId\nm2\nSubscribeURL\n"
                                   b"https://sns.ap-south-1.amazonaws.com/?x=1\nTimestamp\nt\nToken\ntok\n"
                                   b"TopicArn\narn:t\nType\nSubscriptionConfirmation\n")


# --- the endpoint -------------------------------------------------------------------------------------------

@pytest.fixture
async def env(rail, tmp_path):
    runner, deps = rail
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    door = Door(runner, people=PEOPLE, modes=modes)
    view = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                actor_external_id="U0ANIL001")
    ctx = EmailDoorContext(door=door, ses=SesConnector(Settings(_env_file=None, ses_from_address=""),
                                                       outbox_dir=tmp_path),
                           signer=LinkSigner("test-only-decision-link-secret-0123456789abcdef"),
                           public_url="https://cr.test")
    async with deps.db.connection() as c:
        (job,) = [j["payload"] for j in await (await c.execute(
            "select payload from jobs where kind = 'approval.dispatch'")).fetchall() if j["payload"]["approver"] == "p-meera"]
    sent = await handle_approval_dispatch_email(job, ctx)
    fetched, confirmed = [], []

    async def fetch_cert(url):
        fetched.append(url)
        return PEM

    async def confirm(url):
        confirmed.append(url)

    app = create_app(Settings(_env_file=None, ses_sns_topic_arn=TOPIC))
    app.state.door, app.state.sns_cert_fetcher, app.state.sns_subscription_confirmer = door, fetch_cert, confirm
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://cr.test") as http:
        yield {"http": http, "app": app, "deps": deps, "sent": sent, "job": job, "fetched": fetched,
               "confirmed": confirmed, "run_id": view.run_id}


async def post(http, msg):
    return await http.post("/v1/webhooks/ses", content=json.dumps(msg),
                           headers={"content-type": "text/plain; charset=UTF-8",
                                    "x-amz-sns-message-type": msg.get("Type", "")})


async def q(deps, sql, *params):
    async with deps.db.connection() as c:
        return await (await c.execute(sql, params)).fetchall()


async def test_a_signed_bounce_marks_the_email_and_is_audited(env):
    r = await post(env["http"], signed(notification(bounce(env["sent"].message_id))))
    assert r.status_code == 200 and r.json()["status"] == "bounce"
    (dm,) = await q(env["deps"], "select * from door_messages where channel = 'email'")
    assert dm["ref"]["delivery"] == "bounce" and dm["ref"]["bounce_type"] == "Permanent"
    assert dm["ref"]["message_id"] == env["sent"].message_id                  # the send record is kept
    (ev,) = await q(env["deps"], "select run_id, payload from audit where event = 'email.bounce'")
    assert ev["run_id"] == env["run_id"] and ev["payload"] == {
        "action_id": env["job"]["action_id"], "message_id": env["sent"].message_id, "bounce_type": "Permanent",
        "bounce_sub_type": "General", "recipients": 1}                         # a count, not addresses
    (job,) = await q(env["deps"], "select payload from jobs where kind = 'email.undeliverable'")
    assert job["payload"] == {"run_id": str(env["run_id"]), "action_id": env["job"]["action_id"], "event": "bounce"}
    assert env["fetched"] == [CERT_URL]


async def test_a_complaint_is_recorded(env):
    event = {"eventType": "Complaint", "mail": {"messageId": env["sent"].message_id},
             "complaint": {"complainedRecipients": [{"emailAddress": "x@northbeam.example"}],
                           "complaintFeedbackType": "abuse"}}
    assert (await post(env["http"], signed(notification(event)))).json()["status"] == "complaint"
    assert len(await q(env["deps"], "select * from audit where event = 'email.complaint'")) == 1


async def test_signature_version_1_sha1_is_accepted(env):
    r = await post(env["http"], signed(notification(bounce(env["sent"].message_id)), version="1"))
    assert r.status_code == 200


@pytest.mark.parametrize("tamper", [
    lambda m: {**m, "Message": m["Message"].replace("Permanent", "Transient")},       # body edited after signing
    lambda m: {**m, "Signature": signed(dict(m), key=rsa.generate_private_key(public_exponent=65537,
                                                                             key_size=2048))["Signature"]},
    lambda m: {**m, "SignatureVersion": "3"},
])
async def test_a_message_that_does_not_verify_changes_nothing(env, tamper):
    before = await q(env["deps"], "select count(*) as n from audit")
    r = await post(env["http"], tamper(signed(notification(bounce(env["sent"].message_id)))))
    assert r.status_code == 403
    assert await q(env["deps"], "select count(*) as n from audit") == before
    assert (await q(env["deps"], "select ref from door_messages where channel = 'email'"))[0]["ref"].get(
        "delivery") is None


@pytest.mark.parametrize("url", [
    "https://sns.ap-south-1.amazonaws.com.evil.example/cert.pem",
    "http://sns.ap-south-1.amazonaws.com/cert.pem",
    "https://evil.example/SimpleNotificationService.pem",
    "https://sns.ap-south-1.amazonaws.com/cert.txt",
])
async def test_a_certificate_from_anywhere_but_sns_is_never_fetched(env, url):
    msg = signed(notification(bounce(env["sent"].message_id)))
    r = await post(env["http"], {**msg, "SigningCertURL": url})
    assert r.status_code == 403 and env["fetched"] == []


async def test_another_topic_is_rejected_before_any_fetch(env):
    msg = signed(notification(bounce(env["sent"].message_id), topic="arn:aws:sns:ap-south-1:999999999999:other"))
    assert (await post(env["http"], msg)).status_code == 403 and env["fetched"] == []


async def test_an_expired_certificate_is_rejected(env):
    env["app"].state.sns_cert_fetcher = _returning(make_cert(KEY, days=-1))
    assert (await post(env["http"], signed(notification(bounce(env["sent"].message_id))))).status_code == 403


def _returning(pem):
    async def fetch(url):
        return pem
    return fetch


async def test_sns_retries_are_processed_once(env):
    msg = signed(notification(bounce(env["sent"].message_id)))
    await post(env["http"], msg)
    again = await post(env["http"], msg)
    assert again.status_code == 200 and again.json()["status"] == "duplicate"
    assert len(await q(env["deps"], "select * from audit where event = 'email.bounce'")) == 1


async def test_a_subscription_is_confirmed_only_at_an_sns_url(env):
    sub = {"Type": "SubscriptionConfirmation", "MessageId": "sub-1", "TopicArn": TOPIC, "Token": "tok",
           "Message": "You have chosen to subscribe", "Timestamp": "2026-09-26T10:00:00.000Z",
           "SubscribeURL": "https://sns.ap-south-1.amazonaws.com/?Action=ConfirmSubscription&Token=tok"}
    r = await post(env["http"], signed(sub))
    assert r.status_code == 200 and env["confirmed"] == [sub["SubscribeURL"]]
    evil = {**sub, "MessageId": "sub-2", "SubscribeURL": "https://evil.example/?Action=ConfirmSubscription"}
    assert (await post(env["http"], signed(evil))).status_code == 403 and len(env["confirmed"]) == 1


async def test_deliveries_and_unknown_messages_are_acknowledged_and_ignored(env):
    delivery = {"notificationType": "Delivery", "mail": {"messageId": env["sent"].message_id}, "delivery": {}}
    assert (await post(env["http"], signed(notification(delivery, message_id="sns-d")))).json()["status"] == "ignored"
    stranger = signed(notification(bounce("not-one-of-ours"), message_id="sns-u"))
    assert (await post(env["http"], stranger)).json()["status"] == "unknown_message"
    assert await q(env["deps"], "select * from audit where event like %s", "email.%") == []


async def test_without_a_configured_topic_nothing_is_accepted(env, rail):
    app = create_app(Settings(_env_file=None, ses_sns_topic_arn=""))
    app.state.door = env["app"].state.door
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://cr.test") as http:
        assert (await post(http, signed(notification(bounce(env["sent"].message_id))))).status_code == 503


async def test_garbage_is_a_bad_request(env):
    r = await env["http"].post("/v1/webhooks/ses", content=b"not json")
    assert r.status_code == 400
