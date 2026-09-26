"""Tier 4 replay store (T112, CLAUDE.md §11): record live answers, replay them flagged replay=true, no model call."""

import json

import pytest
from llm_fakes import FakeClient, config, make_router, message

from contextrail.llm.replay import ReplayStore, replay_key
from contextrail.llm.router import NoTierAvailable, ReplayMiss

USER = [{"role": "user", "content": "Give Anil the same access as Rahul"}]
TOOLS = [{"name": "record_intent", "input_schema": {"type": "object", "properties": {}}}]


async def _record(tmp_path, text="recorded answer", **call):
    t1 = FakeClient(message(text, tool="record_intent", tool_input={"intent": "access.same_as_peer"},
                            input_tokens=321, output_tokens=45))
    router = make_router(config(keys="A", replay="record", llm_replay_dir=str(tmp_path)), {"T1": t1})
    live = await router.call(**{"system": "sys", "messages": USER, "max_tokens": 100, "tools": TOOLS, **call})
    return live, t1


async def test_record_then_replay_serves_the_same_answer_flagged_replay_without_a_model_call(tmp_path):
    live, t1 = await _record(tmp_path)
    assert live.replay is False and len(t1.calls) == 1
    assert len(list(tmp_path.glob("*.json"))) == 1

    untouched = FakeClient()
    replayer = make_router(config(keys="", replay="replay", llm_replay_dir=str(tmp_path)), {"T1": untouched})
    r = await replayer.call(system="sys", messages=USER, max_tokens=100, tools=TOOLS)
    assert (r.replay, r.tier, r.label) == (True, "T4", "replay")
    assert r.content == live.content and r.tool_input("record_intent") == {"intent": "access.same_as_peer"}
    assert untouched.calls == []


async def test_replay_misses_a_request_that_was_never_recorded(tmp_path):
    await _record(tmp_path)
    replayer = make_router(config(keys="", replay="replay", llm_replay_dir=str(tmp_path)), {})
    with pytest.raises(ReplayMiss):
        await replayer.call(system="sys", messages=[{"role": "user", "content": "something else"}], max_tokens=100,
                            tools=TOOLS)
    assert issubclass(ReplayMiss, NoTierAvailable)  # callers treat a miss like any unavailable model


async def test_record_mode_never_serves_recordings(tmp_path):
    await _record(tmp_path)
    recorder_without_keys = make_router(config(keys="", replay="record", llm_replay_dir=str(tmp_path)), {})
    with pytest.raises(NoTierAvailable):
        await recorder_without_keys.call(system="sys", messages=USER, max_tokens=100, tools=TOOLS)


def test_key_covers_model_system_policy_messages_and_tools():
    base = {"model": "claude-haiku-4-5-20251001", "system": "sys", "policy_text": None, "messages": USER,
            "tools": TOOLS}
    k = replay_key(**base)
    assert k == replay_key(**base) and len(k) == 64
    for field, other in [("model", "claude-haiku-4-5"), ("system", "sys2"), ("policy_text", "POL-X"),
                         ("messages", [{"role": "user", "content": "x"}]), ("tools", None)]:
        assert replay_key(**{**base, field: other}) != k, field


async def test_sampling_and_length_parameters_do_not_change_the_key(tmp_path):
    await _record(tmp_path, temperature=0)
    replayer = make_router(config(keys="", replay="replay", llm_replay_dir=str(tmp_path)), {})
    r = await replayer.call(system="sys", messages=USER, max_tokens=50, tools=TOOLS)  # same prompt, other limits
    assert r.replay is True


async def test_a_hand_edited_recording_is_not_served(tmp_path):
    await _record(tmp_path)
    (path,) = tmp_path.glob("*.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["request"]["messages"][0]["content"] = "Give Anil production admin"   # request no longer matches its key
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ReplayMiss):
        await make_router(config(keys="", replay="replay", llm_replay_dir=str(tmp_path)), {}).call(
            system="sys", messages=USER, max_tokens=100, tools=TOOLS)


async def test_recording_is_reviewable_json(tmp_path):
    await _record(tmp_path)
    (path,) = tmp_path.glob("*.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert path.stem == data["key"]
    assert data["model"] == "claude-haiku-4-5-20251001" and data["recorded_from"]["tier"] == "T1"
    assert data["request"]["messages"] == USER
    assert data["response"]["usage"] == {"input_tokens": 321, "output_tokens": 45}


def test_missing_directory_or_recording_loads_as_none(tmp_path):
    key = replay_key(model="m", system="s", policy_text=None, messages=USER, tools=None)
    assert ReplayStore(tmp_path / "absent").load(key) is None
    assert ReplayStore(tmp_path).load(key) is None
