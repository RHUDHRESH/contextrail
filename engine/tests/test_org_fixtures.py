"""Northbeam, the FIXTURE org, must read as one believable company: every fact agrees with every other fact.

These checks span files (HRIS, identity, entitlements, GitHub, Slack, documents, incidents, payments), so a record
added to one file cannot silently contradict another. The demo outcomes themselves are asserted in test_demo.py.
"""

import hashlib
import json
import re
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


# --- Slack corpus (T076) -----------------------------------------------------------------------------------

ORIGINAL_MESSAGES = ("slk_prod_access_thread", "slk_payments_admin_override", "slk_sec_thread_1", "slk_it_thread_1",
                     "slk_payments_welcome")


def messages():
    return load("slack_corpus")["messages"]


def test_about_thirty_messages_with_unique_ids_and_timestamps():
    assert 28 <= len(messages()) <= 35, len(messages())
    assert len({m["id"] for m in messages()}) == len(messages())
    assert len({(m["channel_id"], m["ts"]) for m in messages()}) == len(messages())
    channels = {}
    for m in messages():
        assert channels.setdefault(m["channel"], m["channel_id"]) == m["channel_id"], m["id"]


def test_authors_are_people_in_the_hris_or_explicitly_unattributed():
    ids = by_id()
    for m in messages():
        if m["author_id"] is not None:
            assert ids[m["author_id"]]["display_name"] == m["author"], m["id"]
    guests = {m["author"] for m in messages() if m["author_id"] is None}
    assert guests == {"Unknown (guest)", "Priyanka Rao"}  # a guest account and the vendor-side IT coordinator


def test_the_five_original_messages_are_unchanged():
    original = [m for m in messages() if m["id"] in ORIGINAL_MESSAGES]
    assert [m["id"] for m in original] == list(ORIGINAL_MESSAGES)
    assert _digest(original) == "279446c7d2d98c1191f4f58094ad21760ff5e390ed5c2831f47c90df16ddd4c9"


def test_the_corpus_has_team_chatter_a_precedent_thread_it_inventory_and_incident_channels():
    by_channel = Counter(m["channel"] for m in messages())
    assert by_channel["#security"] >= 3 and by_channel["#it-helpdesk"] >= 3
    assert by_channel["#incident-2481"] >= 3 and by_channel["#incident-4412"] >= 2
    assert len(by_channel) >= 10
    inc = " ".join(m["text"] for m in messages() if m["channel"] == "#incident-2481")
    assert "INC-2481" in inc and "ap-south-1" in inc


def test_slack_authors_have_a_slack_identity():
    slack_ids = {p["hris_id"]: p["slack_user_id"] for p in load("identity")["people"]}
    for m in messages():
        if m["author_id"] is not None:
            assert slack_ids[m["author_id"]], f"{m['author']} posted in Slack without a Slack account"


def test_the_outage_retrospective_is_ported_verbatim_from_stage1():
    from test_fixtures import _stage1_body

    msg = next(m for m in messages() if m["id"] == "slk_status_outage")
    assert msg["text"] == _stage1_body("slk_status_outage")


async def test_retrieval_for_the_demo_requests_still_surfaces_both_injections(tmp_path):
    from contextrail.connectors.fixture import FixtureSlackCorpus
    from contextrail.connectors.state import FixtureState
    from contextrail.fixtures import subject_from_record
    from contextrail.rail.compile import search_terms

    state = FixtureState("slack_corpus", directory=tmp_path)
    state.reset()
    corpus, ids = FixtureSlackCorpus(state), by_id()
    anil, rahul, priya = (subject_from_record(ids[i]) for i in ("E-1042", "E-0007", "W-8841"))
    same_as = await corpus.search(search_terms(anil, rahul, "access.same_as_peer"), limit=5)
    onboarding = await corpus.search(search_terms(priya, None, "onboarding"), limit=5)
    assert "slk_payments_admin_override" in [m["id"] for m in same_as]
    assert "slk_prod_access_thread" in [m["id"] for m in onboarding]


# --- identity for every door (T080) ------------------------------------------------------------------------

ORIGINAL_ROSTER = {"security-oncall": ["p-dana", "p-omar"], "incident-commander": ["p-omar", "p-dana"],
                   "data-owner": ["p-ravi"], "finance": ["p-ravi"], "vp-finance": ["p-ravi"]}
PHONE = re.compile(r"^\+91999000\d{4}$")  # the fictional range reserved for the demo


def identities():
    return load("identity")["people"]


