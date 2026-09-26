"""The approval email (CLAUDE.md §13.6, checklist T231): rendered from RunView/RowView only, HTML + plain text, with
the lamp, the action, the rule and its clause verbatim, the named approver, the explanation, honest modes and two
signed links. Plus the approval.dispatch job handler for approvers whose preferred door is email."""

import email
import email.policy
import html
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from contextrail.connectors.ses import SesConnector
from contextrail.fixtures import load
from contextrail.settings import Settings
from contextrail.surfaces.decision_link import LinkSigner
from contextrail.surfaces.door import Door
from contextrail.surfaces.email import EmailDoorContext, handle_approval_dispatch_email, render_approval_email
from contextrail.surfaces.presenter import RowView, RunView

SECRET = "test-only-decision-link-secret-0123456789abcdef"  # obviously fake
PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
CLAUSE = ("Paid SaaS seats require approval from the requester's line manager before a licence is assigned; "
          "the seat is billed to the manager's cost centre.")
APPROVE, REFUSE = "https://cr.test/a/APPROVE-TOKEN", "https://cr.test/a/REFUSE-TOKEN"
EXPIRES = datetime(2026, 9, 29, 11, 30, tzinfo=UTC)


def a_view(*, request_text="Give Anil the same access as Rahul Mehta", connector_mode="FIXTURE", replay=False):
    row = RowView(action_id="A16", kind="grant", label="Figma Professional seat", verdict="HOLD", lamp="🟠",
                  state="awaiting", rule_id="POL-ACC-005", clause=CLAUSE, approver_id="p-meera",
                  approver_name="Meera Iyer", explanation="Held for Meera Iyer: paid SaaS seats need manager approval.",
                  explainer="template", verified=False, params_hash="c" * 64, struck_through=False,
                  connector_mode=connector_mode)
    view = RunView(run_id=uuid4(), status="awaiting_approval", stage="finalize", source="slack",
                   request_text=request_text, subject="Anil Kumar", peer="Rahul Mehta", rows=[row],
                   counts={"allow": 15, "hold": 2, "refuse": 1, "verified": 15, "awaiting": 2, "failed": 0},
                   capsule_digest="9f3a" + "0" * 60, modes={"entitlements": connector_mode}, replay=replay)
    return view, row


def render(delivery="FIXTURE", **kw):
    view, row = a_view(**kw)
    return render_approval_email(view, row, approve_url=APPROVE, refuse_url=REFUSE, delivery_mode=delivery,
                                 expires_at=EXPIRES)


def flat(text: str) -> str:
    return " ".join(text.split())


# --- rendering -----------------------------------------------------------------------------------------

def test_subject_names_the_action_with_its_lamp():
    assert render().subject == "🟠 Approval needed: Figma Professional seat"


def test_plain_text_carries_everything_the_approver_needs():
    t = render().text
    for needle in ("🟠", "Figma Professional seat", "POL-ACC-005", "Meera Iyer", "Anil Kumar", "Rahul Mehta",
                   "Held for Meera Iyer: paid SaaS seats need manager approval. (template)",
                   "Nothing is decided until you press Confirm", "29 Sep 2026 17:00 IST", CLAUSE):
        assert needle in flat(t), needle                       # verbatim; lines are only re-flowed for phones
    assert re.search(r"^Approve:\n" + re.escape(APPROVE) + "$", t, re.MULTILINE)
    assert re.search(r"^Refuse:\n" + re.escape(REFUSE) + "$", t, re.MULTILINE)


def test_plain_text_is_readable_on_a_phone():
    lines = render().text.splitlines()
    assert all(len(line) <= 64 for line in lines if not line.startswith("https://")), \
        [line for line in lines if len(line) > 64]


@pytest.mark.parametrize(("delivery", "connector", "expected"), [
    ("FIXTURE", "FIXTURE", "Mode: email FIXTURE, target system FIXTURE"),
    ("LIVE", "FIXTURE", "Mode: email LIVE, target system FIXTURE"),
    ("LIVE", "LIVE", "Mode: email LIVE, target system LIVE"),
])
def test_modes_are_printed_honestly(delivery, connector, expected):
    e = render(delivery=delivery, connector_mode=connector)
    assert expected in e.text and expected.removeprefix("Mode: ") in e.html   # HTML lays facts out as a table


def test_replayed_model_text_is_flagged():
    assert "REPLAY" in render(replay=True).text and "REPLAY" not in render().text


def test_html_has_two_buttons_to_the_signed_links():
    h = render().html
    assert h.count(f'href="{APPROVE}"') == 1 and h.count(f'href="{REFUSE}"') == 1
    assert ">Approve</a>" in h and ">Refuse</a>" in h
    for needle in ("🟠", "Figma Professional seat", "POL-ACC-005", "Meera Iyer", html.escape(CLAUSE, quote=False)):
        assert needle in h, needle


def test_the_requesters_words_are_escaped_in_html():
    h = render(request_text='<img src=x onerror="alert(1)"> same as Rahul').html
    assert "<img" not in h and "&lt;img" in h


