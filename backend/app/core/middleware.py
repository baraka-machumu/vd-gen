"""Request context: correlation id, one access-log line per request, and the last-resort 500 envelope."""

from __future__ import annotations

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_body
from app.core.logging import correlation_id

log = logging.getLogger("app.request")

HEADER = b"x-request-id"
# Accept caller-supplied ids only if they are short and harmless in logs/headers.
_VALID_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = dict(scope["headers"]).get(HEADER, b"").decode("latin-1")
        cid = supplied if _VALID_ID.match(supplied) else uuid.uuid4().hex
        token = correlation_id.set(cid)
        status = 500
        started = False
        t0 = time.perf_counter()

        async def send_with_id(message: Message) -> None:
            nonlocal status, started
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                message["headers"] = [*message.get("headers", []), (HEADER, cid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            log.exception("unhandled exception")
            if started:  # headers already sent: nothing sensible to return, let the server close the connection
                raise
            body = json.dumps(error_body("internal_error", "Internal server error")).encode()
            await send_with_id(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                }
            )
            await send_with_id({"type": "http.response.body", "body": body})
        finally:
            log.info(
                "request",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - t0) * 1000, 1),
                },
            )
            correlation_id.reset(token)
