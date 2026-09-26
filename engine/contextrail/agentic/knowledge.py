"""Knowledge search: the seam every door, MCP tool and the ask loop use to retrieve curated knowledge (§10, §25).

`KnowledgeSearch` is the contract. The OKF/RAG index (section L, T252) implements it over Postgres full-text search.
Until that is wired in, `RuleIndex` answers from the written policy the engine already loads: each rule's title and
clause text, verbatim, with its OKF source clause. It is small and lexical on purpose, and it never guesses: a query
that matches nothing returns nothing.
"""

from __future__ import annotations

import re
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from contextrail.policy.schema import Rule

HitKind = Literal["policy", "concept", "precedent", "receipt", "message", "document"]
_RULE_ID = re.compile(r"\bPOL-[A-Z]{3}-\d{3}\b")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "for", "can", "get", "does", "what", "who", "how", "why", "are", "is", "a", "an", "of",
         "to", "in", "on", "be", "say", "says", "with", "any", "our", "their", "they", "them", "this", "that"}


class KnowledgeHit(BaseModel):
    """One retrieved piece of knowledge, citable by `id`. `trust` says whether it may be relied on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    kind: HitKind
    title: str
    excerpt: str
    uri: str
    rule_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    trust: Literal["record", "curated", "untrusted"]
    score: float = Field(ge=0, le=1)


@runtime_checkable
class KnowledgeSearch(Protocol):
    name: str  # which index answered, reported to the caller

    async def search(self, query: str, *, tags: list[str] | None = None, limit: int = 5) -> list[KnowledgeHit]: ...


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP}


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


class RuleIndex:
    """Lexical search over the loaded policy rules (curated clauses). The fallback until the OKF index lands."""

    name = "policy-rules"

    def __init__(self, rules: list[Rule]) -> None:
        self._rules = list(rules)
        self._docs = {r.id: f"{r.id} {r.title} {r.clause_text} {r.source.okf}".lower() for r in rules}
        self._stems = {rid: {_stem(w) for w in _terms(doc)} for rid, doc in self._docs.items()}

    def _hit(self, rule: Rule, score: float) -> KnowledgeHit:
        return KnowledgeHit(id=rule.id, kind="policy", title=rule.title, excerpt=rule.clause_text,
                            uri=f"{rule.source.okf}#{rule.source.clause}", rule_ids=[rule.id], trust="curated",
                            score=round(score, 3))

    def _tagged(self, rule: Rule, tags: list[str]) -> bool:
        return all(_stem(t.lower()) in self._docs[rule.id] for t in tags)

    async def search(self, query: str, *, tags: list[str] | None = None, limit: int = 5) -> list[KnowledgeHit]:
        named = set(_RULE_ID.findall(query.upper()))
        wanted = {_stem(w) for w in _terms(query)}
        scored = []
        for rule in self._rules:
            if tags and not self._tagged(rule, tags):
                continue
            if rule.id in named:
                score = 1.0
            elif wanted:
                score = len(wanted & self._stems[rule.id]) / len(wanted)
            else:
                score = 0.0
            if score > 0:
                scored.append((score, rule))
        scored.sort(key=lambda s: (-s[0], s[1].id))
        return [self._hit(rule, score) for score, rule in scored[:limit]]
