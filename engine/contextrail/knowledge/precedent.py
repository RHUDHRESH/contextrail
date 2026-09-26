"""Precedents and publish-back (checklist T180, CLAUDE.md §10): episodic memory counted from the audit chain only.

    approved / refused  = approval.decided events in the chain, per (rule, entitlement)
    the rule            = what the run's stage.govern event recorded for that action
    the entitlement     = the action's target, accepted only if hashing it gives the params_hash the decision
                          was bound to (so an edited actions row cannot move a decision to another entitlement)

The whole chain is verified first. A broken chain yields no precedents at all (ChainBroken), because a count that
might have been forged is worse than no count. Only human decisions on held actions are precedents; a policy
refusal is not a precedent, it is the rule.

Publish-back writes drafts only: `draft_precedent_page` rewrites the counts section of a precedent page into
`drafts/`, and `draft_solutions_article` drafts a Freshservice Solutions article for a person to review. Nothing
here edits a curated page or calls Freshservice.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from psycopg import AsyncConnection
from pydantic import BaseModel, ConfigDict

from contextrail.audit.chain import verify_chain
from contextrail.canonical import params_hash
from contextrail.knowledge.okf import Bundle, Page

COUNTS_HEADING = "## Counts from the audit chain"


class ChainBroken(RuntimeError):
    """The audit chain failed verification; precedents are not computed from it."""


class CountedDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seq: int
    run_id: UUID
    action_id: str
    decision: Literal["approved", "refused"]
    approver: str
    channel: str
    day: str


class Precedent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    entitlement: str
    approved: int = 0
    refused: int = 0
    runs: tuple[UUID, ...] = ()
    cites: tuple[int, ...] = ()                 # audit seq of every counted decision
    decisions: tuple[CountedDecision, ...] = ()


class PrecedentBook(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: dict[str, Precedent]
    chain_rows: int                             # audit rows verified before counting
    skipped: list[str]                          # decisions that could not be attributed, and why

    def get(self, rule_id: str, entitlement: str) -> Precedent:
        return self.entries.get(f"{rule_id}|{entitlement}") or Precedent(rule_id=rule_id, entitlement=entitlement)


async def compute_precedents(conn: AsyncConnection) -> PrecedentBook:
    rows = await (await conn.execute(
        "select seq, run_id, event, payload, prev_hash, hash, at from audit order by seq")).fetchall()
    check = verify_chain(rows)
    if not check.ok:
        raise ChainBroken(f"audit chain broken at seq {check.first_broken_seq} ({check.reason}); "
                          "no precedents are computed from it")
    rule_of: dict[tuple[UUID, str], str] = {}
    decided = []
    for r in rows:
        if r["event"] == "stage.govern":
            for aid, (_verdict, rule_id) in r["payload"].get("verdicts", {}).items():
                rule_of[(r["run_id"], aid)] = rule_id
        elif r["event"] == "approval.decided":
            decided.append(r)
    run_ids = list({r["run_id"] for r in decided})
    actions = {(a["run_id"], a["id"]): a for a in await (await conn.execute(
        "select run_id, id, kind, target from actions where run_id = any(%s)", (run_ids,))).fetchall()}

    counted: dict[str, list[CountedDecision]] = {}
    skipped = []
    for r in decided:
        p = r["payload"]
        key = (r["run_id"], p["action_id"])
        action, rule_id = actions.get(key), rule_of.get(key)
        where = f"seq {r['seq']} ({r['run_id']}/{p['action_id']})"
        if rule_id is None:
            skipped.append(f"{where}: no govern event in the chain records its rule")
            continue
        if action is None or params_hash(action["kind"], action["target"]) != p["params_hash"]:
            skipped.append(f"{where}: the action's params_hash no longer matches the decision; not attributed")
            continue
        counted.setdefault(f"{rule_id}|{action['target'].get('entitlement')}", []).append(CountedDecision(
            seq=r["seq"], run_id=r["run_id"], action_id=p["action_id"], decision=p["decision"],
            approver=p["approver"], channel=p["channel"], day=r["at"].date().isoformat()))

    entries = {}
    for k, ds in counted.items():
        rule_id, entitlement = k.split("|", 1)
        entries[k] = Precedent(
            rule_id=rule_id, entitlement=entitlement,
            approved=sum(d.decision == "approved" for d in ds), refused=sum(d.decision == "refused" for d in ds),
            runs=tuple(dict.fromkeys(d.run_id for d in ds)), cites=tuple(d.seq for d in ds), decisions=tuple(ds))
    return PrecedentBook(entries=entries, chain_rows=check.rows, skipped=skipped)


# --- drafts --------------------------------------------------------------------------------------------------------

def page_key(page: Page) -> tuple[str, str]:
    """The (rule, entitlement) a precedent page counts, from its `precedent:` frontmatter key."""
    key = (page.meta.model_extra or {}).get("precedent") if page.meta else None
    if not isinstance(key, dict) or not key.get("rule") or not key.get("entitlement"):
        raise ValueError(f"{page.path} has no `precedent: {{rule, entitlement}}` frontmatter key")
    return key["rule"], key["entitlement"]


def render_counts(p: Precedent, chain_rows: int) -> str:
    lines = [COUNTS_HEADING,
             (f"Approved {p.approved}, refused {p.refused}, for {p.rule_id} and `{p.entitlement}`, counted from "
              f"the verified audit chain ({chain_rows} audit rows checked).")]
    if p.decisions:
        lines.append("")
        lines += [f"- Run `{d.run_id}`: {d.decision} by {d.approver} via {d.channel} on {d.day} (audit seq {d.seq})"
                  for d in p.decisions]
    else:
        lines.append("No decisions have been recorded by ContextRail yet.")
    return "\n".join(lines)


@dataclass(frozen=True)
class PageDraft:
    path: str   # bundle-relative, always under drafts/
    text: str


def draft_precedent_page(bundle: Bundle, path: str, book: PrecedentBook) -> PageDraft:
    """The precedent page with its counts section recomputed, as a draft. Everything else is kept byte for byte."""
    rule_id, entitlement = page_key(bundle.pages[path])
    text = (bundle.root / path).read_text(encoding="utf-8").replace("\r\n", "\n")
    counts = render_counts(book.get(rule_id, entitlement), book.chain_rows) + "\n"
    pattern = re.compile(rf"^{re.escape(COUNTS_HEADING)}\n.*?(?=^## |^# |\Z)", re.MULTILINE | re.DOTALL)
    new = pattern.sub(lambda _m: counts + "\n", text, count=1) if pattern.search(text) else f"{text}\n{counts}"
    return PageDraft(path=f"drafts/{path}", text=new.rstrip("\n") + "\n")


def write_draft(root: Path, draft: PageDraft) -> Path:
    """The only write in the knowledge layer, and it can only land in drafts/ (a person promotes it)."""
    if not draft.path.startswith("drafts/") or ".." in Path(draft.path).parts:
        raise ValueError(f"drafts are written under drafts/ only, not {draft.path}")
    out = root / draft.path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(draft.text, encoding="utf-8", newline="\n")
    return out


class SolutionsDraft(BaseModel):
    """Text for a Freshservice Solutions article, for a person to review and publish. Not an API payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    body_html: str
    status: Literal["draft"] = "draft"
    source_page: str
    cites: tuple[int, ...]


def _times(n: int) -> str:
    return f"{n} time" if n == 1 else f"{n} times"


def _plain(markdown: str) -> str:
    """Page prose for an article: links become their text, code marks go, line wraps become spaces."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", markdown).replace("`", "")
    return " ".join(text.split())


def draft_solutions_article(bundle: Bundle, path: str, book: PrecedentBook) -> SolutionsDraft:
    page = bundle.pages[path]
    rule_id, entitlement = page_key(page)
    p = book.get(rule_id, entitlement)
    situation = page.section("The situation")
    paras = [page.meta.description or "", _plain(situation.text) if situation else "",
             (f"ContextRail's audit chain records this request approved {_times(p.approved)} and refused "
              f"{_times(p.refused)} under {rule_id} for {entitlement}."),
             ("Drafted by ContextRail from the verified audit chain. It is not published: a person reviews it and "
              "publishes it in Freshservice Solutions.")]
    body = f"<h2>{html.escape(page.title)}</h2>" + "".join(f"<p>{html.escape(x)}</p>" for x in paras if x)
    return SolutionsDraft(title=f"Precedent: {page.title}", body_html=body, source_page=f"knowledge/{path}",
                          cites=p.cites)
