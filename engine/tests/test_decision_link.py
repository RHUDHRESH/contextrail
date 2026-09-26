"""CLAUDE.md §18 test_decision_link.py (checklist T232): GET changes nothing; a tampered or expired token is rejected
(and audited when someone tries to use it); POST decides, once. Corporate mail scanners prefetch every link, so a GET
that decided would approve things without a human (§13.6, D-007)."""

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from contextrail.fixtures import load
from contextrail.main import create_app
from contextrail.settings import Settings
from contextrail.surfaces.decision_link import LinkClaims, LinkError, LinkSigner, WeakSecret
from contextrail.surfaces.door import Door

SECRET = "test-only-decision-link-secret-0123456789abcdef"  # obviously fake, >= 32 chars
PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
ANIL_SLACK = "U0ANIL001"
TABLES = ("runs", "actions", "approvals", "audit", "jobs", "door_messages", "webhook_dedupe", "receipts",
          "identity_map", "llm_calls")


def claims(**kw) -> LinkClaims:
    base = {"run_id": uuid4(), "action_id": "A16", "params_hash": "a" * 64, "approver": "p-meera",
            "decision": "approved", "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp())}
    return LinkClaims(**{**base, **kw})


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# --- the token ---------------------------------------------------------------------------------------------

def test_round_trip():
    s, c = LinkSigner(SECRET), claims()
    assert s.verify(s.sign(c)) == c


def test_the_mac_is_hmac_sha256_over_the_pipe_joined_fields():
    s, c = LinkSigner(SECRET), claims()
    payload, mac = s.sign(c).split(".")
    msg = f"{c.run_id}|{c.action_id}|{c.params_hash}|{c.approver}|{c.decision}|{c.exp}".encode()
    assert mac == b64(hmac.new(SECRET.encode(), msg, hashlib.sha256).digest())
    assert LinkClaims.model_validate_json(base64.urlsafe_b64decode(payload + "==")) == c


def test_a_refuse_link_cannot_be_edited_into_an_approve_link():
    s = LinkSigner(SECRET)
    payload, mac = s.sign(claims(decision="refused")).split(".")
    body = json.loads(base64.urlsafe_b64decode(payload + "=="))
    forged = b64(json.dumps({**body, "decision": "approved"}).encode()) + "." + mac
    with pytest.raises(LinkError) as e:
        s.verify(forged)
    assert e.value.reason == "bad_signature" and e.value.claims.decision == "approved"  # claimed, not trusted


@pytest.mark.parametrize("mutate", [
    lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),                  # signature bits flipped
    lambda t: LinkSigner("another-secret-entirely-0123456789abcdef").sign(claims()),  # signed with another key
])
def test_a_bad_signature_is_rejected(mutate):
    s = LinkSigner(SECRET)
    with pytest.raises(LinkError) as e:
        s.verify(mutate(s.sign(claims())))
    assert e.value.reason == "bad_signature"


def test_an_expired_link_is_rejected_after_its_signature_is_checked():
    s = LinkSigner(SECRET)
    c = claims(exp=int((datetime.now(UTC) - timedelta(seconds=1)).timestamp()))
    with pytest.raises(LinkError) as e:
        s.verify(s.sign(c))
    assert (e.value.reason, e.value.claims) == ("expired", c)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "!!!.???", b64(b"[1,2]") + ".x", b64(b'{"run_id":1}') + ".x",
                                   "x" * 5000])
def test_malformed_tokens_are_rejected(token):
    with pytest.raises(LinkError) as e:
        LinkSigner(SECRET).verify(token)
    assert e.value.reason == "malformed"


@pytest.mark.parametrize("secret", ["", "change-me", "short-secret"])
def test_a_weak_secret_signs_nothing(secret):
    with pytest.raises(WeakSecret):
        LinkSigner(secret)


def test_fields_cannot_smuggle_the_separator():
    with pytest.raises(ValidationError):
        claims(approver="p-meera|approved")


# --- the routes: GET shows, POST decides --------------------------------------------------------------------

@pytest.fixture
async def env(rail):
    runner, deps = rail
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    door = Door(runner, people=PEOPLE, modes=modes)
    view = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                actor_external_id=ANIL_SLACK)
    row = next(r for r in view.rows if r.approver_id == "p-meera")
    app = create_app(Settings(_env_file=None, decision_link_secret=SECRET, public_url="https://cr.test"))
    app.state.door = door
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://cr.test") as http:
        yield http, door, deps, view, row


def link(view, row, **kw) -> str:
    return LinkSigner(SECRET).sign(claims(run_id=view.run_id, action_id=row.action_id, params_hash=row.params_hash,
                                          **kw))


async def snapshot(deps) -> dict:
    async with deps.db.connection() as c:
        return {t: await (await c.execute(f"select * from {t} order by 1")).fetchall() for t in TABLES}


async def rows(deps, sql, *params) -> list[dict]:
    async with deps.db.connection() as c:
        return await (await c.execute(sql, params)).fetchall()


