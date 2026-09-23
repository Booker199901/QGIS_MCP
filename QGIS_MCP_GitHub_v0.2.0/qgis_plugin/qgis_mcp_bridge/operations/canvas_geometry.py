"""實作幾何檢查/修復，以及 QGIS 畫布狀態、範圍與 PNG 截圖。"""

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsMapRendererParallelJob,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType, QSize

from ..errors import BridgeError
from ..utils import (
    absolute_output_path,
    crs_dict,
    rectangle_dict,
    require_bbox,
    require_bool,
    require_int,
    require_string,
)


class CanvasGeometryOperations:
    """提供幾何品質控制與可見 QGIS 畫布操作。"""

    def op_check_geometry_validity(self, params):
        """檢查空幾何及 GEOS/內建 validation errors，可建立記憶體錯誤點圖層。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        selected_only = require_bool(params, "selected_only", False)
        create_error_layer = require_bool(params, "create_error_layer", True)
        request = QgsFeatureRequest()
        if selected_only:
            selected_ids = layer.selectedFeatureIds()
            request.setFilterFids(selected_ids)
        issue_records = []
        error_features = []
        checked_count = 0
        error_layer = self._new_geometry_error_layer(layer) if create_error_layer else None
        for feature in layer.getFeatures(request):
            checked_count += 1
            geometry = feature.geometry()
            if geometry is None or geometry.isNull() or geometry.isEmpty():
                issue = {"feature_id": feature.id(), "error": "Empty or null geometry", "location": None}
                issue_records.append(issue)
                if error_layer is not None:
                    error_features.append(
                        self._geometry_error_feature(error_layer, feature, issue["error"], None)
                    )
                continue
            errors = geometry.validateGeometry()
            for geometry_error in errors:
                location = (
                    geometry_error.where() if geometry_error.hasWhere() else geometry.centroid().asPoint()
                )
                issue = {
                    "feature_id": feature.id(),
                    "error": geometry_error.what(),
                    "location": {"x": location.x(), "y": location.y()} if location else None,
                }
                issue_records.append(issue)
                if error_layer is not None:
                    error_features.append(
                        self._geometry_error_feature(error_layer, feature, geometry_error.what(), location)
                    )
        error_layer_id = None
        if error_layer is not None and error_features:
            error_layer.dataProvider().addFeatures(error_features)
            error_layer.updateExtents()
            self.project().addMapLayer(error_layer)
            error_layer_id = error_layer.id()
        return {
            "layer_id": layer.id(),
            "checked_feature_count": checked_count,
            "issue_count": len(issue_records),
            "invalid_feature_count": len({issue["feature_id"] for issue in issue_records}),
            "issues_sample": issue_records[:100],
            "issues_truncated": len(issue_records) > 100,
            "error_layer_id": error_layer_id,
        }

    def op_check_polygon_closedness(self, params):
        """逐一檢查 Polygon/MultiPolygon 每個環的首尾座標是否一致。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        if QgsWkbTypes.geometryType(layer.wkbType()) != Qgis.GeometryType.Polygon:
            raise BridgeError("INVALID_PARAMETERS", "封閉性檢查只支援 Polygon/MultiPolygon 圖層。")
        selected_only = require_bool(params, "selected_only", False)
        request = QgsFeatureRequest()
        if selected_only:
            request.setFilterFids(layer.selectedFeatureIds())
        issues = []
        checked_count = 0
        for feature in layer.getFeatures(request):
            checked_count += 1
            geometry = feature.geometry()
            if geometry.isNull() or geometry.isEmpty():
                issues.append({"feature_id": feature.id(), "part": None, "ring": None, "reason": "empty"})
                continue
            polygons = geometry.asMultiPolygon() if geometry.isMultipart() else [geometry.asPolygon()]
            for part_index, polygon in enumerate(polygons):
                for ring_index, ring in enumerate(polygon):
                    if len(ring) < 4 or ring[0] != ring[-1]:
                        issues.append(
                            {
                                "feature_id": feature.id(),
                                "part": part_index,
                                "ring": ring_index,
                                "reason": "ring_not_closed_or_too_short",
                            }
                        )
        return {
            "layer_id": layer.id(),
            "checked_feature_count": checked_count,
            "issue_count": len(issues),
            "issues_sample": issues[:100],
            "issues_truncated": len(issues) > 100,
        }

    def op_fix_geometries(self, params):
        """預設啟動 native:fixgeometries 新輸出；明確要求才修改原始圖層。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        output_value = require_string(params, "output_path")
        modify_original = require_bool(params, "modify_original", False)
        add_to_project = require_bool(params, "add_to_project", True)
        if modify_original:
            return self._fix_original_geometries(layer)
        if output_value.upper() != "TEMPORARY_OUTPUT":
            output_path = absolute_output_path(output_value)
            self.confirm_overwrite(output_path, "覆寫幾何修復輸出")
            output_value = str(output_path)
        algorithm = QgsApplication.processingRegistry().algorithmById("native:fixgeometries")
        if algorithm is None:
            raise BridgeError("PROCESSING_ALGORITHM_NOT_FOUND", "找不到 native:fixgeometries。")
        job = self.jobs.start_processing(
            algorithm,
            {"INPUT": layer.id(), "OUTPUT": output_value},
            add_to_project,
        )
        return {"status": "queued", **job}

    def op_get_canvas_state(self, _params):
        """取得目前畫布 CRS、範圍、尺寸、比例尺與可見圖層 IDs。"""
        canvas = self.iface.mapCanvas()
        size = canvas.size()
        return {
            "crs": crs_dict(canvas.mapSettings().destinationCrs()),
            "extent": rectangle_dict(canvas.extent()),
            "width": size.width(),
            "height": size.height(),
            "scale": canvas.scale(),
            "rotation": canvas.rotation(),
            "visible_layer_ids": [layer.id() for layer in canvas.layers()],
        }

    def op_set_canvas_extent(self, params):
        """把輸入 bbox 視需要轉換到畫布 CRS 後設定範圍。"""
        rectangle = require_bbox(params.get("bbox"))
        if rectangle is None:
            raise BridgeError("INVALID_PARAMETERS", "bbox 不可為空。")
        crs_text = require_string(params, "crs", allow_empty=True)
        canvas = self.iface.mapCanvas()
        if crs_text:
            source_crs = QgsCoordinateReferenceSystem(crs_text)
            if not source_crs.isValid():
                raise BridgeError("INVALID_PARAMETERS", f"無效 CRS：{crs_text}")
            destination_crs = canvas.mapSettings().destinationCrs()
            if source_crs != destination_crs:
                transform = QgsCoordinateTransform(source_crs, destination_crs, QgsProject.instance())
                rectangle = transform.transformBoundingBox(rectangle)
        canvas.setExtent(rectangle)
        canvas.refresh()
        return {
            "extent": rectangle_dict(canvas.extent()),
            "crs": crs_dict(canvas.mapSettings().destinationCrs()),
        }

    def op_zoom_to_layer(self, params):
        """啟用指定圖層後使用 QGIS 原生 zoomToActiveLayer。"""
        layer = self.layer(require_string(params, "layer_id"))
        self.iface.setActiveLayer(layer)
        self.iface.zoomToActiveLayer()
        self.iface.mapCanvas().refresh()
        return {"layer_id": layer.id(), "extent": rectangle_dict(self.iface.mapCanvas().extent())}

    def op_capture_canvas(self, params):
        """以畫布尺寸或指定像素大小輸出 PNG，不在 JSON 內嵌 base64。"""
        output_path = absolute_output_path(require_string(params, "output_path"), {".png"})
        width = require_int(params, "width", 0, minimum=0, maximum=32768)
        height = require_int(params, "height", 0, minimum=0, maximum=32768)
        if (width == 0) != (height == 0):
            raise BridgeError("INVALID_PARAMETERS", "width 與 height 必須同時為 0 或同時大於 0。")
        self.confirm_overwrite(output_path, "覆寫地圖畫布 PNG")
        canvas = self.iface.mapCanvas()
        if width == 0:
            canvas.saveAsImage(str(output_path))
            actual_width = canvas.size().width()
            actual_height = canvas.size().height()
        else:
            settings = canvas.mapSettings()
            settings.setOutputSize(QSize(width, height))
            render_job = QgsMapRendererParallelJob(settings)
            render_job.start()
            render_job.waitForFinished()
            image = render_job.renderedImage()
            if not image.save(str(output_path), "PNG"):
                raise BridgeError("FILE_ACCESS_DENIED", "無法寫入畫布 PNG。")
            actual_width = image.width()
            actual_height = image.height()
        if not output_path.is_file():
            raise BridgeError("FILE_ACCESS_DENIED", "畫布 PNG 未成功建立。")
        return {
            "output_path": str(output_path),
            "width": actual_width,
            "height": actual_height,
            "size_bytes": output_path.stat().st_size,
        }

    def _fix_original_geometries(self, layer):
        """經真人確認後使用 makeValid 更新原圖層，並保留既有 edit session undo。"""
        self.confirmation.require(
            "修復原始圖層幾何",
            f"即將直接修改「{layer.name()}」內的無效幾何。",
            f"圖層 ID：{layer.id()}\n圖徵數：{layer.featureCount()}\n\n幾何型別可能改變；建議先備份資料。",
        )
        started_here = self._begin_edit(layer, "QGIS MCP 修復原始幾何")
        changed = 0
        failed_ids = []
        type_changed_ids = []
        try:
            for feature in layer.getFeatures():
                geometry = feature.geometry()
                if geometry.isNull() or geometry.isEmpty() or geometry.isGeosValid():
                    continue
                repaired = geometry.makeValid()
                if repaired.isNull() or repaired.isEmpty() or not repaired.isGeosValid():
                    if len(failed_ids) < 100:
                        failed_ids.append(feature.id())
                    continue
                if repaired.wkbType() != geometry.wkbType() and len(type_changed_ids) < 100:
                    type_changed_ids.append(feature.id())
                if not layer.changeGeometry(feature.id(), repaired):
                    if len(failed_ids) < 100:
                        failed_ids.append(feature.id())
                    continue
                changed += 1
            self._finish_edit(layer, started_here)
        except Exception:
            self._abort_edit(layer, started_here)
            raise
        return {
            "layer_id": layer.id(),
            "changed_count": changed,
            "failed_feature_ids_sample": failed_ids,
            "type_changed_feature_ids_sample": type_changed_ids,
            "samples_truncated": len(failed_ids) >= 100 or len(type_changed_ids) >= 100,
        }

    @staticmethod
    def _new_geometry_error_layer(source_layer):
        """建立與來源 CRS 相同的記憶體點圖層。"""
        error_layer = QgsVectorLayer(
            f"Point?crs={source_layer.crs().authid()}",
            f"{source_layer.name()}_geometry_errors",
            "memory",
        )
        meta_types = getattr(QMetaType, "Type", QMetaType)
        fields = [
            QgsField("source_fid", meta_types.LongLong),
            QgsField("error", meta_types.QString, len=1024),
        ]
        error_layer.dataProvider().addAttributes(fields)
        error_layer.updateFields()
        return error_layer

    @staticmethod
    def _geometry_error_feature(error_layer, source_feature, message, location):
        """以驗證錯誤位置或來源幾何中心建立問題點。"""
        feature = QgsFeature(error_layer.fields())
        if location is None:
            source_geometry = source_feature.geometry()
            if source_geometry is not None and not source_geometry.isEmpty():
                location = source_geometry.centroid().asPoint()
        if location is not None:
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(location)))
        feature.setAttributes([source_feature.id(), str(message)[:1024]])
        return feature
