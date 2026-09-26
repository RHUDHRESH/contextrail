---
type: Runbook
title: Contractor onboarding SOP
description: Evidence, handoffs, approval gates, and completion checks for a Northbeam contractor's first day.
tags: [runbook, onboarding, contractors, freshservice, perception]
last_verified: 2026-09-26
owner: it-provisioning@northbeam.example
rules: [POL-CTR-001, POL-ACC-004, POL-SOD-001]
---
# Contractor onboarding SOP

This is a procedure for the fictional Northbeam demo tenant. Use the [Contractor Onboarding Policy](../policies/contractor-onboarding.md) and [Access Control Standard](../policies/access-control-standard.md) for decisions. The Freshservice ticket is the request and receipt record; HRIS and the signed SOW remain the source for worker status, dates, and scope. A simulated result or FIXTURE record is evidence for the demo only, never proof of a real account grant.

## Verified Freshservice demo context (2026-09-26)

- Priya's existing requester is `30002028185`. Her live [ticket #131](https://freshworks065.freshservice.com/a/tickets/131) is in workspace `12` and says, "Priya starts Monday, give her everything she needs." The requester record has no department, job title, or reporting manager set, so confirm those facts against HRIS and the signed SOW.
- The [draft SOP article #30000077374](https://freshworks065.freshservice.com/api/v2/solutions/articles/30000077374) is in workspace `12`, category `30000055606`, folder `30000063763`. It is readable by the API user but is not published to the portal.
- Ticket #131 has six open demo tasks: `25` HRIS identity and paperwork, `26` loaner and identity, `27` Slack guest scope, `28` repository review, `29` first-day handoff, and `30` expiry and reclaim. Their due dates are 2026-09-27 or 2026-09-28, except task `30`, due 2027-03-31. Private context notes `30004926776` and `30004926817` were read back from the ticket. These records describe work to verify; they are not completion receipts.
- The tenant plan rejects the native asset and employee onboarding APIs with `require_feature`. The service catalogue API is also unavailable to this API user (`access_denied`), so CAT-ONB-01 has not been verified in this tenant.

## 1. Open the request and identify the worker

People Ops confirms the worker's exact HRIS identity, employment type, engaging manager, start and end dates, signed NDA, and countersigned SOW. For the Priya scenario, the fixture identifies Priya Raghunathan as W-8841, a Perception contract engineer managed by Marc Liu (E-0120), starting 2026-09-28 and ending 2027-03-31. Her SOW names only `northbeam/perception-sdk`. Resolve any ambiguous name before proceeding. Record the HRIS ID, requester, beneficiary, manager, SOW reference, and start and end dates on the Freshservice request.

## 2. Check the paperwork gate

People Ops verifies both `nda_signed` and `sow_countersigned` in HRIS before IT provisions anything. If either is missing, leave provisioning pending and tell the manager what is needed. Attach or cite the paperwork evidence; do not treat a free-text request or a Slack message as proof that it exists.

## 3. Route work through Freshservice

Use the New starter onboarding catalogue item (CAT-ONB-01) when it exists, route to IT Provisioning, and target the documented 24-hour SLA and the worker's start date. The ticket should name the worker and manager and record the workstream status, due date, approver, evidence links, and each handoff. IT owns equipment and identity tasks; Security owns repository review; the engaging manager confirms team scope and the first-day handoff. Add a private completion note with verified results and open blockers. Priya's live ticket #131 and its open tasks are verified above; the catalogue item remains unverified.

## 4. Prepare equipment and communication

IT assigns a loaner laptop from the contractor pool; buying a new device requires Finance approval. Record the asset tag, assignee, restricted image, and a Freshservice asset readback when the asset feature is available. The current demo tenant does not support that API; task #26 remains an open check, not an asset assignment. Invite the worker to Slack as a single-channel guest for `#perception`, with an expiry equal to the SOW end date. Record the invitation ID, channel scope, expiry, and delivery result. Do not describe an invitation as accepted access until the destination system confirms it.

## 5. Review source control and exclusions

Request read-only access only to the SOW repository `northbeam/perception-sdk`. Its production tag requires Security on-call approval before provisioning. Record the approver's identity, decision, repository, permission, justification, owner, and expiry of 2027-03-31. The requester and beneficiary cannot approve their own access. Contractors receive no production credentials, production database access, or customer PII exports; these are refusals, with no approval path. Any repository write request needs Security review under the contractor policy and must also satisfy the access standard; it is not part of the Priya baseline.

## 6. Finish the first-day handoff

IT or the manager creates an engineering checklist with the security awareness module first, followed by device verification, communication setup, and approved repository access. The manager receives a summary of what was verified, what awaits approval, and what was refused. Before closing the Freshservice ticket, read back the asset assignment, Slack scope and expiry, repository grant and expiry, and any native approval and private receipt note. Keep unresolved items open with an owner and next action.

## 7. Expire and reclaim

Set every contractor access grant to end on the SOW end date with zero grace days. Schedule the offboarding check, then revoke access and reclaim the device using the [offboarding runbook](offboarding.md). A new SOW or extension requires a new evidence check before changing expiry.

# Citations

- Contractor Onboarding Policy §1–§6 and Access Control Standard §1, §3, §7 in this bundle.
- Demo worker and SOW facts: `fixtures/hris.json`, `fixtures/documents.json`, and `fixtures/sow_documents.json`; the latter two disagree on the SOW number and scope wording, so the HRIS record and an individually verified signed SOW must control any actual operation.
- Freshservice catalogue, approval, and receipt conventions: [Freshservice (the base)](../systems/freshservice.md).
