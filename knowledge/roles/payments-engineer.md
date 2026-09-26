---
type: Role
title: Payments Engineer
description: What a payments engineer holds by default, what still needs approval, and what the role never gets by default.
tags: [role, payments, access, baseline]
last_verified: 2026-09-24
owner: meera.iyer@northbeam.example
rules: [POL-ACC-001, POL-ACC-002, POL-ACC-003, POL-ACC-004, POL-ACC-005]
---
# Payments Engineer

Payments engineers build and run Northbeam's payment services. The team is `payments`, managed by Meera Iyer
(E-0301). Holders today: Rahul Mehta (E-0007, senior) and Anil Kumar (E-1042, mid), who moved from
risk-analytics on 2026-09-21.

## Baseline
A holder of the role receives these entitlements without further approval
([Access Control Standard §2](../policies/access-control-standard.md)), except the two listed in the next section.

| Entitlement | What it is | System |
|---|---|---|
| `okta-sso` | Okta SSO | okta |
| `slack-general` | Slack #general | slack |
| `gh-payments-api-read` | GitHub northbeam/payments-api (read) | github |
| `gh-ledger-service-read` | GitHub northbeam/ledger-service (read) | github |
| `gh-payments-web-read` | GitHub northbeam/payments-web (read) | github |
| `gh-payments-core-read` | GitHub northbeam/payments-core (read) | github |
| `slack-payments` | Slack #payments | slack |
| `slack-payments-oncall` | Slack #payments-oncall | slack |
| `jira-pay` | Jira project PAY | jira |
| `confluence-pay` | Confluence space PAY | confluence |
| `datadog-payments-viewer` | Datadog payments dashboards (viewer) | datadog |
| `pagerduty-payments-responder` | PagerDuty payments rotation | pagerduty |
| `sentry-payments` | Sentry project payments | sentry |
| `aws-payments-staging-readonly` | AWS payments-staging ReadOnly | aws |
| `vault-payments-staging-read` | Vault payments/staging secrets (read) | vault |
| `google-group-payments-eng` | Google group payments-eng@ | google |
| `postman-enterprise-seat` | Postman Enterprise seat ($49/mo) | postman |

## Approvals inside the baseline
Two baseline items still wait for a named person:

- `gh-payments-core-read`: `northbeam/payments-core` is tagged `production`, so any access to it is held for the
  Security on-call ([Access Control Standard §3](../policies/access-control-standard.md)).
- `postman-enterprise-seat`: a paid seat costs the team's budget, so the person's manager approves it
  ([Access Control Standard §6](../policies/access-control-standard.md)).

## Outside the baseline
`aws-payments-prod-admin` (AWS payments-prod AdministratorAccess) is within the role's scope but is not part of
the baseline. Administrator rights go only to senior engineers and above, with the Security on-call's approval
([Access Control Standard §4](../policies/access-control-standard.md)). A mid-level payments engineer asking for it
is refused, whoever else holds it.

## Mirrored access
"Give Anil the same access as Rahul" is judged against Anil's own role, not Rahul's
([Access Control Standard §5](../policies/access-control-standard.md)). Anything Rahul holds that the payments
engineer role does not cover is refused.

## Joining from another team
Access that belonged to the previous team is revoked on the day of the move
([Offboarding and transfers runbook](../runbooks/offboarding.md)). For Anil, that is the risk-analytics Looker
dashboards and the #risk-analytics channel.
