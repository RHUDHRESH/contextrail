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
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from anthropic import Anthropic, AnthropicBedrock, APIConnectionError, APIStatusError
from anthropic.types import MessageParam
from pydantic import BaseModel, ConfigDict

from contextrail.canonical import sha256_hex
from contextrail.fixtures import fixtures_dir
from contextrail.llm.pricing import cost_usd, price_for
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
            bedrock_budget_usd=min(s.bedrock_budget_usd, Decimal(20)),  # D-013: env cannot raise the hard cap
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


class BudgetExceeded(LLMError):
    """A live call would cross the per-run spend limit; callers use their deterministic fallback."""


class ReplayMiss(NoTierAvailable):
    """Replay mode, and this exact request was never recorded (or its recording does not match its key)."""


class LLMCallError(LLMError):
    """A tier failed in a way that must not fail over: a non-credit 4xx (the next tier would get the same bad
    request) or an unexpected client exception."""

    def __init__(self, tier: str, status: int | None, detail: str) -> None:
        super().__init__(f"{tier}: {detail}")
        self.tier, self.status = tier, status


class _TierFailed(Exception):
    """Internal: this tier failed in a failover-class way; try the next one."""


# --- failover classifier (T113) ------------------------------------------------------------------------------

Failure = Literal["rate_limited", "failover", "fatal"]
_DEFAULT_RETRY_AFTER_S = 1.0


def classify(exc: BaseException) -> Failure:
    """What a tier failure means for the chain (§11). 429 -> one retry-after wait, then fail over. 529, every 5xx,
    timeouts and connection failures, and credit-exhausted / billing errors -> fail over. Everything else ->
    fatal, including every other 4xx. Status codes, not exception classes, decide: the Bedrock client maps some
    statuses to different classes (503 -> ServiceUnavailableError) than the direct client does."""
    if isinstance(exc, APIConnectionError):  # APITimeoutError is a subclass
        return "failover"
    if isinstance(exc, APIStatusError):
        if exc.status_code == 429:
            return "rate_limited"
        if exc.status_code >= 500:
            return "failover"
        if _credit_exhausted(exc):
            return "failover"
    return "fatal"


def _credit_exhausted(exc: APIStatusError) -> bool:
    # The typed signals come first (error type 'billing_error', HTTP 402). The direct API has also reported an empty
    # balance as a 400 invalid_request_error whose only distinguishing mark is its message, hence the phrase check.
    if exc.type == "billing_error" or exc.status_code == 402:
        return True
    error = exc.body.get("error") if isinstance(exc.body, dict) else None
    detail = error.get("message") if isinstance(error, dict) else exc.message
    return exc.status_code == 400 and "credit balance" in str(detail).lower()


def retry_after_s(exc: APIStatusError, cap: float) -> float:
    """Seconds to wait before the one retry of a 429: `retry-after-ms`, else `retry-after` in seconds, capped.
    An HTTP-date or garbage value falls back to a short default rather than an unbounded wait."""
    for header, scale in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
        raw = exc.response.headers.get(header)
        if raw:
            try:
                return min(max(float(raw) / scale, 0.0), cap)
            except ValueError:
                continue
    return min(_DEFAULT_RETRY_AFTER_S, cap)


def _describe(exc: BaseException) -> str:
    status = getattr(exc, "status_code", None)
    return f"{type(exc).__name__}{f' {status}' if status else ''}"


# --- per-tier circuit breaker (T114) -------------------------------------------------------------------------