def test_every_identity_is_one_hris_person_with_unique_door_ids():
    ids = by_id()
    rows = identities()
    assert [r["display_name"] for r in rows] == [ids[r["hris_id"]]["display_name"] for r in rows]
    for col in ("person_id", "email", "slack_user_id", "teams_aad_id", "phone", "hris_id"):
        values = [r[col].lower() if col == "email" else r[col] for r in rows if r[col] is not None]
        assert len(values) == len(set(values)), f"duplicate {col}"
    for r in rows:
        assert r["email"].endswith("northbeam.example"), r["person_id"]
        assert r["phone"] is None or PHONE.match(r["phone"]), r["person_id"]
        assert r["preferred_door"] in ("slack", "teams", "email", "voice"), r["person_id"]


def test_the_preferred_door_is_one_the_person_can_be_reached_on():
    column = {"slack": "slack_user_id", "teams": "teams_aad_id", "voice": "phone", "email": "email"}
    for r in identities():
        assert r[column[r["preferred_door"]]], f"{r['person_id']} prefers {r['preferred_door']} but has no id there"


def test_everyone_already_working_has_a_slack_account():
    ids = by_id()
    for r in identities():
        started = date.fromisoformat(ids[r["hris_id"]]["start_date"]) <= TODAY
        assert bool(r["slack_user_id"]) == started, r["person_id"]  # starters get Slack from their onboarding run


def test_approvers_are_exactly_the_managers_and_the_roster():
    ident = load("identity")
    person = {r["hris_id"]: r["person_id"] for r in identities()}
    managers = {person[p["manager_id"]] for p in people() if p["manager_id"]}
    rostered = {pid for members in ident["roster"].values() for pid in members}
    approvers = {r["person_id"] for r in identities() if r["can_approve"]}
    assert approvers == managers | rostered
    outsiders = {person[p["source_id"]] for p in people() if p["employment_type"] != "employee"}
    assert not approvers & outsiders


def test_rosters_cover_every_approver_role_and_keep_the_original_order():
    from contextrail.policy.schema import APPROVER_ROLES

    roster = load("identity")["roster"]
    assert set(APPROVER_ROLES) - {"manager"} <= set(roster)  # "manager" resolves through the HRIS record
    for role, original in ORIGINAL_ROSTER.items():
        assert roster[role][: len(original)] == original, role  # appended backups never displace the primary


def test_the_original_ten_identities_are_unchanged():
    original = [r for r in identities() if r["hris_id"] in ORIGINAL_HRIS_IDS]
    assert _digest(original) == "fab951d2471b3b377b52f815a5b6cc2575b2ad54438d633ed4bda1fc0e7c4902"


# --- statements of work and incident INC-4412 (T077) -------------------------------------------------------

REPO = re.compile(r"\bnorthbeam/[a-z0-9-]+")


def sows():
    return [d for d in load("documents")["documents"] if d["kind"] == "sow"]


def incidents():
    return {i["id"]: i for i in load("incidents")["incidents"]}


def test_every_contractor_has_exactly_one_statement_of_work():
    assert load("documents")["_meta"]["mode"] == "FIXTURE"
    contractors = {p["source_id"] for p in people() if p["employment_type"] == "contractor"}
    assert sorted(d["subject_id"] for d in sows()) == sorted(contractors)


def test_each_sow_names_exactly_the_repositories_in_the_hr_record():
    ids = by_id()
    for d in sows():
        assert set(REPO.findall(d["text"])) == set(ids[d["subject_id"]]["sow_repos"]), d["id"]
    priya = next(d for d in sows() if d["subject_id"] == "W-8841")
    assert "Read-only access to northbeam/perception-sdk" in priya["text"]


def test_each_sow_agrees_with_the_hr_record_on_dates_owner_and_id():
    ids = by_id()
    for d in sows():
        hr = ids[d["subject_id"]]
        assert (d["starts"], d["ends"], d["owner_id"]) == (hr["start_date"], hr["end_date"], hr["manager_id"]), d["id"]
        assert d["starts"] in d["text"] and d["ends"] in d["text"] and ids[d["owner_id"]]["display_name"] in d["text"]
        assert hr.get("sow_id", d["sow_id"]) == d["sow_id"]


def test_sow_clauses_are_numbered_so_constraints_can_cite_them():
    for d in sows():
        for n in range(1, 7):
            assert f"§{n} " in d["text"], (d["id"], n)
        assert "production credentials" in d["text"].split("§4 ", 1)[1].split("§5 ", 1)[0], d["id"]


