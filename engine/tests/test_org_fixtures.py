"""Northbeam, the FIXTURE org, must read as one believable company: every fact agrees with every other fact.

These checks span files (HRIS, identity, entitlements, GitHub, Slack, documents, incidents, payments), so a record
added to one file cannot silently contradict another. The demo outcomes themselves are asserted in test_demo.py.
"""

import hashlib
import json
from collections import Counter
from datetime import date

from contextrail.fixtures import load

TODAY = date(2026, 9, 26)
NEXT_MONDAY = date(2026, 9, 28)
TEAMS = {"payments", "risk-analytics", "perception", "platform", "security", "it-ops", "finance", "support",
         "people-ops", "data-analytics"}
ORIGINAL_HRIS_IDS = ("E-1042", "E-0007", "E-0415", "W-8841", "E-0301", "E-0050", "E-0051", "E-0120", "E-0210",
                     "E-0002")


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def people():
    return load("hris")["people"]


def by_id():
    return {p["source_id"]: p for p in people()}


def _d(value):
    return date.fromisoformat(value) if value else None


# --- HRIS (T073) -------------------------------------------------------------------------------------------

def test_a_mid_size_company_across_the_ten_teams():
    assert 45 <= len(people()) <= 60
    headcount = Counter(p["team"] for p in people())
    assert TEAMS <= set(headcount), TEAMS - set(headcount)
    assert all(headcount[t] >= 2 for t in TEAMS), headcount


def test_ids_follow_employment_type():
    prefix = {"employee": "E-", "contractor": "W-", "vendor": "V-"}
    for p in people():
        assert p["source_id"].startswith(prefix[p["employment_type"]]), p["source_id"]


def test_management_chain_is_realistic():
    ids = by_id()
    for p in people():
        boss = ids.get(p["manager_id"]) if p["manager_id"] else None
        if boss is None:
            assert p["seniority"] == "principal", f"{p['source_id']}: only executives have no manager"
            continue
        assert boss["employment_type"] == "employee" and boss["seniority"] in ("lead", "principal"), p["source_id"]
        seen, cur = set(), p
        while cur["manager_id"]:  # every chain ends at an executive, no loops
            assert cur["source_id"] not in seen, f"management loop at {cur['source_id']}"
            seen.add(cur["source_id"])
            cur = ids[cur["manager_id"]]


def test_every_team_has_a_head():
    ids = by_id()
    for team in TEAMS:
        members = [p for p in people() if p["team"] == team]
        if not any(p["seniority"] in ("lead", "principal") for p in members):
            # A team without its own lead (security) reports straight to an executive.
            assert {ids[p["manager_id"]]["seniority"] for p in members} == {"principal"}, team


def test_contractors_have_a_statement_of_work_and_an_end_date():
    contractors = [p for p in people() if p["employment_type"] == "contractor"]
    assert 3 <= len(contractors) <= 4
    for c in contractors:
        assert c["seniority"] is None and c["nda_signed"] and c["sow_countersigned"], c["source_id"]
        assert _d(c["end_date"]) > _d(c["start_date"]), c["source_id"]
        assert _d(c["end_date"]) > TODAY, f"{c['source_id']}: a live engagement, not an expired one"


def test_one_vendor_with_a_contract_end():
    vendors = [p for p in people() if p["employment_type"] == "vendor"]
    assert len(vendors) == 1
    v = vendors[0]
    assert v["end_date"] and v["vendor_company"] and v["manager_id"] in by_id()


def test_recent_team_transfers():
    moved = [p for p in people() if p.get("previous_team")]
    assert 2 <= len(moved) <= 4 and "E-1042" in {p["source_id"] for p in moved}
    for p in moved:
        assert p["previous_team"] != p["team"] and p["previous_team"] in TEAMS, p["source_id"]
        assert 0 <= (TODAY - _d(p["transfer_date"])).days <= 30, p["source_id"]


def test_an_employee_starts_next_monday():
    starters = [p for p in people() if _d(p["start_date"]) == NEXT_MONDAY and p["employment_type"] == "employee"]
    assert len(starters) == 1


def test_first_names_are_unique_except_the_two_rahuls():
    first = Counter(p["display_name"].split()[0] for p in people())
    assert {n: c for n, c in first.items() if c > 1} == {"Rahul": 2}
    assert "Priyanka" not in first  # "Priyanka starts Monday" must stay a no-match (test_discover)


def test_the_original_ten_records_are_byte_for_byte_unchanged():
    # The demo cast (Anil, both Rahuls, Priya, Meera, Dana, Omar, Marc, Sam, Ravi) is only ever appended to.
    original = [p for p in people() if p["source_id"] in ORIGINAL_HRIS_IDS]
    assert [p["source_id"] for p in original] == list(ORIGINAL_HRIS_IDS)
    assert _digest(original) == "7b4ead4084f69fa8671823c7862c70c5ef4207e7ec155e1fcb1ff15166ca8bae"