# --- the approval.dispatch job handler (email door) ---------------------------------------------------------

@pytest.fixture
async def email_env(rail, tmp_path):
    runner, deps = rail
    modes = {n: deps.registry.get(n).mode for n in ("hris", "entitlements", "github", "slack_corpus")}
    door = Door(runner, people=PEOPLE, modes=modes)
    view = await door.start_run("Give Anil the same access as Rahul Mehta", channel="slack",
                                actor_external_id="U0ANIL001")
    ses = SesConnector(Settings(_env_file=None, ses_from_address=""), outbox_dir=tmp_path)
    ctx = EmailDoorContext(door=door, ses=ses, signer=LinkSigner(SECRET), public_url="https://cr.test")
    async with deps.db.connection() as c:
        jobs = {j["payload"]["approver"]: j["payload"] for j in await (await c.execute(
            "select payload from jobs where kind = 'approval.dispatch'")).fetchall()}
    return ctx, deps, view, jobs, tmp_path


def read_outbox(path: str):
    return email.message_from_bytes(Path(path).read_bytes(), policy=email.policy.default)


async def test_meera_prefers_email_and_gets_one_with_signed_links(email_env):
    ctx, deps, view, jobs, _ = email_env
    out = await handle_approval_dispatch_email(jobs["p-meera"], ctx)
    assert (out.outcome, out.mode) == ("sent", "FIXTURE")
    msg = read_outbox(out.outbox_path)
    assert msg["To"] == "meera.iyer@northbeam.example" and "Approval needed" in msg["Subject"]
    text = msg.get_body(("plain",)).get_content()
    urls = re.findall(r"^https://cr\.test/a/(\S+)$", text, re.MULTILINE)
    claims = [ctx.signer.verify(u) for u in urls]
    row = next(r for r in view.rows if r.approver_id == "p-meera")
    assert [(c.decision, c.approver, c.action_id, c.params_hash, c.run_id) for c in claims] == [
        ("approved", "p-meera", row.action_id, row.params_hash, view.run_id),
        ("refused", "p-meera", row.action_id, row.params_hash, view.run_id)]
    assert timedelta(hours=71) < claims[0].expires_at - datetime.now(UTC) <= timedelta(hours=72)
    async with deps.db.connection() as c:
        (ev,) = await (await c.execute("select payload from audit where event = 'approval.email_sent'")).fetchall()
    assert ev["payload"] == {"action_id": row.action_id, "approver": "p-meera", "mode": "FIXTURE",
                             "message_id": out.message_id}


async def test_a_retried_dispatch_job_sends_nothing_new(email_env):
    ctx, _, _, jobs, outbox = email_env
    await handle_approval_dispatch_email(jobs["p-meera"], ctx)
    again = await handle_approval_dispatch_email(jobs["p-meera"], ctx)
    assert again.outcome == "replayed" and len(list(outbox.glob("*.eml"))) == 1


async def test_an_approver_who_prefers_another_door_is_skipped(email_env):
    ctx, _, _, jobs, outbox = email_env
    out = await handle_approval_dispatch_email(jobs["p-dana"], ctx)          # Dana prefers Teams
    assert out.outcome == "skipped" and "teams" in out.reason and list(outbox.glob("*.eml")) == []


async def test_a_stale_dispatch_is_skipped(email_env):
    ctx, _, _, jobs, outbox = email_env
    out = await handle_approval_dispatch_email({**jobs["p-meera"], "params_hash": "d" * 64}, ctx)
    assert out.outcome == "skipped" and "parameters changed" in out.reason and list(outbox.glob("*.eml")) == []


async def test_an_action_already_decided_elsewhere_gets_no_email(email_env):
    ctx, _, view, jobs, outbox = email_env
    row = next(r for r in view.rows if r.approver_id == "p-meera")
    r = await ctx.door.decide(view.run_id, row.action_id, row.params_hash, channel="slack",
                              actor_external_id="U0MEER301", decision="approved")
    assert r.outcome == "recorded"
    out = await handle_approval_dispatch_email(jobs["p-meera"], ctx)
    assert out.outcome == "skipped" and "not awaiting" in out.reason and list(outbox.glob("*.eml")) == []


async def test_links_expire_at_the_action_deadline_when_it_is_sooner(email_env):
    ctx, deps, view, jobs, _ = email_env
    row = next(r for r in view.rows if r.approver_id == "p-meera")
    deadline = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=5)
    async with deps.db.connection() as c:
        await c.execute("update actions set expires_at = %s where run_id = %s and id = %s",
                        (deadline, view.run_id, row.action_id))
    out = await handle_approval_dispatch_email(jobs["p-meera"], ctx)
    text = read_outbox(out.outbox_path).get_body(("plain",)).get_content()
    first = re.search(r"^https://cr\.test/a/(\S+)$", text, re.MULTILINE).group(1)
    assert ctx.signer.verify(first).expires_at == deadline
