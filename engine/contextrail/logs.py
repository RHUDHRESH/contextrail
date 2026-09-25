"""structlog JSON logging with run context, plus PII redaction (CLAUDE.md §16, §17).

`bind_run(run_id=..., channel=..., stage=...)` puts context on every log line emitted in the same task,
because it uses contextvars. Phone numbers and email addresses are masked before rendering: logs are
shipped off-box, and neither belongs there.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

_EMAIL = re.compile(r"(?<![\w.+-])([\w.+-])[\w.+-]*@([\w-]+\.)+[\w-]+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s-]{7,}\d(?!\w)")
_KEYS_NEVER_LOGGED = {"authorization", "password", "api_key", "token", "secret", "cookie"}


def _mask(value: str) -> str:
    value = _EMAIL.sub(lambda m: f"{m.group(1)}***@***", value)
    return _PHONE.sub(lambda m: "***" + re.sub(r"\D", "", m.group(0))[-2:], value)


def _redact(obj: Any) -> Any:
    if isinstance(obj, str):
        return _mask(obj)
    if isinstance(obj, dict):
        return {
            k: ("[redacted]" if isinstance(k, str) and k.lower() in _KEYS_NEVER_LOGGED else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return type(obj)(_redact(v) for v in obj)
    return obj


def redact_processor(_logger: Any, _method: str, event_dict: dict) -> dict:
    return _redact(event_dict)


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    renderer = structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            redact_processor,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level.upper())),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def bind_run(**context: Any) -> None:
    """Bind run_id / channel / stage / action_id for every log line in this task."""
    structlog.contextvars.bind_contextvars(**{k: v for k, v in context.items() if v is not None})


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


def get_logger(name: str | None = None):
    return structlog.get_logger(name)
