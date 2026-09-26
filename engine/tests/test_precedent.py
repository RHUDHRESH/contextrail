"""Precedents from the audit chain (checklist T180, CLAUDE.md §10 precedent + publish-back, X4, X5).

Counts come only from a verified audit chain: approval decisions are chain events, the rule is the one the chain's
govern event recorded, and an action's entitlement is accepted only when its params_hash matches the hash the
decision was bound to. The updated page and the Solutions article are drafts; nothing curated is overwritten.
"""

import hashlib

import psycopg
import pytest
from okf_util import fresh_copy

from contextrail.fixtures import load
from contextrail.knowledge.okf import load_bundle
from contextrail.knowledge.precedent import (
    ChainBroken,
    compute_precedents,
    draft_precedent_page,
    draft_solutions_article,
    write_draft,
)
from contextrail.seed import reset_fixture_state
from contextrail.surfaces.door import Door

PEOPLE = {p["person_id"]: p["display_name"] for p in load("identity")["people"]}
DANA_TEAMS, MEERA_EMAIL = "00000000-0000-4000-8000-000000000050", "meera.iyer@northbeam.example"
PAGE = "precedents/github-readonly-contractors.md"


@pytest.fixture
def door(rail):
    runner, deps = rail
    return Door(runner, people=PEOPLE, modes={}), deps


async def _run(door, text: str, actor: str = "U0ANIL001") -> dict:
    view = await door.start_run(text, channel="slack", actor_external_id=actor)
    return view, {r.label: r for r in view.rows if r.state == "awaiting"}


async def _decide(door, view, row, actor_channel: str, actor: str, decision: str) -> None:
    r = await door.decide(view.run_id, row.action_id, row.params_hash, channel=actor_channel,
                          actor_external_id=actor, decision=decision)
    assert r.outcome == "recorded", r


async def _book(deps):
    async with deps.db.connection() as c:
        return await compute_precedents(c)


async def _two_anil_runs(door, deps, tmp_path):
    """Run 1: Security approves payments-core read, the manager refuses the Postman seat. Run 2 (fixture state
    reset, so the same items are asked again): Security approves payments-core read; the seat stays pending."""
    view, held = await _run(door, "Give Anil the same access as Rahul Mehta")
    await _decide(door, view, held["GitHub northbeam/payments-core (read)"], "teams", DANA_TEAMS, "approved")
    await _decide(door, view, held["Postman Enterprise seat ($49/mo)"], "email", MEERA_EMAIL, "refused")
    reset_fixture_state(tmp_path)
    view2, held2 = await _run(door, "Give Anil the same access as Rahul Mehta")
    await _decide(door, view2, held2["GitHub northbeam/payments-core (read)"], "teams", DANA_TEAMS, "approved")
    return view, view2


async def test_counts_per_rule_and_entitlement_come_from_decisions_in_the_chain(door, tmp_path):
    d, deps = door
    view1, view2 = await _two_anil_runs(d, deps, tmp_path)
    book = await _book(deps)
    core = book.get("POL-ACC-004", "gh-payments-core-read")
    seat = book.get("POL-ACC-005", "postman-enterprise-seat")
    assert (core.approved, core.refused, set(core.runs)) == (2, 0, {view1.run_id, view2.run_id})
    assert (seat.approved, seat.refused, seat.runs) == (0, 1, (view1.run_id,))    # run 2's seat is still pending
    async with deps.db.connection() as c:
        decided = [r["seq"] for r in await (await c.execute(
            "select seq from audit where event = 'approval.decided' order by seq")).fetchall()]
    assert sorted(core.cites + seat.cites) == decided                          # every count cites its audit row
    assert book.get("POL-ACC-004", "never-asked").approved == 0 and book.chain_rows > 0 and book.skipped == []


async def test_a_broken_chain_yields_no_precedents(door, migrated_db):
    d, deps = door
    view, held = await _run(d, "Give Anil the same access as Rahul Mehta")
    await _decide(d, view, held["GitHub northbeam/payments-core (read)"], "teams", DANA_TEAMS, "approved")
    with psycopg.connect(migrated_db, autocommit=True) as c:
        c.execute("alter table audit disable trigger audit_no_update")
        c.execute("update audit set payload = jsonb_set(payload, '{decision}', '\"refused\"') "
                  "where event = 'approval.decided'")
    with pytest.raises(ChainBroken, match="seq"):
        await _book(deps)


