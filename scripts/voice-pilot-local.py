"""Run an isolated local engine for a temporary Vobiz voice pilot.

This is a development helper, not an AWS deployment. It uses throwaway PostgreSQL and
fixture connector state; live Freshservice writes are deliberately disabled. The
voice service and tunnel are started separately once their public URL is known.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pgserver


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
    if not LOCAL_ENV.is_file():
        raise SystemExit("Local source .env is missing")
    run_dir = Path(tempfile.mkdtemp(prefix="contextrail-voice-pilot-"))
    server = pgserver.get_server(str(run_dir / "pg"), cleanup_mode="stop")
    engine: subprocess.Popen | None = None
    try:
        env = {**os.environ, **read_env(LOCAL_ENV)}
        env.update({
            "DATABASE_URL": server.get_uri(),
            "STATE_DIR": str(run_dir / "state"),
            "FS_DOMAIN": "",
            "FS_API_KEY": "",
            "FD_DOMAIN": "",
            "FD_API_KEY": "",
            "FS_WEBHOOK_SECRET": "",
            "SLACK_BOT_TOKEN": "",
            "SLACK_SIGNING_SECRET": "",
            "WORKER_IN_PROCESS": "true",
            "PUBLIC_URL": "http://127.0.0.1:8000",
        })
        subprocess.run([sys.executable, "-m", "contextrail.seed"], cwd=ENGINE, env=env, check=True)
        server_code = (
            "import asyncio, uvicorn; "
            "server=uvicorn.Server(uvicorn.Config('contextrail.main:app', host='127.0.0.1', port=8000)); "
            + ("asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)"
               if sys.platform == "win32" else "asyncio.run(server.serve())")
        )
        engine = subprocess.Popen(
            [sys.executable, "-c", server_code],
            cwd=ENGINE,
            env=env,
        )
        for _ in range(40):
            if engine.poll() is not None:
                raise RuntimeError("engine exited before health check")
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=1) as response:
                    if response.status == 200:
                        print("Isolated engine ready at http://127.0.0.1:8000 (Freshservice fixture mode)", flush=True)
                        break
            except (OSError, TimeoutError):
                time.sleep(0.5)
        else:
            raise RuntimeError("engine health timed out")
        engine.wait()
        return engine.returncode or 0
    finally:
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
