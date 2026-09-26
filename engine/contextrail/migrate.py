"""Plain-SQL migration runner (checklist T037).

Files in `contextrail/migrations/NNNN_name.sql` are applied in filename order, each in its own transaction,
and recorded in `schema_migrations` with a SHA-256 checksum. Applied migrations are immutable: if a file's
checksum no longer matches what was applied, the runner refuses to continue rather than let the schema drift
silently. To change the schema, add a new file.

Usage:  python -m contextrail.migrate [DATABASE_URL]
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from importlib import resources

import psycopg

MIGRATIONS_PACKAGE = "contextrail.migrations"
# One writer at a time: two engines starting together must not race the same migration.
_ADVISORY_LOCK_KEY = 7_214_119_001


class MigrationDrift(RuntimeError):
    """An already-applied migration file was edited after it ran."""


@dataclass(frozen=True)
class Migration:
    version: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def discover() -> list[Migration]:
    files = [f for f in resources.files(MIGRATIONS_PACKAGE).iterdir() if f.name.endswith(".sql")]
    out = [Migration(version=f.name.removesuffix(".sql"), sql=f.read_text(encoding="utf-8")) for f in files]
    return sorted(out, key=lambda m: m.version)


def apply_all(conninfo: str) -> list[str]:
    """Apply pending migrations. Returns the versions applied by this call."""
    applied_now: list[str] = []
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (_ADVISORY_LOCK_KEY,))
        try:
            conn.execute(
                """create table if not exists schema_migrations (
                       version text primary key,
                       checksum text not null,
                       applied_at timestamptz not null default now())"""
            )
            done = dict(conn.execute("select version, checksum from schema_migrations").fetchall())
            for m in sorted(discover(), key=lambda m: m.version):
                if m.version in done:
                    if done[m.version] != m.checksum:
                        raise MigrationDrift(
                            f"migration {m.version} was edited after it was applied; add a new migration instead"
                        )
                    continue
                with conn.transaction():
                    conn.execute(m.sql)
                    conn.execute(
                        "insert into schema_migrations (version, checksum) values (%s, %s)",
                        (m.version, m.checksum),
                    )
                applied_now.append(m.version)
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (_ADVISORY_LOCK_KEY,))
    return applied_now


def main(argv: list[str]) -> int:
    from contextrail.settings import get_settings

    url = argv[1] if len(argv) > 1 else get_settings().database_url
    applied = apply_all(url)
    print(f"migrations applied: {', '.join(applied) if applied else 'none (up to date)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
