"""Amazon SES connector, outbound only (CLAUDE.md §12, D-007, checklist T230).

`boto3` sesv2 `send_email` in the configured region (ap-south-1). The request shape was read from the installed
botocore service model (sesv2 2019-09-27, `SendEmail`: FromEmailAddress, Destination.ToAddresses,
Content.Simple.{Subject, Body.{Text, Html}, Headers}, EmailTags, ConfigurationSetName -> MessageId).

One email per (run_id, action_id), via `connectors.once.send_once` with the key
`canonical.door_send_key(run_id, action_id, "email")` and a `door_messages` row as the record that it went. SES has no
idempotency key of its own, so one window remains: if SES accepts the email and the commit then fails, a retry sends
a duplicate. For an approval email that is harmless (both carry equivalent signed links and the first decision wins).

Mode is honest (D-004): LIVE only when a sender address is configured and is not a reserved placeholder domain.
Otherwise FIXTURE: nothing is sent, the rendered email is written to a local outbox as an .eml file, and the result,
the door_messages ref and the log line all say FIXTURE.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from email.message import EmailMessage
from pathlib import Path
from typing import Literal
from uuid import UUID

import boto3
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)
from pydantic import BaseModel, ConfigDict

from contextrail.connectors.base import ConnectorError, TransientError, UnknownOutcome
from contextrail.connectors.once import send_once
from contextrail.connectors.state import state_dir
from contextrail.db import Database
from contextrail.logs import get_logger
from contextrail.settings import Settings

log = get_logger("contextrail.ses")

CHANNEL = "email"
_RESERVED_DOMAINS = re.compile(r"(^|\.)(example|invalid|test|localhost)$|^example\.(com|net|org)$", re.IGNORECASE)
_TAG_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
_TRANSIENT_CODES = {"TooManyRequestsException", "LimitExceededException", "Throttling", "ThrottlingException"}


class OutboundEmail(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    to: str
    subject: str
    text: str
    html: str


class SendOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["LIVE", "FIXTURE"]
    message_id: str
    idempotency_key: str
    replayed: bool = False            # this (run, action) email already went; nothing was sent now
    outbox_path: str | None = None    # FIXTURE only: where the rendered email was written instead of sent


def is_placeholder_sender(address: str) -> bool:
    domain = address.rpartition("@")[2].strip().rstrip(".")
    return not domain or bool(_RESERVED_DOMAINS.search(domain))


def make_client(settings: Settings):
    """A sesv2 client in the configured region. Credentials come from the default AWS chain (instance role)."""
    return boto3.client("sesv2", region_name=settings.aws_region)


class SesConnector:
    name = "email"

    def __init__(self, settings: Settings, *, client=None, outbox_dir: Path | None = None) -> None:
        self.from_address = settings.ses_from_address
        self.configuration_set = settings.ses_configuration_set
        live = settings.ses_configured and not is_placeholder_sender(self.from_address)
        self.mode: Literal["LIVE", "FIXTURE"] = "LIVE" if live else "FIXTURE"
        self._client = client if client is not None else (make_client(settings) if live else None)
        self.outbox_dir = outbox_dir or state_dir() / "outbox"

    def request(self, message: OutboundEmail, *, run_id: UUID, action_id: str, key: str) -> dict:
        """The sesv2 SendEmail parameters for one email."""
        params = {
            "FromEmailAddress": self.from_address,
            "Destination": {"ToAddresses": [message.to]},
            "Content": {"Simple": {
                "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": message.text, "Charset": "UTF-8"},
                         "Html": {"Data": message.html, "Charset": "UTF-8"}},
                "Headers": [{"Name": "X-ContextRail-Idempotency-Key", "Value": key}],
            }},
            # Tag values allow only ASCII letters, digits, '_' and '-' (sesv2 MessageTag).
            "EmailTags": [{"Name": "contextrail_run", "Value": _TAG_UNSAFE.sub("_", str(run_id))},
                          {"Name": "contextrail_action", "Value": _TAG_UNSAFE.sub("_", action_id)[:256]},
                          {"Name": "contextrail_door", "Value": CHANNEL}],
        }
        if self.configuration_set:
            params["ConfigurationSetName"] = self.configuration_set
        return params

    async def send(self, db: Database, *, run_id: UUID, action_id: str, message: OutboundEmail) -> SendOutcome:
        async def deliver(key: str) -> dict:
            if self.mode == "LIVE":
                message_id, outbox = await self._send_live(message, run_id=run_id, action_id=action_id, key=key), None
            else:
                message_id, outbox = f"fixture-{key[:24]}", str(self._write_outbox(message, key))
                log.info("email_not_sent_fixture_mode", run_id=str(run_id), action_id=action_id, outbox=outbox)
            return {"mode": self.mode, "message_id": message_id, "to": message.to, "outbox": outbox}

        ref, replayed = await send_once(db, run_id=run_id, action_id=action_id, channel=CHANNEL, send=deliver)
        return SendOutcome(mode=ref["mode"], message_id=ref["message_id"], idempotency_key=ref["idempotency_key"],
                           replayed=replayed, outbox_path=ref.get("outbox"))

    async def _send_live(self, message: OutboundEmail, *, run_id: UUID, action_id: str, key: str) -> str:
        params = self.request(message, run_id=run_id, action_id=action_id, key=key)
        try:
            response = await asyncio.to_thread(self._client.send_email, **params)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            if code in _TRANSIENT_CODES or status == 429 or status >= 500:
                raise TransientError(f"ses: {code or status}") from e
            raise ConnectorError(f"ses: {code or status}") from e
        except ReadTimeoutError as e:  # the request went out; SES may have accepted it
            raise UnknownOutcome("ses: timed out waiting for SendEmail") from e
        except (EndpointConnectionError, ConnectTimeoutError) as e:
            raise TransientError(f"ses: {type(e).__name__}") from e
        except BotoCoreError as e:  # no credentials, bad config: permanent until someone fixes it
            raise ConnectorError(f"ses: {type(e).__name__}") from e
        log.info("email_sent", run_id=str(run_id), action_id=action_id, mode="LIVE")
        return response["MessageId"]

    def _write_outbox(self, message: OutboundEmail, key: str) -> Path:
        msg = EmailMessage()
        msg["From"] = self.from_address or "contextrail@fixture.invalid"
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg["X-ContextRail-Mode"] = "FIXTURE"
        msg["X-ContextRail-Idempotency-Key"] = key
        msg.set_content(message.text)
        msg.add_alternative(message.html, subtype="html")
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        path = self.outbox_dir / f"{key[:24]}.eml"
        fd, tmp = tempfile.mkstemp(dir=self.outbox_dir, prefix=".outbox.", suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(bytes(msg))
        os.replace(tmp, path)
        return path