def test_incident_4412_is_open_with_a_rostered_commander_and_real_responders():
    assert load("incidents")["_meta"]["mode"] == "FIXTURE"
    inc = incidents()["INC-4412"]
    assert (inc["status"], inc["severity"], inc["region"]) == ("open", "Sev-2", "ap-south-1")
    commander = next(r["person_id"] for r in identities() if r["hris_id"] == inc["commander_id"])
    assert commander in load("identity")["roster"]["incident-commander"]
    assert set(inc["responder_ids"]) <= set(by_id())


def test_incident_access_request_is_read_only_time_boxed_and_not_already_held():
    inc = incidents()["INC-4412"]
    (req,) = inc["access_requests"]
    target = catalog()[req["entitlement"]]
    assert req["subject_id"] in inc["responder_ids"] and req["status"] == "pending"
    assert (target["permission"], target["resource_class"], req["duration"]) == ("read", "production_read", "4h")
    assert req["entitlement"] not in holdings()[req["subject_id"]]


# --- payments: customers, plans, prior credits, the outage (T078) ------------------------------------------

APPROVAL_LIMIT_USD = {"support-agent": 2000, "customer-success-manager": 2000, "support-manager": 2000,
                      "finance-manager": 10000, "vp-finance": float("inf")}  # Stage 1 refund policy §3


def payments():
    return load("payments")


def customers():
    return {c["account_id"]: c for c in payments()["customers"]}


def test_payments_fixture_is_labelled_and_honest_that_no_refund_rail_reads_it():
    meta = payments()["_meta"]
    assert meta["mode"] == "FIXTURE" and "not built" in meta["note"]


def test_customers_are_fictional_accounts_on_known_plans_with_support_owners():
    ids = by_id()
    for acc, c in customers().items():
        assert re.fullmatch(r"ACC-\d{4}", acc) and c["domain"].endswith(".example"), acc
        assert c["plan"] in payments()["plans"], acc
        assert c["csm_id"] is None or ids[c["csm_id"]]["team"] == "support", acc
    assert customers()["ACC-1042"]["name"] == "Meridian Freight"  # the Stage 1 account


def test_inc_2481_matches_stage1_and_hit_exactly_the_customers_in_its_region():
    inc = incidents()["INC-2481"]
    assert (inc["opened_at"], inc["resolved_at"], inc["duration_hours"]) == (
        "2026-08-17T09:12:00Z", "2026-08-20T07:40:00Z", 70.47)
    assert inc["status"] == "resolved" and inc["sla_breached"] and inc["region"] == "ap-south-1"
    in_region = sorted(a for a, c in customers().items() if c["region"] == inc["region"])
    assert sorted(inc["affected_accounts"]) == in_region == ["ACC-1042", "ACC-2210", "ACC-3318"]


def test_every_incident_has_a_rostered_commander_and_real_responders():
    roster = load("identity")["roster"]["incident-commander"]
    person = {r["hris_id"]: r["person_id"] for r in identities()}
    for inc in incidents().values():
        assert person[inc["commander_id"]] in roster, inc["id"]
        assert set(inc["responder_ids"]) <= set(by_id()), inc["id"]


def test_prior_credits_are_consistent_and_include_the_one_duplicate():
    ids = by_id()
    for cr in payments()["credits"]:
        assert cr["account_id"] in customers() and cr["incident_id"] in incidents(), cr["id"]
        issued = date.fromisoformat(cr["issued_at"])
        assert cr["quarter"] == f"{issued.year}-Q{(issued.month - 1) // 3 + 1}", cr["id"]
        assert cr["amount_usd"] <= APPROVAL_LIMIT_USD[ids[cr["approved_by"]]["role"]], cr["id"]
    already = [cr for cr in payments()["credits"] if cr["incident_id"] == "INC-2481"]
    assert [(c["account_id"], c["quarter"]) for c in already] == [("ACC-3318", "2026-Q3")]


def test_one_credit_request_per_affected_account_and_one_of_them_is_the_duplicate():
    reqs = [r for r in payments()["credit_requests"] if r["incident_id"] == "INC-2481"]
    assert sorted(r["account_id"] for r in reqs) == sorted(incidents()["INC-2481"]["affected_accounts"])
    credited = {(c["account_id"], c["quarter"]) for c in payments()["credits"]}
    dupes = [r["account_id"] for r in reqs if (r["account_id"], "2026-Q3") in credited]
    assert dupes == ["ACC-3318"]  # POL-REF-002 (T071): one outage credit per customer per quarter
