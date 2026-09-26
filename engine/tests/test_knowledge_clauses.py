"""Every shipped rule quotes a clause that exists, word for word, under its heading in the page it cites
(checklist T173, docs/DECISIONS.md D-011).

A verdict prints `clause_text` as the reason. If the curated page said something else, the engine and the written
policy would disagree without anyone noticing. The comparison is byte-for-byte: a clause is written on one line.
"""

import pytest

from contextrail.knowledge.okf import load_bundle
from contextrail.policy.loader import load_rules

RULES = load_rules()
BUNDLE = load_bundle()


def _page(rule):
    assert rule.source.okf.startswith("knowledge/"), f"{rule.id}: source.okf must be a path under knowledge/"
    path = rule.source.okf.removeprefix("knowledge/")
    assert path in BUNDLE.pages, f"{rule.id}: cites {path}, which is not in the bundle"
    return BUNDLE.pages[path]


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_clause_text_is_verbatim_under_the_cited_clause_heading(rule):
    section = _page(rule).section(rule.source.clause)
    assert section is not None, f"{rule.id}: no heading {rule.source.clause!r} in {rule.source.okf}"
    assert rule.clause_text in section.text, f"{rule.id}: clause text not found under {section.heading!r}"


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r.id)
def test_the_cited_page_lists_the_rule_in_its_frontmatter(rule):
    assert rule.id in _page(rule).meta.rules


def test_pages_name_only_rules_that_exist():
    known = {r.id for r in RULES}
    unknown = {p.path: sorted(set(p.meta.rules) - known) for p in BUNDLE.concepts() if set(p.meta.rules) - known}
    assert unknown == {}


def test_every_shipped_rule_is_covered():
    assert len(RULES) >= 8 and {r.id for r in RULES} >= {"POL-CTR-001", "POL-ACC-004", "POL-OFF-001", "POL-SOD-001"}
