"""Error model: every error response has the same envelope, and no exception is swallowed (spec §71).

{"error": {"code": "not_found", "message": "...", "details": {...}, "correlation_id": "..."}}
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import correlation_id

log = logging.getLogger(__name__)


class AppError(Exception):
    """Base for errors that map to a client-visible response. Subclasses set `status_code` and `code`."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class EgressDeniedError(AppError):
    """An outbound call to a host the network policy does not allow (spec §38). A server-side fault."""

    status_code = 502
    code = "egress_denied"

    def __init__(self, host: str) -> None:
        super().__init__(
            f"Outbound connection to {host!r} is not allowed by the network policy", details={"host": host}
        )


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "correlation_id": correlation_id.get()}
    if details:
        body["details"] = details
    return {"error": body}


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - registered for AppError only
    level = logging.ERROR if exc.status_code >= 500 else logging.INFO
    log.log(level, "request failed: %s", exc.message, extra={"error_code": exc.code})
    return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status_code)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized", 403: "forbidden"}.get(
        exc.status_code, "http_error"
    )
    return JSONResponse(
        error_body(code, str(exc.detail)), status_code=exc.status_code, headers=getattr(exc, "headers", None)
    )


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    details = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return JSONResponse(error_body("validation_error", "Request validation failed", details), status_code=422)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    # Unhandled exceptions become a 500 envelope in RequestContextMiddleware (app/core/middleware.py), which
    # runs inside the correlation-id context; Starlette's own Exception handler would run outside it.
