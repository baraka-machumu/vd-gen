from __future__ import annotations

import httpx
import pytest

from app.core.egress import CORRELATION_HEADER, create_http_client
from app.core.errors import EgressDeniedError
from app.core.logging import correlation_id
from tests.conftest import make_settings

seen: list[httpx.Request] = []


def _recording_transport(redirect_to: str | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if redirect_to and request.url.path == "/start":
            return httpx.Response(302, headers={"location": redirect_to})
        return httpx.Response(200, json={"ok": True})

    seen.clear()
    return httpx.MockTransport(handler)


async def test_internal_service_is_reachable_offline() -> None:
    settings = make_settings(comfyui_url="http://gx10.local:8188")
    async with create_http_client(settings, transport=_recording_transport()) as client:
        response = await client.get("http://gx10.local:8188/system_stats")
    assert response.status_code == 200


async def test_external_host_is_blocked_offline_before_any_request_is_sent() -> None:
    async with create_http_client(make_settings(), transport=_recording_transport()) as client:
        with pytest.raises(EgressDeniedError) as err:
            await client.get("https://api.openai.com/v1/models")
    assert err.value.details == {"host": "api.openai.com"}
    assert seen == []


async def test_allow_listed_host_is_reachable_only_when_online_and_enabled() -> None:
    online = make_settings(network_mode="online", enable_external_apis=True, allowed_external_hosts="api.example.com")
    async with create_http_client(online, transport=_recording_transport()) as client:
        assert (await client.get("https://api.example.com/x")).status_code == 200
        with pytest.raises(EgressDeniedError):
            await client.get("https://not-listed.example.com/x")


async def test_online_without_enable_flag_still_blocks_external() -> None:
    settings = make_settings(network_mode="online", allowed_external_hosts="api.example.com")
    async with create_http_client(settings, transport=_recording_transport()) as client:
        with pytest.raises(EgressDeniedError):
            await client.get("https://api.example.com/x")


async def test_redirect_to_external_host_is_blocked() -> None:
    settings = make_settings(comfyui_url="http://gx10.local:8188")
    transport = _recording_transport(redirect_to="https://evil.example.com/steal")
    async with create_http_client(settings, transport=transport, follow_redirects=True) as client:
        with pytest.raises(EgressDeniedError):
            await client.get("http://gx10.local:8188/start")
    assert [r.url.host for r in seen] == ["gx10.local"]


async def test_host_matching_ignores_case_and_trailing_dot() -> None:
    settings = make_settings(comfyui_url="http://gx10.local:8188")
    async with create_http_client(settings, transport=_recording_transport()) as client:
        assert (await client.get("http://GX10.local.:8188/x")).status_code == 200


async def test_correlation_id_is_forwarded() -> None:
    settings = make_settings(comfyui_url="http://gx10.local:8188")
    token = correlation_id.set("req-123")
    try:
        async with create_http_client(settings, transport=_recording_transport()) as client:
            await client.get("http://gx10.local:8188/x")
    finally:
        correlation_id.reset(token)
    assert seen[0].headers[CORRELATION_HEADER] == "req-123"
