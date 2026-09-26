"""Run the job worker in its own process.

    python -m contextrail.worker            # poll until SIGINT/SIGTERM (the current job finishes first)
    python -m contextrail.worker --drain    # run every ready job it has a handler for, then exit

Same Platform (app_state.py) and same handlers (jobs.HANDLER_MODULES) as the API. The API process already runs one
worker by default (WORKER_IN_PROCESS=true), which is all a one-box deployment needs. Run this to add capacity, or set
WORKER_IN_PROCESS=false and run it as its own service. StageEvents are in-process: runs executed here stream to this
process's EventBus, so the API's SSE sees only their final status (read from the database).
"""

from __future__ import annotations

import asyncio
import signal
import sys

from contextrail.app_state import build_platform
from contextrail.jobs import Worker, load_handlers
from contextrail.logs import configure_logging, get_logger
from contextrail.policy.loader import load_rules
from contextrail.settings import Settings, get_settings

log = get_logger("contextrail.worker")


def _on_stop_signals(stop) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:  # Windows event loops: fall back to a plain handler that wakes the loop
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop))


async def main(argv: list[str], settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    kinds = load_handlers()
    platform = build_platform(settings, rules=load_rules())
    async with platform.serving(worker=False):
        worker = Worker(platform.db, platform)
        if "--drain" in argv:
            ran = 0
            while await worker.run_once() is not None:
                ran += 1
            log.info("worker_drained", jobs=ran, kinds=kinds)
            return 0
        _on_stop_signals(worker.stop)
        await worker.run()
    return 0


if __name__ == "__main__":
    # psycopg's async mode needs the selector loop on Windows (see db.py); Linux uses the default.
    factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    raise SystemExit(asyncio.run(main(sys.argv[1:]), loop_factory=factory))
