"""Structured JSON logging with a per-request correlation id (spec §71)."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Attributes every LogRecord has; anything else was passed via `extra=` and is emitted as a field.
_STANDARD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if cid := correlation_id.get():
            payload["correlation_id"] = cid
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


class _CorrelationFilter(logging.Filter):
    """Makes %(correlation_id)s available to the plain-text format used in development."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id.get() or "-"
        return True


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.addFilter(_CorrelationFilter())
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [%(correlation_id)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's own access log duplicates our request log line.
    logging.getLogger("uvicorn.access").disabled = True
