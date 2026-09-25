"""The FIXTURE data set is itself a deliverable: it must be internally consistent and produce the demo outcomes."""

from contextrail.fixtures import load, subject_from_record

# --- HRIS (T073) -------------------------------------------------------------------------------------------


def people():
    return load("hris")["people"]


def test_hris_is_labelled_fixture_and_every_record_is_a_valid_subject():
    assert load("hris")["_meta"]["mode"] == "FIXTURE"
    subjects = [subject_from_record(p) for p in people()]
    ids = [s.source_id for s in subjects]
    assert len(ids) == len(set(ids))


def test_every_manager_id_resolves_to_a_person():
    ids = {p["source_id"] for p in people()}
    assert all(p["manager_id"] in ids for p in people() if p["manager_id"])


def test_demo_cast():
    by_id = {p["source_id"]: p for p in people()}
    anil, rahul, priya = by_id["E-1042"], by_id["E-0007"], by_id["W-8841"]
    assert (anil["role"], anil["seniority"], anil["previous_team"]) == ("payments-engineer", "mid", "risk-analytics")
    assert (rahul["role"], rahul["seniority"]) == ("payments-engineer", "senior")
    assert priya["employment_type"] == "contractor" and priya["sow_repos"] == ["northbeam/perception-sdk"]


def test_two_people_named_rahul_for_the_ambiguity_demo():
    rahuls = [p for p in people() if p["display_name"].split()[0] == "Rahul"]
    assert len(rahuls) == 2 and len({r["team"] for r in rahuls}) == 2


def test_subject_projection_drops_extra_hr_fields():
    s = subject_from_record(next(p for p in people() if p["source_id"] == "E-1042"))
    assert not hasattr(s, "previous_team")
