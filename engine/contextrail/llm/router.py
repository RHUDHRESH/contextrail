"""The LLM router (CLAUDE.md §11): T1 -> T2 -> T3 (Bedrock) -> T4 (replay), tier recorded on every call.

One model only: Claude Haiku 4.5 (D-013). The direct tiers send `claude-haiku-4-5-20251001`; Bedrock sends the global
inference profile `global.anthropic.claude-haiku-4-5-20251001-v1:0`. Any other model is refused, both when the
router is configured and when a call names one. The settings `sonnet_model` / `bedrock_sonnet_id` are not read.

Configuration (T109) is read once from Settings. The tier order is fixed; configuration only decides which tiers are
enabled. The direct model ID is the logical model: it prices every call and keys replay recordings, whichever tier
served it.
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

HAIKU_DIRECT_ID = "claude-haiku-4-5-20251001"
HAIKU_BEDROCK_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"


class ModelNotAllowed(ValueError):
    """A model other than Claude Haiku 4.5 was configured or requested (D-013). A caller bug, so it is loud."""


class TierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tier: Tier
    provider: Provider
    enabled: bool
    model: str  # the model ID this tier sends


class RouterConfig(BaseModel):
    """Everything the router needs except secrets: API keys stay in Settings and go straight into the clients."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tiers: tuple[TierConfig, ...]
    model: str                          # the logical model (direct Haiku ID): prices calls, keys replays
    run_budget_usd: Decimal
    bedrock_budget_usd: Decimal
    replay_mode: ReplayMode
    replay_dir: Path
    breaker_cooldown_s: float = 180.0   # a failed tier is skipped this long (§11)
    timeout_s: float = 30.0             # per request; a timeout fails over
    max_retry_after_s: float = 10.0     # cap on the one retry-after wait before a 429 fails over
    max_tokens_cap: int = 800           # §11: Haiku calls stay small; callers use far less (<= 300)

    @classmethod
    def from_settings(cls, s: Settings) -> RouterConfig:
        for configured, allowed in ((s.haiku_model, HAIKU_DIRECT_ID), (s.bedrock_haiku_id, HAIKU_BEDROCK_ID)):
            if configured != allowed:
                raise ModelNotAllowed(f"only Claude Haiku 4.5 is allowed (D-013): got {configured!r}, "
                                      f"expected {allowed!r}")
        return cls(
            tiers=(
                TierConfig(tier="T1", provider="anthropic", enabled=bool(s.anthropic_key_a.get_secret_value()),
                           model=HAIKU_DIRECT_ID),
                TierConfig(tier="T2", provider="anthropic", enabled=bool(s.anthropic_key_b.get_secret_value()),
                           model=HAIKU_DIRECT_ID),
                TierConfig(tier="T3", provider="bedrock", enabled=s.bedrock_enabled, model=HAIKU_BEDROCK_ID),
                TierConfig(tier="T4", provider="replay", enabled=s.llm_replay_mode == "replay",
                           model=HAIKU_DIRECT_ID),
            ),
            model=HAIKU_DIRECT_ID,
            run_budget_usd=s.run_budget_usd,
            bedrock_budget_usd=s.bedrock_budget_usd,
            replay_mode=s.llm_replay_mode,
            replay_dir=Path(s.llm_replay_dir) if s.llm_replay_dir else fixtures_dir() / "llm_replay",
        )

    def chain(self) -> list[TierConfig]:
        """The enabled tiers, in failover order."""
        return [t for t in self.tiers if t.enabled]

    def check_model(self, model: str) -> None:
        """A call may name the model, but only as one of the configured Haiku IDs."""
        if model not in {t.model for t in self.tiers}:
            raise ModelNotAllowed(f"model {model!r} is not allowed; only Claude Haiku 4.5 ({self.model}) (D-013)")


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
    """Calls Claude Haiku 4.5 on the first available tier. The SDK clients are synchronous (`Anthropic`,
    `AnthropicBedrock`, per CLAUDE.md §11), so each call runs in a worker thread to keep the event loop free."""

    def __init__(self, config: RouterConfig, clients: Mapping[str, Any]) -> None:
        self.config = config
        self.clients = dict(clients)

    async def call(self, *, system: str, messages: list[MessageParam], max_tokens: int, model: str | None = None,
                   tools: list[dict] | None = None, tool_choice: dict | None = None, thinking: dict | None = None,
                   temperature: float | None = None) -> LLMResponse:
        if model is not None:
            self.config.check_model(model)
        if max_tokens > self.config.max_tokens_cap:
            raise ValueError(f"max_tokens={max_tokens} exceeds the cap of {self.config.max_tokens_cap} (§11)")
        chain = [t for t in self.config.chain() if t.tier in self.clients]
        if not chain:
            raise NoTierAvailable(f"no enabled tier can serve {self.config.model}")
        tier = chain[0]
        request: dict[str, Any] = {"model": tier.model, "system": system, "messages": messages,
                                   "max_tokens": max_tokens}
        optional = {"tools": tools, "tool_choice": tool_choice, "thinking": thinking}
        request.update({k: v for k, v in optional.items() if v is not None})
        if temperature is not None:
            # anthropic 1.8.0 has no typed `temperature` argument; Haiku 4.5 accepts it in the body (§11: 0 for
            # extraction). extra_body is the SDK's documented way to send a body field it does not type.
            request["extra_body"] = {"temperature": temperature}
        t0 = time.perf_counter()
        msg = await asyncio.to_thread(self.clients[tier.tier].messages.create, **request)
        return LLMResponse(
            tier=tier.tier, model=request["model"], stop_reason=msg.stop_reason,
            content=[b.model_dump(mode="json", exclude_none=True) for b in msg.content],
            input_tokens=msg.usage.input_tokens, output_tokens=msg.usage.output_tokens,
            latency_ms=int((time.perf_counter() - t0) * 1000))
