"""Sarvam-native phone dialogue; the engine remains the source of workflow facts.

The live voice runtime uses Sarvam Saaras for listening, Sarvam-105B Conversations
for brief dialogue and intent classification, and Sarvam Bulbul for speech. It
never calls Anthropic. The model's text cannot directly create a run or decide
an approval; flows still call the engine's door contract.
"""

from __future__ import annotations

import logging

import httpx

from llm import ROUTE_SYSTEM, fence

CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
MODEL = "sarvam-105b-conversations"
TIMEOUT_S = 8.0
MAX_HISTORY = 12
logger = logging.getLogger("voice.sarvam_chat")


class SarvamConversation:
    def __init__(self, key: str, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.key = key
        self.transport = transport
        self.mode = "LIVE" if key else "FIXTURE"
        self.provider = "SARVAM"

    @classmethod
    def from_key(cls, key: str) -> SarvamConversation:
        return cls(key)

    async def _complete(self, messages: list[dict], *, max_tokens: int, temperature: float) -> str | None:
        if not self.key:
            return None
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=TIMEOUT_S) as client:
                response = await client.post(
                    CHAT_URL, headers={"api-subscription-key": self.key},
                    json={"model": MODEL, "messages": messages, "max_tokens": max_tokens,
                          "temperature": temperature, "reasoning_effort": None})
                response.raise_for_status()
                choices = response.json().get("choices", [])
                content = choices[0]["message"]["content"] if choices else None
                return content.strip() if isinstance(content, str) and content.strip() else None
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Sarvam conversation unavailable (%s)", type(exc).__name__)
            return None

    async def reply(self, turns: list[dict], *, system: str) -> str | None:
        messages = [{"role": "system", "content": system}]
        messages.extend({"role": turn["role"],
                         "content": fence(turn["content"]) if turn["role"] == "user" else turn["content"]}
                        for turn in turns[-MAX_HISTORY:])
        return await self._complete(messages, max_tokens=150, temperature=0.3)

    async def classify(self, text: str, labels: tuple[str, ...]) -> str | None:
        system = (f"{ROUTE_SYSTEM} Reply with exactly one of these labels and no other text: "
                  f"{', '.join(labels)}.")
        answer = await self._complete([{"role": "system", "content": system},
                                       {"role": "user", "content": fence(text)}],
                                      max_tokens=24, temperature=0)
        return answer if answer in labels else None
