"""Egress guard (spec §38, §73): the only sanctioned way to make outbound HTTP calls from the backend.

Every request, including each redirect hop, is checked at the transport layer:
- hosts of the platform's own services (LLM, ComfyUI, object store, Redis, EXTRA_INTERNAL_HOSTS) are always allowed;
- any other host is allowed only when NETWORK_MODE=online, ENABLE_EXTERNAL_APIS=true and the host is in
  ALLOWED_EXTERNAL_HOSTS.
Direct use of httpx/requests/urllib elsewhere in the backend is a lint error (ruff TID251, backend/pyproject.toml).
Network isolation in compose (M01) is the second line of defence.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import EgressDeniedError
from app.core.logging import correlation_id

log = logging.getLogger(__name__)

CORRELATION_HEADER = "X-Request-ID"


class EgressPolicy:
    def __init__(self, settings: Settings) -> None:
        self._internal = settings.internal_hosts()
        self._external = settings.allowed_external_hosts if settings.external_apis_enabled else frozenset()

    def is_allowed(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        return host in self._internal or host in self._external

    def check(self, url: httpx.URL) -> None:
        if not self.is_allowed(url.host):
            log.warning("egress denied", extra={"host": url.host, "scheme": url.scheme})
            raise EgressDeniedError(url.host)


class _GuardedTransport(httpx.AsyncBaseTransport):
    def __init__(self, policy: EgressPolicy, inner: httpx.AsyncBaseTransport) -> None:
        self._policy = policy
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._policy.check(request.url)
        if (cid := correlation_id.get()) and CORRELATION_HEADER not in request.headers:
            request.headers[CORRELATION_HEADER] = cid
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        await self._inner.aclose()


def create_http_client(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None, **kwargs: Any
) -> httpx.AsyncClient:
    """An AsyncClient whose every request passes the egress policy. `transport` is for tests only."""
    inner = transport or httpx.AsyncHTTPTransport(retries=0)
    kwargs.setdefault("timeout", httpx.Timeout(30.0))
    return httpx.AsyncClient(transport=_GuardedTransport(EgressPolicy(settings), inner), **kwargs)
