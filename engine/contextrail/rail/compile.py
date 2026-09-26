"""Compile (CLAUDE.md §8): Subject (+ peer) -> one case file, sealed.

Code fetches, in parallel, everything the case needs: the people's records, what they hold now, the entitlement
catalogue, the role catalogue entry, the written policy clauses, the curated OKF pages linked to the case, and (as
untrusted evidence) retrieved messages. Nothing here decides anything; Govern does, from records only.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Protocol

from contextrail.fixtures import load
from contextrail.knowledge import query as knowledge_query
from contextrail.knowledge.okf import Bundle
from contextrail.models import Evidence, Subject
from contextrail.policy.matchers import applies_to
from contextrail.policy.schema import Rule


@dataclass
class CompileInputs:
    """What Govern and Plan need, fetched once per run (reads are cached for the run, CLAUDE.md §12)."""

    subject_holdings: list[str]
    peer_holdings: list[str]
    catalog: dict[str, dict]
    role: dict
    evidence: list[Evidence] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)   # missing policy text: a blocker, not an assumption (§8)


def _record_evidence(record: dict, now: datetime) -> Evidence:
    last = record.get("last_verified")
    return Evidence(
        id=f"EV-hris-{record['source_id']}", kind="record", source="hris", uri=f"hris://people/{record['source_id']}",
        excerpt=(f"{record['display_name']}: {record['employment_type']}, role {record.get('role')}, "
                 f"team {record.get('team')}, seniority {record.get('seniority')}"),
        retrieved_at=now, last_verified=date.fromisoformat(last) if last else now.date(), trust="record")


def _policy_evidence(rule: Rule, now: datetime) -> Evidence:
    return Evidence(
        id=f"EV-{rule.id}", kind="policy", source="policy", uri=f"{rule.source.okf}#{rule.source.clause}",
        excerpt=rule.clause_text, retrieved_at=now, trust="curated")


def _missing_policy(rule: Rule) -> str:
    return (f"Policy text missing: {rule.id} cites {rule.source.okf} {rule.source.clause}, but that page does not "
            f"carry the rule's clause text. Restore the page before acting.")


def role_entry(role: str | None) -> dict:
    """The role catalogue entry Govern uses; Policy Studio rebuilds the same value for a stored run."""
    return load("roles")["roles"].get(role or "", {"baseline": []})


def _knowledge_evidence(knowledge: Bundle, rules: list[Rule], now: datetime) -> tuple[list[Evidence], list[str]]:
    """T177: each rule's clause from its curated page (dated, so freshness can be judged) and the precedent pages
    linked to the rules. A clause missing from its page keeps the rule-file text as evidence and opens a blocker."""
    evidence, blockers = [], []
    for r in rules:
        ev = knowledge_query.rule_evidence(knowledge, r, now)
        if ev is None:
            ev = _policy_evidence(r, now)
            blockers.append(_missing_policy(r))
        evidence.append(ev)
    return evidence + knowledge_query.precedent_evidence(knowledge, [r.id for r in rules], now), blockers


async def gather_inputs(subject_record: dict, peer_record: dict | None, *, entitlements, rules: list[Rule],
                        now: datetime | None = None, knowledge: Bundle | None = None) -> CompileInputs:
    """T089: fetch records, holdings, catalogue, role and policy text concurrently. With the OKF bundle (T177), the
    policy text comes from the curated pages the rules cite."""
    now = now or datetime.now(UTC)

    async def holdings(record: dict | None) -> list[str]:
        if not record:
            return []
        return (await entitlements.read({"subject_id": record["source_id"]}))["holdings"]

    async def subject_role() -> dict:
        return role_entry(subject_record.get("role"))

    subject_h, peer_h, catalog, role = await asyncio.gather(
        holdings(subject_record), holdings(peer_record), entitlements.read({}), subject_role())
    evidence = [_record_evidence(subject_record, now)]
    if peer_record:
        evidence.append(_record_evidence(peer_record, now))
    blockers: list[str] = []
    if knowledge is None:
        evidence += [_policy_evidence(r, now) for r in rules]
    else:
        policy, blockers = _knowledge_evidence(knowledge, rules, now)
        evidence += policy
    return CompileInputs(subject_holdings=subject_h, peer_holdings=peer_h, catalog=catalog["catalog"], role=role,
                         evidence=evidence, blockers=blockers)


def subject_constraints(subject: Subject) -> list[str]:
    """Constraints that follow directly from the record (SOW text extraction with citations is T091, P1)."""
    out = []
    if subject.employment_type in ("contractor", "vendor"):
        out.append("No production credentials, production database access or customer PII exports (POL-CTR-001).")
        if subject.sow_repos:
            out.append(f"Repository access read-only and limited to the SOW: {', '.join(subject.sow_repos)}.")
        if subject.end_date:
            out.append(f"All access expires on the SOW end date {subject.end_date.isoformat()}.")
    return out


# --- OKF concepts: curated knowledge, linked by rules and tags (T090) -----------------------------------------

class KnowledgeSource(Protocol):
    """What Compile needs from the OKF bundle (knowledge/okf.py `Bundle`, section L, satisfies it).

    `concepts()` returns the curated pages only (never raw/ or drafts/). Each page has a bundle-relative `path` and a
    frontmatter `meta` with `type`, `title`, `description`, `tags`, `rules` and `last_verified`."""

    def concepts(self) -> list: ...


@dataclass
class ConceptLoad:
    configured: bool
    evidence: list[Evidence] = field(default_factory=list)
    missing_sources: list[str] = field(default_factory=list)  # rule source pages the bundle does not have


_EMPLOYMENT_TAG = {"contractor": "contractors", "vendor": "vendors", "employee": "employees",
                   "customer": "customers"}
_INTENT_TAGS = {"onboarding": ["onboarding"], "refund.outage": ["refunds", "credits"]}


def _bundle_path(okf: str) -> str:
    return okf.removeprefix("knowledge/")


def load_concepts(source: KnowledgeSource | None, subject: Subject, intent: str, rules: list[Rule],
                  now: datetime | None = None) -> ConceptLoad:
    """Pages linked to this case: by `rules:` (a rule that applies to this subject) or by `tags:` (the intent, the
    employment type, the role, the team). A Role page describes one role, so it is linked only by the subject's own
    role or team, never through rules it shares with every other role. Attached as policy/precedent evidence,
    trust=curated. Knowledge explains; the engine never reads it. A rule whose source page is missing is reported for
    the audit and the lint (T179): the verdict still quotes the rule's own clause text, so nothing is assumed."""
    if source is None:
        return ConceptLoad(configured=False)
    now = now or datetime.now(UTC)
    applying = [r for r in rules if applies_to(r, subject)]
    rule_ids = {r.id for r in applying}
    tags = {*_INTENT_TAGS.get(intent, []), _EMPLOYMENT_TAG[subject.employment_type],
            *(t for t in (subject.role, subject.team) if t)}
    pages = source.concepts()
    evidence = []
    for p in sorted(pages, key=lambda p: p.path):
        m = p.meta
        page_type = (m.type or "").lower()
        by_rule = page_type != "role" and bool(rule_ids & set(m.rules))
        if not (by_rule or tags & set(m.tags) or p.path == f"roles/{subject.role}.md"):
            continue
        evidence.append(Evidence(
            id=f"EV-okf-{p.path}", kind="precedent" if page_type == "precedent" else "policy",
            source="okf", uri=f"okf:{p.path}", excerpt=": ".join(x for x in (m.title or p.path, m.description) if x),
            retrieved_at=now, last_verified=m.last_verified, trust="curated"))
    have = {p.path for p in pages}
    missing = sorted({_bundle_path(r.source.okf) for r in applying} - have)
    return ConceptLoad(configured=True, evidence=evidence, missing_sources=missing)


