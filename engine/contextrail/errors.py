"""Request ids and RFC 9457 problem+json errors.

Every response carries `X-Request-ID`. Every error, whether expected or not, is returned as
`application/problem+json` with that request id, so a door (or a judge) can quote one id and we can find
the log lines. Unhandled exceptions never leak stack traces or internals to the caller.
"""

from __future__ import annotations

import re
import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from contextrail.logs import get_logger

PROBLEM = "application/problem+json"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
log = get_logger("contextrail.http")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def _problem(request: Request, status: int, title: str, detail: str | None = None, **extra) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "instance": request.url.path,
        "request_id": getattr(request.state, "request_id", None),
    }
    if detail:
        body["detail"] = detail
    body.update(extra)
    headers = {"X-Request-ID": body["request_id"]} if body["request_id"] else None
    return JSONResponse(body, status_code=status, media_type=PROBLEM, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    app.add_middleware(RequestIdMiddleware)

    # Starlette's class, not FastAPI's subclass: routing 404/405 raise the Starlette one.
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        title = {400: "Bad request", 401: "Unauthorized", 403: "Forbidden", 404: "Not found",
                 409: "Conflict", 422: "Unprocessable"}.get(exc.status_code, "Error")
        return _problem(request, exc.status_code, title, str(exc.detail) if exc.detail else None)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return _problem(request, 422, "Request failed validation", errors=errors)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.error("unhandled_exception", path=request.url.path, error_type=type(exc).__name__, exc_info=exc)
        return _problem(request, 500, "Internal error", "The engine hit an unexpected error; quote the request_id.")
