"""透過已驗證的 loopback HTTP 呼叫指定 QGIS Bridge。"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from pydantic import ValidationError

from .errors import BridgeConnectionError, InvalidBridgeResponseError, QgisMcpError
from .models import OperationResponse
from .registry import InstanceRegistry


class BridgeClient:
    """將 MCP 工具呼叫轉成 QGIS Bridge JSON 命令。"""

    def __init__(self, registry: InstanceRegistry, timeout_seconds: float) -> None:
        self._registry = registry  # 每次操作重新解析實例，避免使用過期 token 或連接埠。
        self._timeout = httpx.Timeout(timeout_seconds)  # 對 GUI 確認保留合理等待時間。

    async def call(
        self, instance_id: str, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """呼叫單一 Bridge action 並驗證共通回應格式。"""
        record = self._registry.get_online(instance_id)
        request_id = str(uuid.uuid4())  # 每次請求使用新識別碼，便於稽核與去重。
        payload = {
            "request_id": request_id,
            "action": action,
            "params": params or {},
        }
        headers = {
            "Authorization": f"Bearer {record.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-QGIS-MCP-API-Version": str(record.api_version),
        }
        url = f"http://127.0.0.1:{record.port}/v1/command"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                response = await client.post(url, json=payload, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise BridgeConnectionError(instance_id, type(exc).__name__) from exc
        except httpx.HTTPError as exc:
            raise BridgeConnectionError(instance_id, "HTTP transport error") from exc

        if response.status_code == 401:
            raise BridgeConnectionError(instance_id, "Bridge token rejected")
        if response.status_code == 413:
            raise QgisMcpError("INVALID_PARAMETERS", "Bridge 請求內容超過允許大小。")
        if response.status_code == 409:
            try:
                bridge_error = response.json().get("error")
            except ValueError:
                bridge_error = "conflict"
            if bridge_error == "bridge_busy":
                raise QgisMcpError(
                    "QGIS_INSTANCE_BUSY",
                    "QGIS 正在處理另一個命令或等待真人確認，請稍後重試。",
                )
            raise BridgeConnectionError(instance_id, f"Bridge protocol conflict: {bridge_error}")
        if response.status_code >= 500:
            raise BridgeConnectionError(instance_id, f"Bridge HTTP {response.status_code}")
        try:
            raw_result = response.json()
            validated = OperationResponse.model_validate(raw_result)
        except (ValueError, ValidationError) as exc:
            raise InvalidBridgeResponseError(type(exc).__name__) from exc
        if validated.instance_id != instance_id:
            raise InvalidBridgeResponseError("instance_id mismatch")
        return validated.model_dump(mode="json")
