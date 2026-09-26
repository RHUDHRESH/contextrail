"""Offline stand-ins for the providers the voice door talks to. Each records exactly what it was asked."""

from __future__ import annotations

import json
from types import SimpleNamespace


class FakeMessages:
    """Mimics anthropic's AsyncMessages.create: records kwargs, replies with canned blocks or raises."""

    def __init__(self, replies: list | None = None, error: Exception | None = None):
        self.calls: list[dict] = []
        self.replies = list(replies or [])
        self.error = error

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        reply = self.replies.pop(0) if self.replies else "OK."
        if isinstance(reply, dict):  # a forced tool call
            blocks = [SimpleNamespace(type="tool_use", name=kwargs["tool_choice"]["name"], input=reply)]
        else:
            blocks = [SimpleNamespace(type="text", text=reply)]
        return SimpleNamespace(content=blocks, stop_reason="end_turn")


class FakeAnthropic:
    def __init__(self, replies: list | None = None, error: Exception | None = None):
        self.messages = FakeMessages(replies, error)


class FakeWS:
    """A Starlette-like WebSocket: collects what the session sends back to Vobiz."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_text(self, data: str):
        self.sent.append(json.loads(data))
