"""Scripted FIXTURE demo through the real rail (checklist T221, partial: replay recording and deployment are not done).

    python -m contextrail.demo [DATABASE_URL] [--state-dir DIR] [--markdown PATH] [--embedded-postgres]

Seeds the database (migrations and the identity map for every door), resets FIXTURE connector state, then sends
each scripted request through the real Runner, in order, with the offline HeuristicExtractor and TemplateExplainer,
so it needs no model key and no network. It prints one row per scenario, built from the same RunView every door
renders. `--markdown` writes docs/DEMO_DATA.md from that same run: every verdict in the document is one the rail
produced. `--embedded-postgres` starts a throwaway PostgreSQL via pgserver (a dev dependency) for laptops without one.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from contextrail import repo
from contextrail.connectors.registry import build_registry
from contextrail.db import Database
from contextrail.fixtures import load
from contextrail.migrate import apply_all
from contextrail.policy.engine import PolicyEngine
from contextrail.policy.loader import load_rules
from contextrail.rail.discover import HeuristicExtractor
from contextrail.rail.plan import TemplateExplainer
from contextrail.rail.runner import RailDeps, Runner
from contextrail.seed import approver_directory, reset_fixture_state, seed_identity
from contextrail.surfaces.door import Door
from contextrail.surfaces.presenter import RowView, RunView

SOURCE = "web"  # the operator's glass-box channel; no door (Slack, email, Teams, voice) is exercised by this script


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    request: str
    requested_by: str  # person_id of whoever asks, as a door would resolve them
    shows: str


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("same-as-rahul", "Same access as a peer", "Give Anil the same access as Rahul Mehta", "p-anil",
             "Mirrored access filtered by Anil's own role and seniority; old-team access revoked on transfer; the "
             "planted 'ignore policy' message is in the case file and changes nothing."),
    Scenario("ambiguous-rahul", "Two people named Rahul", "Give Anil the same access as Rahul", "p-anil",
             "Relevance is not identity: two exact matches, so the rail asks instead of guessing."),
    Scenario("contractor-onboarding", "Contractor onboarding", "Priya starts Monday, give her everything she needs",
             "p-sanjay", "'Everything' includes what policy must refuse: the SOW repo is held for Security, "
             "production credentials are refused with no approval path."),
    Scenario("team-transfer", "Team transfer", "Give Tanvi the same access as Wei Zhang", "p-tanvi",
             "A transfer: new-team access granted and old-team access revoked in the same run, all read back."),
    Scenario("senior-admin", "A senior engineer asks for production admin",
             "Give Kiran the same access as Mariam Qureshi", "p-kiran",
             "The class of entitlement refused for Anil (mid-level) is held for Security for a senior engineer."),
    Scenario("raw-pii", "An analytics hire's access includes raw customer PII",
             "Neha Joshi starts Monday, give her everything she needs", "p-sanjay",
             "Masked views come from the role baseline; written POL-DAT-001 allows raw PII only for the "
             "data-analytics team."),
    Scenario("paid-seat", "A paid SaaS seat", "Give Leela the same access as Jonas Weber", "p-leela",
             "A paid seat is held for the person's manager; the free repository read is granted and read back."),
    Scenario("question", "A question, not a request", "What happened to Anil's access request?", "p-anil",
             "Questions are routed to receipts; nothing is run."),
)


@dataclass(frozen=True)
class Outcome:
    scenario: Scenario
    view: RunView
    message: str                          # the rail's last stage message
    untrusted: tuple[str, ...] = ()       # Slack message ids retrieved into the case file as untrusted evidence

    @property
    def status(self) -> str:
        return self.view.status

    @property
    def grants(self) -> Counter:
        return Counter(r.verdict for r in self.view.rows if r.kind == "grant")

    @property
    def revokes(self) -> list[RowView]:
        return [r for r in self.view.rows if r.kind == "revoke"]


def people() -> dict[str, str]:
    return {p["person_id"]: p["display_name"] for p in load("identity")["people"]}


def build_deps(db: Database, state_dir: Path | None = None) -> RailDeps:
    """The rail as the conftest `rail` fixture builds it: FIXTURE connectors, shipped rules, no model."""
    rules = load_rules()
    return RailDeps(db=db, registry=build_registry(state_dir), engine=PolicyEngine(rules, approver_directory()),
                    rules=rules, extractor=HeuristicExtractor(), explainer=TemplateExplainer(people()))


def door_for(runner: Runner) -> Door:
    modes = {name: c.mode for name, c in runner.d.registry.connectors.items()}
    return Door(runner, people=people(), modes=modes)


async def run_scenario(door: Door, scenario: Scenario) -> Outcome:
    """Start and run one request through the real Runner; read the result back the way a door does."""
    runner = door.runner
    rid = await runner.start(source=SOURCE, request_text=scenario.request, source_ref=f"demo:{scenario.key}",
                             requested_by=scenario.requested_by)
    await runner.run(rid)
    view = await door.get_status(rid)
    async with door.db.connection() as c:
        capsule = (await repo.get_run(c, rid))["capsule"] or {}
    untrusted = tuple(e["id"].removeprefix("EV-") for e in capsule.get("evidence", []) if e["kind"] == "message")
    return Outcome(scenario, view, runner.d.events.history(rid)[-1].message, untrusted)


async def run_script(database_url: str, *, state_dir: Path | None = None,
                     scenarios: tuple[Scenario, ...] = SCENARIOS) -> tuple[list[Outcome], dict[str, str]]:
    """Seed, reset FIXTURE state, run every scenario in order. Returns the outcomes and the rail's labels."""
    apply_all(database_url)
    seed_identity(database_url)
    reset_fixture_state(state_dir)
    async with Database(database_url, max_size=4) as db:
        deps = build_deps(db, state_dir)
        door = door_for(Runner(deps))
        outcomes = [await run_scenario(door, s) for s in scenarios]
    labels = {"extractor": deps.extractor.name, "explainer": deps.explainer.name, **door.modes}
    return outcomes, labels


