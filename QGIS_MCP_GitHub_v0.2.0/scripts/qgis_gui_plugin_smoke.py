"""由 QGIS --code 載入完整 Bridge Plugin，驗證真實 iface 生命週期。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from qgis.core import Qgis
from qgis.PyQt.QtCore import QTimer
from qgis.utils import iface

PROJECT_ROOT = Path(os.environ["QGIS_MCP_GUI_SMOKE_ROOT"]).resolve()  # QGIS exec 不保證 __file__。
INPUT_DIR = PROJECT_ROOT / "qgis_plugin"  # 直接驗證準備封裝的外掛來源。
OUTPUT_DIR = PROJECT_ROOT / "build" / "qgis-gui-smoke" / "reports"
RUNTIME_LABEL = os.environ.get("QGIS_MCP_GUI_SMOKE_LABEL", "unknown")
REPORT_PATH = OUTPUT_DIR / f"{RUNTIME_LABEL}.json"

sys.path.insert(0, str(INPUT_DIR))


def _write_report(report: dict) -> None:
    """把有限狀態寫入 build，不包含 Bridge token。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _quit_test_process() -> None:
    """先要求 QGIS 正常關閉；offscreen 若卡在不可見對話框則結束隔離測試程序。"""
    iface.mainWindow().close()
    QTimer.singleShot(250, lambda: os._exit(0))


try:
    from qgis_mcp_bridge import classFactory

    plugin = classFactory(iface)
    plugin.initGui()
except Exception as startup_error:
    _write_report(
        {
            "success": False,
            "qgis_version": Qgis.QGIS_VERSION,
            "error_type": type(startup_error).__name__,
            "error": str(startup_error),
        }
    )
    QTimer.singleShot(0, _quit_test_process)
else:

    def finish_smoke() -> None:
        """event loop 啟動後檢查 registry heartbeat，再卸載並確認清理。"""
        try:
            publisher = plugin._publisher
            server = plugin._server
            registry_path = publisher._path if publisher is not None else None
            registry_exists_before_unload = bool(registry_path and registry_path.is_file())
            instance_id = plugin._instance_id
            port = server.port if server is not None else 0
            action_created = plugin._action is not None
            plugin.unload()
            registry_removed_after_unload = bool(registry_path and not registry_path.exists())
            _write_report(
                {
                    "success": all(
                        [
                            instance_id,
                            port > 0,
                            action_created,
                            registry_exists_before_unload,
                            registry_removed_after_unload,
                            plugin._server is None,
                            plugin._publisher is None,
                        ]
                    ),
                    "qgis_version": Qgis.QGIS_VERSION,
                    "instance_id_length": len(instance_id or ""),
                    "port_valid": port > 0,
                    "menu_action_created": action_created,
                    "registry_published": registry_exists_before_unload,
                    "registry_removed": registry_removed_after_unload,
                    "plugin_unloaded": plugin._server is None and plugin._publisher is None,
                }
            )
        except Exception as finish_error:
            _write_report(
                {
                    "success": False,
                    "qgis_version": Qgis.QGIS_VERSION,
                    "error_type": type(finish_error).__name__,
                    "error": str(finish_error),
                }
            )
        finally:
            QTimer.singleShot(0, _quit_test_process)

    # 讓 QGIS main event loop 至少完成一次 paint/network/timer 循環。
    QTimer.singleShot(500, finish_smoke)
