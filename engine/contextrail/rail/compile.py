"""Compile (CLAUDE.md §8): Subject (+ peer) -> one case file, sealed.

Code fetches, in parallel, everything the case needs: the people's records, what they hold now, the entitlement
catalogue, the role catalogue entry, the written policy clauses, and (as untrusted evidence) retrieved messages.
Nothing here decides anything; Govern does, from records only.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from contextrail.fixtures import load
from contextrail.models import Evidence, Subject
from contextrail.policy.schema import Rule


@dataclass
class CompileInputs:
    """What Govern and Plan need, fetched once per run (reads are cached for the run, CLAUDE.md §12)."""

    subject_holdings: list[str]
    peer_holdings: list[str]
    catalog: dict[str, dict]
    role: dict
    evidence: list[Evidence] = field(default_factory=list)


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


async def gather_inputs(subject_record: dict, peer_record: dict | None, *, entitlements, rules: list[Rule],
                        now: datetime | None = None) -> CompileInputs:
    """T089: fetch records, holdings, catalogue, role and policy text concurrently."""
    now = now or datetime.now(UTC)

    async def holdings(record: dict | None) -> list[str]:
        if not record:
            return []
        return (await entitlements.read({"subject_id": record["source_id"]}))["holdings"]

    async def role_entry() -> dict:
        return load("roles")["roles"].get(subject_record.get("role") or "", {"baseline": []})

    subject_h, peer_h, catalog, role = await asyncio.gather(
        holdings(subject_record), holdings(peer_record), entitlements.read({}), role_entry())
    evidence = [_record_evidence(subject_record, now)]
    if peer_record:
        evidence.append(_record_evidence(peer_record, now))
    evidence += [_policy_evidence(r, now) for r in rules]
    return CompileInputs(subject_holdings=subject_h, peer_holdings=peer_h, catalog=catalog["catalog"], role=role,
                         evidence=evidence)


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
