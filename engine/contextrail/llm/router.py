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

from anthropic import Anthropic, AnthropicBedrock
from anthropic.types import MessageParam
from pydantic import BaseModel, ConfigDict

from contextrail.canonical import sha256_hex
from contextrail.fixtures import fixtures_dir
from contextrail.llm.replay import ReplayStore, request_for
from contextrail.logs import get_logger
from contextrail.settings import Settings

log = get_logger("contextrail.llm")

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


class ReplayMiss(NoTierAvailable):
    """Replay mode, and this exact request was never recorded (or its recording does not match its key)."""


# --- responses -----------------------------------------------------------------------------------------------

class LLMResponse(BaseModel):
    """One model answer, with where it came from. Content blocks are plain dicts (text / tool_use)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tier: Tier
    model: str                  # the model ID the serving tier was sent
    replay: bool = False
    content: list[dict]
    stop_reason: str | None = None
    input_tokens: int = 0       # uncached input, as the API reports it
    output_tokens: int = 0
    cache_write_tokens: int = 0  # usage.cache_creation_input_tokens
    cache_read_tokens: int = 0   # usage.cache_read_input_tokens
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
    own, and the router must own retries and failover (T113) so the tier it logs is the tier that answered.

    T3 (T111) signs with the AWS default credential chain (env, profile, instance role); no AWS secret is read
    from Settings. The Bedrock model is the global Haiku 4.5 inference profile (TierConfig.model)."""
    keys = {"T1": s.anthropic_key_a, "T2": s.anthropic_key_b}
    clients: dict[Tier, Any] = {}
    for t in config.chain():
        if t.provider == "anthropic":
            clients[t.tier] = Anthropic(api_key=keys[t.tier].get_secret_value(), max_retries=0,
                                        timeout=config.timeout_s)
        elif t.provider == "bedrock":
            clients[t.tier] = AnthropicBedrock(aws_region=s.aws_region, max_retries=0, timeout=config.timeout_s)
    return clients


# --- the router ----------------------------------------------------------------------------------------------

class Router:
    """Calls Claude Haiku 4.5 on the first available tier. The SDK clients are synchronous (`Anthropic`,
    `AnthropicBedrock`, per CLAUDE.md §11), so each call runs in a worker thread to keep the event loop free."""

    def __init__(self, config: RouterConfig, clients: Mapping[str, Any], *,
                 replay_store: ReplayStore | None = None) -> None:
        self.config = config
        self.clients = dict(clients)
        self.replay_store = replay_store or ReplayStore(config.replay_dir)

    async def call(self, *, system: str, messages: list[MessageParam], max_tokens: int, model: str | None = None,
                   policy_text: str | None = None, tools: list[dict] | None = None, tool_choice: dict | None = None,
                   thinking: dict | None = None, temperature: float | None = None) -> LLMResponse:
        """`system` is the stable prompt; `policy_text` (optional) is stable reference text such as policy clauses.
        Both go in the cached prefix (T118). Anything that varies per call belongs in `messages`."""
        if model is not None:
            self.config.check_model(model)
        if max_tokens > self.config.max_tokens_cap:
            raise ValueError(f"max_tokens={max_tokens} exceeds the cap of {self.config.max_tokens_cap} (§11)")
        keyed = request_for(model=self.config.model, system=system, policy_text=policy_text, messages=messages,
                            tools=tools)
        chain = [t for t in self.config.chain() if t.provider == "replay" or t.tier in self.clients]
        if not chain:
            raise NoTierAvailable(f"no enabled tier can serve {self.config.model}")
        tier = chain[0]
        if tier.provider == "replay":
            return self._replay(keyed)
        request: dict[str, Any] = {"model": tier.model, "system": system_blocks(system, policy_text),
                                   "messages": messages, "max_tokens": max_tokens}
        optional = {"tools": tools, "tool_choice": tool_choice, "thinking": thinking}
        request.update({k: v for k, v in optional.items() if v is not None})
        if temperature is not None:
            # anthropic 1.8.0 has no typed `temperature` argument; Haiku 4.5 accepts it in the body (§11: 0 for
            # extraction). extra_body is the SDK's documented way to send a body field it does not type.
            request["extra_body"] = {"temperature": temperature}
        response = await self._live(tier, request)
        if self.config.replay_mode == "record":
            self._record(keyed, response)
        return response

    async def _live(self, tier: TierConfig, request: dict[str, Any]) -> LLMResponse:
        t0 = time.perf_counter()
        msg = await asyncio.to_thread(self.clients[tier.tier].messages.create, **request)
        u = msg.usage
        return LLMResponse(
            tier=tier.tier, model=request["model"], stop_reason=msg.stop_reason,
            content=[b.model_dump(mode="json", exclude_none=True) for b in msg.content],
            input_tokens=u.input_tokens, output_tokens=u.output_tokens,
            cache_write_tokens=u.cache_creation_input_tokens or 0, cache_read_tokens=u.cache_read_input_tokens or 0,
            latency_ms=int((time.perf_counter() - t0) * 1000))

    # --- T4 replay (T112) ------------------------------------------------------------------------------------

    def _replay(self, keyed: dict) -> LLMResponse:
        t0 = time.perf_counter()
        key = sha256_hex(keyed)
        rec = self.replay_store.load(key)
        if rec is None:
            raise ReplayMiss(f"no recording for this request (key {key[:12]}) in {self.replay_store.directory}")
        return LLMResponse(tier="T4", model=self.config.model, replay=True, content=rec["content"],
                           stop_reason=rec.get("stop_reason"), input_tokens=rec["usage"]["input_tokens"],
                           output_tokens=rec["usage"]["output_tokens"],
                           latency_ms=int((time.perf_counter() - t0) * 1000))

    def _record(self, keyed: dict, r: LLMResponse) -> None:
        """Save a live answer for the demo script. A failed write is logged; it never costs the caller the answer."""
        try:
            self.replay_store.save(
                request=keyed, recorded_from={"tier": r.tier, "model": r.model},
                response={"content": r.content, "stop_reason": r.stop_reason,
                          "usage": {"input_tokens": r.input_tokens, "output_tokens": r.output_tokens}})
        except OSError as e:
            log.warning("llm.replay_record_failed", error=type(e).__name__)


def system_blocks(system: str, policy_text: str | None = None) -> list[dict]:
    """The system prompt (then the policy text, when given) as text blocks, with one ephemeral cache breakpoint on
    the last block (T118). Block-level, because the legacy Bedrock integration rejects top-level cache_control.
    Haiku 4.5 caches only prefixes of 4096+ tokens; below that the request is simply uncached, at no premium."""
    blocks = [{"type": "text", "text": system}]
    if policy_text:
        blocks.append({"type": "text", "text": policy_text})
    blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
    return blocks
