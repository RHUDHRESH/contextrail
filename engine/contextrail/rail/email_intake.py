"""Discover for the email door (CLAUDE.md §13.6, §8, checklist T229).

An email reaches the engine as a Freshservice ticket (`source=email`). Before anything reads it, the body is reduced
to what the sender actually wrote this time: quoted history ("On Mon ... wrote:", "-----Original Message-----",
Outlook's From/Sent block, "> " lines) and signatures ("-- ", "Sent from my iPhone") are cut, so a status question
that quotes the original request is not mistaken for a second request.

What remains is untrusted text (P6). It enters an extractor only fenced by `compile.wrap_untrusted`, it becomes
mentions at most, and the policy engine has no way to receive it.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from contextrail.models import Evidence
from contextrail.rail.compile import wrap_untrusted

if TYPE_CHECKING:
    from contextrail.rail.discover import Intent, IntentExtractor

_REPLY_PREFIX = re.compile(r"^\s*(?:(?:re|aw|sv|antw|fw|fwd|wg)\s*(?:\[\d+\])?\s*:\s*)+", re.IGNORECASE)

# Where quoted history starts. Everything from the first match on is the thread, not this message.
_QUOTE_STARTS = (
    re.compile(r"^On\b[^\n]{0,200}(?:\n[^\n]{0,200})?\bwrote:[ \t]*$", re.MULTILINE),        # Gmail, Apple Mail
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}", re.MULTILINE | re.IGNORECASE),        # Outlook (classic)
    re.compile(r"^_{8,}[ \t]*$", re.MULTILINE),                                             # Outlook separator
    re.compile(r"^From:[^\n]*\n(?:[^\n]*\n){0,3}?(?:Sent|Date):", re.MULTILINE),            # Outlook header block
)
# Where a signature starts: the RFC 3676 delimiter and the mobile client footers.
_SIGNATURE_STARTS = (
    re.compile(r"^--[ \t]?$", re.MULTILINE),
    re.compile(r"^Sent from my \w+", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Get Outlook for \w+", re.MULTILINE | re.IGNORECASE),
)
_ANSWER_WORD = re.compile(r"^\s*(?:approve[ds]?|refuse[ds]?|reject(?:ed)?|yes|no)\b[\s,.!:;-]*", re.IGNORECASE)


def is_reply(subject: str) -> bool:
    return bool(_REPLY_PREFIX.match(subject or ""))


def strip_reply_prefix(subject: str) -> str:
    return _REPLY_PREFIX.sub("", subject or "", count=1).strip()


def clean_body(body: str) -> str:
    """This message only: quoted history and signature removed, inline '> ' quotes dropped, whitespace trimmed."""
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n")
    cut = min((m.start() for p in (*_QUOTE_STARTS, *_SIGNATURE_STARTS) if (m := p.search(text))), default=len(text))
    kept = [line for line in text[:cut].split("\n") if not line.lstrip().startswith(">")]
    return "\n".join(kept).strip()


def email_evidence(text: str, *, uri: str, now: datetime | None = None) -> Evidence:
    """An email body as the case file may hold it: a message, untrusted, always (P6)."""
    digest = hashlib.sha256(f"{uri}\n{text}".encode()).hexdigest()[:12]
    return Evidence(id=f"EV-email-{digest}", kind="message", source="email", uri=uri, excerpt=text,
                    retrieved_at=now or datetime.now(UTC), trust="untrusted")


def untrusted_email(text: str, *, uri: str = "email://inbound") -> str:
    """How email text enters any prompt: cleaned, then fenced as data by the compile stage's wrapper (§11)."""
    return wrap_untrusted(email_evidence(clean_body(text), uri=uri))


class InboundEmail(BaseModel):
    """One inbound email as the Freshservice ticket carries it. Every field is untrusted input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sender: str
    subject: str = ""
    body: str = ""
    ticket_id: str | None = None

    @property
    def is_reply(self) -> bool:
        return is_reply(self.subject)

    @property
    def uri(self) -> str:
        return f"freshservice://tickets/{self.ticket_id}" if self.ticket_id else "email://inbound"

    @property
    def text(self) -> str:
        """What the sender wrote this time; the subject stands in when the body is empty."""
        return clean_body(self.body) or strip_reply_prefix(self.subject)


async def classify_email(email: InboundEmail, extractor: IntentExtractor) -> Intent:
    """Request, query or approval-reply. The extractor sees only the fenced text, never the raw email."""
    intent = await extractor.extract(untrusted_email(email.text, uri=email.uri))
    if intent.kind == "approval_reply" and not email.is_reply and (m := _ANSWER_WORD.match(email.text)):
        # A new email cannot be answering an approval email we sent: "Yes, give Anil ..." is a request.
        rest = email.text[m.end():]
        if rest.strip():
            intent = await extractor.extract(untrusted_email(rest, uri=email.uri))
    return intent
