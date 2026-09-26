"""The LLM router (CLAUDE.md §11): T1 -> T2 -> T3 (Bedrock) -> T4 (replay), tier recorded on every call.

Configuration (T109) is read once from Settings. The tier order is fixed; configuration only decides which tiers are
enabled and which model ID each tier sends. Callers name a model by alias ("haiku", "sonnet"); the logical model ID
behind the alias (the first-party ID) is what prices a call and keys a replay recording, whichever tier served it.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from contextrail.fixtures import fixtures_dir
from contextrail.settings import Settings

Tier = Literal["T1", "T2", "T3", "T4"]
Provider = Literal["anthropic", "bedrock", "replay"]
ReplayMode = Literal["off", "record", "replay"]


class TierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tier: Tier
    provider: Provider
    enabled: bool
    models: dict[str, str]  # alias -> the model ID this tier sends; a missing alias is not served by this tier


class RouterConfig(BaseModel):
    """Everything the router needs except secrets: API keys stay in Settings and go straight into the clients."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tiers: tuple[TierConfig, ...]
    models: dict[str, str]              # alias -> logical (first-party) model ID
    run_budget_usd: Decimal
    bedrock_budget_usd: Decimal
    replay_mode: ReplayMode
    replay_dir: Path
    breaker_cooldown_s: float = 180.0   # a failed tier is skipped this long (§11)
    timeout_s: float = 30.0             # per request; a timeout fails over
    max_retry_after_s: float = 10.0     # cap on the one retry-after wait before a 429 fails over

    @classmethod
    def from_settings(cls, s: Settings) -> RouterConfig:
        direct = {"haiku": s.haiku_model, "sonnet": s.sonnet_model}
        bedrock = {k: v for k, v in {"haiku": s.bedrock_haiku_id, "sonnet": s.bedrock_sonnet_id}.items() if v}
        return cls(
            tiers=(
                TierConfig(tier="T1", provider="anthropic", enabled=bool(s.anthropic_key_a.get_secret_value()),
                           models=direct),
                TierConfig(tier="T2", provider="anthropic", enabled=bool(s.anthropic_key_b.get_secret_value()),
                           models=direct),
                TierConfig(tier="T3", provider="bedrock", enabled=s.bedrock_enabled, models=bedrock),
                TierConfig(tier="T4", provider="replay", enabled=s.llm_replay_mode == "replay", models=direct),
            ),
            models=direct,
            run_budget_usd=s.run_budget_usd,
            bedrock_budget_usd=s.bedrock_budget_usd,
            replay_mode=s.llm_replay_mode,
            replay_dir=Path(s.llm_replay_dir) if s.llm_replay_dir else fixtures_dir() / "llm_replay",
        )

    def chain(self, alias: str) -> list[TierConfig]:
        """The enabled tiers that can serve this model, in failover order."""
        if alias not in self.models:
            raise ValueError(f"unknown model alias {alias!r}; expected one of {sorted(self.models)}")
        return [t for t in self.tiers if t.enabled and t.models.get(alias)]