# --- retrieved messages: evidence, never instructions (T093) ------------------------------------------------

def search_terms(subject: Subject | None, peer: Subject | None, intent: str) -> list[str]:
    terms = []
    for person in (subject, peer):
        if person:
            terms += [person.display_name.split()[0].lower(), person.display_name.lower()]
            if person.team:
                terms.append(person.team)
    terms += {"access.same_as_peer": ["same as", "access"], "onboarding": ["onboarding", "starts", "joins"],
              "refund.outage": ["outage", "credit"]}.get(intent, [])
    return list(dict.fromkeys(terms))


async def retrieve_messages(corpus, terms: list[str], now: datetime | None = None, limit: int = 5) -> list[Evidence]:
    """Retrieval surfaces relevant messages, including planted ones. All are kind=message, trust=untrusted (P6)."""
    now = now or datetime.now(UTC)
    out = []
    for m in await corpus.search(terms, limit=limit):
        posted = datetime.fromisoformat(m["posted_at"])  # Python 3.11+ parses the trailing 'Z'
        out.append(Evidence(
            id=f"EV-{m['id']}", kind="message", source="slack", uri=f"slack://{m['channel_id']}/{m['ts']}",
            excerpt=m["text"], retrieved_at=now, last_verified=posted.date(), trust="untrusted"))
    return out


def wrap_untrusted(ev: Evidence) -> str:
    """How untrusted text enters any prompt: fenced as data, with no way to close the fence from inside (§11)."""
    body = ev.excerpt.replace("<", "&lt;").replace(">", "&gt;")
    return f'<untrusted source="{ev.source}" uri="{ev.uri}" trust="{ev.trust}">\n{body}\n</untrusted>'


# --- freshness: stale evidence becomes a blocker, not an assumption (T092) -----------------------------------

FRESHNESS_DAYS = {"record": 90, "policy": 365, "precedent": 180, "document": 180, "message": 30}
_DECIDING_KINDS = {"record", "policy", "precedent"}  # what Govern relies on; untrusted text never decides


def mark_stale(evidence: list[Evidence], now: datetime | None = None) -> tuple[list[Evidence], list[str]]:
    """Flag evidence older than its freshness budget. Stale records/policies become open blockers; stale messages
    and documents are only flagged. Evidence without last_verified is not judged here: an unknown date is reported
    by the knowledge lint (T179), not silently treated as fresh or stale."""
    today = (now or datetime.now(UTC)).date()
    out, blockers = [], []
    for e in evidence:
        if e.last_verified is None:
            out.append(e)
            continue
        age = (today - e.last_verified).days
        stale = age > FRESHNESS_DAYS[e.kind]
        out.append(e.model_copy(update={"stale": stale}) if stale != e.stale else e)
        if stale and e.kind in _DECIDING_KINDS:
            blockers.append(f"Stale {e.kind}: {e.uri} last verified {e.last_verified.isoformat()} "
                            f"({age} days; budget {FRESHNESS_DAYS[e.kind]}). Re-verify before acting.")
    return out, blockers
