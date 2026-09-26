"""Turn a Freshservice ticket into the rail's untrusted request, without mixing live and fixture reads."""

from __future__ import annotations

from html.parser import HTMLParser

from contextrail.connectors.base import ConnectorError, TransientError
from contextrail.connectors.freshservice import FreshserviceConnector
from contextrail.intake import TicketRequest


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _description(ticket: dict) -> str:
    plain = ticket.get("description_text")
    if isinstance(plain, str) and plain.strip():
        return plain.strip()
    html = ticket.get("description")
    if not isinstance(html, str):
        return ""
    parser = _PlainText()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


class FreshserviceTicketReader:
    """The TicketReader used by webhook jobs. Catalog request_text takes precedence over ticket description."""

    def __init__(self, connector: FreshserviceConnector) -> None:
        self.connector = connector

    @property
    def mode(self) -> str:
        return self.connector.mode

    async def ticket_request(self, ticket_id: str) -> TicketRequest:
        read = await self.connector.get_ticket(ticket_id)
        if self.mode == "LIVE" and read.mode != "LIVE":
            raise TransientError(f"Freshservice ticket {ticket_id} was not read from the live tenant")
        ticket = read.data
        if str(ticket.get("id")) != str(ticket_id):
            raise ConnectorError(f"Freshservice returned a different ticket for {ticket_id}")
        text = ""
        try:
            items = await self.connector.get_requested_items(ticket_id)
        except ConnectorError:
            items = None
        if items is not None and items.mode == read.mode:
            candidates = {value.strip() for item in items.data if isinstance(item, dict)
                          for fields in [item.get("custom_fields")]
                          for value in [fields.get("request_text") if isinstance(fields, dict) else None]
                          if isinstance(value, str) and value.strip()}
            if len(candidates) > 1:
                raise ConnectorError(f"Freshservice ticket {ticket_id} has conflicting request texts")
            if candidates:
                text = candidates.pop()
        text = text or _description(ticket)
        if not text:
            raise ConnectorError(f"Freshservice ticket {ticket_id} has no request text")
        requester = ticket.get("requester_id")
        external_id = str(requester) if requester is not None else None
        if requester is not None:
            try:
                person = await self.connector.get_requester(requester)
            except ConnectorError:
                if self.mode == "LIVE":
                    raise TransientError(f"Freshservice requester {requester} could not be verified") from None
            else:
                if self.mode == "LIVE" and person.mode != "LIVE":
                    raise TransientError(f"Freshservice requester {requester} was not read from the live tenant")
                if person.mode == read.mode:
                    email = person.data.get("primary_email") or person.data.get("email")
                    if isinstance(email, str) and email.strip():
                        external_id = email.strip()
        return TicketRequest(ticket_id=str(ticket_id), text=text,
                             requester_external_id=external_id)
