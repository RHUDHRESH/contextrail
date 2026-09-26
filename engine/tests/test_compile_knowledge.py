"""Compile loads OKF concepts by their rules:/tags: links as curated evidence (checklist T090, CLAUDE.md §10).

The fake bundle has the shape of knowledge/okf.py's Bundle (section L): `concepts()` returns pages with a bundle-relative
`path` and a frontmatter `meta` (type, title, description, tags, rules, last_verified).
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import pytest

from contextrail import repo
from contextrail.fixtures import load, subject_from_record
from contextrail.policy.loader import load_rules
from contextrail.rail.compile import load_concepts, mark_stale

NOW = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Meta:
    type: str
    title: str
    description: str | None = None
    tags: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    last_verified: date | None = None


@dataclass(frozen=True)
class Page:
    path: str
    meta: Meta


class FakeBundle:
    def __init__(self, *pages: Page) -> None:
        self.pages = pages

    def concepts(self) -> list[Page]:
        return list(self.pages)


CONTRACTOR_POLICY = Page("policies/contractor-onboarding.md", Meta(
    "Policy", "Contractor Onboarding Policy", "What contractors and vendors may receive.",
    tags=["access", "contractors"], rules=["POL-CTR-001"], last_verified=date(2026, 9, 20)))
ACCESS_STANDARD = Page("policies/access-control-standard.md", Meta(
    "Policy", "Access Control Standard", "Least privilege, default deny.",
    tags=["access"], rules=["POL-ACC-001", "POL-ACC-003", "POL-ACC-004"], last_verified=date(2026, 9, 18)))
PAYMENTS_ROLE = Page("roles/payments-engineer.md", Meta(
    "Role", "Payments Engineer", "What a payments engineer holds by default.",
    tags=["role", "payments"], rules=["POL-ACC-001", "POL-ACC-004"], last_verified=date(2026, 9, 24)))
PRECEDENT = Page("precedents/github-readonly-contractors.md", Meta(
    "Precedent", "Read-only GitHub for contractors", "Approved 12 times, refused 0 times.",
    tags=["github", "contractors"], last_verified=date(2026, 9, 21)))
REFUNDS = Page("policies/refunds.md", Meta(
    "Policy", "Refunds", "Outage credits.", tags=["refunds"], rules=["POL-REF-001"], last_verified=date(2026, 9, 1)))
BUNDLE = FakeBundle(CONTRACTOR_POLICY, ACCESS_STANDARD, PAYMENTS_ROLE, PRECEDENT, REFUNDS)


def person(source_id: str):
    return subject_from_record(next(p for p in load("hris")["people"] if p["source_id"] == source_id))


def test_contractor_onboarding_loads_linked_policy_and_precedent_as_curated():
    got = load_concepts(BUNDLE, person("W-8841"), "onboarding", load_rules(), now=NOW)
    by_uri = {e.uri: e for e in got.evidence}
    assert set(by_uri) == {"okf:policies/contractor-onboarding.md", "okf:policies/access-control-standard.md",
                           "okf:precedents/github-readonly-contractors.md"}
    assert all((e.source, e.trust) == ("okf", "curated") for e in got.evidence)
    assert by_uri["okf:precedents/github-readonly-contractors.md"].kind == "precedent"
    policy = by_uri["okf:policies/contractor-onboarding.md"]
    assert policy.kind == "policy" and policy.last_verified == date(2026, 9, 20)
    assert policy.excerpt == "Contractor Onboarding Policy: What contractors and vendors may receive."
    assert policy.id == "EV-okf-policies/contractor-onboarding.md" and policy.retrieved_at == NOW


def test_employee_gets_role_page_by_team_tag_and_never_the_contractor_policy():
    got = load_concepts(BUNDLE, person("E-1042"), "access.same_as_peer", load_rules(), now=NOW)
    uris = {e.uri for e in got.evidence}
    assert "okf:roles/payments-engineer.md" in uris and "okf:policies/access-control-standard.md" in uris
    assert "okf:policies/contractor-onboarding.md" not in uris  # POL-CTR-001 does not apply to an employee
    assert "okf:policies/refunds.md" not in uris                # neither linked by rule nor by tag


def test_a_role_page_is_linked_by_the_subjects_role_or_team_never_by_shared_rules():
    # The payments role page lists rules that apply to everyone; a perception contractor still does not get it.
    priya = load_concepts(BUNDLE, person("W-8841"), "onboarding", load_rules(), now=NOW)
    assert "okf:roles/payments-engineer.md" not in {e.uri for e in priya.evidence}
    rahul_verma = load_concepts(BUNDLE, person("E-0415"), "access.same_as_peer", load_rules(), now=NOW)
    assert "okf:roles/payments-engineer.md" not in {e.uri for e in rahul_verma.evidence}


def test_rule_sources_missing_from_the_bundle_are_reported_not_invented():
    got = load_concepts(FakeBundle(PAYMENTS_ROLE), person("W-8841"), "onboarding", load_rules(), now=NOW)
    assert "policies/contractor-onboarding.md" in got.missing_sources
    assert "policies/access-control-standard.md" in got.missing_sources
    assert all(e.uri != "okf:policies/contractor-onboarding.md" for e in got.evidence)


def test_no_knowledge_source_loads_nothing_and_says_so():
    got = load_concepts(None, person("W-8841"), "onboarding", load_rules(), now=NOW)
    assert (got.configured, got.evidence, got.missing_sources) == (False, [], [])


def test_a_stale_policy_page_becomes_a_blocker():
    old = Page("policies/contractor-onboarding.md", Meta(
        "Policy", "Contractor Onboarding Policy", tags=["contractors"], rules=["POL-CTR-001"],
        last_verified=date(2025, 6, 1)))
    got = load_concepts(FakeBundle(old), person("W-8841"), "onboarding", load_rules(), now=NOW)
    _, blockers = mark_stale(got.evidence, now=NOW)
    assert len(blockers) == 1 and "okf:policies/contractor-onboarding.md" in blockers[0]


def test_real_okf_bundle_satisfies_the_knowledge_source_contract():
    """Runs once section L's loader is merged; skipped before that."""
    okf = pytest.importorskip("contextrail.knowledge.okf")
    got = load_concepts(okf.load_bundle(), person("W-8841"), "onboarding", load_rules(), now=NOW)
    assert "okf:systems/github.md" in {e.uri for e in got.evidence}
    assert all(e.trust == "curated" for e in got.evidence)


async def test_rail_attaches_concepts_to_the_case_file_and_verdicts_do_not_move(rail):
    runner, deps = rail
    deps.knowledge = BUNDLE
    rid = await runner.start(source="slack", request_text="Give Anil the same access as Rahul Mehta",
                             requested_by="p-anil")
    await runner.run(rid)
    async with deps.db.connection() as c:
        run = await repo.get_run(c, rid)
        actions = await repo.list_actions(c, rid)
        compile_audit = (await (await c.execute(
            "select payload from audit where run_id = %s and event = 'stage.compile'", (rid,))).fetchone())["payload"]
    okf = [e for e in run["capsule"]["evidence"] if e["source"] == "okf"]
    assert {e["uri"] for e in okf} >= {"okf:roles/payments-engineer.md", "okf:policies/access-control-standard.md"}
    assert all(e["trust"] == "curated" for e in okf)
    assert compile_audit["okf"]["configured"] is True and len(compile_audit["okf"]["loaded"]) == len(okf)
    grants = [a for a in actions if a["kind"] == "grant"]
    assert Counter(a["verdict"] for a in grants) == {"ALLOW": 13, "HOLD": 2, "REFUSE": 1}
