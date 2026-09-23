"""為本機 Streamable HTTP 加上固定時間 Bearer token 驗證。"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from .constants import MAX_REQUEST_BYTES


class BearerTokenMiddleware:
    """拒絕未帶正確 Bearer token 的 HTTP 與 WebSocket 請求。"""

    def __init__(self, app: Callable[..., Awaitable[None]], token: str) -> None:
        self._app = app  # 保存由官方 MCP SDK 建立的 ASGI application。
        self._expected = f"Bearer {token}".encode()  # 預先編碼，便於固定時間比對。

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[..., Awaitable[dict[str, Any]]],
        send: Callable[..., Awaitable[None]],
    ) -> None:
        """驗證 Authorization header，成功才把請求交給 MCP SDK。"""
        if scope.get("type") not in {"http", "websocket"}:
            await self._app(scope, receive, send)
            return
        header_items = [(key.lower(), value) for key, value in scope.get("headers", [])]
        if self._has_duplicate_security_header(header_items):
            await self._reject(scope, send, 400, b'{"error":"duplicate_security_header"}')
            return
        headers = dict(header_items)
        if not self._origin_allowed(headers.get(b"origin")):
            await self._reject(scope, send, 403, b'{"error":"origin_not_allowed"}')
            return
        supplied = headers.get(b"authorization", b"")
        if not hmac.compare_digest(supplied, self._expected):
            await self._reject(scope, send, 401, b'{"error":"unauthorized"}', authenticate=True)
            return
        if scope.get("type") == "http" and scope.get("method") in {"POST", "PUT", "PATCH"}:
            buffered_receive = await self._bounded_receive(receive, send)
            if buffered_receive is None:
                return
            await self._app(scope, buffered_receive, send)
            return
        await self._app(scope, receive, send)

    @staticmethod
    def _has_duplicate_security_header(headers: list[tuple[bytes, bytes]]) -> bool:
        """拒絕重複認證與 Origin header，避免不同 ASGI 層解析結果不一致。"""
        for protected_name in (b"authorization", b"origin", b"content-length"):
            if sum(1 for name, _value in headers if name == protected_name) > 1:
                return True
        return False

    @staticmethod
    def _origin_allowed(raw_origin: bytes | None) -> bool:
        """非瀏覽器 Client 可不帶 Origin；有帶時只接受 loopback 網頁來源。"""
        if raw_origin is None:
            return True
        try:
            origin = urlsplit(raw_origin.decode("ascii"))
            return (
                origin.scheme in {"http", "https"}
                and origin.hostname in {"127.0.0.1", "localhost", "::1"}
                and origin.username is None
                and origin.password is None
                and not origin.path
                and not origin.query
                and not origin.fragment
            )
        except (UnicodeDecodeError, ValueError):
            return False

    @staticmethod
    async def _bounded_receive(receive, send):
        """先以 4 MiB 上限緩衝單一 MCP HTTP body，再交給官方 SDK 解析。"""
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                received_message = message

                async def disconnected(event: dict[str, Any] = received_message) -> dict[str, Any]:
                    return event

                return disconnected
            body = message.get("body", b"")
            total += len(body)
            if total > MAX_REQUEST_BYTES:
                response_body = b'{"error":"request_too_large"}'
                await send(
                    {
                        "type": "http.response.start",
                        "status": 413,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(response_body)).encode("ascii")),
                            (b"cache-control", b"no-store"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": response_body})
                return None
            chunks.append(body)
            if not message.get("more_body", False):
                break
        delivered = False

        async def buffered() -> dict[str, Any]:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        return buffered

    @staticmethod
    async def _reject(scope, send, status: int, body: bytes, *, authenticate: bool = False) -> None:
        """以無快取錯誤拒絕 HTTP；WebSocket 使用對應的 private close code。"""
        if scope.get("type") == "websocket":
            await send({"type": "websocket.close", "code": 4401 if status == 401 else 4403})
            return
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"cache-control", b"no-store"),
        ]
        if authenticate:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
