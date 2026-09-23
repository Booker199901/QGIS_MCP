"""定義 Bridge 登錄檔與工具回應的資料模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .constants import BRIDGE_API_VERSION


class InstanceRecord(BaseModel):
    """QGIS 外掛寫入本機 registry 的單一實例資料。"""

    model_config = ConfigDict(extra="forbid")  # 拒絕未知欄位以提早發現版本不相容。

    api_version: int = Field(default=BRIDGE_API_VERSION, ge=1)
    instance_id: str = Field(min_length=8, max_length=128)
    pid: int = Field(gt=0)
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(ge=1024, le=65535)
    token: str = Field(min_length=32, max_length=512, repr=False)
    qgis_version: str = Field(min_length=1, max_length=64)
    plugin_version: str = Field(min_length=1, max_length=64)
    project_name: str = Field(default="", max_length=512)
    project_path: str = Field(default="", max_length=32768)
    locale: str = Field(default="zh_TW", max_length=32)
    started_at: datetime
    heartbeat_at: datetime

    @field_validator("instance_id")
    @classmethod
    def validate_instance_id(cls, value: str) -> str:
        """限制實例 ID 字元，避免它被當成路徑片段時產生穿越風險。"""
        if not all(character.isalnum() or character in {"-", "_"} for character in value):
            raise ValueError("instance_id 只能包含英數字、連字號與底線")
        return value

    def public_dict(self, *, online: bool) -> dict[str, Any]:
        """移除 token 後回傳可安全提供給 MCP Client 的實例資訊。"""
        return {
            "api_version": self.api_version,
            "instance_id": self.instance_id,
            "pid": self.pid,
            "qgis_version": self.qgis_version,
            "plugin_version": self.plugin_version,
            "project_name": self.project_name,
            "project_path": self.project_path,
            "locale": self.locale,
            "started_at": self.started_at.isoformat(),
            "heartbeat_at": self.heartbeat_at.isoformat(),
            "online": online,
        }


class OperationResponse(BaseModel):
    """所有 Bridge 命令共用的結構化回應。"""

    model_config = ConfigDict(extra="allow")  # 保留未來 Bridge 增加的相容欄位。

    success: bool
    operation_id: str = Field(min_length=8, max_length=128)
    instance_id: str = Field(min_length=8, max_length=128)
    status: Literal[
        "completed",
        "queued",
        "running",
        "cancelled",
        "failed",
        "confirmation_required",
    ]
    message: str
    warnings: list[str] = Field(default_factory=list)
    duration_ms: int | None = Field(default=None, ge=0)
    result: dict[str, Any] | list[Any] | None = None
    error: dict[str, Any] | None = None
