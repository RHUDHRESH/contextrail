"""Offline stand-ins for the Anthropic SDK (no network, no keys).

Responses are real `anthropic.types.Message` objects, and errors are built by the SDK's own
`_make_status_error_from_response`, so the router is tested against exactly the classes and bodies the pinned SDK
(anthropic 1.8.0) raises for a given HTTP response.
"""

from __future__ import annotations

import anthropic
import httpx2
from anthropic.types import Message

from contextrail.llm.router import RouterConfig
from contextrail.settings import Settings

_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
_ERROR_TYPES = {400: "invalid_request_error", 401: "authentication_error", 402: "billing_error",
                403: "permission_error", 404: "not_found_error", 429: "rate_limit_error", 529: "overloaded_error"}


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def config(*, keys: str = "AB", bedrock: bool = False, replay: str = "off", **kw) -> RouterConfig:
    """A router config with the named tiers switched on ('A' -> T1, 'B' -> T2)."""
    return RouterConfig.from_settings(settings(
        anthropic_key_a="test-key-a" if "A" in keys else "", anthropic_key_b="test-key-b" if "B" in keys else "",
        bedrock_enabled=bedrock, llm_replay_mode=replay, **kw))


def message(text: str | None = "ok", *, tool: str | None = None, tool_input: dict | None = None,
            input_tokens: int = 100, output_tokens: int = 20, model: str = "claude-haiku-4-5-20251001",
            **usage) -> Message:
    content: list[dict] = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool:
        content.append({"type": "tool_use", "id": "toolu_fake", "name": tool, "input": tool_input or {}})
    return Message.model_validate({
        "id": "msg_fake", "type": "message", "role": "assistant", "model": model, "content": content,
        "stop_reason": "tool_use" if tool else "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, **usage}})


def api_error(status: int, message: str = "error", *, error_type: str | None = None,
              headers: dict | None = None) -> anthropic.APIStatusError:
    """The exception the SDK raises for this HTTP error response."""
    etype = error_type or _ERROR_TYPES.get(status, "api_error")
    response = httpx2.Response(status, json={"type": "error", "error": {"type": etype, "message": message}},
                               headers=headers or {}, request=_REQ)
    return anthropic.Anthropic(api_key="test-key", max_retries=0)._make_status_error_from_response(response)


def timeout_error() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(request=_REQ)


class FakeClient:
    """`client.messages.create(**kw)` returns or raises the scripted outcomes in order. An unscripted call fails."""

    def __init__(self, *outcomes) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._outcomes:
            raise AssertionError(f"unexpected model call #{len(self.calls)}")
        out = self._outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return out
