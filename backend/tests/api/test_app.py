"""API tests: error envelope, correlation id and health, against the real app (no database needed)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from app.core.errors import NotFoundError
from app.main import create_app
from tests.conftest import make_settings


class Payload(BaseModel):
    count: int


@pytest.fixture
def app() -> FastAPI:
    app = create_app(make_settings())

    @app.get("/_test/missing")
    async def missing() -> None:
        raise NotFoundError("shot not found", details={"shot_id": "s1"})

    @app.get("/_test/crash")
    async def crash() -> None:
        raise RuntimeError("unexpected")

    @app.post("/_test/validate")
    async def validate(body: Payload) -> Payload:
        return body

    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    # No lifespan: these tests don't touch the database.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-request-id"]


async def test_supplied_request_id_is_echoed_in_header_and_error_body(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/missing", headers={"X-Request-ID": "abc-123"})
    assert response.status_code == 404
    assert response.headers["x-request-id"] == "abc-123"
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "shot not found",
            "details": {"shot_id": "s1"},
            "correlation_id": "abc-123",
        }
    }


async def test_unsafe_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert response.headers["x-request-id"] != "bad id\twith spaces"
    assert len(response.headers["x-request-id"]) == 32


async def test_unknown_route_uses_envelope(client: httpx.AsyncClient) -> None:
    response = await client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_validation_error_uses_envelope(client: httpx.AsyncClient) -> None:
    response = await client.post("/_test/validate", json={"count": "many"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"] == ["body", "count"]


async def test_unhandled_exception_is_logged_and_returns_500_envelope(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = await client.get("/_test/crash", headers={"X-Request-ID": "crash-1"})
    assert response.status_code == 500
    assert response.headers["x-request-id"] == "crash-1"
    assert response.json()["error"] == {
        "code": "internal_error",
        "message": "Internal server error",
        "correlation_id": "crash-1",
    }
    assert "unexpected" not in response.text  # internals are logged, not returned
    assert any(r.exc_info and "unexpected" in str(r.exc_info[1]) for r in caplog.records)
