"""驗證 MCP Server 設定的路徑與安全邊界。"""

from __future__ import annotations

from pathlib import Path

import pytest

from qgis_mcp.config import ServerSettings
from qgis_mcp.errors import QgisMcpError


def _clear_qgis_mcp_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """只清除本專案明確使用的環境變數，不影響其他系統設定。"""
    for name in [
        "QGIS_MCP_REGISTRY_DIR",
        "QGIS_MCP_BRIDGE_TIMEOUT_SECONDS",
        "QGIS_MCP_REGISTRY_TTL_SECONDS",
        "QGIS_MCP_HTTP_HOST",
        "QGIS_MCP_HTTP_PORT",
        "QGIS_MCP_HTTP_TOKEN",
        "QGIS_MCP_LOG_DIR",
        "QGIS_MCP_LOG_RETENTION_DAYS",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_windows_registry_path_matches_plugin(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """外部 Server 應與外掛共用 LocalAppData/QGISMCP/instances。"""
    _clear_qgis_mcp_environment(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings = ServerSettings.from_env()
    assert settings.registry_dir == (tmp_path / "QGISMCP" / "instances").resolve()


def test_non_loopback_http_host_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """即使由環境變數設定，也不得監聽外部網路介面。"""
    _clear_qgis_mcp_environment(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("QGIS_MCP_HTTP_HOST", "0.0.0.0")
    with pytest.raises(QgisMcpError, match="loopback"):
        ServerSettings.from_env()


def test_short_http_token_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """HTTP token 不足 32 字元時應在啟動前失敗。"""
    _clear_qgis_mcp_environment(monkeypatch)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("QGIS_MCP_HTTP_TOKEN", "too-short")
    with pytest.raises(QgisMcpError, match="32"):
        ServerSettings.from_env()
