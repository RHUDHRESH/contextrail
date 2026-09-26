"""Query the bundle by its links (checklist T177): `rules:` and `tags:` frontmatter, no vector search.

At this size a link is a better index than a similarity score: a page that lists POL-ACC-004 is about POL-ACC-004,
and saying so is explainable (CLAUDE.md §10, D-014). Compile uses these queries to attach curated evidence to a
case file; retrieval (T252) uses `terms_in` to boost chunks that share a rule or tag with the question.

Only curated pages are queried: `raw/` and `drafts/` are never loaded (okf.py).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from contextrail.knowledge.okf import Bundle, Page, Section
from contextrail.models import Evidence
from contextrail.policy.schema import Rule

_RULE_ID = re.compile(r"\bPOL-[A-Z]{3}-\d{3}\b", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")


def pages_for(bundle: Bundle, *, rules: Iterable[str] = (), tags: Iterable[str] = (),
              types: set[str] | None = None) -> list[Page]:
    """Curated pages linked to any of these rules or tags. A shared rule counts twice a shared tag; ties by path."""
    rules, tags = set(rules), set(tags)
    scored = []
    for page in bundle.concepts():
        if types is not None and page.meta.type not in types:
            continue
        score = 2 * len(rules & set(page.meta.rules)) + len(tags & set(page.meta.tags))
        if score:
            scored.append((-score, page.path, page))
    return [p for *_, p in sorted(scored, key=lambda x: x[:2])]


@dataclass(frozen=True)
class Terms:
    rules: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


def _norm(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word   # "contractors" ~ "contractor"


def terms_in(bundle: Bundle, text: str) -> Terms:
    """The rule ids and bundle tags a piece of text names. Unknown ids and words that are not tags are ignored."""
    known_rules = {r for p in bundle.concepts() for r in p.meta.rules}
    words = {_norm(w) for w in _WORD.findall(text.lower())}
    rules = {m.upper() for m in _RULE_ID.findall(text)} & known_rules
    tags = {t for p in bundle.concepts() for t in p.meta.tags
            if all(_norm(w) in words for w in t.lower().split("-"))}
    return Terms(tuple(sorted(rules)), tuple(sorted(tags)))


def clause_section(bundle: Bundle, rule: Rule) -> tuple[Page, Section] | None:
    """The page and section a rule cites, only if the rule's clause text is verbatim under that heading."""
    page = bundle.pages.get(rule.source.okf.removeprefix("knowledge/"))
    if page is None or page.meta is None:
        return None
    section = page.section(rule.source.clause)
    if section is None or rule.clause_text not in section.text:
        return None
    return page, section


def rule_evidence(bundle: Bundle, rule: Rule, now: datetime) -> Evidence | None:
    """The rule's clause as curated evidence, dated by its page (so Compile can judge freshness). None when the
    page does not carry the clause: the caller must treat that as missing policy, never as an assumption."""
    found = clause_section(bundle, rule)
    if found is None:
        return None
    page, _ = found
    return Evidence(id=f"EV-{rule.id}", kind="policy", source="okf", uri=f"{rule.source.okf}#{rule.source.clause}",
                    excerpt=rule.clause_text, retrieved_at=now, last_verified=page.meta.last_verified,
                    trust="curated")


def _summary(page: Page) -> str:
    first = next((s.text for s in page.sections if s.level == 2 and s.text), "")
    return "\n\n".join(x for x in (page.meta.description, first) if x)


def precedent_evidence(bundle: Bundle, rule_ids: Iterable[str], now: datetime) -> list[Evidence]:
    """Precedent pages linked to these rules, as curated evidence. Counts on approval cards come from the audit
    chain (T180), not from these pages."""
    return [Evidence(id=f"EV-okf-{p.path}", kind="precedent", source="okf", uri=f"knowledge/{p.path}",
                     excerpt=_summary(p), retrieved_at=now, last_verified=p.meta.last_verified, trust="curated")
            for p in pages_for(bundle, rules=rule_ids, types={"Precedent"})]
