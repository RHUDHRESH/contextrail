---
type: System
title: Freshservice (the base)
description: The Freshservice ticket is the source of truth for every request; how requests arrive, get approved and get their receipt.
tags: [freshservice, tickets, approvals, receipts, catalog]
last_verified: 2026-09-26
owner: it-provisioning@northbeam.example
rules: [POL-SOD-001]
---
# Freshservice (the base)

Northbeam runs IT and access requests in Freshservice. The ticket is the source of truth for a request: ContextRail
starts from it, asks for approvals on it, and leaves its receipt on it.

## How a request arrives
A service catalogue request, or an email to the support mailbox, creates a ticket. A Workflow Automator rule
("ticket is raised") sends the ticket id to ContextRail, which answers at once and ignores repeats of the same
ticket, because webhooks are retried.

## Service catalogue
| Item | What it is for | SLA | Group |
|---|---|---|---|
| CAT-ONB-01 | New starter onboarding | 24 hours | IT Provisioning |
| CAT-ACC-04 | Repository access request | 8 hours | Security |
| CAT-BIL-02 | Billing adjustment or service credit | 48 hours | Finance |

## Approvals
A held action gets a native Freshservice approval on the ticket, and a card or email in the approver's preferred
door (Slack, Microsoft Teams, email or phone). The first decision from any door wins; the other doors then show who
decided, where and when. Nobody may approve a request they raised or benefit from
([Access Control Standard §7](../policies/access-control-standard.md)).

## Receipts
When a run finishes, its receipt goes on the ticket as a private note, with the audit sequence range it covers, and
the ticket is read back to confirm the note is there.

## Connector status
The live Freshservice connector is being built (checklist section I). It is LIVE only when `FS_DOMAIN` and
`FS_API_KEY` are configured and a call succeeds. Until then `GET /v1/connectors` lists it as planned, and nothing
claims it is live.
