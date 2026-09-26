"""The knowledge lint (checklist T179, CLAUDE.md §18 test_knowledge_lint.py, P1-1).

Planted contradiction flagged, both claims preserved with their dates; stale pages, broken links, orphans and rules
without source clauses reported; nothing is ever overwritten.
"""

import hashlib
from datetime import date
from pathlib import Path

from okf_util import edit, fresh_copy

from contextrail.knowledge.lint import lint, main
from contextrail.knowledge.okf import load_bundle
from contextrail.policy.loader import load_rules

TODAY = date(2026, 9, 26)
RULES = load_rules()
WRITE_ACCESS = ("policies/contractor-onboarding.md", "allowed after Security review")


def _snapshot(root: Path) -> dict[str, str]:
    return {f.relative_to(root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file()}


def _lint(root: Path, today: date = TODAY):
    return lint(load_bundle(root), RULES, today=today)


def _checks(report) -> list[str]:
    return sorted(f.check for f in report.findings)


# --- the shipped bundle -----------------------------------------------------------------------------------------

def test_the_shipped_bundle_reports_only_its_recorded_contradiction():
    report = lint(load_bundle(), RULES, today=TODAY)
    assert _checks(report) == ["contradiction"], report.render()
    f = report.findings[0]
    assert f.key == "contractor.repository-write-access"
    assert {(c.page, c.value, c.last_verified) for c in f.claims} == {
        (*WRITE_ACCESS, date(2026, 9, 20)),
        ("policies/access-control-standard.md", "never", date(2026, 9, 20))}


# --- contradictions -----------------------------------------------------------------------------------------------

def test_a_planted_contradiction_is_flagged_with_both_claims_and_dates_and_nothing_is_rewritten(tmp_path):
    root = fresh_copy(tmp_path, verified="2026-09-18")
    # plant it: an older GitHub page still says break-glass access lasts a day
    edit(root, "systems/github.md", "last_verified: 2026-09-18\n",
         "last_verified: 2026-03-02\nclaims:\n  emergency-access.max-duration: 24 hours\n")
    before = _snapshot(root)
    report = _lint(root)
    assert _snapshot(root) == before                                       # report only, never overwrite
    planted = next(f for f in report.findings if f.key == "emergency-access.max-duration")
    assert planted.check == "contradiction"
    assert [(c.page, c.value, c.last_verified) for c in planted.claims] == [
        ("runbooks/emergency-access.md", "4 hours", date(2026, 9, 18)),
        ("systems/github.md", "24 hours", date(2026, 3, 2))]
    assert "4 hours" in planted.detail and "24 hours" in planted.detail and "2026-03-02" in planted.detail


def test_agreeing_claims_are_not_a_contradiction(tmp_path):
    root = fresh_copy(tmp_path)
    edit(root, "policies/contractor-onboarding.md", "allowed after Security review", "Never")   # case differs only
    assert "contradiction" not in _checks(_lint(root))


# --- staleness ----------------------------------------------------------------------------------------------------

def test_stale_and_undated_pages_are_reported_against_their_budget(tmp_path):
    root = fresh_copy(tmp_path, verified="2026-09-01")
    edit(root, "precedents/github-readonly-contractors.md", "last_verified: 2026-09-01", "last_verified: 2026-03-01")
    edit(root, "runbooks/offboarding.md", "last_verified: 2026-09-01", "last_verified: 2026-03-01")
    edit(root, "systems/freshservice.md", "last_verified: 2026-09-01\n", "")
    stale = {f.page: f.detail for f in _lint(root).findings if f.check == "stale"}
    assert set(stale) == {"precedents/github-readonly-contractors.md", "systems/freshservice.md"}
    assert "209 days" in stale["precedents/github-readonly-contractors.md"] and "180" in stale[
        "precedents/github-readonly-contractors.md"]                       # precedent budget 180 days
    assert "no last_verified" in stale["systems/freshservice.md"]
    # the runbook is 209 days old too, but within the 365-day budget for non-precedent pages


# --- links ----------------------------------------------------------------------------------------------------------

def test_broken_links_and_orphans_are_reported(tmp_path):
    root = fresh_copy(tmp_path)
    edit(root, "systems/github.md", "## Verifying a grant", "See [the SSO page](sso.md).\n\n## Verifying a grant")
    (root / "systems" / "okta.md").write_text("---\ntype: System\nlast_verified: 2026-09-26\n---\n# Okta\n",
                                              encoding="utf-8")
    found = {(f.check, f.page) for f in _lint(root).findings}
    assert ("broken_link", "systems/github.md") in found and ("orphan", "systems/okta.md") in found
    detail = next(f.detail for f in _lint(root).findings if f.check == "broken_link")
    assert "sso.md" in detail and "systems/sso.md" in detail


def test_links_into_drafts_and_raw_count_only_if_the_file_exists(tmp_path):
    root = fresh_copy(tmp_path)
    (root / "raw").mkdir()
    (root / "raw" / "article-1.md").write_text("source copy\n", encoding="utf-8")
    edit(root, "systems/github.md", "## Verifying a grant",
         "Source: [article](../raw/article-1.md), [draft](../drafts/github.md).\n\n## Verifying a grant")
    broken = [f.detail for f in _lint(root).findings if f.check == "broken_link"]
    assert len(broken) == 1 and "drafts/github.md" in broken[0]


# --- rules and their source clauses -------------------------------------------------------------------------------

def test_a_rule_whose_clause_text_left_its_page_is_reported(tmp_path):
    rule = next(r for r in RULES if r.id == "POL-ACC-005")
    root = fresh_copy(tmp_path, drop_clause=rule.clause_text)
    f = next(f for f in _lint(root).findings if f.check == "rule_source")
    assert f.rule == "POL-ACC-005" and f.page == "policies/access-control-standard.md" and "§6" in f.detail


def test_missing_heading_unlisted_rule_and_unknown_rule_ids_are_reported(tmp_path):
    root = fresh_copy(tmp_path)
    edit(root, "runbooks/offboarding.md", "## Transfers", "## Team moves")
    edit(root, "policies/contractor-onboarding.md", "rules: [POL-CTR-001, POL-ACC-004]", "rules: [POL-ACC-004, POL-ZZZ-999]")
    rule_findings = {(f.rule, f.page) for f in _lint(root).findings if f.check == "rule_source"}
    assert rule_findings == {("POL-OFF-001", "runbooks/offboarding.md"),        # heading gone
                             ("POL-CTR-001", "policies/contractor-onboarding.md"),  # not listed by its page
                             ("POL-ZZZ-999", "policies/contractor-onboarding.md")}  # no such rule


def test_a_page_the_loader_rejected_is_reported(tmp_path):
    root = fresh_copy(tmp_path)
    edit(root, "roles/payments-engineer.md", "type: Role\n", "")
    f = next(f for f in _lint(root).findings if f.check == "invalid_page")
    assert f.page == "roles/payments-engineer.md" and "type" in f.detail


# --- the command line -----------------------------------------------------------------------------------------------

def test_cli_prints_the_report_and_exits_nonzero_only_when_something_is_found(tmp_path, capsys):
    root = fresh_copy(tmp_path)
    before = _snapshot(root)
    assert main(["lint", str(root)]) == 1
    out = capsys.readouterr().out
    assert "contradiction" in out and "contractor.repository-write-access" in out and WRITE_ACCESS[1] in out
    assert _snapshot(root) == before
    edit(root, "policies/contractor-onboarding.md", "allowed after Security review", "never")
    assert main(["lint", str(root)]) == 0
    assert "no findings" in capsys.readouterr().out