class CircuitBreaker:
    """A tier that failed over is skipped for `cooldown_s` (180 s, §11), then tried again; a success closes it,
    another failure re-opens it. Only failover-class failures trip it: a bad request is not the tier's fault.
    Process-local on purpose: one engine process, and a restart simply retries every tier."""

    def __init__(self, cooldown_s: float = 180.0, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.cooldown_s = cooldown_s
        self.clock = clock
        self._opened_at: dict[str, float] = {}

    def is_open(self, tier: str) -> bool:
        opened = self._opened_at.get(tier)
        return opened is not None and self.clock() - opened < self.cooldown_s

    def trip(self, tier: str) -> None:
        self._opened_at[tier] = self.clock()

    def reset(self, tier: str) -> None:
        self._opened_at.pop(tier, None)


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
    cost_usd: Decimal = Decimal(0)  # 0 for replay: nothing was spent
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

class Ledger(Protocol):
    """Where every call attempt is recorded (llm/ledger.py writes the llm_calls table)."""

    async def record(self, *, run_id: UUID | None, stage: str | None, model: str, tier: str, replay: bool,
                     input_tokens: int | None, output_tokens: int | None, cost_usd: Decimal, latency_ms: int,
                     outcome: str, error: str | None) -> None: ...

    def budget_guard(self, run_id: UUID | None, tier: str) -> AbstractAsyncContextManager[None]: ...

    async def run_spend(self, run_id: UUID) -> Decimal: ...

    async def tier_spend(self, tier: str) -> Decimal: ...


@dataclass(frozen=True)
class _Ctx:
    run_id: UUID | None
    stage: str | None


class Router:
    """Calls Claude Haiku 4.5 down the chain T1 -> T2 -> T3 -> T4 until a tier answers (T113 decides when to move
    on). The SDK clients are synchronous (`Anthropic`, `AnthropicBedrock`, per CLAUDE.md §11), so each call runs in
    a worker thread to keep the event loop free.

    Every attempt (T115) leaves one ledger row: 'ok' with tokens, cost and latency; 'failover' when the chain moves
    on; 'error' for a fatal failure, a 429 that is being retried, or a replay miss. Tiers skipped by an open breaker
    are not calls and leave no row. The ledger is required: a router that could not log would break §11."""

    def __init__(self, config: RouterConfig, clients: Mapping[str, Any], *, ledger: Ledger,
                 replay_store: ReplayStore | None = None, breaker: CircuitBreaker | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        price_for(config.model)  # an unpriced model cannot be budgeted: fail at startup, not mid-run
        self.config = config
        self.clients = dict(clients)
        self.ledger = ledger
        self.replay_store = replay_store or ReplayStore(config.replay_dir)
        self.breaker = breaker or CircuitBreaker(config.breaker_cooldown_s)
        self.sleep = sleep

    async def call(self, *, system: str, messages: list[MessageParam], max_tokens: int, model: str | None = None,
                   policy_text: str | None = None, tools: list[dict] | None = None, tool_choice: dict | None = None,
                   thinking: dict | None = None, temperature: float | None = None, run_id: UUID | None = None,
                   stage: str | None = None) -> LLMResponse:
        """`system` is the stable prompt; `policy_text` (optional) is stable reference text such as policy clauses.
        Both go in the cached prefix (T118). Anything that varies per call belongs in `messages`. `run_id` and
        `stage` attribute the ledger rows (and, in T116, the run's budget)."""
        ctx = _Ctx(run_id, stage)
        if model is not None:
            self.config.check_model(model)
        if max_tokens > self.config.max_tokens_cap:
            raise ValueError(f"max_tokens={max_tokens} exceeds the cap of {self.config.max_tokens_cap} (§11)")
        keyed = request_for(model=self.config.model, system=system, policy_text=policy_text, messages=messages,
                            tools=tools)
        chain = [t for t in self.config.chain() if t.provider == "replay" or t.tier in self.clients]
        if not chain:
            raise NoTierAvailable(f"no enabled tier can serve {self.config.model}")
        base: dict[str, Any] = {"system": system_blocks(system, policy_text), "messages": messages,
                                "max_tokens": max_tokens}
        optional = {"tools": tools, "tool_choice": tool_choice, "thinking": thinking}
        base.update({k: v for k, v in optional.items() if v is not None})
        if temperature is not None:
            # anthropic 1.8.0 has no typed `temperature` argument; Haiku 4.5 accepts it in the body (§11: 0 for
            # extraction). extra_body is the SDK's documented way to send a body field it does not type.
            base["extra_body"] = {"temperature": temperature}
        failures: list[str] = []
        run_refusal: BudgetExceeded | None = None
        reserve = self._maximum_call_cost(base, max_tokens)
        for tier in chain:
            if tier.provider == "replay":
                return await self._replay(keyed, ctx)
            if self.breaker.is_open(tier.tier):
                failures.append(f"{tier.tier}: breaker open")
                continue
            async with self.ledger.budget_guard(ctx.run_id, tier.tier):
                refusal = await self._budget_refusal(tier, ctx, reserve)
                if refusal:
                    failures.append(f"{tier.tier}: {refusal}")
                    if isinstance(refusal, BudgetExceeded):
                        run_refusal = refusal
                    continue
                try:
                    response = await self._attempt(tier, {"model": tier.model, **base}, ctx)
                except _TierFailed as f:
                    self.breaker.trip(tier.tier)
                    failures.append(f"{tier.tier}: {f}")
                    continue
            self.breaker.reset(tier.tier)
            if self.config.replay_mode == "record":
                self._record(keyed, response)
            return response
        if run_refusal:
            raise run_refusal
        raise NoTierAvailable("no tier answered: " + "; ".join(failures))

    def _maximum_call_cost(self, request: dict[str, Any], max_tokens: int) -> Decimal:
        """Conservative preflight: charge the whole request as cache-write tokens plus maximum output.

        A byte upper-bounds a text token in the serialized request; the extra 1024 covers API framing and
        tool-use overhead. Actual spend is logged after the response and checked again before the next call.
        """
        prompt_bytes = len(json.dumps(request, ensure_ascii=False, default=str).encode("utf-8"))
        return cost_usd(self.config.model, input_tokens=0, cache_write_tokens=prompt_bytes + 1024,
                        output_tokens=max_tokens)

    async def _budget_refusal(self, tier: TierConfig, ctx: _Ctx, reserve: Decimal) -> LLMError | None:
        t0 = time.perf_counter()
        if ctx.run_id is not None:
            spent = await self.ledger.run_spend(ctx.run_id)
            if spent + reserve > self.config.run_budget_usd:
                detail = (f"run budget ${self.config.run_budget_usd} would be exceeded: "
                          f"${spent} spent, up to ${reserve} for this call")
                await self._log(ctx, tier.tier, tier.model, outcome="budget_refused", t0=t0, error=detail)
                return BudgetExceeded(detail)
        if tier.provider == "bedrock":
            spent = await self.ledger.tier_spend(tier.tier)
            if spent + reserve > self.config.bedrock_budget_usd:
                detail = (f"Bedrock cap ${self.config.bedrock_budget_usd} would be exceeded: "
                          f"${spent} spent, up to ${reserve} for this call")
                await self._log(ctx, tier.tier, tier.model, outcome="budget_refused", t0=t0, error=detail)
                return NoTierAvailable(detail)
        return None

    async def _attempt(self, tier: TierConfig, request: dict[str, Any], ctx: _Ctx) -> LLMResponse:
        """One tier: a 429 gets exactly one retry-after wait; failover-class errors raise _TierFailed; anything else
        raises LLMCallError and stops the chain. Each HTTP attempt is logged."""
        retried = False
        while True:
            t0 = time.perf_counter()
            try:
                response = await self._live(tier, request)
            except Exception as e:  # the SDK client boundary: every failure is classified, none escapes raw
                kind = classify(e)
                will_retry = kind == "rate_limited" and not retried
                outcome = "failover" if kind != "fatal" and not will_retry else "error"
                await self._log(ctx, tier.tier, request["model"], outcome=outcome, t0=t0,
                                error=_describe(e) + (" (retried)" if will_retry else ""))
                if will_retry:
                    retried = True
                    await self.sleep(retry_after_s(e, self.config.max_retry_after_s))
                    continue
                if kind == "fatal":
                    raise LLMCallError(tier.tier, getattr(e, "status_code", None), _describe(e)) from e
                raise _TierFailed(_describe(e)) from e
            await self._log(ctx, tier.tier, response.model, outcome="ok", t0=t0, response=response)
            return response

    async def _live(self, tier: TierConfig, request: dict[str, Any]) -> LLMResponse:
        t0 = time.perf_counter()
        msg = await asyncio.to_thread(self.clients[tier.tier].messages.create, **request)
        u = msg.usage
        tokens = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                  "cache_write_tokens": u.cache_creation_input_tokens or 0,
                  "cache_read_tokens": u.cache_read_input_tokens or 0}
        return LLMResponse(
            tier=tier.tier, model=request["model"], stop_reason=msg.stop_reason,
            content=[b.model_dump(mode="json", exclude_none=True) for b in msg.content],
            cost_usd=cost_usd(self.config.model, **tokens),  # Bedrock too: priced as the logical Haiku model
            latency_ms=int((time.perf_counter() - t0) * 1000), **tokens)

    async def _log(self, ctx: _Ctx, tier: str, model: str, *, outcome: str, t0: float,
                   response: LLMResponse | None = None, error: str | None = None, replay: bool = False) -> None:
        r = response
        await self.ledger.record(
            run_id=ctx.run_id, stage=ctx.stage, model=model, tier=tier, replay=replay,
            input_tokens=r.input_tokens + r.cache_write_tokens + r.cache_read_tokens if r else None,
            output_tokens=r.output_tokens if r else None, cost_usd=r.cost_usd if r else Decimal(0),
            latency_ms=int((time.perf_counter() - t0) * 1000), outcome=outcome, error=error)

    # --- T4 replay (T112) ------------------------------------------------------------------------------------

    async def _replay(self, keyed: dict, ctx: _Ctx) -> LLMResponse:
        t0 = time.perf_counter()
        key = sha256_hex(keyed)
        rec = self.replay_store.load(key)
        if rec is None:
            await self._log(ctx, "T4", self.config.model, outcome="error", t0=t0, error="ReplayMiss", replay=True)
            raise ReplayMiss(f"no recording for this request (key {key[:12]}) in {self.replay_store.directory}")
        response = LLMResponse(tier="T4", model=self.config.model, replay=True, content=rec["content"],
                               stop_reason=rec.get("stop_reason"), input_tokens=rec["usage"]["input_tokens"],
                               output_tokens=rec["usage"]["output_tokens"],
                               latency_ms=int((time.perf_counter() - t0) * 1000))  # cost 0: nothing was spent
        await self._log(ctx, "T4", response.model, outcome="ok", t0=t0, response=response, replay=True)
        return response

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
