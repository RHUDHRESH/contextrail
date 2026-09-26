"""The LLM router (CLAUDE.md §11): T1 -> T2 -> T3 (Bedrock) -> T4 (replay), tier recorded on every call.

Configuration (T109) is read once from Settings. The tier order is fixed; configuration only decides which tiers are
enabled and which model ID each tier sends. Callers name a model by alias ("haiku", "sonnet"); the logical model ID
behind the alias (the first-party ID) is what prices a call and keys a replay recording, whichever tier served it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from anthropic import Anthropic
from anthropic.types import MessageParam
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


# --- errors: callers catch LLMError and fall back to their deterministic path --------------------------------

class LLMError(Exception):
    """Base for every failure the router reports. The rail treats any of these as 'no model answer'."""


class NoTierAvailable(LLMError):
    """No enabled tier could serve the call (none configured, all failed over, or all skipped)."""


# --- responses -----------------------------------------------------------------------------------------------

class LLMResponse(BaseModel):
    """One model answer, with where it came from. Content blocks are plain dicts (text / tool_use)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tier: Tier
    model: str                  # the model ID the serving tier was sent
    replay: bool = False
    content: list[dict]
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text").strip()

    def tool_input(self, name: str) -> dict | None:
        return next((b["input"] for b in self.content if b.get("type") == "tool_use" and b.get("name") == name), None)

    @property
    def label(self) -> str:
        """How every door and audit event names the author of model-written text."""
        return "replay" if self.replay else f"llm:{self.tier}"


# --- clients (T110) ------------------------------------------------------------------------------------------

def build_clients(s: Settings, config: RouterConfig) -> dict[Tier, Any]:
    """One SDK client per enabled live tier. `max_retries=0`: the SDK would otherwise retry 429/5xx twice on its
    own, and the router must own retries and failover (T113) so the tier it logs is the tier that answered."""
    keys = {"T1": s.anthropic_key_a, "T2": s.anthropic_key_b}
    return {t.tier: Anthropic(api_key=keys[t.tier].get_secret_value(), max_retries=0, timeout=config.timeout_s)
            for t in config.tiers if t.provider == "anthropic" and t.enabled}


# --- the router ----------------------------------------------------------------------------------------------

class Router:
    """Calls the first tier of the chain that can serve the model. The SDK clients are synchronous (`Anthropic`,
    `AnthropicBedrock`, per CLAUDE.md §11), so each call runs in a worker thread to keep the event loop free."""

    def __init__(self, config: RouterConfig, clients: Mapping[str, Any]) -> None:
        self.config = config
        self.clients = dict(clients)

    async def call(self, *, model: str, system: str, messages: list[MessageParam], max_tokens: int,
                   tools: list[dict] | None = None, tool_choice: dict | None = None,
                   thinking: dict | None = None) -> LLMResponse:
        chain = [t for t in self.config.chain(model) if t.tier in self.clients]
        if not chain:
            raise NoTierAvailable(f"no enabled tier can serve {model!r}")
        tier = chain[0]
        request: dict[str, Any] = {"model": tier.models[model], "system": system, "messages": messages,
                                   "max_tokens": max_tokens}
        optional = {"tools": tools, "tool_choice": tool_choice, "thinking": thinking}
        request.update({k: v for k, v in optional.items() if v is not None})
        t0 = time.perf_counter()
        msg = await asyncio.to_thread(self.clients[tier.tier].messages.create, **request)
        return LLMResponse(
            tier=tier.tier, model=request["model"], stop_reason=msg.stop_reason,
            content=[b.model_dump(mode="json", exclude_none=True) for b in msg.content],
            input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens,
            latency_ms=int((time.perf_counter() - t0) * 1000))
