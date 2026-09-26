"""Router failover (T113, CLAUDE.md §11, §18): T1 429 -> T2; T2 credit error -> T3; non-credit 400 -> no failover.

Fail over on: 429 (after one retry-after wait), 529, 5xx, timeouts (and connection failures), credit-exhausted /
billing errors. Every other error, including every other 4xx, is raised to the caller: the next tier would get the
same bad request.
"""

import anthropic
import pytest
from llm_fakes import (
    CREDIT_MESSAGE,
    FakeClient,
    Sleeps,
    api_error,
    config,
    connection_error,
    message,
    timeout_error,
)

from contextrail.llm.router import LLMCallError, NoTierAvailable, Router, classify

USER = [{"role": "user", "content": "hi"}]


def _router(clients: dict, sleeps: Sleeps | None = None, **cfg) -> Router:
    return Router(config(**{"keys": "AB", "bedrock": True, **cfg}), clients, sleep=sleeps or Sleeps())


async def _call(router: Router):
    return await router.call(system="s", messages=USER, max_tokens=10)


# --- the three cases CLAUDE.md §18 names -------------------------------------------------------------------

async def test_t1_429_waits_once_then_fails_over_to_t2():
    sleeps = Sleeps()
    t1 = FakeClient(api_error(429, headers={"retry-after": "2"}), api_error(429, headers={"retry-after": "2"}))
    t2 = FakeClient(message("from T2"))
    r = await _call(_router({"T1": t1, "T2": t2, "T3": FakeClient()}, sleeps))
    assert (r.tier, r.text) == ("T2", "from T2")
    assert len(t1.calls) == 2 and sleeps.waits == [2.0]  # exactly one retry-after wait, then fail over


async def test_t2_credit_error_fails_over_to_t3():
    t1 = FakeClient(api_error(529, error_type="overloaded_error"))
    t2 = FakeClient(api_error(400, CREDIT_MESSAGE, error_type="invalid_request_error"))
    t3 = FakeClient(message("from Bedrock"))
    r = await _call(_router({"T1": t1, "T2": t2, "T3": t3}))
    assert (r.tier, r.model, r.text) == ("T3", "global.anthropic.claude-haiku-4-5-20251001-v1:0", "from Bedrock")
    assert t3.calls[0]["model"] == "global.anthropic.claude-haiku-4-5-20251001-v1:0"


async def test_non_credit_400_does_not_fail_over():
    sleeps = Sleeps()
    t1 = FakeClient(api_error(400, "messages: roles must alternate", error_type="invalid_request_error"))
    t2, t3 = FakeClient(), FakeClient()
    with pytest.raises(LLMCallError) as err:
        await _call(_router({"T1": t1, "T2": t2, "T3": t3}, sleeps))
    assert (err.value.tier, err.value.status) == ("T1", 400)
    assert t2.calls == [] and t3.calls == [] and sleeps.waits == []


# --- the rest of the rule ------------------------------------------------------------------------------------

async def test_429_then_success_stays_on_the_same_tier():
    sleeps = Sleeps()
    t1 = FakeClient(api_error(429, headers={"retry-after": "1"}), message("second try"))
    t2 = FakeClient()
    r = await _call(_router({"T1": t1, "T2": t2}, sleeps))
    assert (r.tier, r.text, sleeps.waits, t2.calls) == ("T1", "second try", [1.0], [])


@pytest.mark.parametrize(("headers", "wait"), [
    ({"retry-after": "120"}, 10.0),      # capped: max_retry_after_s
    ({"retry-after-ms": "500"}, 0.5),    # the SDK's own precise header wins
    ({}, 1.0),                           # no header: a short default
    ({"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"}, 1.0),  # HTTP-date form is not trusted for a wait
])
async def test_retry_after_wait_is_parsed_and_capped(headers, wait):
    sleeps = Sleeps()
    t1 = FakeClient(api_error(429, headers=headers), message("ok"))
    await _call(_router({"T1": t1}, sleeps))
    assert sleeps.waits == [wait]


@pytest.mark.parametrize("failure", [
    api_error(529, error_type="overloaded_error"),
    api_error(500, error_type="api_error"),
    api_error(503, error_type="api_error"),
    api_error(503, bedrock=True),
    api_error(402, "billing problem"),
    api_error(400, "account suspended for billing", error_type="billing_error"),
    timeout_error(),
    connection_error(),
])
async def test_failover_class_errors_move_to_the_next_tier(failure):
    t1, t2 = FakeClient(failure), FakeClient(message("next"))
    r = await _call(_router({"T1": t1, "T2": t2}))
    assert r.tier == "T2" and len(t1.calls) == 1  # no retry on the failing tier


@pytest.mark.parametrize("failure", [
    api_error(401, error_type="authentication_error"),
    api_error(403, error_type="permission_error"),
    api_error(404, error_type="not_found_error"),
    api_error(413, error_type="request_too_large"),
    api_error(422, error_type="invalid_request_error"),
])
async def test_other_4xx_are_raised_not_failed_over(failure):
    t2 = FakeClient()
    with pytest.raises(LLMCallError):
        await _call(_router({"T1": FakeClient(failure), "T2": t2}))
    assert t2.calls == []


async def test_an_unexpected_client_exception_is_reported_not_failed_over():
    t2 = FakeClient()
    with pytest.raises(LLMCallError, match="RuntimeError"):
        await _call(_router({"T1": FakeClient(RuntimeError("could not resolve credentials")), "T2": t2}))
    assert t2.calls == []


async def test_every_tier_failing_is_no_tier_available():
    with pytest.raises(NoTierAvailable, match="T1.*T2.*T3"):
        await _call(_router({"T1": FakeClient(api_error(500)), "T2": FakeClient(timeout_error()),
                             "T3": FakeClient(api_error(503, bedrock=True))}))


async def test_live_failures_fall_through_to_replay(tmp_path):
    recorder = Router(config(keys="A", replay="record", llm_replay_dir=str(tmp_path)),
                      {"T1": FakeClient(message("recorded"))})
    await _call(recorder)
    r = await _call(_router({"T1": FakeClient(api_error(529)), "T2": FakeClient(timeout_error()),
                             "T3": FakeClient(api_error(500, bedrock=True))},
                            replay="replay", llm_replay_dir=str(tmp_path)))
    assert (r.tier, r.replay, r.text) == ("T4", True, "recorded")


@pytest.mark.parametrize(("error", "kind"), [
    (api_error(429), "rate_limited"),
    (api_error(529), "failover"),
    (api_error(502), "failover"),
    (api_error(400, CREDIT_MESSAGE), "failover"),
    (api_error(402), "failover"),
    (api_error(400, "bad"), "fatal"),
    (api_error(401), "fatal"),
    (timeout_error(), "failover"),
    (connection_error(), "failover"),
    (ValueError("ours"), "fatal"),
])
def test_classify(error, kind):
    assert classify(error) == kind


def test_the_sdk_timeout_is_a_connection_error_subclass():
    assert issubclass(anthropic.APITimeoutError, anthropic.APIConnectionError)
