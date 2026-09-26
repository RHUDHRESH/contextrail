"""Query by rules and tags (checklist T177): curated pages become case-file evidence, and missing policy text blocks.

CLAUDE.md §8 Compile: "load OKF concepts, mark stale ... Missing policy -> blocker, not assumption".
"""

import re
import shutil
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from contextrail import repo
from contextrail.connectors.fixture import FixtureEntitlements, FixtureHRIS
from contextrail.connectors.state import FixtureState
from contextrail.knowledge.okf import load_bundle
from contextrail.knowledge.query import pages_for, precedent_evidence, rule_evidence, terms_in
from contextrail.policy.loader import load_rules
from contextrail.rail.compile import gather_inputs

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
BUNDLE = load_bundle()
RULES = {r.id: r for r in load_rules()}


def fresh_copy(tmp_path: Path, *, drop_clause: str | None = None) -> Path:
    """The shipped bundle, re-verified today (so no test depends on the calendar), optionally with one clause cut."""
    root = tmp_path / "knowledge"
    shutil.copytree(BUNDLE.root, root)
    for f in root.rglob("*.md"):
        text = re.sub(r"^last_verified: .*$", f"last_verified: {datetime.now(UTC).date().isoformat()}",
                      f.read_text(encoding="utf-8"), flags=re.MULTILINE)
        if drop_clause:
            text = text.replace(drop_clause, "(clause removed)")
        f.write_text(text, encoding="utf-8")
    return root


# --- pages by links ---------------------------------------------------------------------------------------------

def test_pages_for_a_rule_are_the_pages_that_list_it():
    assert [p.path for p in pages_for(BUNDLE, rules=["POL-CTR-001"])] == ["policies/contractor-onboarding.md"]
    paths = [p.path for p in pages_for(BUNDLE, rules=["POL-ACC-004"])]
    assert set(paths) == {"policies/access-control-standard.md", "policies/contractor-onboarding.md",
                          "precedents/github-readonly-contractors.md", "roles/payments-engineer.md",
                          "systems/github.md"}


def test_pages_for_rank_rule_links_above_tag_links_and_filter_by_type():
    ranked = [p.path for p in pages_for(BUNDLE, rules=["POL-CTR-001"], tags=["contractors"])]
    assert ranked[0] == "policies/contractor-onboarding.md"            # rule + tag
    assert set(ranked[1:]) == {"precedents/github-readonly-contractors.md", "systems/github.md"}  # tag only
    # one rule link outranks one tag link: the offboarding runbook (POL-OFF-001) before the production-tagged pages
    assert pages_for(BUNDLE, rules=["POL-OFF-001"], tags=["production"])[0].path == "runbooks/offboarding.md"
    only = pages_for(BUNDLE, rules=["POL-ACC-004"], types={"Precedent"})
    assert [p.path for p in only] == ["precedents/github-readonly-contractors.md"]


def test_nothing_linked_means_nothing_returned():
    assert pages_for(BUNDLE, rules=["POL-XXX-999"], tags=["cafeteria"]) == []
    assert pages_for(BUNDLE) == []


def test_terms_in_a_question_are_the_known_rules_and_tags_it_names():
    t = terms_in(BUNDLE, "Can contractors get production credentials? What does pol-ctr-001 say?")
    assert t.rules == ("POL-CTR-001",) and {"contractors", "production"} <= set(t.tags)
    assert terms_in(BUNDLE, "What is the least privilege rule?").tags == ("least-privilege",)
    assert terms_in(BUNDLE, "POL-XXX-999 and the cafeteria menu") == terms_in(BUNDLE, "")


# --- evidence ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("rule", list(RULES.values()), ids=lambda r: r.id)
def test_rule_evidence_is_the_curated_clause_dated_by_its_page(rule):
    ev = rule_evidence(BUNDLE, rule, NOW)
    page = BUNDLE.pages[rule.source.okf.removeprefix("knowledge/")]
    assert (ev.id, ev.kind, ev.trust, ev.source) == (f"EV-{rule.id}", "policy", "curated", "okf")
    assert ev.excerpt == rule.clause_text and ev.uri == f"{rule.source.okf}#{rule.source.clause}"
    assert ev.last_verified == page.meta.last_verified


def test_no_rule_evidence_when_the_page_lacks_the_clause_text(tmp_path):
    rule = RULES["POL-ACC-005"]
    assert rule_evidence(load_bundle(fresh_copy(tmp_path, drop_clause=rule.clause_text)), rule, NOW) is None


