"""定義可穩定回傳給 MCP Client 的錯誤類型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class QgisMcpError(Exception):
    """代表可預期且可安全揭露給 AI 的領域錯誤。"""

    code: str  # 穩定錯誤碼，供 MCP Client 決定是否重試或修正參數。
    message: str  # 不含敏感資訊的使用者可讀說明。
    details: dict[str, Any] | None = None  # 可選的結構化修正資訊。

    def __str__(self) -> str:
        """讓日誌與例外輸出維持一致、簡潔的格式。"""
        return f"{self.code}: {self.message}"


class InstanceNotFoundError(QgisMcpError):
    """指定的 QGIS 實例不存在、已過期或已離線。"""

    def __init__(self, instance_id: str) -> None:
        super().__init__(
            code="QGIS_INSTANCE_NOT_FOUND",
            message=f"找不到可用的 QGIS 實例：{instance_id}",
            details={"instance_id": instance_id, "hint": "請先呼叫 list_qgis_instances。"},
        )


class BridgeConnectionError(QgisMcpError):
    """MCP Server 無法與已登錄的 QGIS Bridge 通訊。"""

    def __init__(self, instance_id: str, reason: str) -> None:
        super().__init__(
            code="QGIS_INSTANCE_DISCONNECTED",
            message="QGIS Bridge 目前無法連線。",
            details={"instance_id": instance_id, "reason": reason},
        )


class InvalidBridgeResponseError(QgisMcpError):
    """Bridge 回傳不符合協定，避免將未知內容直接交給 AI。"""

    def __init__(self, reason: str) -> None:
        super().__init__(
            code="INTERNAL_ERROR",
            message="QGIS Bridge 回應格式無效。",
            details={"reason": reason},
        )
