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


# --- roles and entitlements (T074) -------------------------------------------------------------------------

SENIOR = {"senior", "lead", "principal"}
CONTRACTOR_FORBIDDEN = {"production_credential", "production_admin", "production_db", "customer_pii_export"}


def catalog():
    return load("entitlements")["catalog"]


def holdings():
    return load("entitlements")["holdings"]


def roles():
    return load("roles")["roles"]


def test_every_role_in_use_has_a_baseline_inside_its_own_scope():
    in_use = {p["role"] for p in people()}
    assert in_use <= set(roles()), in_use - set(roles())
    for name, role in roles().items():
        for ent in role["baseline"]:
            assert name in catalog()[ent]["role_scope"], f"{name} baseline {ent} is outside the role's scope"


def test_catalogue_spans_the_systems_a_mid_size_company_runs():
    cat = catalog()
    assert 60 <= len(cat) <= 80, len(cat)
    systems = {t["system"] for t in cat.values()}
    assert {"okta", "slack", "jira", "confluence", "aws", "datadog", "pagerduty", "sentry", "vault", "google",
            "looker", "snowflake", "postman", "figma"} <= systems, systems
    aws = {t["resource_class"] for t in cat.values() if t["system"] == "aws"}
    assert {"standard", "admin", "production_admin", "production_credential"} <= aws, aws


def test_snowflake_separates_raw_pii_from_masked_views():
    snow = {e: t for e, t in catalog().items() if t["system"] == "snowflake"}
    assert all(t["data_class"] in ("raw_pii", "masked", "internal") for t in snow.values())
    raw = [e for e, t in snow.items() if t["data_class"] == "raw_pii"]
    assert raw == ["snowflake-raw-pii"] and catalog()["snowflake-raw-pii"]["teams"] == ["data-analytics"]
    assert any(t["data_class"] == "masked" for t in snow.values())


def test_paid_seats_carry_their_cost():
    paid = {e for e, t in catalog().items() if t.get("seat_cost_usd", 0) > 0}
    assert {"postman-enterprise-seat", "figma-professional-seat", "looker-developer-seat"} <= paid
    assert catalog()["figma-viewer"]["seat_cost_usd"] == 0  # a free viewer seat is not a paid seat


def test_only_the_original_perception_items_are_team_scoped_to_perception():
    # Govern adds team-scoped items for "everything" requests; Priya's outcome must not grow (T095 test).
    scoped = sorted(e for e, t in catalog().items() if "perception" in t.get("teams", []))
    assert scoped == ["aws-perception-prod-credentials", "gh-perception-sdk-read"]


def test_everyone_has_a_holdings_entry_and_every_holding_is_catalogued():
    assert set(holdings()) == {p["source_id"] for p in people()}
    for pid, held in holdings().items():
        assert set(held) <= set(catalog()), pid
        assert len(held) == len(set(held)), f"{pid}: duplicate holding"


def test_holdings_sit_inside_the_role_scope_unless_the_person_moved_team():
    for p in people():
        outside = [e for e in holdings()[p["source_id"]] if p["role"] not in catalog()[e]["role_scope"]]
        if p.get("previous_team"):
            assert outside, f"{p['source_id']} moved team and still holds old-team access to revoke"
        else:
            assert outside == [], f"{p['source_id']} holds {outside} outside role {p['role']}"


def test_holdings_already_obey_the_written_rules():
    for p in people():
        for ent in holdings()[p["source_id"]]:
            rc = catalog()[ent]["resource_class"]
            if rc in ("admin", "production_admin"):  # POL-ACC-003
                assert p["seniority"] in SENIOR, f"{p['source_id']} ({p['seniority']}) holds admin {ent}"
            if p["employment_type"] in ("contractor", "vendor"):  # POL-CTR-001
                assert rc not in CONTRACTOR_FORBIDDEN, f"{p['source_id']} holds {ent}"


def test_the_original_holdings_and_role_baselines_are_unchanged():
    assert _digest({k: holdings()[k] for k in ("E-0007", "E-1042", "E-0415", "W-8841")}) == (
        "ed3e9ac98417cca7bc9308a051f2f3705f4ac85877d7fbe0869a06ad0dad09e1")
    original = ("payments-engineer", "risk-analyst", "contract-engineer", "engineering-manager")
    assert _digest({k: roles()[k] for k in original}) == (
        "eb67960710266c02e8a7a8a82d92e7814f5b79114c1a2bca8fe7ece38f8a853f")


# --- GitHub (T075) -----------------------------------------------------------------------------------------

def github():
    return load("github")


def _repo_access(pid: str) -> dict[str, str]:
    """What the entitlement holdings say this person can do in GitHub: {repo: permission}."""
    return {catalog()[e]["repo"]: catalog()[e]["permission"] for e in holdings()[pid]
            if catalog()[e]["system"] == "github"}


def test_about_fifteen_repositories_tagged_production_pci_or_internal():
    repos = github()["repos"]
    assert 14 <= len(repos) <= 16, len(repos)
    tags = [t for r in repos.values() for t in r["tags"]]
    assert set(tags) <= {"production", "pci", "internal", "pii"}
    assert {"production", "pci", "internal"} <= set(tags)
    assert all(name.startswith("northbeam/") for name in repos)


def test_every_login_belongs_to_one_person():
    logins = github()["logins"]
    assert set(logins) <= set(by_id())
    assert len(set(logins.values())) == len(logins)


def test_collaborators_are_exactly_what_the_holdings_say_for_everyone():
    logins, repos = github()["logins"], github()["repos"]
    for p in people():
        expected = _repo_access(p["source_id"])
        login = logins.get(p["source_id"])
        if login is None:
            assert expected == {}, f"{p['source_id']} holds repo access but has no GitHub login"
            continue
        actual = {name: r["collaborators"][login] for name, r in repos.items() if login in r["collaborators"]}
        assert actual == expected, p["source_id"]
    known = set(logins.values())
    assert {c for r in repos.values() for c in r["collaborators"]} <= known


def test_contractors_only_read_the_repositories_in_their_sow():
    for p in people():
        if p["employment_type"] != "employee":
            access = _repo_access(p["source_id"])
            assert set(access) <= set(p["sow_repos"]) and set(access.values()) <= {"read"}, p["source_id"]


def test_the_demo_subjects_can_be_granted_repository_access():
    # Execute writes GitHub grants by login; a missing login would fail the demo runs' GitHub rows.
    assert {"E-1042", "E-0641", "E-0698", "E-0462", "W-8841"} <= set(github()["logins"])
