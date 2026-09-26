"""The phone's conversational model: Claude Haiku 4.5, and nothing else (D-013, CLAUDE.md §13.3).

It replaces the upstream GPT-4o-mini call. The model only talks: it phrases short replies to the caller. It never
decides what happens: starting a run, answering a status or policy question and deciding an approval all go to
the engine's door contract, which answers from records, receipts and written policy.

The caller's words are untrusted. They enter the prompt fenced as data, with angle brackets escaped so a caller
cannot close the fence (the same rule as the engine's wrap_untrusted, CLAUDE.md §11).

Without ANTHROPIC_KEY_A the conversation runs in FIXTURE mode: no model is called and the caller hears fixed lines.
"""

from __future__ import annotations

import logging
from typing import Literal

import anthropic

HAIKU_MODEL = "claude-haiku-4-5-20251001"
REPLY_MAX_TOKENS = 150  # one or two spoken sentences
REPLY_TEMPERATURE = 0.3  # prose, not extraction (CLAUDE.md §11)
TIMEOUT_S = 8.0  # a caller is waiting on the line

logger = logging.getLogger("voice.llm")


class ModelNotAllowed(ValueError):
    """A model other than Claude Haiku 4.5 was configured (D-013)."""


def fence(text: str) -> str:
    body = text.replace("<", "&lt;").replace(">", "&gt;")
    return f'<untrusted source="voice-transcript">\n{body}\n</untrusted>'


class Conversation:
    def __init__(self, client, *, model: str = HAIKU_MODEL) -> None:
        if model != HAIKU_MODEL:
            raise ModelNotAllowed(f"only Claude Haiku 4.5 is allowed (D-013): got {model!r}")
        self.client, self.model = client, model
        self.mode: Literal["LIVE", "FIXTURE"] = "LIVE" if client is not None else "FIXTURE"

    @classmethod
    def from_key(cls, api_key: str) -> Conversation:
        if not api_key:
            return cls(None)
        return cls(anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, timeout=TIMEOUT_S))

    async def reply(self, turns: list[dict], *, system: str) -> str | None:
        """Next spoken line, or None when there is no model or it failed (the caller then hears a fixed line)."""
        if self.client is None:
            return None
        messages = [{"role": t["role"], "content": fence(t["content"]) if t["role"] == "user" else t["content"]}
                    for t in turns]
        try:
            msg = await self.client.messages.create(
                model=self.model, max_tokens=REPLY_MAX_TOKENS, system=system, messages=messages,
                # anthropic 1.8.0 has no typed `temperature`; the API accepts it in the body (as engine llm/router)
                extra_body={"temperature": REPLY_TEMPERATURE})
        except anthropic.APIError as e:
            logger.warning("Haiku unavailable (%s); speaking the fixed line", type(e).__name__)
            return None
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        return text or None
