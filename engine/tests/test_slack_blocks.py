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


def test_decision_value_round_trips_and_anything_else_is_rejected():
    value = blocks.decision_value(_view(), _hold(_view()))
    assert blocks.parse_decision_value(value) == (RUN_ID, "a-github", HASH)
    for bad in ("", "x|y|z", f"{RUN_ID}|a-github", f"{RUN_ID}|a-github|{HASH[:-1]}", f"not-a-uuid|a|{HASH}",
                f"{RUN_ID}||{HASH}", f"{RUN_ID}|a-github|{HASH}|extra", f"{RUN_ID}|a-github|{HASH.upper()}"):
        assert blocks.parse_decision_value(bad) is None, bad


# --- T150: the card after a decision --------------------------------------------------------------------------------

DECIDED_AT = datetime(2026, 9, 26, 8, 32, tzinfo=UTC)


def test_decided_card_says_who_where_when_and_has_no_buttons():
    decision = {"approver": "p-dana", "decision": "approved", "channel": "teams", "decided_at": DECIDED_AT,
                "reason": None}
    content = blocks.decided_card(_view(), _hold(_view()), decision)
    assert "actions" not in [b["type"] for b in content["blocks"]]
    assert content["blocks"][0]["text"]["text"] == "Approved · GitHub northbeam/perception-sdk (read)"
    text = _all_text(content)
    assert "✅ *Approved* by Dana Osei in Teams" in text
    assert f"<!date^{int(DECIDED_AT.timestamp())}^{{date_short_pretty}} at {{time}}|2026-09-26 08:32 UTC>" in text
    assert "POL-ACC-004" in text and content["text"].startswith("Approved by Dana Osei")


def test_refused_card_quotes_the_reason():
    decision = {"approver": "p-dana", "decision": "refused", "channel": "email", "decided_at": DECIDED_AT,
                "reason": "No production access <this> quarter"}
    text = _all_text(blocks.decided_card(_view(), _hold(_view()), decision))
    assert "⛔ *Refused* by Dana Osei in email" in text and "No production access &lt;this&gt; quarter" in text


# --- T154: needs_input asks, with a button per candidate --------------------------------------------------------------

RAHULS = [{"source_id": "E-0007", "display_name": "Rahul Mehta", "team": "payments", "role": "payments-engineer",
           "employment_type": "employee"},
          {"source_id": "E-0415", "display_name": "Rahul Verma", "team": "risk-analytics", "role": "risk-analyst",
           "employment_type": "employee"}]


def _needs_view(*needs: dict) -> RunView:
    return _view(status="needs_input", stage="discover", rows=[], subject=None, peer=None, capsule_digest=None,
                 counts={"allow": 0, "hold": 0, "refuse": 0, "verified": 0, "awaiting": 0, "failed": 0},
                 request_text="Give Anil the same access as Rahul", needs=list(needs))


def test_ambiguous_name_asks_which_one_with_a_button_per_candidate():
    view = _needs_view({"role": "peer", "mention": "Rahul", "reason": "ambiguous", "candidates": RAHULS})
    content = blocks.run_summary(view)
    text = _all_text(content)
    assert "I need one more detail" in text and "Which *Rahul* do you mean?" in text
    [actions] = [b for b in content["blocks"] if b["type"] == "actions"]
    labels = [e["text"]["text"] for e in actions["elements"]]
    values = [e["value"] for e in actions["elements"]]
    assert labels == ["Rahul Mehta · payments", "Rahul Verma · risk-analytics"]
    assert values == [f"{RUN_ID}|peer|E-0007", f"{RUN_ID}|peer|E-0415"]
    ids = [e["action_id"] for e in actions["elements"]]
    assert len(set(ids)) == 2 and all(i.startswith("pick_candidate:") for i in ids)


def test_questions_without_candidates_are_asked_in_words():
    for need, fragment in [
        ({"role": "peer", "mention": "Rahull", "reason": "no_match", "candidates": []}, "I couldn't find *Rahull*"),
        ({"role": "subject", "mention": None, "reason": "no_mention", "candidates": []}, "Who is this for?"),
        ({"role": "request", "mention": None, "reason": "unclear_request", "candidates": []}, "What should be done"),
        ({"role": "peer", "mention": "Anil", "reason": "same_person", "candidates": []}, "Whose access should"),
    ]:
        content = blocks.run_summary(_needs_view(need))
        assert fragment in _all_text(content), need["reason"]
        assert "actions" not in [b["type"] for b in content["blocks"]]


def test_pick_value_round_trips_and_anything_else_is_rejected():
    assert blocks.parse_pick_value(blocks.pick_value(RUN_ID, "peer", "E-0007")) == (RUN_ID, "peer", "E-0007")
    for bad in ("", f"{RUN_ID}|boss|E-0007", f"{RUN_ID}|peer|", f"{RUN_ID}|peer|E 0007", "x|peer|E-0007",
                f"{RUN_ID}|peer|E-0007|x"):
        assert blocks.parse_pick_value(bad) is None, bad


def test_run_summary_after_decisions_says_who_approved_and_who_refused():
    view = _view(status="partial", rows=[
        _row("a-github", "HOLD", "verified", approver_id="p-dana", approver_name="Dana Osei"),
        _row("a-seat", "HOLD", "refused", approver_id="p-meera", approver_name="Meera Iyer"),
    ])
    text = _all_text(blocks.run_summary(view))
    assert "🟠 a-github · approved by Dana Osei · verified" in text
    assert "🟠 a-seat · refused by Meera Iyer" in text
