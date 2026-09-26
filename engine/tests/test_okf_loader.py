"""The OKF loader (checklist T176): frontmatter, sections, links and the link graph of a knowledge bundle."""

from datetime import date
from pathlib import Path

import pytest

from contextrail.knowledge.okf import load_bundle, parse_page, slugify

POLICY = """---
type: Policy
title: Contractor Onboarding Policy
tags: [access, contractors]
last_verified: 2026-09-20
rules: [POL-CTR-001]
claims:
  contractor.production-credentials: never
  contractor.max-duration-days: 180
reviewed_by: dana            # not an OKF or ContextRail key: preserved, never rejected
---
# Contractor Onboarding Policy

Intro line. See [GitHub](../systems/github.md#repositories) and [the spec](https://example.org/okf).

## §4 Production access
Contractors must never receive production credentials.

## §40 Something else
Not clause four.

```markdown
## §5 Not a heading, this is inside a fence
[not a link](../nowhere.md)
```

## Notes
Inline code is not a link: `[x](../missing.md)`. Images are not links: ![logo](../img/logo.png).
"""


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# --- one page --------------------------------------------------------------------------------------------------

def test_frontmatter_is_parsed_typed_and_unknown_keys_are_kept():
    page, problems = parse_page("policies/contractor-onboarding.md", POLICY)
    assert problems == []
    m = page.meta
    assert (m.type, m.title, m.tags, m.rules) == ("Policy", "Contractor Onboarding Policy",
                                                  ["access", "contractors"], ["POL-CTR-001"])
    assert m.last_verified == date(2026, 9, 20)
    assert m.claims == {"contractor.production-credentials": "never", "contractor.max-duration-days": "180"}
    assert m.model_extra == {"reviewed_by": "dana"}


def test_sections_split_on_headings_outside_code_fences():
    page, _ = parse_page("policies/contractor-onboarding.md", POLICY)
    assert [s.heading for s in page.sections] == [
        "Contractor Onboarding Policy", "§4 Production access", "§40 Something else", "Notes"]
    s4 = page.section("§4")
    assert s4.text == "Contractors must never receive production credentials."
    assert s4.slug == "§4-production-access" and s4.level == 2
    assert "## §5 Not a heading" in page.section("§40").text   # fenced content stays text, not a heading


def test_clause_lookup_matches_the_whole_heading_or_its_leading_mark_only():
    later, _ = parse_page("q.md", "---\ntype: Policy\n---\n# Q\n## §40 Forty\nno\n## §4 Four\nyes\n")
    assert later.section("§4").text == "yes"                             # "§40" does not start with "§4 "
    page, _ = parse_page("p.md", POLICY)
    assert page.section("§4").heading == "§4 Production access"
    assert page.section("§4 Production access").heading == "§4 Production access"
    assert page.section("Notes").heading == "Notes"
    assert page.section("§5") is None and page.section("Production") is None


def test_links_resolve_relative_to_the_page_and_skip_code_images_and_schemes():
    page, _ = parse_page("policies/contractor-onboarding.md", POLICY)
    assert [(lk.target, lk.resolved) for lk in page.links] == [
        ("../systems/github.md#repositories", "systems/github.md"),
        ("https://example.org/okf", None),
    ]


def test_a_concept_page_without_a_type_is_a_problem_not_a_crash():
    page, problems = parse_page("roles/x.md", "---\ntitle: No type\n---\n# X\n")
    assert page is not None and page.meta is None
    assert [p.message for p in problems] == ["frontmatter must have a non-empty 'type' (OKF v0.1)"]
    _, problems = parse_page("roles/y.md", "# No frontmatter at all\n")
    assert "missing YAML frontmatter" in problems[0].message
    _, problems = parse_page("roles/z.md", "---\ntype: Role\nlast_verified: someday\n---\n# Z\n")
    assert "last_verified" in problems[0].message
    _, problems = parse_page("roles/w.md", "---\n- a list\n---\n# W\n")
    assert problems[0].message == "invalid frontmatter: expected a mapping, got list"
    _, problems = parse_page("roles/v.md", "---\ntype: [unclosed\n---\n# V\n")
    assert problems[0].message.startswith("invalid frontmatter: while parsing")


def test_reserved_files_need_no_frontmatter():
    page, problems = parse_page("policies/index.md", "# Policies\n\n- [A](a.md) - the A policy\n")
    assert problems == [] and page.reserved and page.meta is None
    assert page.links[0].resolved == "policies/a.md"


def test_duplicate_headings_get_distinct_slugs():
    page, _ = parse_page("p.md", "---\ntype: Guide\n---\n# P\n## Steps\none\n## Steps\ntwo\n")
    assert [s.slug for s in page.sections] == ["p", "steps", "steps-2"]


@pytest.mark.parametrize(("heading", "slug"), [
    ("§4 Production access", "§4-production-access"),
    ('Mirrored access ("same as")', "mirrored-access-same-as"),
    ("  Transfers  ", "transfers"),
])
def test_slugify(heading, slug):
    assert slugify(heading) == slug


# --- a bundle ---------------------------------------------------------------------------------------------------

@pytest.fixture
def bundle_dir(tmp_path):
    _write(tmp_path, "index.md", "# Knowledge\n\n- [Policies](policies/index.md)\n")
    _write(tmp_path, "policies/index.md", "# Policies\n\n- [Contractor onboarding](contractor-onboarding.md)\n")
    _write(tmp_path, "policies/contractor-onboarding.md", POLICY)
    _write(tmp_path, "systems/github.md", "---\ntype: System\n---\n# GitHub\n\nSee [policy](../policies/contractor-onboarding.md).\n")
    _write(tmp_path, "raw/solutions-article-1.md", "not frontmatter, and ignored: raw/ is source material\n")
    _write(tmp_path, "drafts/policies/contractor-onboarding.md", "---\ntype: Policy\n---\n# Draft, not curated\n")
    _write(tmp_path, "systems/broken.md", "---\ntitle: missing type\n---\n# Broken\n")
    return tmp_path


def test_bundle_skips_raw_and_drafts_and_collects_problems(bundle_dir):
    b = load_bundle(bundle_dir)
    assert sorted(b.pages) == ["index.md", "policies/contractor-onboarding.md", "policies/index.md",
                               "systems/broken.md", "systems/github.md"]
    assert sorted(p.path for p in b.concepts()) == ["policies/contractor-onboarding.md", "systems/github.md"]
    assert [(p.path, p.message) for p in b.problems] == [
        ("systems/broken.md", "frontmatter must have a non-empty 'type' (OKF v0.1)")]


def test_link_graph_has_outgoing_edges_and_backlinks(bundle_dir):
    b = load_bundle(bundle_dir)
    assert b.outgoing("policies/contractor-onboarding.md") == {"systems/github.md"}
    assert b.backlinks("policies/contractor-onboarding.md") == {"policies/index.md", "systems/github.md"}
    assert b.backlinks("policies/index.md") == {"index.md"}
    assert b.backlinks("systems/github.md") == {"policies/contractor-onboarding.md"}


def test_the_shipped_bundle_loads_without_problems():
    b = load_bundle()
    assert b.problems == []
    assert {"SCHEMA.md", "README.md"} <= set(b.pages)
    assert all(p.meta is not None and p.meta.type for p in b.concepts())
