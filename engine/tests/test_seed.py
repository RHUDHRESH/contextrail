import psycopg

from contextrail.fixtures import load
from contextrail.models import Subject
from contextrail.policy.approvers import resolve_approver
from contextrail.seed import approver_directory, main, reset_fixture_state, seed_identity


def test_identity_fixture_covers_every_hris_person_and_every_roster_member():
    ident, hris = load("identity"), load("hris")
    assert ident["_meta"]["mode"] == "FIXTURE"
    assert {p["hris_id"] for p in ident["people"]} == {p["source_id"] for p in hris["people"]}
    ids = {p["person_id"] for p in ident["people"]}
    approvers = {p["person_id"] for p in ident["people"] if p["can_approve"]}
    for role, people in ident["roster"].items():
        assert set(people) <= approvers, role  # nobody on a roster who cannot approve
    assert approvers <= ids


def test_seed_is_idempotent_and_loads_every_door_identity(migrated_db):
    assert seed_identity(migrated_db) == seed_identity(migrated_db) == len(load("identity")["people"])
    with psycopg.connect(migrated_db) as c:
        n = c.execute("select count(*) from identity_map").fetchone()[0]
        dana = c.execute("select slack_user_id, teams_aad_id, phone, preferred_door from identity_map "
                         "where person_id = 'p-dana'").fetchone()
    assert n == len(load("identity")["people"])
    assert dana == ("U0DANA050", "00000000-0000-4000-8000-000000000050", "+919990000150", "teams")


def test_directory_from_identity_resolves_demo_approvers():
    d = approver_directory()
    anil = Subject(source="hris", source_id="E-1042", display_name="Anil Kumar", employment_type="employee",
                   manager_id="E-0301")
    assert resolve_approver(d, "manager", anil) == "p-meera"
    assert resolve_approver(d, "security-oncall", anil) == "p-dana"
    assert resolve_approver(d, "security-oncall", anil, requested_by="p-dana") == "p-omar"


def test_main_migrates_seeds_and_resets_state(empty_db, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    assert main(["seed", empty_db]) == 0
    out = capsys.readouterr().out
    assert f"identity rows: {len(load('identity')['people'])}" in out and "slack_corpus" in out
    assert sorted(p.name for p in tmp_path.glob("*.json")) == [
        "entitlements.json", "freshservice.json", "github.json", "hris.json", "slack_corpus.json"]


def test_reset_restores_seed_state(tmp_path):
    import json

    reset_fixture_state(tmp_path)
    doc = json.loads((tmp_path / "entitlements.json").read_text(encoding="utf-8"))
    doc["holdings"]["E-1042"].append("aws-payments-prod-admin")
    (tmp_path / "entitlements.json").write_text(json.dumps(doc), encoding="utf-8")
    reset_fixture_state(tmp_path)
    doc = json.loads((tmp_path / "entitlements.json").read_text(encoding="utf-8"))
    assert "aws-payments-prod-admin" not in doc["holdings"]["E-1042"] and doc["_ledger"] == {}


# --- local demo email override (routes fixture approvers to SES-verified inboxes) --------------------------

def test_overrides_route_approver_mail_and_leave_everyone_else(migrated_db):
    import pytest as _pytest

    from contextrail.seed import OverrideError, parse_email_overrides

    people = {p["person_id"] for p in load("identity")["people"]}
    spec = "p-dana=demo+dana@example.com, p-meera=demo+meera@example.com"
    assert parse_email_overrides(spec, people) == {"p-dana": "demo+dana@example.com",
                                                  "p-meera": "demo+meera@example.com"}
    seed_identity(migrated_db, email_overrides=spec)
    with psycopg.connect(migrated_db) as c:
        emails = dict(c.execute("select person_id, email from identity_map").fetchall())
    assert emails["p-dana"] == "demo+dana@example.com" and emails["p-meera"] == "demo+meera@example.com"
    assert emails["p-anil"] == "anil.kumar@northbeam.example"  # untouched
    for bad in ("p-dana", "p-dana=not-an-email", "p-nobody=x@example.com",
                "p-dana=same@example.com,p-meera=SAME@example.com"):
        with _pytest.raises(OverrideError):
            parse_email_overrides(bad, people)


def test_no_override_keeps_fixture_addresses(migrated_db):
    seed_identity(migrated_db, email_overrides="")
    with psycopg.connect(migrated_db) as c:
        assert c.execute("select email from identity_map where person_id = 'p-dana'").fetchone()[0] == \
            "dana.osei@northbeam.example"
