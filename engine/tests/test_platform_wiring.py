"""Composition root: curated knowledge, run-scoped model intent, and the worker's outbound Slack door."""

from llm_fakes import FakeClient, message

from contextrail.app_state import build_platform
from contextrail.llm.adapters import LLMIntentExtractor
from contextrail.models import RunStatus
from contextrail.rail.discover import HeuristicExtractor
from contextrail.settings import Settings


def settings(tmp_path, **overrides) -> Settings:
    fields = {"state_dir": str(tmp_path / "state"), "anthropic_key_a": "", "anthropic_key_b": "",
              "bedrock_enabled": False, "llm_replay_mode": "off", "slack_bot_token": "",
              "slack_signing_secret": ""}
    fields.update(overrides)
    return Settings(_env_file=None, **fields)


def test_default_platform_loads_curated_knowledge_and_uses_heuristic_without_a_tier(tmp_path):
    platform = build_platform(settings(tmp_path))
    assert isinstance(platform.runner.d.extractor, HeuristicExtractor)
    bundle = platform.runner.d.knowledge
    assert bundle is not None and "policies/access-control-standard.md" in bundle.pages
    assert platform.slack is None


def test_explicit_knowledge_dir_is_the_bundle_the_rail_receives(tmp_path):
    root = tmp_path / "kb"
    root.mkdir()
    (root / "example.md").write_text("---\ntype: policy\ntitle: Example\n---\n# Example\nOne clause.\n",
                                     encoding="utf-8")
    platform = build_platform(settings(tmp_path, knowledge_dir=str(root)))
    assert platform.runner.d.knowledge.root == root
    assert set(platform.runner.d.knowledge.pages) == {"example.md"}


async def test_configured_model_extracts_intent_with_the_actual_run_id(migrated_db, tmp_path):
    platform = build_platform(settings(tmp_path, database_url=migrated_db, anthropic_key_a="test-key"))
    extractor = platform.runner.d.extractor
    assert isinstance(extractor, LLMIntentExtractor)
    assert extractor.run_id is None and extractor.router.ledger.db is platform.db
    client = FakeClient(message(None, tool="extract_intent", tool_input={"intent": "query", "kind": "query"}))
    extractor.router.clients["T1"] = client

    async with platform.serving(worker=False):
        run_id = await platform.runner.start(source="slack", request_text="What happened to my request?")
        assert await platform.runner.run(run_id) is RunStatus.DONE
        async with platform.db.connection() as conn:
            (call,) = await (await conn.execute("select run_id, stage from llm_calls")).fetchall()
            (audit,) = await (await conn.execute(
                "select payload from audit where run_id = %s and event = 'stage.discover'", (run_id,))).fetchall()
    assert (call["run_id"], call["stage"]) == (run_id, "discover")
    assert audit["payload"]["extractor"] == "llm:T1"
    assert extractor.run_id is None  # no shared mutable run context after the call


async def test_bot_token_alone_creates_outbound_slack_door_without_an_http_secret(rail, tmp_path):
    runner, _ = rail
    platform = build_platform(settings(tmp_path, slack_bot_token="xoxb-test"), runner=runner)
    async with platform.serving(worker=False):
        assert platform.slack is not None and platform.slack.door is platform.door
    assert platform.slack is not None


async def test_serving_reuses_a_pre_attached_slack_door(rail, tmp_path):
    runner, _ = rail
    platform = build_platform(settings(tmp_path, slack_bot_token="xoxb-test"), runner=runner)
    attached = object()
    platform.slack = attached
    async with platform.serving(worker=False):
        assert platform.slack is attached
