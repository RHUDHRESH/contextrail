---
name: contextrail-discover
description: Search connected enterprise knowledge sources (Notion, Google Docs, Slack, Freshservice, CRM, GitHub, Linear, HRIS) and return cited evidence with a freshness verdict on every hit. Use when a question depends on what company policy, records, or live system state actually say — before reasoning, and always before acting.
---

# ContextRail — Discover

Retrieval that a governance layer can stand on. Every hit carries the system it
came from, the excerpt that justified it, a confidence score, and whether the
source is past its freshness budget.

## When to use

- A question turns on company policy, an employee or customer record, or live
  system state.
- You are about to answer "is this allowed?" and need the clause, not a vibe.
- Another skill needs evidence before it can compile a capsule.

## Tool

`search_enterprise_knowledge(query, sources?, user_context?)`

| field | meaning |
| --- | --- |
| `query` | Natural language or keywords. |
| `sources` | Optional filter over the eight connectors. |
| `user_context` | `{ user_id, tenant_id, role }` — results the role may not see are omitted, not redacted. |

Returns `evidence[]` (`id`, `system`, `kind`, `title`, `excerpt`, `confidence`,
`lastVerifiedAt`, `stale`) plus a `coverage` report naming which connectors were
searched and which returned stale material.

## Rules

1. **Never state a policy without its citation.** Quote the excerpt and name the
   system and document.
2. **Surface staleness, do not silently trust it.** A source past its freshness
   budget is reported with `stale: true`; say so in your answer and treat any
   policy derived from it as `require_approval` rather than `allow`.
3. **Low coverage is a finding.** If a connector was unavailable, report the gap
   instead of presenting partial results as complete.
4. **Read-only.** This skill never writes to a source system.

## Example

> "What access can a contractor get to a production repository?"

Returns the Contractor Onboarding Policy (Notion, 0.99, current), the Security
Review Checklist (Google Docs, 0.83, current), and the Access Control Standard —
each with the sentence that answers the question, so the next step can cite it.
