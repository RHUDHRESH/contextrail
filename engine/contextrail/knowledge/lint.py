"""Knowledge lint (checklist T179, CLAUDE.md §10): report what is wrong with the bundle; never fix it.

    python -m contextrail.knowledge.lint [BUNDLE_DIR]      exit 0 = no findings, 1 = findings printed

Checks:
- contradiction: two pages state the same `claims` key with different values. Both claims are reported with their
  pages and `last_verified` dates; which one is right is a person's call, not the lint's.
- stale: `last_verified` missing, or older than the page's budget (the Compile stage's FRESHNESS_DAYS: precedent
  pages 180 days, every other page 365).
- broken_link: a relative link to a file that does not exist.
- orphan: a page (or folder index) that nothing links to, so no reader can reach it.
- rule_source: a rule whose cited page, clause heading or verbatim clause text is missing, a rule its source page
  does not list, or a page listing a rule that does not exist.
- invalid_page: a page the loader could not accept (no frontmatter, no `type`, bad field).

The lint reads files and returns a report. It has no write path at all, so it cannot overwrite a claim.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from contextrail.knowledge.okf import Bundle, load_bundle
from contextrail.knowledge.query import clause_section
from contextrail.policy.schema import Rule
from contextrail.rail.compile import FRESHNESS_DAYS

Check = Literal["contradiction", "stale", "broken_link", "orphan", "rule_source", "invalid_page"]


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    page: str
    value: str
    last_verified: date | None


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check: Check
    page: str | None
    detail: str
    key: str | None = None          # the claim key, for contradictions
    rule: str | None = None         # the rule id, for rule_source
    claims: tuple[Claim, ...] = ()  # every side of a contradiction, as written


@dataclass(frozen=True)
class LintReport:
    findings: list[Finding]
    pages: int
    today: date

    @property
    def ok(self) -> bool:
        return not self.findings

    def render(self) -> str:
        head = f"Knowledge lint {self.today.isoformat()}: {self.pages} pages, "
        if self.ok:
            return head + "no findings."
        lines = [head + f"{len(self.findings)} finding(s). Nothing was changed; each needs a person."]
        for f in self.findings:
            lines.append(f"- [{f.check}] {f.page or '(bundle)'}: {f.detail}")
        return "\n".join(lines)


def _budget(page_type: str) -> int:
    return FRESHNESS_DAYS["precedent" if page_type == "Precedent" else "policy"]


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def _contradictions(bundle: Bundle) -> list[Finding]:
    by_key: dict[str, list[Claim]] = defaultdict(list)
    for p in bundle.concepts():
        for key, value in p.meta.claims.items():
            by_key[key].append(Claim(page=p.path, value=value, last_verified=p.meta.last_verified))
    out = []
    for key, claims in sorted(by_key.items()):
        if len({_norm(c.value) for c in claims}) < 2:
            continue
        claims = sorted(claims, key=lambda c: c.page)
        sides = "; ".join(f"{c.page} says {c.value!r} (verified {c.last_verified or 'never'})" for c in claims)
        out.append(Finding(check="contradiction", page=claims[0].page, key=key, claims=tuple(claims),
                           detail=f"pages disagree on {key!r}: {sides}"))
    return out


def _stale(bundle: Bundle, today: date) -> list[Finding]:
    out = []
    for p in sorted(bundle.concepts(), key=lambda p: p.path):
        budget = _budget(p.meta.type)
        if p.meta.last_verified is None:
            out.append(Finding(check="stale", page=p.path, detail="no last_verified: nobody has confirmed this page"))
        elif (age := (today - p.meta.last_verified).days) > budget:
            out.append(Finding(check="stale", page=p.path, detail=(
                f"last verified {p.meta.last_verified.isoformat()}, {age} days ago; budget {budget} days")))
    return out


def _links(bundle: Bundle) -> list[Finding]:
    out = []
    for path in sorted(bundle.pages):
        for lk in bundle.pages[path].links:
            if lk.resolved is None or lk.resolved in bundle.pages:
                continue
            if not (bundle.root / lk.resolved).exists():
                out.append(Finding(check="broken_link", page=path, detail=(
                    f"line {lk.line}: link to {lk.target!r} resolves to {lk.resolved}, which does not exist")))
    for path in sorted(bundle.pages):
        page = bundle.pages[path]
        if path == "index.md" or (page.meta is None and not page.reserved):
            continue  # the root is the entry point; a page the loader rejected is reported as invalid_page
        if not bundle.backlinks(path):
            out.append(Finding(check="orphan", page=path, detail="no page or index links here, so no reader finds it"))
    return out


def _rule_sources(bundle: Bundle, rules: list[Rule]) -> list[Finding]:
    out = []
    for r in rules:
        path = r.source.okf.removeprefix("knowledge/")
        page = bundle.pages.get(path)
        where = f"{r.source.okf} {r.source.clause}"
        if page is None or page.meta is None:
            problem = f"cites {where}, but that page is not in the bundle"
        elif page.section(r.source.clause) is None:
            problem = f"cites {where}, but the page has no heading {r.source.clause!r}"
        elif clause_section(bundle, r) is None:
            problem = f"cites {where}, but its clause text is not verbatim under that heading"
        elif r.id not in page.meta.rules:
            problem = f"is quoted from {where}, but the page's frontmatter does not list {r.id}"
        else:
            continue
        out.append(Finding(check="rule_source", page=path, rule=r.id, detail=f"{r.id} {problem}"))
    known = {r.id for r in rules}
    for p in sorted(bundle.concepts(), key=lambda p: p.path):
        for rid in p.meta.rules:
            if rid not in known:
                out.append(Finding(check="rule_source", page=p.path, rule=rid,
                                   detail=f"lists {rid}, which is not a shipped rule"))
    return out


def lint(bundle: Bundle, rules: list[Rule], *, today: date | None = None) -> LintReport:
    today = today or datetime.now(UTC).date()
    findings = [Finding(check="invalid_page", page=p.path, detail=p.message) for p in bundle.problems]
    findings += _contradictions(bundle) + _stale(bundle, today) + _links(bundle) + _rule_sources(bundle, rules)
    return LintReport(findings=findings, pages=len(bundle.pages), today=today)


def main(argv: list[str]) -> int:
    from contextrail.policy.loader import load_rules

    bundle = load_bundle(Path(argv[1]) if len(argv) > 1 else None)
    report = lint(bundle, load_rules())
    print(report.render())
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
