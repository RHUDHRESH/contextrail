import pytest

from contextrail.canonical import idempotency_key
from contextrail.connectors.base import Connector, ConnectorError, TransientError, UnknownOutcome
from contextrail.connectors.fixture import FixtureEntitlements, FixtureGitHub, FixtureHRIS, FixtureSlackCorpus
from contextrail.connectors.state import FixtureState
from contextrail.models import Action


@pytest.fixture
def states(tmp_path):
    def make(name):
        s = FixtureState(name, directory=tmp_path)
        s.reset()
        return s
    return make


def grant_ent(ent="jira-pay", subject="E-1042", kind="grant"):
    return Action.create(f"A-{ent}", kind, {"system": "jira", "entitlement": ent, "subject_id": subject})


def gh(repo="northbeam/payments-api", permission="read", kind="grant", subject="E-1042"):
    return Action.create(f"G-{repo}", kind, {"system": "github", "repo": repo, "permission": permission,
                                            "subject_id": subject})


def key(a):
    return idempotency_key("run-1", a.id, a.params_hash)


def test_all_fixture_connectors_satisfy_the_protocol_and_say_fixture(states):
    for c in (FixtureEntitlements(states("entitlements")), FixtureGitHub(states("github")),
              FixtureHRIS(states("hris")), FixtureSlackCorpus(states("slack_corpus"))):
        assert isinstance(c, Connector) and c.mode == "FIXTURE"


async def test_grant_is_written_persisted_and_verified(states):
    c = FixtureEntitlements(states("entitlements"))
    a = grant_ent()
    assert (await c.verify(a))[0] is False
    r = await c.write(a, key(a))
    assert r.ok and not r.replayed and r.mode == "FIXTURE"
    fresh = FixtureEntitlements(FixtureState("entitlements", directory=c.state.path.parent))  # re-read from disk
    assert (await fresh.verify(a))[0] is True


async def test_same_idempotency_key_writes_once(states):
    c = FixtureEntitlements(states("entitlements"))
    a = grant_ent()
    await c.write(a, key(a))
    again = await c.write(a, key(a))
    assert again.replayed
    held = (await c.read({"subject_id": "E-1042"}))["holdings"]
    assert held.count("jira-pay") == 1


async def test_revoke_is_verified_by_absence(states):
    c = FixtureEntitlements(states("entitlements"))
    r = grant_ent("looker-risk-dashboards", kind="revoke")
    await c.write(r, key(r))
    ok, observed = await c.verify(r)
    assert ok and observed["present"] is False


async def test_ack_without_apply_is_caught_by_verify(states):
    # P3: a 200 is not done. The system says OK; the state says otherwise.
    c = FixtureEntitlements(states("entitlements"))
    a = grant_ent()
    await c.state.inject_fault("jira-pay", "ack_without_apply")
    assert (await c.write(a, key(a))).ok
    assert (await c.verify(a))[0] is False


async def test_transient_and_unknown_outcomes(states):
    c = FixtureGitHub(states("github"))
    a = gh()
    await c.state.inject_fault("northbeam/payments-api:anil-k-nb", "transient_once")
    with pytest.raises(TransientError):
        await c.write(a, key(a))
    assert (await c.write(a, key(a))).ok  # retry after a transient succeeds
    b = gh("northbeam/payments-web")
    await c.state.inject_fault("northbeam/payments-web:anil-k-nb", "timeout_after_apply")
    with pytest.raises(UnknownOutcome):
        await c.write(b, key(b))
    assert (await c.verify(b))[0] is True  # reconcile: it did happen, so do not retry


async def test_github_grant_and_revoke(states):
    c = FixtureGitHub(states("github"))
    a = gh("northbeam/payments-core")
    await c.write(a, key(a))
    assert (await c.read({"repo": "northbeam/payments-core"}))["collaborators"]["anil-k-nb"] == "read"
    wrong = gh("northbeam/payments-core", permission="write")
    assert (await c.verify(wrong))[0] is False  # read was granted, not write
    r = gh("northbeam/payments-core", kind="revoke")
    await c.write(r, key(r))
    assert (await c.verify(r))[0] is True


async def test_github_unknown_login_or_repo_is_a_permanent_error(states):
    c = FixtureGitHub(states("github"))
    with pytest.raises(ConnectorError):
        await c.write(gh(subject="E-9999"), "k")
    with pytest.raises(ConnectorError):
        await c.write(gh(repo="northbeam/nope"), "k2")


async def test_hris_exact_lookups_return_every_match(states):
    h = FixtureHRIS(states("hris"))
    assert (await h.read({"source_id": "W-8841"}))["display_name"] == "Priya Raghunathan"
    assert [p["source_id"] for p in await h.find_by_name("Rahul")] == ["E-0007", "E-0415"]  # ambiguous: both
    assert [p["source_id"] for p in await h.find_by_name("rahul  mehta")] == ["E-0007"]
    assert await h.find_by_name("Rahu") == []  # no fuzzy matching
    with pytest.raises(ConnectorError):
        await h.write(grant_ent(), "k")


async def test_slack_search_surfaces_the_planted_message(states):
    s = FixtureSlackCorpus(states("slack_corpus"))
    hits = await s.search(["anil", "same as rahul", "access"])
    assert hits[0]["id"] == "slk_payments_admin_override" and hits[0]["planted"]