def test_precedent_evidence_comes_from_precedent_pages_linked_to_the_rules():
    evs = precedent_evidence(BUNDLE, ["POL-ACC-004", "POL-CTR-001"], NOW)
    assert [(e.id, e.kind, e.trust) for e in evs] == [
        ("EV-okf-precedents/github-readonly-contractors.md", "precedent", "curated")]
    assert evs[0].last_verified == date(2026, 9, 20) and "Security on-call" in evs[0].excerpt
    assert precedent_evidence(BUNDLE, ["POL-CTR-001"], NOW) == []


# --- Compile ----------------------------------------------------------------------------------------------------

@pytest.fixture
def conns(tmp_path):
    out = {}
    for name, cls in (("hris", FixtureHRIS), ("entitlements", FixtureEntitlements)):
        s = FixtureState(name, directory=tmp_path)
        s.reset()
        out[name] = cls(s)
    return out


async def test_compile_with_knowledge_attaches_dated_clauses_and_precedents(conns):
    anil = await conns["hris"].read({"source_id": "E-1042"})
    rahul = await conns["hris"].read({"source_id": "E-0007"})
    inputs = await gather_inputs(anil, rahul, entitlements=conns["entitlements"], rules=list(RULES.values()),
                                 now=NOW, knowledge=BUNDLE)
    policy = [e for e in inputs.evidence if e.kind == "policy"]
    assert len(policy) == len(RULES) and all(e.last_verified and e.source == "okf" for e in policy)
    assert [e.kind for e in inputs.evidence].count("precedent") == 1 and inputs.blockers == []


async def test_compile_turns_a_missing_clause_into_a_blocker_and_keeps_the_rule_text(conns, tmp_path):
    rule = RULES["POL-ACC-005"]
    broken = load_bundle(fresh_copy(tmp_path, drop_clause=rule.clause_text))
    anil = await conns["hris"].read({"source_id": "E-1042"})
    inputs = await gather_inputs(anil, None, entitlements=conns["entitlements"], rules=list(RULES.values()),
                                 now=NOW, knowledge=broken)
    ev = next(e for e in inputs.evidence if e.id == "EV-POL-ACC-005")
    assert (ev.source, ev.excerpt, ev.last_verified) == ("policy", rule.clause_text, None)  # the rule file still says it
    assert len(inputs.blockers) == 1
    assert "POL-ACC-005" in inputs.blockers[0] and "knowledge/policies/access-control-standard.md" in inputs.blockers[0]


async def test_compile_without_knowledge_is_unchanged(conns):
    anil = await conns["hris"].read({"source_id": "E-1042"})
    inputs = await gather_inputs(anil, None, entitlements=conns["entitlements"], rules=list(RULES.values()), now=NOW)
    policy = [e for e in inputs.evidence if e.kind == "policy"]
    assert all(e.source == "policy" and e.last_verified is None for e in policy) and inputs.blockers == []


async def test_a_run_with_missing_policy_text_blocks_instead_of_acting(rail, tmp_path):
    runner, deps = rail
    deps.knowledge = load_bundle(fresh_copy(tmp_path, drop_clause=RULES["POL-ACC-001"].clause_text))
    rid = await runner.start(source="slack", request_text="Give Anil the same access as Rahul Mehta",
                             requested_by="p-anil")
    await runner.run(rid)
    async with deps.db.connection() as c:
        run = await repo.get_run(c, rid)
        states = {a["state"] for a in await repo.list_actions(c, rid)}
    assert any("POL-ACC-001" in b for b in run["capsule"]["open_blockers"])
    assert "verified" not in states                                  # nothing executed while policy text is missing


async def test_a_run_with_the_curated_bundle_carries_it_as_evidence(rail, tmp_path):
    runner, deps = rail
    deps.knowledge = load_bundle(fresh_copy(tmp_path))
    rid = await runner.start(source="slack", request_text="Give Anil the same access as Rahul Mehta",
                             requested_by="p-anil")
    await runner.run(rid)
    async with deps.db.connection() as c:
        run = await repo.get_run(c, rid)
    kinds = {(e["kind"], e["source"]) for e in run["capsule"]["evidence"]}
    assert ("policy", "okf") in kinds and ("precedent", "okf") in kinds
    assert run["capsule"]["open_blockers"] == [] and run["status"] == "awaiting_approval"
