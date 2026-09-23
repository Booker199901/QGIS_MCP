"""將目前 QGIS Desktop 實例安全公布給本機 MCP Server。"""

import json
import os
import secrets
import uuid
from contextlib import suppress
from datetime import datetime, timezone

from qgis.core import Qgis, QgsProject
from qgis.PyQt.QtCore import QTimer

from .constants import BRIDGE_API_VERSION, HEARTBEAT_INTERVAL_MS, PLUGIN_VERSION
from .settings import current_locale, registry_directory


class InstancePublisher:
    """以原子 JSON 檔維護單一 QGIS 程序的 instance_id 與短生命週期 token。"""

    def __init__(self, port, instance_id=None, token=None, parent=None):
        self.instance_id = instance_id or str(uuid.uuid4())  # 每次載入用新 ID，除非啟動器已先建立。
        self.token = token or secrets.token_urlsafe(48)  # 允許啟動器先將同一 token 交給 HTTP Server。
        self._port = int(port)  # 只保存 QTcpServer 實際綁定的 loopback port。
        self._directory = registry_directory()
        self._path = self._directory / f"{self.instance_id}.json"
        self._started_at = datetime.now(timezone.utc)
        self._timer = QTimer(parent)
        self._timer.setInterval(HEARTBEAT_INTERVAL_MS)
        self._timer.timeout.connect(self.publish)

    def start(self):
        """建立資料夾、立即公布並開始 heartbeat。"""
        self._directory.mkdir(parents=True, exist_ok=True)
        self.publish()
        self._timer.start()

    def _payload(self):
        """建立外部 MCP Server 可驗證的實例資料。"""
        project = QgsProject.instance()
        project_path = project.fileName() or ""
        project_name = project.title() or (self._path_name(project_path) if project_path else "Untitled")
        now = datetime.now(timezone.utc)
        return {
            "api_version": BRIDGE_API_VERSION,
            "instance_id": self.instance_id,
            "pid": os.getpid(),
            "host": "127.0.0.1",
            "port": self._port,
            "token": self.token,
            "qgis_version": Qgis.QGIS_VERSION,
            "plugin_version": PLUGIN_VERSION,
            "project_name": project_name,
            "project_path": project_path,
            "locale": current_locale(),
            "started_at": self._started_at.isoformat(),
            "heartbeat_at": now.isoformat(),
        }

    @staticmethod
    def _path_name(path_value):
        """只在有專案路徑時取檔名，避免未命名專案誤顯示 registry 名稱。"""
        from pathlib import Path

        return Path(path_value).stem

    def publish(self):
        """先寫暫存檔再原子替換，避免 MCP Server 讀到半份 JSON。"""
        temporary_path = self._path.with_suffix(".tmp")
        serialized = json.dumps(self._payload(), ensure_ascii=False, indent=2)
        temporary_path.write_text(serialized, encoding="utf-8")
        with suppress(OSError):
            os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, self._path)

    def stop(self):
        """停止 heartbeat 並只移除目前實例自己的精確登錄檔。"""
        self._timer.stop()
        try:
            if self._path.is_file() and self._path.parent == self._directory:
                self._path.unlink()
        except OSError:
            pass  # 無法清除時交由 TTL 將登錄判定為離線。
