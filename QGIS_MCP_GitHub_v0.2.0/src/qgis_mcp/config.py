"""讀取 MCP Server 設定，並集中執行安全驗證。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

from .constants import DEFAULT_BRIDGE_TIMEOUT_SECONDS, DEFAULT_REGISTRY_TTL_SECONDS
from .errors import QgisMcpError


def _read_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """讀取受範圍限制的整數環境變數，避免無效設定延後到執行期才爆炸。"""
    raw_value = os.environ.get(name)  # 只讀取明確命名的環境變數，不掃描或輸出其他秘密。
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise QgisMcpError("INVALID_CONFIGURATION", f"{name} 必須是整數。") from exc
    if not minimum <= value <= maximum:
        raise QgisMcpError(
            "INVALID_CONFIGURATION",
            f"{name} 必須介於 {minimum} 與 {maximum} 之間。",
        )
    return value


def _read_float(name: str, default: float, minimum: float, maximum: float) -> float:
    """讀取受範圍限制的浮點數環境變數。"""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise QgisMcpError("INVALID_CONFIGURATION", f"{name} 必須是數值。") from exc
    if not minimum <= value <= maximum:
        raise QgisMcpError(
            "INVALID_CONFIGURATION",
            f"{name} 必須介於 {minimum} 與 {maximum} 之間。",
        )
    return value


@dataclass(frozen=True, slots=True)
class ServerSettings:
    """MCP Server 的唯讀執行設定。"""

    registry_dir: Path  # QGIS 外掛公布實例資訊的資料夾。
    bridge_timeout_seconds: float  # 一般 Bridge HTTP 呼叫逾時。
    registry_ttl_seconds: int  # 登錄檔的存活秒數。
    http_host: str  # Streamable HTTP 監聽位址，必須為 loopback。
    http_port: int  # Streamable HTTP 監聽連接埠。
    http_token: str | None  # HTTP 模式的 Bearer token；stdio 不使用。
    log_dir: Path  # 僅保存去敏後操作稽核紀錄的資料夾。
    log_retention_days: int  # 稽核檔超過此天數後於下次啟動清除。

    @classmethod
    def from_env(cls) -> ServerSettings:
        """由環境變數建立經驗證的設定。"""
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            default_registry = Path(local_app_data) / "QGISMCP" / "instances"
        else:
            default_registry = user_data_path("QGISMCP", appauthor=False) / "instances"
        registry_dir = Path(os.environ.get("QGIS_MCP_REGISTRY_DIR", str(default_registry))).expanduser()
        default_log_dir = default_registry.parent / "logs"
        log_dir = Path(os.environ.get("QGIS_MCP_LOG_DIR", str(default_log_dir))).expanduser()
        http_host = os.environ.get("QGIS_MCP_HTTP_HOST", "127.0.0.1").strip()
        if http_host not in {"127.0.0.1", "localhost", "::1"}:
            raise QgisMcpError(
                "INVALID_CONFIGURATION",
                "QGIS_MCP_HTTP_HOST 僅允許 loopback 位址。",
                {"allowed": ["127.0.0.1", "localhost", "::1"]},
            )
        http_token = os.environ.get("QGIS_MCP_HTTP_TOKEN")
        if http_token is not None and len(http_token) < 32:
            raise QgisMcpError(
                "INVALID_CONFIGURATION",
                "QGIS_MCP_HTTP_TOKEN 至少需要 32 個字元。",
            )
        return cls(
            registry_dir=registry_dir.resolve(),
            bridge_timeout_seconds=_read_float(
                "QGIS_MCP_BRIDGE_TIMEOUT_SECONDS",
                DEFAULT_BRIDGE_TIMEOUT_SECONDS,
                1.0,
                600.0,
            ),
            registry_ttl_seconds=_read_int(
                "QGIS_MCP_REGISTRY_TTL_SECONDS",
                DEFAULT_REGISTRY_TTL_SECONDS,
                5,
                300,
            ),
            http_host=http_host,
            http_port=_read_int("QGIS_MCP_HTTP_PORT", 8765, 1024, 65535),
            http_token=http_token,
            log_dir=log_dir.resolve(),
            log_retention_days=_read_int("QGIS_MCP_LOG_RETENTION_DAYS", 14, 1, 365),
        )
