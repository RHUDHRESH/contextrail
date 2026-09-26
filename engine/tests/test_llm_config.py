"""Router configuration from settings (T109, CLAUDE.md §11, D-013): tiers in fixed order, the one model (Claude
Haiku 4.5) per tier, budgets."""

from decimal import Decimal
from pathlib import Path

import pytest

from contextrail.llm.router import HAIKU_BEDROCK_ID, HAIKU_DIRECT_ID, ModelNotAllowed, RouterConfig
from contextrail.settings import Settings


@pytest.fixture(autouse=True)
def _no_llm_env(monkeypatch):
    for k in ("ANTHROPIC_KEY_A", "ANTHROPIC_KEY_B", "BEDROCK_ENABLED", "BEDROCK_HAIKU_ID", "BEDROCK_SONNET_ID",
              "LLM_REPLAY_MODE", "LLM_REPLAY_DIR", "RUN_BUDGET_USD", "BEDROCK_BUDGET_USD", "HAIKU_MODEL",
              "SONNET_MODEL", "FIXTURES_DIR"):
        monkeypatch.delenv(k, raising=False)


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _tiers(cfg: RouterConfig) -> list[tuple[str, str]]:
    return [(t.tier, t.model) for t in cfg.chain()]


def test_the_only_model_is_claude_haiku_4_5():
    assert (HAIKU_DIRECT_ID, HAIKU_BEDROCK_ID) == ("claude-haiku-4-5-20251001",
                                                   "global.anthropic.claude-haiku-4-5-20251001-v1:0")


def test_nothing_configured_means_no_tier():
    cfg = RouterConfig.from_settings(_settings())
    assert cfg.chain() == []
    assert [t.tier for t in cfg.tiers] == ["T1", "T2", "T3", "T4"]  # the order is fixed; only enablement varies


def test_key_a_only_enables_t1_and_t2_stays_unavailable():
    cfg = RouterConfig.from_settings(_settings(anthropic_key_a="test-key-a"))
    assert _tiers(cfg) == [("T1", HAIKU_DIRECT_ID)]


def test_full_chain_in_failover_order_all_haiku():
    cfg = RouterConfig.from_settings(_settings(anthropic_key_a="test-key-a", anthropic_key_b="test-key-b",
                                               bedrock_enabled=True, llm_replay_mode="replay"))
    assert _tiers(cfg) == [("T1", HAIKU_DIRECT_ID), ("T2", HAIKU_DIRECT_ID), ("T3", HAIKU_BEDROCK_ID),
                           ("T4", HAIKU_DIRECT_ID)]
    assert [t.provider for t in cfg.chain()] == ["anthropic", "anthropic", "bedrock", "replay"]


def test_replay_tier_only_in_replay_mode():
    record = RouterConfig.from_settings(_settings(llm_replay_mode="record"))
    replay = RouterConfig.from_settings(_settings(llm_replay_mode="replay"))
    assert record.chain() == []                  # recording writes; it never serves
    assert [t.tier for t in replay.chain()] == ["T4"]


def test_a_non_haiku_direct_model_is_refused_at_configuration():
    with pytest.raises(ModelNotAllowed, match="claude-sonnet-5"):
        RouterConfig.from_settings(_settings(haiku_model="claude-sonnet-5"))


def test_a_non_haiku_bedrock_model_is_refused_at_configuration():
    with pytest.raises(ModelNotAllowed, match="sonnet"):
        RouterConfig.from_settings(_settings(bedrock_haiku_id="global.anthropic.claude-sonnet-5-v1:0"))


def test_sonnet_settings_are_ignored():
    plain = RouterConfig.from_settings(_settings(anthropic_key_a="test-key-a", bedrock_enabled=True))
    with_sonnet = RouterConfig.from_settings(_settings(anthropic_key_a="test-key-a", bedrock_enabled=True,
                                                       sonnet_model="claude-sonnet-5",
                                                       bedrock_sonnet_id="global.anthropic.claude-sonnet-5-v1:0"))
    assert plain == with_sonnet
    assert "sonnet" not in with_sonnet.model_dump_json()


def test_check_model_allows_only_the_configured_haiku_ids():
    cfg = RouterConfig.from_settings(_settings())
    cfg.check_model(HAIKU_DIRECT_ID)
    cfg.check_model(HAIKU_BEDROCK_ID)
    for other in ("claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5", "haiku"):
        with pytest.raises(ModelNotAllowed):
            cfg.check_model(other)


def test_budgets_come_from_settings():
    cfg = RouterConfig.from_settings(_settings(run_budget_usd=Decimal("0.25"), bedrock_budget_usd=Decimal(12)))
    assert (cfg.run_budget_usd, cfg.bedrock_budget_usd) == (Decimal("0.25"), Decimal(12))
    assert cfg.breaker_cooldown_s == 180


def test_defaults_run_cap_050_and_bedrock_hard_cap_20():
    cfg = RouterConfig.from_settings(_settings())
    assert (cfg.run_budget_usd, cfg.bedrock_budget_usd) == (Decimal("0.50"), Decimal(20))
    assert cfg.max_tokens_cap == 800  # CLAUDE.md §11: Haiku calls stay small


def test_env_example_bedrock_cap_is_20():
    root = Path(__file__).resolve().parents[2]
    assert "\nBEDROCK_BUDGET_USD=20\n" in (root / ".env.example").read_text(encoding="utf-8")


def test_replay_dir_default_and_override(tmp_path):
    assert RouterConfig.from_settings(_settings()).replay_dir.parts[-2:] == ("fixtures", "llm_replay")
    assert RouterConfig.from_settings(_settings(llm_replay_dir=str(tmp_path))).replay_dir == Path(tmp_path)


def test_config_carries_no_secrets():
    cfg = RouterConfig.from_settings(_settings(anthropic_key_a="test-key-a-do-not-print"))
    assert "test-key-a-do-not-print" not in repr(cfg) and "test-key-a-do-not-print" not in cfg.model_dump_json()
