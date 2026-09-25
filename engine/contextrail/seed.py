"""Seed a database and the FIXTURE connectors for a demo or a test (checklist T080).

    python -m contextrail.seed [DATABASE_URL] [--keep-state]

1. Apply migrations.
2. Upsert the identity map for every door from fixtures/identity.json.
3. Reset FIXTURE connector state from the seeds (unless --keep-state).

`approver_directory()` builds the FIXTURE approver directory that the policy engine uses (roster plus
HRIS manager_id -> person_id), from the same identity file, so the directory and the identity map cannot disagree.
"""

from __future__ import annotations

import sys

import psycopg

from contextrail.fixtures import load
from contextrail.migrate import apply_all
from contextrail.policy.approvers import StaticDirectory

FIXTURE_CONNECTORS = ("hris", "entitlements", "github", "slack_corpus")
_ID_COLUMNS = ("person_id", "display_name", "email", "slack_user_id", "teams_aad_id", "phone", "hris_id",
               "preferred_door", "can_approve")


def seed_identity(conninfo: str) -> int:
    rows = load("identity")["people"]
    cols = ", ".join(_ID_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in _ID_COLUMNS[1:])
    with psycopg.connect(conninfo) as conn, conn.transaction():
        for r in rows:
            conn.execute(
                f"insert into identity_map ({cols}) values ({', '.join(['%s'] * len(_ID_COLUMNS))}) "
                f"on conflict (person_id) do update set {updates}",
                tuple(r.get(c) for c in _ID_COLUMNS))
    return len(rows)


def reset_fixture_state(directory=None) -> list[str]:
    from contextrail.connectors.state import FixtureState

    for name in FIXTURE_CONNECTORS:
        FixtureState(name, directory=directory).reset()
    return list(FIXTURE_CONNECTORS)


def approver_directory() -> StaticDirectory:
    ident = load("identity")
    by_hris = {p["hris_id"]: p["person_id"] for p in ident["people"] if p.get("hris_id")}
    return StaticDirectory(roster={k: list(v) for k, v in ident["roster"].items()}, managers=by_hris)


def main(argv: list[str]) -> int:
    from contextrail.settings import get_settings

    args = [a for a in argv[1:] if not a.startswith("--")]
    url = args[0] if args else get_settings().database_url
    applied = apply_all(url)
    n = seed_identity(url)
    reset = [] if "--keep-state" in argv else reset_fixture_state()
    print(f"migrations: {applied or 'up to date'}; identity rows: {n}; fixture state reset: {reset or 'kept'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
