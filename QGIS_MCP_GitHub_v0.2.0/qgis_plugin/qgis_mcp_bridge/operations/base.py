"""所有 QGIS 操作共用的圖層、確認與路徑基礎能力。"""

from pathlib import Path

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

from ..errors import BridgeError


class BaseOperations:
    """保存 iface、confirmation 與 jobs，並只公布 op_ 開頭的方法。"""

    def __init__(self, iface, confirmation, jobs):
        self.iface = iface
        self.confirmation = confirmation
        self.jobs = jobs

    def action_handler(self, action):
        """只回傳既有、可呼叫且命名為 op_<action> 的公開 handler。"""
        handler = getattr(self, f"op_{action}", None)
        return handler if callable(handler) else None

    @staticmethod
    def project():
        """永遠取得目前 QGIS 實例自己的 singleton 專案。"""
        return QgsProject.instance()

    def layer(self, layer_id, vector=False, raster=False):
        """以穩定 ID 取得圖層，並視需要限制向量或 Raster 型別。"""
        if not isinstance(layer_id, str) or not layer_id.strip():
            raise BridgeError("INVALID_PARAMETERS", "layer_id 不可為空。")
        layer = self.project().mapLayer(layer_id)
        if layer is None:
            raise BridgeError("LAYER_NOT_FOUND", f"找不到圖層：{layer_id}", {"layer_id": layer_id})
        if vector and not isinstance(layer, QgsVectorLayer):
            raise BridgeError("INVALID_PARAMETERS", "此操作只支援向量圖層。")
        if raster and not isinstance(layer, QgsRasterLayer):
            raise BridgeError("INVALID_PARAMETERS", "此操作只支援 Raster 圖層。")
        return layer

    def confirm_overwrite(self, path, operation_name):
        """只在輸出已存在時顯示包含完整路徑的預設拒絕確認。"""
        if Path(path).exists():
            self.confirmation.require(
                operation_name,
                "目標檔案已存在，繼續將覆寫既有內容。",
                f"完整目標路徑：\n{path}\n\n此操作可能無法復原。",
            )
