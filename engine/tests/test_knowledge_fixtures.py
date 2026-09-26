"""The knowledge bundle agrees with the FIXTURE records it describes (checklist T174, T175).

Pages are written by people (or drafted by a model and promoted by people); records come from systems. When the two
disagree, a case file would carry contradictory evidence, so the agreement is tested, not assumed.
"""

import re

import pytest

from contextrail.fixtures import load
from contextrail.knowledge.okf import load_bundle

BUNDLE = load_bundle()
CATALOG = load("entitlements")["catalog"]
ROLE = load("roles")["roles"]["payments-engineer"]
HRIS = {p["source_id"]: p for p in load("hris")["people"]}
_KEY = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`")   # entitlement keys are hyphenated: `jira-pay`
_PERSON = re.compile(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\s+\(((?:E|W)-\d{4})")   # names may wrap across lines


def _keys(text: str) -> list[str]:
    keys = _KEY.findall(text)
    unknown = sorted(set(keys) - set(CATALOG))
    assert not unknown, f"not in the entitlement catalogue: {unknown}"
    return keys


def _page(path: str):
    assert path in BUNDLE.pages, f"{path} is missing from the bundle"
    return BUNDLE.pages[path]


def test_payments_engineer_baseline_is_the_role_catalogue_in_order():
    assert _keys(_page("roles/payments-engineer.md").section("Baseline").text) == ROLE["baseline"]


def test_baseline_items_that_still_need_approval_are_the_paid_and_production_tagged_ones():
    expected = {e for e in ROLE["baseline"]
                if CATALOG[e].get("seat_cost_usd", 0) > 0 or "production" in CATALOG[e].get("repo_tags", [])}
    section = _page("roles/payments-engineer.md").section("Approvals inside the baseline")
    assert set(_keys(section.text)) == expected == {"gh-payments-core-read", "postman-enterprise-seat"}


def test_outside_the_baseline_lists_what_the_role_may_hold_but_does_not_get_by_default():
    expected = {e for e, c in CATALOG.items() if "payments-engineer" in c["role_scope"] and e not in ROLE["baseline"]}
    section = _page("roles/payments-engineer.md").section("Outside the baseline")
    assert set(_keys(section.text)) == expected == {"aws-payments-prod-admin"}


def test_github_page_lists_every_repository_with_its_tags():
    text = _page("systems/github.md").section("Repositories").text
    rows = re.findall(r"^\|\s*`([\w-]+/[\w-]+)`\s*\|\s*([^|]*?)\s*\|", text, flags=re.MULTILINE)
    listed = {repo: sorted(t.strip() for t in tags.split(",") if t.strip() not in ("", "none")) for repo, tags in rows}
    assert listed == {repo: sorted(r["tags"]) for repo, r in load("github")["repos"].items()}


@pytest.mark.parametrize("page", sorted(p.path for p in BUNDLE.concepts()))
def test_every_person_named_with_an_id_matches_the_hr_record(page):
    for raw_name, source_id in _PERSON.findall(BUNDLE.pages[page].body):
        name = " ".join(raw_name.split())
        assert source_id in HRIS, f"{page}: {source_id} is not in fixtures/hris.json"
        assert HRIS[source_id]["display_name"] == name, f"{page}: {source_id} is {HRIS[source_id]['display_name']}"
