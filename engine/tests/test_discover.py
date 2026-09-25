import pytest

from contextrail.rail.discover import HeuristicExtractor, lookup

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
