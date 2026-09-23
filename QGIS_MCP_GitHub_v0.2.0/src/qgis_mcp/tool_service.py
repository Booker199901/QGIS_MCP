"""提供 MCP tools 共用的 Bridge 呼叫與錯誤封裝。"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from .audit import AuditLogger
from .bridge_client import BridgeClient
from .errors import QgisMcpError
from .registry import InstanceRegistry


class ToolService:
    """集中處理 tools 的成功、失敗與實例列舉行為。"""

    def __init__(self, registry: InstanceRegistry, bridge: BridgeClient, audit: AuditLogger) -> None:
        self._registry = registry  # 唯讀工具可直接由安全 registry 取得資料。
        self._bridge = bridge  # QGIS 操作統一經由 BridgeClient 驗證。
        self._audit = audit  # 只寫入明確允許的稽核欄位。

    @staticmethod
    def _error_response(instance_id: str, error: QgisMcpError) -> dict[str, Any]:
        """將可預期錯誤轉成模型可理解、可修正的 tool result。"""
        return {
            "success": False,
            "operation_id": str(uuid.uuid4()),
            "instance_id": instance_id,
            "status": "failed",
            "message": error.message,
            "warnings": [],
            "duration_ms": 0,
            "result": None,
            "error": {
                "code": error.code,
                "message": error.message,
                "details": error.details or {},
            },
        }

    async def call(
        self,
        instance_id: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """安全呼叫 Bridge，避免領域例外變成不透明的 MCP 內部錯誤。"""
        try:
            response = await self._bridge.call(instance_id, action, params)
        except QgisMcpError as error:
            response = self._error_response(instance_id, error)
        self._audit.record(
            operation_id=response["operation_id"],
            instance_id=instance_id,
            action=action,
            params=params,
            status=response["status"],
            duration_ms=response["duration_ms"],
            error_code=(response.get("error") or {}).get("code"),
        )
        return response

    async def local_call(
        self,
        operation: Callable[[], Awaitable[dict[str, Any]]] | Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """為 MCP Server 本機操作提供與 Bridge 一致的錯誤封裝。"""
        try:
            result = operation()
            if hasattr(result, "__await__"):
                return await result  # type: ignore[misc]
            return result  # type: ignore[return-value]
        except QgisMcpError as error:
            return self._error_response("server", error)

    def list_instances(self, *, include_offline: bool) -> dict[str, Any]:
        """列出實例時永遠移除 Bridge token 與連接埠。"""
        records = self._registry.list_records(include_offline=include_offline)
        instances = [record.public_dict(online=online) for record, online in records]
        response = {
            "success": True,
            "operation_id": str(uuid.uuid4()),
            "instance_id": "server",
            "status": "completed",
            "message": f"找到 {len(instances)} 個 QGIS 實例。",
            "warnings": [],
            "duration_ms": 0,
            "result": {"instances": instances, "count": len(instances)},
            "error": None,
        }
        self._audit.record(
            operation_id=response["operation_id"],
            instance_id="server",
            action="list_qgis_instances",
            status="completed",
            duration_ms=0,
        )
        return response