# --- rendering -------------------------------------------------------------------------------------------------

def _counts(o: Outcome) -> str:
    g = o.grants
    return f"{g['ALLOW']}/{g['HOLD']}/{g['REFUSE']}"


def _notes(o: Outcome) -> list[str]:
    if not o.view.rows:
        return [o.message]
    out = []
    for r in o.view.rows:
        if r.verdict == "HOLD":
            out.append(f"held: {r.label} -> {r.approver_name or r.approver_id} ({r.rule_id})")
        elif r.verdict == "REFUSE":
            out.append(f"refused: {r.label} ({r.rule_id})")
    return out


def render_table(outcomes: list[Outcome]) -> str:
    lines = [f"{'#':>2}  {'scenario':<22} {'status':<18} {'grants A/H/R':<13} {'revokes':<8} {'verified':<8}",
             "-" * 78]
    for i, o in enumerate(outcomes, 1):
        verified = sum(r.state == "verified" for r in o.view.rows)
        lines.append(f"{i:>2}  {o.scenario.key:<22} {o.status:<18} {_counts(o):<13} {len(o.revokes):<8} {verified:<8}")
        lines += [f"      {n}" for n in _notes(o)]
    return "\n".join(lines)


def _org_section() -> list[str]:
    hr = load("hris")["people"]
    by_id = {p["source_id"]: p for p in hr}
    execs = [p for p in hr if p["manager_id"] is None]
    teams: dict[str, list[dict]] = {}
    for p in hr:
        teams.setdefault(p["team"], []).append(p)
    exec_only = {t for t, members in teams.items() if all(p["manager_id"] is None for p in members)}
    intro = (f"Northbeam Robotics is invented. {len(hr)} people; every email is on `northbeam.example`, every "
             "phone number is in the fictional `+91999000xxxx` range, and every connector reports FIXTURE.")
    leaders = ", ".join(f"{p['display_name']} ({p['role']})" for p in execs)
    out = ["## The organisation (FIXTURE)", "", intro, "",
           f"Executives (no manager in the fixture; the CEO is out of scope): {leaders}.", "",
           "| Team | Led by | People | Roles |", "|---|---|---|---|"]
    for team in sorted(set(teams) - exec_only):
        members = teams[team]
        heads = [p for p in members if by_id.get(p["manager_id"] or "", {}).get("team") != team]
        managers = {p["manager_id"] for p in heads}
        if len(heads) == 1:
            led = f"{heads[0]['display_name']} ({heads[0]['role']})"
        else:
            led = f"no team lead; reports to {by_id[managers.pop()]['display_name']}" if len(managers) == 1 else "-"
        roles = Counter(p["role"] for p in members)
        role_text = ", ".join(f"{r} x{n}" if n > 1 else r for r, n in sorted(roles.items()))
        out.append(f"| {team} | {led} | {len(members)} | {role_text} |")
    contractors = [p for p in hr if p["employment_type"] == "contractor"]
    vendor = [p for p in hr if p["employment_type"] == "vendor"]
    moved = [p for p in hr if p.get("previous_team")]
    starters = [p for p in hr if p["start_date"] == "2026-09-28"]
    rahuls = [p for p in hr if p["display_name"].split()[0] == "Rahul"]
    out += ["", "| Who | Detail |", "|---|---|"]
    out += [f"| Contractor {p['source_id']} {p['display_name']} | {p['team']}; SOW repos "
            f"{', '.join(p['sow_repos']) or 'none'}; ends {p['end_date']} |" for p in contractors]
    out += [f"| Vendor {p['source_id']} {p['display_name']} | {p['vendor_company']}; {p['team']}; ends "
            f"{p['end_date']} |" for p in vendor]
    out += [f"| Transfer {p['source_id']} {p['display_name']} | {p['previous_team']} -> {p['team']} on "
            f"{p['transfer_date']} |" for p in moved]
    out += [f"| Starts Monday {p['source_id']} {p['display_name']} | {p['employment_type']}, {p['role']}, "
            f"{p['team']} |" for p in starters]
    out += [f"| Rahul {p['source_id']} {p['display_name']} | {p['role']}, {p['team']} |" for p in rahuls]
    slack = load("slack_corpus")["messages"]
    sizes = (f"Fixture sizes: {len(load('entitlements')['catalog'])} catalogue entitlements, "
             f"{len(load('roles')['roles'])} role baselines, {len(load('github')['repos'])} GitHub repositories, "
             f"{len(slack)} Slack messages ({sum(m['planted'] for m in slack)} planted injections), "
             f"{len(load('documents')['documents'])} statements of work, {len(load('incidents')['incidents'])} "
             f"incidents, {len(load('payments')['customers'])} customer accounts.")
    return [*out, "", sizes]


