"""`python -m contextrail.worker --drain` in a real subprocess: same platform, same handlers, own process."""

import os
import subprocess
import sys
import uuid

import psycopg
from psycopg.types.json import Jsonb


def test_worker_process_drains_ready_jobs_it_has_handlers_for(migrated_db, tmp_path):
    rid = uuid.uuid4()
    with psycopg.connect(migrated_db, autocommit=True) as c:
        c.execute("insert into runs (id, source, source_ref, request_text) values (%s, 'freshservice', '31', %s)",
                  (rid, "Give Anil the same access as Rahul Mehta"))
        c.execute("insert into jobs (kind, payload) values ('rail.run', %s), ('door.update', '{}')",
                  (Jsonb({"run_id": str(rid)}),))
    env = {**os.environ, "DATABASE_URL": migrated_db, "STATE_DIR": str(tmp_path / "state"),
           "WORKER_IN_PROCESS": "false", "LOG_JSON": "true"}
    r = subprocess.run([sys.executable, "-m", "contextrail.worker", "--drain"], cwd=tmp_path, env=env,
                       capture_output=True, text=True, timeout=180, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    with psycopg.connect(migrated_db) as c:
        status = c.execute("select status from runs where id = %s", (rid,)).fetchone()[0]
        jobs = dict(c.execute("select kind, done from jobs where kind in ('rail.run', 'door.update')").fetchall())
    assert status == "awaiting_approval"
    assert jobs == {"rail.run": True, "door.update": False}   # door.update's handler lives with the doors
    assert '"worker_drained"' in r.stdout
