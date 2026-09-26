"""Router configuration from settings (T109, CLAUDE.md §11): tiers in fixed order, model IDs per tier, budgets."""

from decimal import Decimal
from pathlib import Path

import pytest

from contextrail.llm.router import RouterConfig
from contextrail.settings import Settings


@pytest.fixture(autouse=True)
def _no_llm_env(monkeypatch):
    for k in ("ANTHROPIC_KEY_A", "ANTHROPIC_KEY_B", "BEDROCK_ENABLED", "BEDROCK_SONNET_ID", "LLM_REPLAY_MODE",
              "LLM_REPLAY_DIR", "RUN_BUDGET_USD", "BEDROCK_BUDGET_USD", "HAIKU_MODEL", "SONNET_MODEL", "FIXTURES_DIR"):
        monkeypatch.delenv(k, raising=False)


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _tiers(cfg: RouterConfig, alias: str) -> list[tuple[str, str]]:
    return [(t.tier, t.models[alias]) for t in cfg.chain(alias)]


def test_nothing_configured_means_no_tier():
    cfg = RouterConfig.from_settings(_settings())
    assert cfg.chain("haiku") == [] and cfg.chain("sonnet") == []
    assert [t.tier for t in cfg.tiers] == ["T1", "T2", "T3", "T4"]  # the order is fixed; only enablement varies


def test_one_key_enables_only_its_tier():
    cfg = RouterConfig.from_settings(_settings(anthropic_key_a="test-key-a"))
    assert _tiers(cfg, "haiku") == [("T1", "claude-haiku-4-5-20251001")]
    assert _tiers(cfg, "sonnet") == [("T1", "claude-sonnet-5")]


def test_full_chain_in_failover_order_with_bedrock_ids():
    cfg = RouterConfig.from_settings(_settings(
        anthropic_key_a="test-key-a", anthropic_key_b="test-key-b", bedrock_enabled=True,
        bedrock_sonnet_id="global.anthropic.claude-sonnet-5-v1:0", llm_replay_mode="replay"))
    assert _tiers(cfg, "haiku") == [("T1", "claude-haiku-4-5-20251001"), ("T2", "claude-haiku-4-5-20251001"),
                                    ("T3", "global.anthropic.claude-haiku-4-5-20251001-v1:0"),
                                    ("T4", "claude-haiku-4-5-20251001")]
    assert [t.provider for t in cfg.chain("haiku")] == ["anthropic", "anthropic", "bedrock", "replay"]


def test_bedrock_tier_skips_a_model_without_a_bedrock_id():
    cfg = RouterConfig.from_settings(_settings(anthropic_key_a="test-key-a", bedrock_enabled=True))
    assert [t for t, _ in _tiers(cfg, "haiku")] == ["T1", "T3"]
    assert [t for t, _ in _tiers(cfg, "sonnet")] == ["T1"]  # BEDROCK_SONNET_ID is empty by default


def test_replay_tier_only_in_replay_mode():
    record = RouterConfig.from_settings(_settings(llm_replay_mode="record"))
    replay = RouterConfig.from_settings(_settings(llm_replay_mode="replay"))
    assert record.chain("haiku") == []                  # recording writes; it never serves
    assert [t.tier for t in replay.chain("haiku")] == ["T4"]


def test_logical_models_and_budgets_come_from_settings():
    cfg = RouterConfig.from_settings(_settings(run_budget_usd=Decimal("0.25"), bedrock_budget_usd=Decimal(12),
                                               sonnet_model="claude-sonnet-5"))
    assert cfg.models == {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-5"}
    assert (cfg.run_budget_usd, cfg.bedrock_budget_usd) == (Decimal("0.25"), Decimal(12))
    assert cfg.breaker_cooldown_s == 180


def test_defaults_match_the_brief():
    cfg = RouterConfig.from_settings(_settings())
    assert (cfg.run_budget_usd, cfg.bedrock_budget_usd) == (Decimal("0.50"), Decimal(30))


def test_replay_dir_default_and_override(tmp_path):
    assert RouterConfig.from_settings(_settings()).replay_dir.parts[-2:] == ("fixtures", "llm_replay")
    assert RouterConfig.from_settings(_settings(llm_replay_dir=str(tmp_path))).replay_dir == Path(tmp_path)


def test_unknown_model_alias_is_an_error():
    with pytest.raises(ValueError, match="opus"):
        RouterConfig.from_settings(_settings()).chain("opus")


def test_config_carries_no_secrets():
    cfg = RouterConfig.from_settings(_settings(anthropic_key_a="test-key-a-do-not-print"))
    assert "test-key-a-do-not-print" not in repr(cfg) and "test-key-a-do-not-print" not in cfg.model_dump_json()
