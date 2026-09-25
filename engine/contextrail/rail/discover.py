"""Discover (CLAUDE.md §8): request -> intent + mentions -> Subject (+ peer), by exact lookup only.

AI reads, code resolves. The extractor (an LLM via the router, or the deterministic heuristic when no model is
available) only returns *mentions*: the words the person used ("Anil", "Rahul", "W-8841"). Turning a mention into
a person is code: an exact ID lookup, or an exact name lookup that returns every match. No match, or more than one
match, means `needs_input` with the candidates, never a guess (P1: relevance is not identity).
"""

from __future__ import annotations

import re
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from contextrail.connectors.base import ConnectorError
from contextrail.fixtures import subject_from_record
from contextrail.models import Subject

IntentName = Literal["access.same_as_peer", "onboarding", "access.request", "refund.outage", "query",
                     "approval_reply", "unknown"]
RequestKind = Literal["request", "query", "approval_reply"]


class Intent(BaseModel):
    """What the extractor may return. Mentions are raw text; nothing here is a resolved identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: IntentName
    kind: RequestKind
    subject_mention: str | None = None
    peer_mention: str | None = None
    dates: list[str] = []
    extractor: str  # "heuristic" | "llm:<tier>" | "replay": shown to users and recorded in the audit


class IntentExtractor(Protocol):
    name: str

    async def extract(self, text: str) -> Intent: ...


# --- deterministic fallback -------------------------------------------------------------------------------

_ID = r"[EWV]-\d{4}"
_NAME = r"[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)?"
# Keywords are case-insensitive via scoped (?i:...) groups; names stay case-sensitive ("Anil", never "Anil the").
_SAME_AS = re.compile(
    rf"\b(?i:give|grant|set up|provision)\s+(?P<subject>{_ID}|{_NAME})\s+(?i:(?:the\s+)?same\s+access\s+as)\s+"
    rf"(?P<peer>{_ID}|{_NAME})")
_ONBOARD = re.compile(rf"(?P<subject>{_ID}|{_NAME})\s+(?:starts|joins|is joining|begins|is starting)\b")
_ONBOARD_WORDS = re.compile(r"\b(onboard|new (?:hire|starter|joiner)|everything (?:she|he|they) needs?|"
                            r"new\b.{0,40}\b(?:starting|joining|starts|joins))\b", re.IGNORECASE)
_REFUND = re.compile(r"\b(service credits?|refunds?|outage)\b", re.IGNORECASE)
_APPROVAL = re.compile(r"^\s*(approve[ds]?|refuse[ds]?|reject(?:ed)?|yes|no)\b", re.IGNORECASE)
_QUERY = re.compile(r"^\s*(what|why|status|how|when|where|who|is|has|did|can)\b|\?\s*$", re.IGNORECASE)
_DAY = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow|next week|"
                  r"\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)
_STOP = {"The", "Give", "Grant", "Please", "Our", "New", "Hi", "Hello", "Can", "Could"}


def _clean(name: str | None) -> str | None:
    if not name:
        return None
    words = [w for w in name.split() if w not in _STOP]
    return " ".join(words) or None


class HeuristicExtractor:
    """Deterministic, offline intent parser, used when no model tier is available. Labelled 'heuristic' everywhere."""

    name = "heuristic"

    async def extract(self, text: str) -> Intent:
        dates = [m.group(0) for m in _DAY.finditer(text)]
        if _APPROVAL.match(text):
            return Intent(intent="approval_reply", kind="approval_reply", dates=dates, extractor=self.name)
        if m := _SAME_AS.search(text):
            return Intent(intent="access.same_as_peer", kind="request", subject_mention=_clean(m["subject"]),
                          peer_mention=_clean(m["peer"]), dates=dates, extractor=self.name)
        if (m := _ONBOARD.search(text)) or _ONBOARD_WORDS.search(text):
            return Intent(intent="onboarding", kind="request", subject_mention=_clean(m["subject"]) if m else None,
                          dates=dates, extractor=self.name)
        if _REFUND.search(text):
            return Intent(intent="refund.outage", kind="request", dates=dates, extractor=self.name)
        if _QUERY.search(text):
            ids = re.findall(_ID, text)
            return Intent(intent="query", kind="query", subject_mention=ids[0] if ids else None, dates=dates,
                          extractor=self.name)
        return Intent(intent="unknown", kind="request", dates=dates, extractor=self.name)


# --- resolution: mentions -> people, by exact lookup only (T086) ---------------------------------------------

_ID_RE = re.compile(rf"^{_ID}$")


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    display_name: str
    team: str | None = None
    role: str | None = None
    employment_type: str


def _candidate(record: dict) -> Candidate:
    return Candidate(**{k: record.get(k) for k in Candidate.model_fields})


async def lookup(hris, mention: str) -> list[dict]:
    """Exact lookup. An ID reads that one record; a name returns every exact full- or first-name match."""
    mention = mention.strip()
    if _ID_RE.match(mention):
        try:
            return [await hris.read({"source_id": mention})]
        except ConnectorError:  # "no such record" is zero matches; an outage (anything else) must propagate
            return []
    return await hris.find_by_name(mention)


# --- ambiguity -> needs_input (T087) ------------------------------------------------------------------------

NeedReason = Literal["no_mention", "no_match", "ambiguous", "same_person", "unclear_request"]
_NEEDS_SUBJECT = {"access.same_as_peer", "onboarding", "access.request"}


class NeedsInput(BaseModel):
    """A question for the requester's door: 'Two people named Rahul, which one?' (X1). Never answered by a guess."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Literal["subject", "peer", "request"]
    mention: str | None
    reason: NeedReason
    candidates: list[Candidate] = []


class Discovery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["resolved", "needs_input"]
    intent: Intent
    subject: Subject | None = None
    peer: Subject | None = None
    subject_record: dict | None = None   # full record (e.g. previous_team) for code, never for policy
    peer_record: dict | None = None
    needs: list[NeedsInput] = []


async def resolve_one(hris, mention: str | None, role: str, *, pinned_id: str | None = None
                      ) -> tuple[dict | None, NeedsInput | None]:
    """One person or one question. A pinned ID (from a candidate pick or a ticket requester) is still looked up."""
    if pinned_id:
        records = await lookup(hris, pinned_id)
        mention = pinned_id
    elif not mention:
        return None, NeedsInput(role=role, mention=None, reason="no_mention")
    else:
        records = await lookup(hris, mention)
    if len(records) == 1:
        return records[0], None
    reason = "no_match" if not records else "ambiguous"
    return None, NeedsInput(role=role, mention=mention, reason=reason, candidates=[_candidate(r) for r in records])


async def discover(text: str, extractor: IntentExtractor, hris, *, subject_id: str | None = None,
                   peer_id: str | None = None) -> Discovery:
    intent = await extractor.extract(text)
    needs: list[NeedsInput] = []
    if intent.kind == "request" and intent.intent == "unknown":
        # A request nobody can classify never proceeds: ask what is wanted (and for whom) instead.
        needs.append(NeedsInput(role="request", mention=None, reason="unclear_request"))
    subject_record = None
    if intent.intent in _NEEDS_SUBJECT or subject_id or intent.subject_mention:
        subject_record, need = await resolve_one(hris, intent.subject_mention, "subject", pinned_id=subject_id)
        if need and (intent.intent in _NEEDS_SUBJECT or intent.subject_mention):
            needs.append(need)
    return Discovery(
        status="needs_input" if needs else "resolved",
        intent=intent,
        subject=subject_from_record(subject_record) if subject_record else None,
        subject_record=subject_record,
        needs=needs,
    )
