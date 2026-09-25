import pytest

from contextrail.rail.discover import HeuristicExtractor, discover, lookup

# --- intent + mentions (T085, heuristic path) ---------------------------------------------------------------


@pytest.mark.parametrize(("text", "intent", "subject", "peer"), [
    ("Give Anil the same access as Rahul", "access.same_as_peer", "Anil", "Rahul"),
    ("please give Anil Kumar the same access as Rahul Mehta.", "access.same_as_peer", "Anil Kumar", "Rahul Mehta"),
    ("Grant E-1042 same access as E-0007", "access.same_as_peer", "E-1042", "E-0007"),
    ("Priya starts Monday, give her everything she needs", "onboarding", "Priya", None),
    ("Priya joins engineering on Monday. Please arrange everything she needs.", "onboarding", "Priya", None),
    ("Issue service credits to the customers affected by last night's outage", "refund.outage", None, None),
    ("What happened to my access request?", "query", None, None),
    ("Why was W-8841 refused production credentials?", "query", "W-8841", None),
    ("Approve", "approval_reply", None, None),
    ("make it so", "unknown", None, None),
])
async def test_heuristic_intents_and_mentions(text, intent, subject, peer):
    i = await HeuristicExtractor().extract(text)
    assert (i.intent, i.subject_mention, i.peer_mention, i.extractor) == (intent, subject, peer, "heuristic")


async def test_extractor_returns_mentions_never_identities():
    i = await HeuristicExtractor().extract("Give Anil the same access as Rahul")
    assert not hasattr(i, "subject") and not hasattr(i, "source_id")  # resolution is code's job (T086)


async def test_dates_are_captured():
    i = await HeuristicExtractor().extract("Priya starts Monday 2026-09-28")
    assert "Monday" in i.dates and "2026-09-28" in i.dates


# --- exact lookup (T086) -----------------------------------------------------------------------------------

@pytest.fixture
def hris(tmp_path):
    from contextrail.connectors.fixture import FixtureHRIS
    from contextrail.connectors.state import FixtureState

    s = FixtureState("hris", directory=tmp_path)
    s.reset()
    return FixtureHRIS(s)


async def test_lookup_by_id_is_exact(hris):
    assert [r["display_name"] for r in await lookup(hris, "W-8841")] == ["Priya Raghunathan"]
    assert await lookup(hris, "W-9999") == []


async def test_lookup_by_name_is_exact_never_fuzzy(hris):
    assert [r["source_id"] for r in await lookup(hris, "Anil")] == ["E-1042"]
    assert [r["source_id"] for r in await lookup(hris, "anil kumar")] == ["E-1042"]
    assert await lookup(hris, "Anill") == []          # a typo is not a match
    assert await lookup(hris, "Kumar") == []          # surnames alone do not resolve


async def test_hris_outage_is_not_mistaken_for_no_match():
    class DownHRIS:
        async def read(self, ref):
            raise TimeoutError("hris unreachable")

        async def find_by_name(self, name):
            raise TimeoutError("hris unreachable")

    with pytest.raises(TimeoutError):
        await lookup(DownHRIS(), "W-8841")


# --- needs_input instead of guessing (T087) ----------------------------------------------------------------

H = HeuristicExtractor()


async def test_single_exact_match_resolves(hris):
    d = await discover("Priya starts Monday, give her everything she needs", H, hris)
    assert d.status == "resolved" and d.subject.source_id == "W-8841" and d.subject.employment_type == "contractor"


async def test_two_matches_ask_which_one_with_candidates(hris):
    d = await discover("Rahul starts Monday", H, hris)
    assert d.status == "needs_input" and d.subject is None
    (need,) = d.needs
    assert (need.role, need.reason, need.mention) == ("subject", "ambiguous", "Rahul")
    assert {c.source_id: c.team for c in need.candidates} == {"E-0007": "payments", "E-0415": "risk-analytics"}


async def test_no_match_asks_rather_than_guessing(hris):
    d = await discover("Priyanka starts Monday", H, hris)
    assert d.status == "needs_input" and d.needs[0].reason == "no_match" and d.needs[0].candidates == []


async def test_request_with_no_named_person_asks(hris):
    d = await discover("new starter on Monday, onboard them please", H, hris)
    assert d.status == "needs_input" and d.needs[0].reason == "no_mention"


async def test_paraphrase_never_yields_a_wrong_subject(hris):
    # CLAUDE.md §18 test_paraphrase_identity: needs_input or the correct ID, never a wrong subject.
    d = await discover("new contract engineer starting next week", H, hris)
    assert d.status == "needs_input" or d.subject.source_id == "W-8841"


async def test_pinned_id_from_a_candidate_pick_resolves(hris):
    d = await discover("Rahul starts Monday", H, hris, subject_id="E-0415")
    assert d.status == "resolved" and d.subject.display_name == "Rahul Verma"


async def test_queries_do_not_require_a_subject(hris):
    d = await discover("What happened to my access request?", H, hris)
    assert d.status == "resolved" and d.subject is None


async def test_an_unclassifiable_request_never_proceeds(hris):
    d = await discover("make it so", H, hris)
    assert d.status == "needs_input" and d.needs[0].reason == "unclear_request"


# --- peer resolution for "same as X" (T088) ----------------------------------------------------------------

async def test_same_as_peer_resolves_both_people_by_exact_lookup(hris):
    d = await discover("Give Anil the same access as Rahul Mehta", H, hris)
    assert d.status == "resolved"
    assert (d.subject.source_id, d.peer.source_id) == ("E-1042", "E-0007")
    assert d.subject_record["previous_team"] == "risk-analytics"  # full record kept for the Plan stage


async def test_ambiguous_peer_asks_which_rahul(hris):
    d = await discover("Give Anil the same access as Rahul", H, hris)
    assert d.status == "needs_input" and d.subject.source_id == "E-1042" and d.peer is None
    (need,) = d.needs
    assert (need.role, need.reason, sorted(c.source_id for c in need.candidates)) == (
        "peer", "ambiguous", ["E-0007", "E-0415"])


async def test_peer_pick_resumes(hris):
    d = await discover("Give Anil the same access as Rahul", H, hris, peer_id="E-0007")
    assert d.status == "resolved" and d.peer.display_name == "Rahul Mehta"


async def test_subject_and_peer_both_ambiguous_asks_both(hris):
    d = await discover("Give Rahul the same access as Rahul", H, hris)
    assert [n.role for n in d.needs] == ["subject", "peer"]


async def test_same_access_as_themselves_is_refused_as_input(hris):
    d = await discover("Give Anil the same access as Anil Kumar", H, hris)
    assert d.status == "needs_input" and d.needs[0].reason == "same_person"