async def test_a_decision_whose_action_row_was_edited_is_not_attributed(door, migrated_db):
    d, deps = door
    view, held = await _run(d, "Give Anil the same access as Rahul Mehta")
    row = held["GitHub northbeam/payments-core (read)"]
    await _decide(d, view, row, "teams", DANA_TEAMS, "approved")
    with psycopg.connect(migrated_db, autocommit=True) as c:   # relabel the action after the decision
        c.execute("update actions set target = jsonb_set(target, '{entitlement}', '\"aws-payments-prod-admin\"') "
                  "where run_id = %s and id = %s", (view.run_id, row.action_id))
    book = await _book(deps)
    assert book.get("POL-ACC-004", "aws-payments-prod-admin").approved == 0
    assert book.get("POL-ACC-004", "gh-payments-core-read").approved == 0
    assert len(book.skipped) == 1 and "params_hash" in book.skipped[0] and row.action_id in book.skipped[0]


# --- drafts: the curated page and Freshservice are never written ----------------------------------------------------

async def test_the_updated_precedent_page_is_a_draft_and_the_curated_page_is_untouched(door, tmp_path):
    d, deps = door
    view, held = await _run(d, "Priya starts Monday, give her everything she needs", actor="U0MARC120")
    await _decide(d, view, held["GitHub northbeam/perception-sdk (read)"], "teams", DANA_TEAMS, "approved")
    root = fresh_copy(tmp_path / "okf")
    bundle = load_bundle(root)
    curated = hashlib.sha256((root / PAGE).read_bytes()).hexdigest()
    draft = draft_precedent_page(bundle, PAGE, await _book(deps))
    assert draft.path == f"drafts/{PAGE}"
    assert "Approved 1, refused 0" in draft.text and str(view.run_id) in draft.text
    assert "No decisions have been recorded" not in draft.text
    assert draft.text.split("## Counts from the audit chain")[0] == (root / PAGE).read_text(
        encoding="utf-8").split("## Counts from the audit chain")[0]            # only the counts section changes
    assert draft.text.split("## Related")[1] == (root / PAGE).read_text(encoding="utf-8").split("## Related")[1]
    written = write_draft(root, draft)
    assert written == root / "drafts" / PAGE and written.read_text(encoding="utf-8") == draft.text
    assert hashlib.sha256((root / PAGE).read_bytes()).hexdigest() == curated
    assert PAGE in load_bundle(root).pages and len(load_bundle(root).pages) == len(bundle.pages)  # drafts not loaded


async def test_the_solutions_article_is_a_draft_with_escaped_text_and_citations(door, tmp_path):
    d, deps = door
    view, held = await _run(d, "Priya starts Monday, give her everything she needs", actor="U0MARC120")
    await _decide(d, view, held["GitHub northbeam/perception-sdk (read)"], "teams", DANA_TEAMS, "approved")
    book = await _book(deps)
    art = draft_solutions_article(load_bundle(), PAGE, book)
    assert art.status == "draft" and art.source_page == f"knowledge/{PAGE}"
    assert "approved 1 time" in art.body_html and "refused 0 times" in art.body_html
    assert art.cites == book.get("POL-ACC-004", "gh-perception-sdk-read").cites
    assert "contractor&#x27;s statement of work" in art.body_html          # page text is HTML-escaped
    assert "](" not in art.body_html and "`" not in art.body_html            # no Markdown syntax leaks into HTML
    assert "Access Control Standard §3" in art.body_html


def test_a_page_without_a_precedent_key_cannot_be_drafted():
    with pytest.raises(ValueError, match="precedent"):
        draft_precedent_page(load_bundle(), "runbooks/offboarding.md", _empty_book())


def _empty_book():
    from contextrail.knowledge.precedent import PrecedentBook
    return PrecedentBook(entries={}, chain_rows=0, skipped=[])
