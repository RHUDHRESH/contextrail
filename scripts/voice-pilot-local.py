"""Run an isolated local engine for a temporary Vobiz voice pilot.

This is a development helper, not an AWS deployment. It uses throwaway PostgreSQL and
fixture connector state; live Freshservice writes are deliberately disabled. The
voice service and tunnel are started separately once their public URL is known.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pgserver
import psycopg

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"
LOCAL_ENV = ROOT.parent / "contextrail" / ".env"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slack", action="store_true",
                        help="also run the real Slack Socket Mode door against this isolated pilot database")
    parser.add_argument("--freshservice", action="store_true",
                        help="enable the configured Freshservice tenant for labeled live ticket requests")
    parser.add_argument("--port", type=int, default=8000, help="local engine port (default: 8000)")
    args = parser.parse_args()
    if not LOCAL_ENV.is_file():
        raise SystemExit("Local source .env is missing")
    run_dir = Path(tempfile.mkdtemp(prefix="contextrail-voice-pilot-"))
    server = pgserver.get_server(str(run_dir / "pg"), cleanup_mode="stop")
    engine: subprocess.Popen | None = None
    slack: subprocess.Popen | None = None
    try:
        env = {**os.environ, **read_env(LOCAL_ENV)}
        env.update({
            "DATABASE_URL": server.get_uri(),
            "STATE_DIR": str(run_dir / "state"),
            "FS_DOMAIN": env.get("FS_DOMAIN", "") if args.freshservice else "",
            "FS_API_KEY": env.get("FS_API_KEY", "") if args.freshservice else "",
            "FS_WORKSPACE_ID": env.get("FS_WORKSPACE_ID", "") if args.freshservice else "",
            "FD_DOMAIN": "",
            "FD_API_KEY": "",
            "FS_WEBHOOK_SECRET": "",
            "SLACK_BOT_TOKEN": "" if not args.slack else env.get("SLACK_BOT_TOKEN", ""),
            "SLACK_APP_TOKEN": "" if not args.slack else env.get("SLACK_APP_TOKEN", ""),
            "SLACK_SIGNING_SECRET": "",
            # When Socket Mode is enabled, its worker has the live Slack client. A separate API worker with Slack
            # credentials stripped would claim approvals first and incorrectly exhaust its retries.
            "WORKER_IN_PROCESS": "false" if args.slack else "true",
            "PUBLIC_URL": f"http://127.0.0.1:{args.port}",
        })
        engine_env = {**env, "SLACK_BOT_TOKEN": "", "SLACK_APP_TOKEN": "", "SLACK_SIGNING_SECRET": ""}
        subprocess.run([sys.executable, "-m", "contextrail.seed"], cwd=ENGINE, env=engine_env, check=True)
        manager_slack_id = env.get("SLACK_DEMO_MANAGER_ID", "").strip()
        if args.slack and manager_slack_id:
            # The override is deliberately confined to this throwaway pilot database.
            with psycopg.connect(env["DATABASE_URL"]) as connection:
                connection.execute("update identity_map set slack_user_id = %s where person_id = 'p-dana'",
                                   (manager_slack_id,))
        server_code = (
            f"import asyncio, uvicorn; server=uvicorn.Server(uvicorn.Config('contextrail.main:app', "
            f"host='127.0.0.1', port={args.port})); "
            + ("asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)"
               if sys.platform == "win32" else "asyncio.run(server.serve())")
        )
        engine = subprocess.Popen(
            [sys.executable, "-c", server_code],
            cwd=ENGINE,
            env=engine_env,
        )
        for _ in range(40):
            if engine.poll() is not None:
                raise RuntimeError("engine exited before health check")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/health", timeout=1) as response:
                    if response.status == 200:
                        fs_mode = "configured Freshservice mode" if args.freshservice else "Freshservice fixture mode"
                        print(f"Isolated engine ready at http://127.0.0.1:{args.port} ({fs_mode})", flush=True)
                        break
            except (OSError, TimeoutError):
                time.sleep(0.5)
        else:
            raise RuntimeError("engine health timed out")
        if args.slack:
            missing = [key for key in ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN") if not env.get(key)]
            if missing:
                raise RuntimeError(f"Slack Socket Mode needs {', '.join(missing)} in the local .env")
            slack = subprocess.Popen(
                [sys.executable, "-m", "contextrail.surfaces.slack_socket"],
                cwd=ENGINE,
                env=env,
            )
            time.sleep(2)
            if slack.poll() is not None:
                raise RuntimeError("Slack Socket Mode exited during startup")
            print("Slack Socket Mode connected to the isolated pilot engine", flush=True)
        engine.wait()
        return engine.returncode or 0
    finally:
        if slack is not None and slack.poll() is None:
            slack.terminate()
            try:
                slack.wait(timeout=5)
            except subprocess.TimeoutExpired:
                slack.kill()
        if engine is not None and engine.poll() is None:
            engine.terminate()
            try:
                engine.wait(timeout=5)
            except subprocess.TimeoutExpired:
                engine.kill()
        server.cleanup()
        shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
