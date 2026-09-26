---
type: Runbook
title: Emergency access during an incident
description: How a responder gets time-boxed, read-only production access during a declared incident, and who approves it.
tags: [runbook, incident, emergency, access, production]
last_verified: 2026-09-18
owner: security@northbeam.example
rules: [POL-EMG-001]
claims:
  emergency-access.max-duration: 4 hours
---
# Emergency access during an incident

## When this applies
Only during a declared Sev-1 or Sev-2 incident that has an open Freshservice incident ticket. It is not a shortcut
for routine work. It never applies to contractors or vendors: the
[Contractor Onboarding Policy §4](../policies/contractor-onboarding.md) has no incident exception.

## Who approves
The incident commander on the roster approves each grant. Today the roster is Omar Haddad (E-0051),
Dana Osei (E-0050), and Grace Okafor (E-0140). An incident commander never approves access for themselves;
another commander on the roster does.

## What is granted
During a declared incident, an employee may be given read-only access to the affected system with the incident commander's approval. The access expires 4 hours after it is requested and is never extended; write or administrator access, and access for contractors or vendors, is not granted this way.

The [Access Control Standard §4](../policies/access-control-standard.md) governs other administrator access.

## Steps
1. The responder asks for access on the incident ticket, naming the system and why it is needed.
2. The incident commander approves or refuses on the ticket.
3. Access is granted read-only and expires 4 hours after it is granted. More time means a new request.
4. The grant, its approver and its expiry are recorded on the incident ticket.
5. Within one working day of the incident closing, Security reviews every emergency grant made during it.

## ContextRail today
The engine carries POL-EMG-001. People follow this runbook by hand where incident intake is not configured.