def _scenario_section(i: int, o: Outcome) -> list[str]:
    s, names = o.scenario, people()
    planted = {m["id"] for m in load("slack_corpus")["messages"] if m["planted"]}
    out = [f"### {i}. {s.title} (`{s.key}`)", "", f"> {s.request}", "",
           f"Asked by {names[s.requested_by]} (`{s.requested_by}`). {s.shows}", "",
           f"Rail status: **{o.status}**. Last stage message: \"{o.message}\""]
    if o.view.needs:
        cands = "; ".join(f"{c['display_name']} ({c['source_id']}, {c['team']})"
                          for n in o.view.needs for c in n["candidates"])
        out += ["", f"Candidates offered, nothing compiled on a guess: {cands}."]
    if o.untrusted:
        marked = [f"`{m}`" + (" (planted injection)" if m in planted else "") for m in o.untrusted]
        out += ["", "Untrusted Slack evidence in the sealed case file: " + ", ".join(marked) + "."]
    if o.view.rows:
        out += ["", "| Action | Verdict | Rule | Approver | State |", "|---|---|---|---|---|"]
        out += [f"| {r.kind} {r.label} | {r.verdict} | {r.rule_id} | {r.approver_name or ''} | {r.state} |"
                for r in o.view.rows]
        quoted = [r for r in o.view.rows if r.verdict != "ALLOW"]
        out += [""] + [f"- {r.action_id} {r.verdict}: {r.explanation} Clause: \"{r.clause}\"" for r in quoted]
    return out + [""]


