"""CLAUDE.md §18 test_verify_not_success.py: a connector returns 200 but the state is absent -> failed, not verified."""

import uuid

import pytest

from contextrail.connectors.registry import build_registry
from contextrail.models import Action, ActionState, Verdict, apply_verdict
from contextrail.rail.execute import execute_action
from contextrail.rail.verify import verify_action

RID = uuid.UUID(int=7)


@pytest.fixture
def registry(tmp_path):
    from contextrail.seed import reset_fixture_state

    reset_fixture_state(tmp_path)
    return build_registry(tmp_path)


def allowed(ent="jira-pay", **target):
    a = Action.create("A01", "grant", {"system": target.pop("system", "jira"), "entitlement": ent,
                                       "subject_id": "E-1042", **target})
    return apply_verdict(a, Verdict(verdict="ALLOW", rule_id="POL-ACC-001", clause_text="baseline clause text"))


async def _run(action, registry):
    async def no_sleep(_):
        return None
    out = await execute_action(action, run_id=RID, registry=registry, sleep=no_sleep)
    action.transition(out.state)
    return out, await verify_action(action, registry=registry)


async def test_a_real_write_is_verified_with_a_timestamp(registry):
    out, v = await _run(allowed(), registry)
    assert out.state is ActionState.EXECUTED and v.state is ActionState.VERIFIED and v.at is not None
    assert v.observed["present"] is True


async def test_acknowledged_but_not_applied_is_failed_not_verified(registry):
    await registry.get("entitlements").state.inject_fault("jira-pay", "ack_without_apply")
    out, v = await _run(allowed(), registry)
    assert out.state is ActionState.EXECUTED       # the system said OK...
    assert v.state is ActionState.FAILED           # ...and the read-back says otherwise
    assert v.observed["present"] is False and "does not match" in v.note


async def test_github_permission_mismatch_fails(registry):
    await registry.get("github").state.inject_fault("northbeam/payments-api:anil-k-nb", "ack_without_apply")
    _, v = await _run(allowed("gh-payments-api-read", system="github", repo="northbeam/payments-api",
                              permission="read"), registry)
    assert v.state is ActionState.FAILED and v.observed["permission"] is None


async def test_only_executed_actions_are_verified(registry):
    with pytest.raises(ValueError):
        await verify_action(allowed(), registry=registry)  # still 'planned'
