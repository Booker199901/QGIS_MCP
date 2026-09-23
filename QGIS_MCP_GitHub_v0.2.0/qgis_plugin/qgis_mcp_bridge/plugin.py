"""QGIS MCP Bridge 外掛生命週期與最小狀態 UI。"""

import secrets
import uuid

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtWidgets import QAction, QMessageBox

from .confirmation import ConfirmationService
from .http_server import BridgeHttpServer
from .jobs import JobManager
from .operations import OperationHandler
from .registry import InstancePublisher
from .router import CommandRouter
from .settings import registry_directory, tr


class QgisMcpBridgePlugin:
    """啟動 loopback Bridge、公布 instance_id 並管理 QGIS 選單項目。"""

    def __init__(self, iface):
        self.iface = iface  # QGIS 提供的主視窗與 map canvas 介面。
        self._action = None
        self._server = None
        self._publisher = None
        self._jobs = None
        self._instance_id = None

    def initGui(self):  # noqa: N802 - QGIS 外掛介面要求固定命名。
        """建立功能元件並在全部成功後加入 QGIS 選單。"""
        try:
            self._start_bridge()
        except Exception as error:
            self._stop_bridge()
            QgsMessageLog.logMessage(
                f"QGIS MCP Bridge startup failed: {type(error).__name__}: {error}",
                "QGIS MCP",
                Qgis.Critical,
            )
            self.iface.messageBar().pushCritical(
                tr("QGIS MCP 啟動失敗", "QGIS MCP failed to start"),
                str(error),
            )
            return
        self._action = QAction(tr("QGIS MCP Bridge 狀態", "QGIS MCP Bridge status"), self.iface.mainWindow())
        self._action.triggered.connect(self._show_status)
        self.iface.addPluginToMenu("&QGIS MCP", self._action)
        self.iface.messageBar().pushSuccess(
            "QGIS MCP",
            tr("Bridge 已在本機安全啟動。", "Bridge started securely on localhost."),
        )

    def unload(self):
        """先停止對外公布與 socket，再移除選單，避免卸載後仍可接受命令。"""
        if self._action is not None:
            self.iface.removePluginMenu("&QGIS MCP", self._action)
            self._action.deleteLater()
            self._action = None
        self._stop_bridge()

    def _start_bridge(self):
        """以同一 instance_id/token 組合 Router、HTTP Server 與 Registry Publisher。"""
        self._instance_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(48)
        self._jobs = JobManager(self.iface.mainWindow())
        confirmation = ConfirmationService(self.iface.mainWindow())
        operations = OperationHandler(self.iface, confirmation, self._jobs)
        router = CommandRouter(self._instance_id, operations)
        self._server = BridgeHttpServer(router, token, self.iface.mainWindow())
        self._server.start()
        self._publisher = InstancePublisher(
            self._server.port,
            instance_id=self._instance_id,
            token=token,
            parent=self.iface.mainWindow(),
        )
        self._publisher.start()

    def _stop_bridge(self):
        """按 registry、socket 的順序安全停止目前外掛自己的資源。"""
        if self._publisher is not None:
            self._publisher.stop()
            self._publisher = None
        if self._server is not None:
            self._server.stop()
            self._server = None
        self._jobs = None
        self._instance_id = None

    def _show_status(self):
        """顯示不含 token 的連線資訊，方便使用者確認 MCP 目標實例。"""
        if self._server is None or self._publisher is None:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "QGIS MCP",
                tr("Bridge 目前未執行。", "Bridge is not running."),
            )
            return
        message = tr(
            "Bridge 狀態：執行中\n實例 ID：{}\n本機連接埠：{}\nRegistry：{}",
            "Bridge status: running\nInstance ID: {}\nLocal port: {}\nRegistry: {}",
        ).format(self._instance_id, self._server.port, registry_directory())
        QMessageBox.information(self.iface.mainWindow(), "QGIS MCP", message)
