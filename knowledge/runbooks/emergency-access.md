---
type: Runbook
title: Emergency access during an incident
description: How a responder gets time-boxed, read-only production access during a declared incident, and who approves it.
tags: [runbook, incident, emergency, access, production]
last_verified: 2026-09-18
owner: security@northbeam.example
claims:
  emergency-access.max-duration: 4 hours
---
# Emergency access during an incident

## When this applies
Only during a declared Sev-1 or Sev-2 incident that has an open Freshservice incident ticket. It is not a shortcut
for routine work. It never applies to contractors or vendors: the
[Contractor Onboarding Policy §4](../policies/contractor-onboarding.md) has no incident exception.

## Who approves
The incident commander on the roster approves each grant. Today the roster is Omar Haddad (E-0051) and
Dana Osei (E-0050). An incident commander never approves access for themselves; the other one does.

## What is granted
Read-only access to the affected production system, for at most 4 hours. Write and administrator access are never
granted under this runbook; they follow the [Access Control Standard §4](../policies/access-control-standard.md).

## Steps
1. The responder asks for access on the incident ticket, naming the system and why it is needed.
2. The incident commander approves or refuses on the ticket.
3. Access is granted read-only and expires 4 hours after it is granted. More time means a new request.
4. The grant, its approver and its expiry are recorded on the incident ticket.
5. Within one working day of the incident closing, Security reviews every emergency grant made during it.

## ContextRail today
ContextRail does not handle emergency access requests yet. The rule for them (POL-EMG-001: read-only, at most
4 hours, incident commander approval) is planned, not shipped, so people follow this runbook by hand.
