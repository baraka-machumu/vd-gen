from __future__ import annotations

import json
import logging

from app.core.logging import JsonFormatter, correlation_id


def _record(msg: str = "hello", **extra: object) -> logging.LogRecord:
    record = logging.makeLogRecord({"name": "t", "levelname": "INFO", "msg": msg})
    record.__dict__.update(extra)
    return record


def test_json_line_has_core_fields_and_extras() -> None:
    out = json.loads(JsonFormatter().format(_record(shot_id="s1", attempt=2)))
    assert out["msg"] == "hello"
    assert out["level"] == "INFO"
    assert out["shot_id"] == "s1"
    assert out["attempt"] == 2
    assert "correlation_id" not in out


def test_correlation_id_is_included_when_set() -> None:
    token = correlation_id.set("abc")
    try:
        out = json.loads(JsonFormatter().format(_record()))
    finally:
        correlation_id.reset(token)
    assert out["correlation_id"] == "abc"


def test_exception_is_serialised() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})
    out = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in out["exc"]
