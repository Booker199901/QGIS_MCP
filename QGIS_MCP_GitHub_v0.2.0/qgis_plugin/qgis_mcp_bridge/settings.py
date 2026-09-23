"""集中管理 QGIS Bridge 的本機路徑與語言設定。"""

import os
from pathlib import Path

from qgis.PyQt.QtCore import QLocale, QStandardPaths


def registry_directory():
    """取得 MCP Server 與所有 QGIS 實例共同使用的登錄資料夾。"""
    configured = os.environ.get("QGIS_MCP_REGISTRY_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        return (Path(local_app_data) / "QGISMCP" / "instances").resolve()
    generic_data = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)
    return (Path(generic_data) / "QGISMCP" / "instances").resolve()


def current_locale():
    """回傳 QGIS/作業系統語系，用於繁中與英文訊息切換。"""
    locale_name = QLocale.system().name()
    return locale_name or "en_US"


def tr(zh_tw, en):
    """在未引入編譯翻譯檔前，提供穩定的繁中/英文雙語切換。"""
    return zh_tw if current_locale().lower().startswith("zh") else en