async def test_get_renders_a_confirm_page_and_changes_nothing(env):
    http, _, deps, view, row = env
    before = await snapshot(deps)
    r = await http.get(f"/a/{link(view, row)}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    assert row.label in page and row.rule_id in page and "Meera Iyer" in page and "🟠" in page
    assert '<form method="post">' in page and "Confirm: approve" in page
    assert await snapshot(deps) == before                      # every table, row for row, including updated_at


async def test_get_is_safe_to_prefetch_many_times(env):
    http, _, deps, view, row = env
    before = await snapshot(deps)
    for token in (link(view, row), link(view, row, decision="refused")):
        for _ in range(3):
            assert (await http.get(f"/a/{token}")).status_code == 200
    assert await snapshot(deps) == before


async def test_get_sends_headers_that_keep_the_page_private_and_unframeable(env):
    http, _, _, view, row = env
    h = (await http.get(f"/a/{link(view, row)}")).headers
    assert h["cache-control"] == "no-store" and h["referrer-policy"] == "no-referrer"
    assert h["x-frame-options"] == "DENY" and "frame-ancestors 'none'" in h["content-security-policy"]


@pytest.mark.parametrize(("make", "status"), [
    (lambda v, r: link(v, r)[:-3] + "AAA", 400),
    (lambda v, r: link(v, r, exp=int(datetime.now(UTC).timestamp()) - 5), 410),
])
async def test_get_with_a_bad_or_expired_link_explains_and_changes_nothing(env, make, status):
    http, _, deps, view, row = env
    before = await snapshot(deps)
    assert (await http.get(f"/a/{make(view, row)}")).status_code == status
    assert await snapshot(deps) == before


async def test_post_decides_once(env):
    http, _, deps, view, row = env
    token = link(view, row)
    first = await http.post(f"/a/{token}", data={"reason": "within budget"})
    assert first.status_code == 200 and "Approved" in first.text
    (a,) = await rows(deps, "select * from approvals where run_id = %s", view.run_id)
    assert (a["action_id"], a["approver"], a["decision"], a["channel"], a["reason"]) == (
        row.action_id, "p-meera", "approved", "email", "within budget")
    again = await http.post(f"/a/{token}")
    assert again.status_code == 409 and "already approved" in again.text.lower()
    assert len(await rows(deps, "select * from approvals where run_id = %s", view.run_id)) == 1


@pytest.mark.parametrize(("make", "status", "reason"), [
    (lambda v, r: link(v, r)[:-3] + "AAA", 400, "bad_signature"),
    (lambda v, r: link(v, r, exp=int(datetime.now(UTC).timestamp()) - 5), 410, "expired"),
])
async def test_post_with_a_bad_or_expired_link_is_rejected_and_audited(env, make, status, reason):
    http, _, deps, view, row = env
    token = make(view, row)
    r = await http.post(f"/a/{token}")
    assert r.status_code == status
    assert await rows(deps, "select * from approvals where run_id = %s", view.run_id) == []
    (ev,) = await rows(deps, "select * from audit where event = 'decision_link.rejected'")
    assert ev["run_id"] == view.run_id and ev["payload"]["reason"] == reason
    assert ev["payload"]["claimed"]["action_id"] == row.action_id
    assert token.split(".")[1] not in json.dumps(ev["payload"])   # a fingerprint is kept, never the capability


async def test_post_with_garbage_is_audited_without_a_run(env):
    http, _, deps, _, _ = env
    assert (await http.post("/a/not-a-token")).status_code == 400
    (ev,) = await rows(deps, "select * from audit where event = 'decision_link.rejected'")
    assert ev["run_id"] is None and ev["payload"]["reason"] == "malformed"


async def test_a_link_for_changed_parameters_is_rejected_by_the_door_and_audited(env):
    http, _, deps, view, row = env
    stale = LinkSigner(SECRET).sign(claims(run_id=view.run_id, action_id=row.action_id, params_hash="b" * 64))
    r = await http.post(f"/a/{stale}")
    assert r.status_code == 403 and "out of date" in r.text
    assert await rows(deps, "select * from approvals where run_id = %s", view.run_id) == []
    (ev,) = await rows(deps, "select * from audit where event = 'approval.rejected'")
    assert ev["payload"]["channel"] == "email" and "out of date" in ev["payload"]["reason"]


async def test_a_link_signed_for_someone_else_cannot_decide(env):
    http, _, deps, view, row = env
    r = await http.post(f"/a/{link(view, row, approver='p-dana')}")   # Meera's action, Dana's link
    assert r.status_code == 403 and "only Meera Iyer can decide" in r.text
    assert await rows(deps, "select * from approvals where run_id = %s", view.run_id) == []
    (ev,) = await rows(deps, "select * from audit where event = 'approval.rejected'")
    assert ev["payload"]["actor"] == "p-dana"


async def test_user_text_is_escaped_on_the_page(env):
    http, _, deps, view, row = env
    async with deps.db.connection() as c:
        await c.execute("update runs set request_text = %s where id = %s",
                        ('<script>alert("x")</script> same as Rahul', view.run_id))
    page = (await http.get(f"/a/{link(view, row)}")).text
    assert "<script>" not in page and "&lt;script&gt;" in page


async def test_a_weak_secret_turns_links_off(env, rail):
    _, door, deps, view, row = env
    app = create_app(Settings(_env_file=None, decision_link_secret="change-me"))
    app.state.door = door
    before = await snapshot(deps)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://cr.test") as http:
        assert (await http.get(f"/a/{link(view, row)}")).status_code == 503
        assert (await http.post(f"/a/{link(view, row)}")).status_code == 503
    assert await snapshot(deps) == before
