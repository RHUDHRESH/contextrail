import uuid

import pytest

from contextrail.connectors.registry import build_registry
from contextrail.models import Action, ActionState, Verdict, apply_verdict
from contextrail.rail.execute import execute_action

RID = uuid.UUID(int=42)


@pytest.fixture
def registry(tmp_path):
    from contextrail.seed import reset_fixture_state

    reset_fixture_state(tmp_path)
    return build_registry(tmp_path)


def allowed(ent="jira-pay", system="jira", **extra):
    a = Action.create("A01", "grant", {"system": system, "entitlement": ent, "subject_id": "E-1042", **extra})
    return apply_verdict(a, Verdict(verdict="ALLOW", rule_id="POL-ACC-001", clause_text="baseline clause text"))


async def _no_sleep(_):
    return None


# --- dispatch with idempotency and backoff (T103) ----------------------------------------------------------

async def test_allowed_action_executes_through_its_connector(registry):
    out = await execute_action(allowed(), run_id=RID, registry=registry, sleep=_no_sleep)
    assert (out.state, out.attempts, out.replayed) == (ActionState.EXECUTED, 1, False)
    assert "jira-pay" in (await registry.get("entitlements").read({"subject_id": "E-1042"}))["holdings"]


async def test_github_actions_route_to_github(registry):
    a = allowed("gh-payments-api-read", "github", repo="northbeam/payments-api", permission="read")
    await execute_action(a, run_id=RID, registry=registry, sleep=_no_sleep)
    assert (await registry.get("github").read({"repo": "northbeam/payments-api"}))["collaborators"]["anil-k-nb"] == "read"


async def test_replayed_execution_writes_once(registry):
    a = allowed()
    await execute_action(a, run_id=RID, registry=registry, sleep=_no_sleep)
    again = await execute_action(allowed(), run_id=RID, registry=registry, sleep=_no_sleep)
    assert again.replayed
    held = (await registry.get("entitlements").read({"subject_id": "E-1042"}))["holdings"]
    assert held.count("jira-pay") == 1


async def test_transient_error_backs_off_then_succeeds(registry):
    waits = []

    async def record(s):
        waits.append(s)

    await registry.get("entitlements").state.inject_fault("jira-pay", "transient_once")
    out = await execute_action(allowed(), run_id=RID, registry=registry, sleep=record)
    assert (out.state, out.attempts) == (ActionState.EXECUTED, 2) and waits == [1.0]


async def test_permanent_error_fails_without_retry(registry):
    out = await execute_action(allowed("no-such-entitlement"), run_id=RID, registry=registry, sleep=_no_sleep)
    assert (out.state, out.attempts) == (ActionState.FAILED, 1) and "permanent" in out.note


async def test_refused_or_unapproved_actions_never_execute(registry):
    refused = apply_verdict(Action.create("A09", "grant", {"entitlement": "aws-payments-prod-admin",
                                                           "subject_id": "E-1042"}),
                            Verdict(verdict="REFUSE", rule_id="POL-ACC-003", clause_text="admin clause text"))
    held = apply_verdict(Action.create("A10", "grant", {"entitlement": "postman-enterprise-seat",
                                                        "subject_id": "E-1042"}),
                         Verdict(verdict="HOLD", rule_id="POL-ACC-005", clause_text="seat clause", approver="p-meera"))
    for a in (refused, held):
        with pytest.raises(ValueError):
            await execute_action(a, run_id=RID, registry=registry, sleep=_no_sleep)
    held.transition("approved")
    assert (await execute_action(held, run_id=RID, registry=registry, sleep=_no_sleep)).state is ActionState.EXECUTED


# --- unknown outcome: reconcile before any retry (T104) ----------------------------------------------------

class CountingConnector:
    """Wraps a fixture connector and counts writes, to prove a reconciled timeout does not write twice."""

    def __init__(self, inner):
        self.inner, self.writes = inner, 0
        self.name, self.mode, self.state = inner.name, inner.mode, inner.state

    async def write(self, action, key):
        self.writes += 1
        return await self.inner.write(action, key)

    async def verify(self, action):
        return await self.inner.verify(action)

    async def read(self, ref):
        return await self.inner.read(ref)


async def test_timeout_after_apply_is_reconciled_without_a_second_write(registry):
    counting = CountingConnector(registry.get("entitlements"))
    registry.connectors["entitlements"] = counting
    await counting.state.inject_fault("jira-pay", "timeout_after_apply")
    out = await execute_action(allowed(), run_id=RID, registry=registry, sleep=_no_sleep)
    assert (out.state, out.attempts, counting.writes) == (ActionState.EXECUTED, 1, 1)
    assert "reconciled" in out.note


async def test_timeout_before_apply_is_retried_with_the_same_key(registry):
    counting = CountingConnector(registry.get("entitlements"))
    registry.connectors["entitlements"] = counting
    await counting.state.inject_fault("jira-pay", "timeout_before_apply")
    out = await execute_action(allowed(), run_id=RID, registry=registry, sleep=_no_sleep)
    assert (out.state, out.attempts, counting.writes) == (ActionState.EXECUTED, 2, 2)
    assert (await counting.verify(allowed()))[0]


async def test_unreconcilable_timeout_stops_at_unknown(registry):
    class Opaque(CountingConnector):
        async def write(self, action, key):
            from contextrail.connectors.base import UnknownOutcome
            raise UnknownOutcome("timed out")

        async def verify(self, action):
            from contextrail.connectors.base import ConnectorError
            raise ConnectorError("read-back unavailable")

    registry.connectors["entitlements"] = Opaque(registry.get("entitlements"))
    out = await execute_action(allowed(), run_id=RID, registry=registry, sleep=_no_sleep)
    assert out.state is ActionState.UNKNOWN and out.attempts == 1  # no blind retry