_GENERATED = ("Generated by `python -m contextrail.demo --embedded-postgres --markdown ../docs/DEMO_DATA.md` "
              "(run in `engine/`) from a real run of the rail over the FIXTURE data. Do not edit by hand: "
              "`engine/tests/test_demo.py` fails when this file and the rail disagree.")
_RUN_ORDER = ("Each request below was run in this order on one freshly seeded database and FIXTURE state. The "
              "verdicts, rules, approvers and states are copied from the rail's RunView, not written by hand.")
_NOT_BUILT = [
    "- The incident access rule (POL-EMG-001) is implemented but this script does not show that scenario.",
    ("- The refund rail (POL-REF-001/002, T071; Dodo refund with read-back, T207): `fixtures/payments.json` "
     "(customers, plans, prior credits including the duplicate) is data only."),
    "- T221 is partial: replay recordings for the LLM replay tier and the deployed host are not done.",
]


def render_markdown(outcomes: list[Outcome], labels: dict[str, str]) -> str:
    modes = ", ".join(f"{k} {v}" for k, v in labels.items() if k not in ("extractor", "explainer"))
    fixture = (f"Everything. Connectors: {modes}. Intent extraction: `{labels['extractor']}` (deterministic, no "
               f"model call); explanations: `{labels['explainer']}`. No network call and no LIVE system is touched. "
               "People, companies, emails, phone numbers, Slack messages, SOWs, incidents and customers are "
               f"invented. Runs are recorded with source `{SOURCE}`: this script calls the Runner directly and "
               "renders the same RunView the doors render; it does not exercise the Slack, email, Teams or voice "
               "doors.")
    out = ["# Demo data: Northbeam (FIXTURE)", "", _GENERATED, "", "## What is FIXTURE", "", fixture, ""]
    out += _org_section()
    out += ["", "## Scenarios and what the rail decided", "", _RUN_ORDER, "",
            "| # | Scenario | Status | Grants ALLOW/HOLD/REFUSE | Revokes | Verified |", "|---|---|---|---|---|---|"]
    for i, o in enumerate(outcomes, 1):
        verified = sum(r.state == "verified" for r in o.view.rows)
        out.append(f"| {i} | {o.scenario.title} | {o.status} | {_counts(o)} | {len(o.revokes)} | {verified} |")
    out.append("")
    for i, o in enumerate(outcomes, 1):
        out += _scenario_section(i, o)
    out += ["## Not shown or not built yet", "", *_NOT_BUILT, ""]
    return "\n".join(out)


# --- command line ----------------------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m contextrail.demo", description=__doc__.splitlines()[0])
    parser.add_argument("database_url", nargs="?", help="default: DATABASE_URL from settings")
    parser.add_argument("--state-dir", type=Path, help="FIXTURE connector state (default: STATE_DIR or <repo>/.state)")
    parser.add_argument("--markdown", type=Path, help="also write the demo data document here")
    parser.add_argument("--embedded-postgres", action="store_true", help="run against a throwaway pgserver database")
    args = parser.parse_args(argv[1:])

    server, datadir = None, None
    url = args.database_url
    if args.embedded_postgres:
        import pgserver  # dev dependency; only needed without a PostgreSQL server

        datadir = tempfile.mkdtemp(prefix="cr-demo-pg-")
        server = pgserver.get_server(datadir, cleanup_mode="stop")
        url = server.get_uri()
    if url is None:
        from contextrail.settings import get_settings

        url = get_settings().database_url
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None  # psycopg async needs it on Windows
    try:
        outcomes, labels = asyncio.run(run_script(url, state_dir=args.state_dir), loop_factory=loop)
    finally:
        if server is not None:
            server.cleanup()
            shutil.rmtree(datadir, ignore_errors=True)
    print(render_table(outcomes))
    if args.markdown:
        args.markdown.write_bytes(render_markdown(outcomes, labels).encode("utf-8"))
        print(f"\nwrote {args.markdown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
