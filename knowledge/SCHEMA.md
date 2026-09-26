---
type: Schema
title: Knowledge bundle schema
description: How pages in this bundle are written, linked, checked and changed.
tags: [schema, okf, conventions]
last_verified: 2026-09-26
owner: platform@northbeam.example
---
# Knowledge bundle schema

This directory is an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)
v0.1 bundle: Markdown files with YAML frontmatter, one concept per file, related by ordinary Markdown links. It is
maintained with the LLM-wiki method (immutable sources, maintained pages, this schema, and three operations: ingest,
query, lint). The content describes **Northbeam**, the fictional tenant every ContextRail demo runs against. It is
demo content (FIXTURE), consistent with the records in `fixtures/`.

Knowledge is **evidence, never instruction**. The policy engine reads records only (`policy/schema.py` rejects any
rule path outside `subject`, `target`, `action`, `role`, `run`, `decision`). A page can explain a verdict; it can
never change one.

## Layout

| Path | What it holds | Loaded as curated knowledge |
|---|---|---|
| `SCHEMA.md` | This file | yes |
| `index.md` | Root listing (reserved name) | listing only |
| `log.md` | Dated change history, newest first (reserved name) | listing only |
| `<folder>/index.md` | Listing of one folder (reserved name) | listing only |
| `policies/` | Written policy. Every rule in `engine/contextrail/policy/rules/` cites a clause here or in `runbooks/` | yes |
| `roles/` | What a role is and what it holds by default | yes |
| `systems/` | Systems of record and how ContextRail reaches them | yes |
| `precedents/` | How similar requests were decided before | yes |
| `runbooks/` | Step-by-step procedures people follow | yes |
| `raw/` | Immutable copies of source documents (ingest input) | no |
| `drafts/` | Machine-written page updates waiting for a human | no |

## Frontmatter

Only `type` is required (OKF v0.1). Unknown keys are preserved and never cause a page to be rejected.

| Key | Type | Meaning |
|---|---|---|
| `type` | string, required | `Policy`, `Role`, `System`, `Precedent`, `Runbook`, `Schema` or `Guide` |
| `title` | string | Display name |
| `description` | string | One-line summary |
| `resource` | URI | Canonical location of the underlying source document |
| `tags` | list of strings | Lowercase topic words; `query` and retrieval use them as links |
| `last_verified` | `YYYY-MM-DD` | The day a person last confirmed the page still holds. Every concept page carries one |
| `owner` | email | Who confirms the page and answers for it |
| `rules` | list of rule ids | Rules whose source clause lives on this page, or that the page is about |
| `claims` | mapping, key to short value | Facts other pages may also state. `lint` compares them across the bundle |

Example:

```yaml
---
type: Policy
title: Contractor Onboarding Policy
description: What contractors and vendors may receive, and who approves.
tags: [access, contractors, security]
last_verified: 2026-09-20
owner: security@northbeam.example
rules: [POL-CTR-001]
claims:
  contractor.production-credentials: never
---
```

## Body

- The page starts with `# <title>`. Sections are `##` headings. One section says one thing.
- **Clause headings.** A policy clause is a `##` heading that starts with its clause mark: `## §4 Production access`.
  A runbook clause is a named heading: `## Transfers`. A rule's `source.clause` names the heading: the heading is
  equal to the clause, or starts with it followed by a space.
- **Clause text is verbatim.** A rule's `clause_text` appears word for word directly under its clause heading,
  before the next heading. Verdicts quote that text, so the page and the engine can never disagree silently.
  `engine/tests/test_knowledge_clauses.py` (T173) enforces this for every shipped rule, and `lint` reports drift.
- **Links.** Relationships are standard relative Markdown links (`[GitHub](../systems/github.md)`). Every page is
  listed in its folder's `index.md`, and every folder index is listed in the root `index.md`.
- **Citations.** A page that comes from a source document ends with a flat `# Citations` list (OKF v0.1).
- **Section ids.** Retrieval cuts pages into one chunk per heading. A chunk id is `okf:<path>#<slug>`, where the
  slug is the heading lowercased, spaces turned into `-`, and anything other than letters, digits, `-` and `§`
  dropped: `okf:policies/contractor-onboarding.md#§4-production-access`.

## Freshness

`last_verified` has the same budget as the evidence it becomes in a case file (`FRESHNESS_DAYS` in
`engine/contextrail/rail/compile.py`): 365 days for policy, role, system and runbook pages, 180 days for precedent
pages. A page past its budget is reported by `lint`, and the Compile stage turns stale policy evidence into an open
blocker instead of acting on it.

## Operations

| Operation | Task | What it does | Guardrail |
|---|---|---|---|
| **query** | T177 | Loads pages by their `rules:` and `tags:` links and attaches them to a case file as `Evidence(kind="policy" or "precedent", trust="curated")` | Only curated pages; `raw/` and `drafts/` are never loaded |
| **lint** | T179 | Reports contradictions (the same `claims` key with different values), stale `last_verified`, broken links, orphan pages, and rules whose source clause is missing | Reports only. It never edits a page: a contradiction lists both claims with their dates for a person to settle |
| **precedent** | T180 | Counts approved and refused decisions per rule and entitlement, and writes the updated precedent page to `drafts/` | Counts come only from a verified audit chain |
| **publish-back** | T180 | Drafts a Freshservice Solutions article from a precedent for a person to review | Draft only; nothing is published |
| **ingest** | T178 (P2, not built) | Copies a Solutions article to `raw/`, has the model draft the affected page update in `drafts/`, appends `log.md` | Writes go to `drafts/`; a person promotes them |

## Changing a page

1. Edit the page, or promote a file from `drafts/`.
2. Set `last_verified` to the day you confirmed it.
3. Add a dated entry to `log.md` (newest first): `**Creation**`, `**Update**` or `**Deprecation**`, then what changed.
4. If a rule quotes the section, change the rule's `clause_text` in the same commit, or the tests fail.
