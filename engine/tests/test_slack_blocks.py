"""Block Kit renderers for the Slack door: pure functions of RunView, tested without a database or Slack."""

import json
from datetime import UTC, datetime
from uuid import UUID

from contextrail.models import StageEvent
from contextrail.surfaces import slack_blocks as blocks
from contextrail.surfaces.presenter import RowView, RunView

RUN_ID = UUID("0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0")
DIGEST = "9f3a" + "0" * 58 + "e1"
HASH = "ab" * 32


def _row(action_id: str, verdict: str, state: str, **kw) -> RowView:
    lamp = {"ALLOW": "✅", "HOLD": "🟠", "REFUSE": "⛔"}[verdict]
    base = {"action_id": action_id, "kind": "grant", "label": action_id, "verdict": verdict, "lamp": lamp,
            "state": state, "rule_id": "POL-ACC-001", "clause": "Role baseline.", "verified": state == "verified",
            "params_hash": HASH, "struck_through": verdict == "REFUSE", "connector_mode": "FIXTURE"}
    return RowView(**(base | kw))


def _view(**kw) -> RunView:
    rows = [
        _row("a-jira", "ALLOW", "verified", label="Jira payments project"),
        _row("a-github", "HOLD", "awaiting", label="GitHub northbeam/perception-sdk (read)", rule_id="POL-ACC-004",
             clause="Production-tagged repositories need Security approval.", approver_id="p-dana",
             approver_name="Dana Osei", explanation="Held for Dana Osei: the repository is production-tagged.",
             explainer="template", connector_mode="FIXTURE"),
        _row("a-aws", "REFUSE", "refused", label="AWS payments-prod AdministratorAccess", rule_id="POL-ACC-003",
             clause="Administrator rights on production require a senior engineer."),
    ]
    base = {"run_id": RUN_ID, "status": "awaiting_approval", "stage": "finalize", "source": "slack",
            "request_text": "Give Anil the same access as Rahul Mehta", "subject": "Anil Kumar", "peer": "Rahul Mehta",
            "rows": rows, "counts": {"allow": 1, "hold": 1, "refuse": 1, "verified": 1, "awaiting": 1, "failed": 0},
            "capsule_digest": DIGEST, "modes": {"entitlements": "FIXTURE", "github": "FIXTURE", "hris": "FIXTURE"}}
    return RunView(**(base | kw))


def _all_text(content: dict) -> str:
    return json.dumps(content, ensure_ascii=False)


def test_untrusted_text_cannot_become_a_mention_or_a_link():
    hostile = "ping <!channel> & see <https://evil.example|payroll>"
    shown = blocks.ack_text(hostile)
    assert "<!channel>" not in shown and "<https://" not in shown
    assert "&lt;!channel&gt; &amp; see &lt;https://evil.example|payroll&gt;" in shown


# --- T142: the run status message ---------------------------------------------------------------------------------

def test_stage_message_names_the_step_and_quotes_the_rail():
    event = StageEvent(run_id=RUN_ID, seq=2, stage="govern", status="running", at=datetime.now(UTC),
                       message="Govern: 15 allowed, 2 held, 1 refused", counts={"allow": 15, "hold": 2, "refuse": 1})
    content = blocks.stage_message("Give Anil the same access as Rahul Mehta", event)
    text = _all_text(content)
    assert "Step 3 of 9" in text and "Govern: 15 allowed, 2 held, 1 refused" in text
    assert "Give Anil the same access as Rahul Mehta" in text and content["text"]


def test_run_summary_shows_every_row_with_its_lamp_and_the_honest_modes():
    content = blocks.run_summary(_view())
    text = _all_text(content)
    assert "Waiting for approval" in text
    assert "✅ Jira payments project · verified" in text
    assert "🟠 GitHub northbeam/perception-sdk (read) · waiting for Dana Osei" in text
    assert "⛔ ~AWS payments-prod AdministratorAccess~ · POL-ACC-003: Administrator rights on production" in text
    assert "1 verified · 🟠 1 waiting · ⛔ 1 refused" in text
    assert "9f3a…e1" in text and "hris FIXTURE" in text and "replay" not in text
    assert "replay" in _all_text(blocks.run_summary(_view(replay=True)))


def _hold(view: RunView) -> RowView:
    return next(r for r in view.rows if r.verdict == "HOLD")


# --- T146: the approval card ----------------------------------------------------------------------------------------

def test_approval_card_buttons_are_bound_to_run_action_and_params_hash():
    content = blocks.approval_card(_view(), _hold(_view()))
    header, section, context, actions = content["blocks"]
    assert [b["type"] for b in (header, section, context, actions)] == ["header", "section", "context", "actions"]
    approve, refuse = actions["elements"]
    assert (approve["action_id"], approve["style"], refuse["action_id"], refuse["style"]) == \
        ("approve", "primary", "refuse", "danger")
    assert approve["value"] == refuse["value"] == f"{RUN_ID}|a-github|{HASH}"
    assert len(approve["value"]) <= 2000 and content["text"]


def test_approval_card_quotes_subject_action_rule_clause_approver_and_why():
    header, section, context, _ = blocks.approval_card(_view(), _hold(_view()))["blocks"]
    assert header["text"]["text"] == "Approval needed · GitHub northbeam/perception-sdk (read)"
    text = section["text"]["text"]
    assert "*Anil Kumar*" in text and "Give Anil the same access as Rahul Mehta" in text
    assert "GitHub northbeam/perception-sdk (read)" in text
    assert "POL-ACC-004 — Production-tagged repositories need Security approval." in text
    assert "Dana Osei" in text and "Held for Dana Osei: the repository is production-tagged." in text
    line = context["elements"][0]["text"]
    assert "0f1e2d3c" in line and "9f3a…e1" in line and "this action: FIXTURE" in line


def test_approval_card_labels_replay_and_respects_slack_limits():
    long = _row("a-long", "HOLD", "awaiting", label="x" * 400 + " <!here>", approver_id="p-dana",
                approver_name="Dana Osei")
    view = _view(replay=True, rows=[long])
    header, section, context, _ = blocks.approval_card(view, long)["blocks"]
    assert len(header["text"]["text"]) <= 150 and header["text"]["type"] == "plain_text"
    assert "<!here>" not in section["text"]["text"] and "&lt;!here&gt;" in section["text"]["text"]
    assert "replay" in context["elements"][0]["text"]


def test_run_summary_after_decisions_says_who_approved_and_who_refused():
    view = _view(status="partial", rows=[
        _row("a-github", "HOLD", "verified", approver_id="p-dana", approver_name="Dana Osei"),
        _row("a-seat", "HOLD", "refused", approver_id="p-meera", approver_name="Meera Iyer"),
    ])
    text = _all_text(blocks.run_summary(view))
    assert "🟠 a-github · approved by Dana Osei · verified" in text
    assert "🟠 a-seat · refused by Meera Iyer" in text
