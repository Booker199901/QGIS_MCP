"""驗證 Streamable HTTP 外層的 Bearer token middleware。"""

from __future__ import annotations

from typing import Any

import pytest

from qgis_mcp.http_auth import BearerTokenMiddleware


async def _run_request(
    authorization: bytes | None,
    *,
    origin: bytes | None = None,
    body: bytes = b"",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """以最小 ASGI scope 執行 middleware 並收集下游/回應事件。"""
    downstream_calls: list[dict[str, Any]] = []
    sent_messages: list[dict[str, Any]] = []

    async def downstream(scope: dict[str, Any], _receive: Any, send: Any) -> None:
        downstream_calls.append(scope)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent_messages.append(message)

    headers = [] if authorization is None else [(b"authorization", authorization)]
    if origin is not None:
        headers.append((b"origin", origin))
    scope = {"type": "http", "method": "POST", "path": "/mcp", "headers": headers}
    middleware = BearerTokenMiddleware(downstream, "t" * 48)
    await middleware(scope, receive, send)
    return downstream_calls, sent_messages


@pytest.mark.asyncio
async def test_missing_token_is_rejected() -> None:
    """無 Authorization header 時不得呼叫 MCP application。"""
    downstream_calls, sent = await _run_request(None)
    assert downstream_calls == []
    assert sent[0]["status"] == 401


@pytest.mark.asyncio
async def test_correct_token_reaches_mcp_application() -> None:
    """完全相符的 Bearer token 才能通過。"""
    downstream_calls, sent = await _run_request(f"Bearer {'t' * 48}".encode())
    assert len(downstream_calls) == 1
    assert sent[0]["status"] == 204


@pytest.mark.asyncio
async def test_remote_origin_is_rejected() -> None:
    """Bearer token 正確也不能讓遠端網頁 Origin 通過。"""
    downstream_calls, sent = await _run_request(
        f"Bearer {'t' * 48}".encode(), origin=b"https://attacker.example"
    )
    assert downstream_calls == []
    assert sent[0]["status"] == 403


@pytest.mark.asyncio
async def test_loopback_origin_is_allowed() -> None:
    """本機 Browser 型 MCP Client 的 localhost Origin 可正常使用。"""
    downstream_calls, sent = await _run_request(
        f"Bearer {'t' * 48}".encode(), origin=b"http://localhost:3000"
    )
    assert len(downstream_calls) == 1
    assert sent[0]["status"] == 204
