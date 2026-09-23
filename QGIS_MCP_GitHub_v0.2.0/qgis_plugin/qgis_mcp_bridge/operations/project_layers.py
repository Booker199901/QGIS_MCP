"""實作 QGIS 系統、專案與圖層管理 actions。"""

import os
import platform
import sys
from pathlib import Path

from osgeo import gdal
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsRasterLayer,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

from ..constants import PLUGIN_VERSION
from ..errors import BridgeError
from ..utils import (
    absolute_output_path,
    crs_dict,
    enum_int,
    json_safe,
    rectangle_dict,
    require_bool,
    require_string,
    vector_driver_for_path,
)


class ProjectLayerOperations:
    """提供不依賴特定 AI Client 的專案與圖層結構化操作。"""

    def op_get_qgis_status(self, _params):
        """回傳不含秘密的 QGIS 執行環境摘要。"""
        project = self.project()
        return {
            "qgis_version": Qgis.QGIS_VERSION,
            "qgis_version_int": Qgis.QGIS_VERSION_INT,
            "qt_version": QT_VERSION_STR,
            "pyqt_version": PYQT_VERSION_STR,
            "python_version": platform.python_version(),
            "gdal_version": gdal.VersionInfo("--version"),
            "plugin_version": PLUGIN_VERSION,
            "prefix_path": QgsApplication.prefixPath(),
            "process_id": os.getpid(),
            "platform": sys.platform,
            "project_path": project.fileName() or "",
            "project_dirty": project.isDirty(),
        }

    def op_get_project_info(self, _params):
        """取得目前專案 CRS、圖層數與保存狀態。"""
        project = self.project()
        path = project.fileName() or ""
        return {
            "title": project.title() or (Path(path).stem if path else "Untitled"),
            "path": path,
            "crs": crs_dict(project.crs()),
            "layer_count": len(project.mapLayers()),
            "is_dirty": project.isDirty(),
            "home_path": project.homePath(),
            "distance_units": enum_int(project.distanceUnits()),
            "area_units": enum_int(project.areaUnits()),
        }

    def op_save_project(self, _params):
        """經真人確認後保存有明確路徑的目前專案。"""
        project = self.project()
        path = project.fileName() or ""
        if not path:
            raise BridgeError("PROJECT_NOT_FOUND", "目前專案尚未命名，請使用 save_project_as。")
        self.confirmation.require(
            "儲存 QGIS 專案",
            "MCP 要求儲存目前專案與所有尚未保存的專案設定。",
            f"完整專案路徑：\n{path}\n\n此操作將覆寫現有專案檔。",
        )
        if not project.write():
            raise BridgeError("FILE_ACCESS_DENIED", "QGIS 無法儲存目前專案。", {"path": path})
        return {"path": path, "is_dirty": project.isDirty()}

    def op_save_project_as(self, params):
        """驗證 QGZ/QGS 絕對路徑並經真人確認後另存專案。"""
        output_path = absolute_output_path(require_string(params, "output_path"), {".qgz", ".qgs"})
        project = self.project()
        self.confirmation.require(
            "另存 QGIS 專案",
            "MCP 要求將目前專案儲存到指定位置。",
            f"完整目標路徑：\n{output_path}\n\n若檔案存在將被覆寫。",
        )
        if not project.write(str(output_path)):
            raise BridgeError("FILE_ACCESS_DENIED", "QGIS 無法另存專案。", {"path": str(output_path)})
        return {"path": str(output_path), "is_dirty": project.isDirty()}

    def op_list_layers(self, params):
        """依專案圖層樹順序列出圖層，避免 mapLayers dict 順序誤導 AI。"""
        layer_type = params.get("layer_type", "all")
        if layer_type not in {"all", "vector", "raster"}:
            raise BridgeError("INVALID_PARAMETERS", "layer_type 必須是 all、vector 或 raster。")
        layers = []
        for node in self.project().layerTreeRoot().findLayers():
            layer = node.layer()
            if layer is None:
                continue
            if layer_type == "vector" and not isinstance(layer, QgsVectorLayer):
                continue
            if layer_type == "raster" and not isinstance(layer, QgsRasterLayer):
                continue
            layers.append(self._layer_summary(layer, visible=node.isVisible()))
        return {"layers": layers, "count": len(layers)}

    def op_get_layer_info(self, params):
        """依 layer_id 回傳向量或 Raster 的詳細 metadata。"""
        layer = self.layer(require_string(params, "layer_id"))
        info = self._layer_summary(layer)
        info.update(
            {
                "provider": layer.providerType(),
                "source": layer.publicSource(),
                "extent": rectangle_dict(layer.extent()),
                "crs": crs_dict(layer.crs()),
                "is_valid": layer.isValid(),
                "is_spatial": layer.isSpatial(),
            }
        )
        if isinstance(layer, QgsVectorLayer):
            info.update(
                {
                    "feature_count": layer.featureCount(),
                    "selected_feature_count": layer.selectedFeatureCount(),
                    "geometry_type": QgsWkbTypes.displayString(layer.wkbType()),
                    "fields": [
                        self._field_summary(field, index) for index, field in enumerate(layer.fields())
                    ],
                    "is_editable": layer.isEditable(),
                    "is_modified": layer.isModified(),
                }
            )
        elif isinstance(layer, QgsRasterLayer):
            info.update(
                {
                    "width": layer.width(),
                    "height": layer.height(),
                    "band_count": layer.bandCount(),
                }
            )
        return info

    def op_add_layer(self, params):
        """嘗試以明確或自動類型建立圖層，只有 valid 才加入專案。"""
        source = require_string(params, "source")
        requested_name = require_string(params, "name", allow_empty=True)
        provider = require_string(params, "provider", allow_empty=True)
        layer_kind = params.get("layer_kind", "auto")
        if layer_kind not in {"auto", "vector", "raster"}:
            raise BridgeError("INVALID_PARAMETERS", "layer_kind 必須是 auto、vector 或 raster。")
        default_name = requested_name or self._safe_source_name(source)
        candidates = []
        if layer_kind in {"auto", "vector"}:
            vector_provider = provider or "ogr"
            candidates.append(QgsVectorLayer(source, default_name, vector_provider))
        if layer_kind in {"auto", "raster"}:
            raster_provider = provider or "gdal"
            candidates.append(QgsRasterLayer(source, default_name, raster_provider))
        valid_layer = next((candidate for candidate in candidates if candidate.isValid()), None)
        if valid_layer is None:
            raise BridgeError(
                "UNSUPPORTED_FORMAT",
                "QGIS 無法以指定來源與 provider 建立有效圖層。",
                {"provider": provider, "layer_kind": layer_kind},
            )
        self.project().addMapLayer(valid_layer)
        return self._layer_summary(valid_layer)

    def op_remove_layer(self, params):
        """經真人確認後只從專案移除圖層，不刪除來源檔案。"""
        layer = self.layer(require_string(params, "layer_id"))
        self.confirmation.require(
            "從 QGIS 專案移除圖層",
            f"即將從目前專案移除圖層「{layer.name()}」。",
            f"圖層 ID：{layer.id()}\n資料來源：{layer.publicSource()}\n\n來源檔案不會被刪除。",
        )
        self.project().removeMapLayer(layer.id())
        return {"removed_layer_id": layer.id(), "removed_layer_name": layer.name()}

    def op_set_layer_visibility(self, params):
        """變更圖層樹節點可見性並刷新畫布。"""
        layer = self.layer(require_string(params, "layer_id"))
        visible = require_bool(params, "visible")
        node = self.project().layerTreeRoot().findLayer(layer.id())
        if node is None:
            raise BridgeError("LAYER_NOT_FOUND", "圖層存在，但圖層樹節點不存在。")
        node.setItemVisibilityChecked(visible)
        self.iface.mapCanvas().refresh()
        return {"layer_id": layer.id(), "visible": visible}

    def op_reorder_layers(self, params):
        """將指定圖層依序排在根群組中，未列出的圖層由 QGIS 保留。"""
        ordered_ids = params.get("ordered_layer_ids")
        if not isinstance(ordered_ids, list) or not ordered_ids:
            raise BridgeError("INVALID_PARAMETERS", "ordered_layer_ids 必須是非空列表。")
        if any(not isinstance(layer_id, str) for layer_id in ordered_ids):
            raise BridgeError("INVALID_PARAMETERS", "ordered_layer_ids 每筆都必須是字串。")
        if len(set(ordered_ids)) != len(ordered_ids):
            raise BridgeError("INVALID_PARAMETERS", "ordered_layer_ids 不可重複。")
        ordered_layers = [self.layer(layer_id) for layer_id in ordered_ids]
        self.project().layerTreeRoot().reorderGroupLayers(ordered_layers)
        return {"ordered_layer_ids": ordered_ids}

    def op_rename_layer(self, params):
        """只改專案顯示名稱，不改資料來源名稱。"""
        layer = self.layer(require_string(params, "layer_id"))
        new_name = require_string(params, "new_name")
        old_name = layer.name()
        layer.setName(new_name)
        return {"layer_id": layer.id(), "old_name": old_name, "new_name": layer.name()}

    def op_export_layer(self, params):
        """匯出向量；Raster 則交由 QGIS Processing 背景工作。"""
        layer = self.layer(require_string(params, "layer_id"))
        output_path = absolute_output_path(require_string(params, "output_path"))
        output_crs = require_string(params, "output_crs", allow_empty=True)
        only_selected = require_bool(params, "only_selected", False)
        add_to_project = require_bool(params, "add_to_project", True)
        self.confirm_overwrite(output_path, "覆寫圖層匯出檔案")
        if isinstance(layer, QgsVectorLayer):
            return self._export_vector_layer(layer, output_path, output_crs, only_selected, add_to_project)
        if isinstance(layer, QgsRasterLayer):
            algorithm_id = "gdal:warpreproject" if output_crs else "gdal:translate"
            algorithm = QgsApplication.processingRegistry().algorithmById(algorithm_id)
            if algorithm is None:
                raise BridgeError("PROCESSING_ALGORITHM_NOT_FOUND", f"找不到 {algorithm_id}。")
            processing_params = {"INPUT": layer.id(), "OUTPUT": str(output_path)}
            if output_crs:
                processing_params["TARGET_CRS"] = output_crs
            job = self.jobs.start_processing(algorithm, processing_params, add_to_project)
            return {"status": "queued", **job}
        raise BridgeError("UNSUPPORTED_FORMAT", "此圖層類型不支援匯出。")

    def _export_vector_layer(self, layer, output_path, output_crs, only_selected, add_to_project):
        """使用官方 writeAsVectorFormatV3 進行向量匯出與可選重投影。"""
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = vector_driver_for_path(output_path)
        options.layerName = output_path.stem
        options.onlySelectedFeatures = only_selected
        if output_crs:
            destination_crs = QgsCoordinateReferenceSystem(output_crs)
            if not destination_crs.isValid():
                raise BridgeError("INVALID_PARAMETERS", f"無效 output_crs：{output_crs}")
            options.destCRS = destination_crs
        error_code, error_message, new_filename, new_layer_name = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer,
            str(output_path),
            self.project().transformContext(),
            options,
        )
        no_error = getattr(QgsVectorFileWriter, "NoError", QgsVectorFileWriter.WriterError.NoError)
        if error_code != no_error:
            raise BridgeError(
                "PROCESSING_FAILED",
                "向量圖層匯出失敗。",
                {"writer_error": enum_int(error_code), "message": error_message},
            )
        added_layer = None
        if add_to_project:
            added_layer = QgsVectorLayer(
                new_filename or str(output_path), new_layer_name or output_path.stem, "ogr"
            )
            if added_layer.isValid():
                self.project().addMapLayer(added_layer)
        return {
            "output_path": new_filename or str(output_path),
            "output_layer_name": new_layer_name or output_path.stem,
            "added_layer_id": added_layer.id() if added_layer and added_layer.isValid() else None,
            "feature_count": added_layer.featureCount() if added_layer and added_layer.isValid() else None,
        }

    @staticmethod
    def _safe_source_name(source):
        """只用來源最後片段當顯示名稱，不把連線字串整段暴露在 UI。"""
        file_name = Path(source.split("|", 1)[0]).stem
        return file_name or "MCP Layer"

    @staticmethod
    def _field_summary(field, index):
        """以 JSON 相容欄位摘要取代 SIP 物件。"""
        return {
            "index": index,
            "name": field.name(),
            "type_name": field.typeName(),
            "length": field.length(),
            "precision": field.precision(),
            "alias": field.alias(),
            "comment": field.comment(),
        }

    @staticmethod
    def _layer_summary(layer, visible=None):
        """建立適合 tools/list 後續決策使用的最小圖層摘要。"""
        if isinstance(layer, QgsVectorLayer):
            layer_type = "vector"
        elif isinstance(layer, QgsRasterLayer):
            layer_type = "raster"
        else:
            layer_type = "other"
        summary = {
            "layer_id": layer.id(),
            "name": layer.name(),
            "layer_type": layer_type,
            "provider": layer.providerType(),
            "crs": crs_dict(layer.crs()),
            "is_valid": layer.isValid(),
        }
        if visible is not None:
            summary["visible"] = bool(visible)
        if isinstance(layer, QgsVectorLayer):
            summary["feature_count"] = layer.featureCount()
            summary["geometry_type"] = QgsWkbTypes.displayString(layer.wkbType())
        elif isinstance(layer, QgsRasterLayer):
            summary["width"] = layer.width()
            summary["height"] = layer.height()
            summary["band_count"] = layer.bandCount()
        return json_safe(summary)
