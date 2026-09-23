"""實作欄位、QGIS Expression、搜尋、選取與分頁圖徵 actions。"""

import json
import os
import uuid

from qgis.core import (
    Qgis,
    QgsExpression,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeatureRequest,
    QgsField,
    QgsJsonExporter,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType

from ..constants import MAX_PAGE_SIZE
from ..errors import BridgeError
from ..utils import (
    absolute_output_path,
    json_safe,
    rectangle_dict,
    require_bbox,
    require_bool,
    require_int,
    require_string,
)


class FeatureOperations:
    """提供原始資料安全確認、交易式欄位修改與上下文保護。"""

    def op_list_fields(self, params):
        """列出指定向量圖層的欄位 metadata。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        fields = [self._field_details(layer, field, index) for index, field in enumerate(layer.fields())]
        return {"layer_id": layer.id(), "fields": fields, "count": len(fields)}

    def op_validate_expression(self, params):
        """解析並 prepare QGIS Expression，但不對任何圖徵寫值。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        expression_text = require_string(params, "expression")
        expression, context = self._prepared_expression(layer, expression_text)
        return {
            "valid": True,
            "expression": expression_text,
            "referenced_columns": sorted(expression.referencedColumns()),
            "needs_geometry": expression.needsGeometry(),
            "is_field": expression.isField(),
            "is_static": self._expression_is_static(expression, context),
        }

    @staticmethod
    def _expression_is_static(expression, context):
        """兼容 QGIS 3.44（由 root node 判斷）與新版 expression API。"""
        is_static = getattr(expression, "isStatic", None)
        if callable(is_static):
            return bool(is_static(context))
        root_node = expression.rootNode()
        return bool(root_node is not None and root_node.isStatic(expression, context))

    def op_add_fields(self, params):
        """經確認後在可復原編輯命令或新交易中新增欄位。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        field_specs = params.get("fields")
        if not isinstance(field_specs, list) or not field_specs:
            raise BridgeError("INVALID_PARAMETERS", "fields 必須是非空列表。")
        fields = [self._field_from_spec(spec) for spec in field_specs]
        existing_names = {field.name().casefold() for field in layer.fields()}
        requested_names = [field.name().casefold() for field in fields]
        if len(set(requested_names)) != len(requested_names):
            raise BridgeError("INVALID_PARAMETERS", "新增欄位名稱不可重複。")
        conflicts = [field.name() for field in fields if field.name().casefold() in existing_names]
        if conflicts:
            raise BridgeError("INVALID_PARAMETERS", "欄位已存在。", {"conflicts": conflicts})
        self.confirmation.require(
            "新增向量圖層欄位",
            f"即將在「{layer.name()}」新增 {len(fields)} 個欄位。",
            "圖層 ID：{}\n欄位：{}\n\n若資料提供者不支援交易，可能無法完整復原。".format(
                layer.id(), ", ".join(field.name() for field in fields)
            ),
        )
        started_here = self._begin_edit(layer, "QGIS MCP 新增欄位")
        try:
            for field in fields:
                if not layer.addAttribute(field):
                    raise BridgeError("PROCESSING_FAILED", f"無法新增欄位：{field.name()}")
            layer.updateFields()
            self._finish_edit(layer, started_here)
        except Exception:
            self._abort_edit(layer, started_here)
            raise
        return {"layer_id": layer.id(), "added_fields": [field.name() for field in fields]}

    def op_calculate_field(self, params):
        """先完整驗證 Expression，再經確認更新指定範圍的圖徵。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        field_name = require_string(params, "field_name")
        expression_text = require_string(params, "expression")
        only_selected = require_bool(params, "only_selected", False)
        field_index = layer.fields().indexOf(field_name)
        if field_index < 0:
            raise BridgeError("INVALID_PARAMETERS", f"找不到欄位：{field_name}")
        expression, context = self._prepared_expression(layer, expression_text)
        feature_ids = sorted(layer.selectedFeatureIds()) if only_selected else None
        target_count = len(feature_ids) if feature_ids is not None else layer.featureCount()
        self.confirmation.require(
            "批次計算欄位",
            f"即將使用 QGIS Expression 更新「{field_name}」欄位，預估影響 {target_count} 筆。",
            (
                f"圖層：{layer.name()}\n圖層 ID：{layer.id()}\n"
                f"Expression：\n{expression_text}\n\n此操作將修改原始圖層資料。"
            ),
        )
        request = QgsFeatureRequest()
        if feature_ids is not None:
            request.setFilterFids(feature_ids)
        started_here = self._begin_edit(layer, "QGIS MCP 欄位計算")
        updated = 0
        skipped = 0
        try:
            for feature in layer.getFeatures(request):
                context.setFeature(feature)
                value = expression.evaluate(context)
                if expression.hasEvalError():
                    raise BridgeError(
                        "INVALID_EXPRESSION",
                        "Expression 評估失敗。",
                        {"feature_id": feature.id(), "error": expression.evalErrorString()},
                    )
                if layer.changeAttributeValue(feature.id(), field_index, value):
                    updated += 1
                else:
                    skipped += 1
            self._finish_edit(layer, started_here)
        except Exception:
            self._abort_edit(layer, started_here)
            raise
        return {
            "layer_id": layer.id(),
            "field_name": field_name,
            "updated_count": updated,
            "skipped_count": skipped,
            "only_selected": only_selected,
        }

    def op_delete_fields(self, params):
        """經確認後刪除指定欄位，並在失敗時回復此次編輯命令。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        field_names = params.get("field_names")
        if (
            not isinstance(field_names, list)
            or not field_names
            or any(not isinstance(name, str) or not name.strip() for name in field_names)
        ):
            raise BridgeError("INVALID_PARAMETERS", "field_names 必須是非空字串列表。")
        if len(set(field_names)) != len(field_names):
            raise BridgeError("INVALID_PARAMETERS", "field_names 不可重複。")
        indices = [layer.fields().indexOf(name) for name in field_names]
        missing = [name for name, index in zip(field_names, indices, strict=True) if index < 0]
        if missing:
            raise BridgeError("INVALID_PARAMETERS", "部分欄位不存在。", {"missing": missing})
        self.confirmation.require(
            "刪除向量圖層欄位",
            f"即將從「{layer.name()}」刪除 {len(field_names)} 個欄位。",
            f"欄位：{', '.join(field_names)}\n\n欄位與其中資料將被刪除，可能無法完整復原。",
        )
        started_here = self._begin_edit(layer, "QGIS MCP 刪除欄位")
        try:
            if not layer.deleteAttributes(sorted(indices, reverse=True)):
                raise BridgeError("PROCESSING_FAILED", "資料提供者拒絕刪除欄位。")
            layer.updateFields()
            self._finish_edit(layer, started_here)
        except Exception:
            self._abort_edit(layer, started_here)
            raise
        return {"layer_id": layer.id(), "deleted_fields": field_names}

    def op_select_features(self, params):
        """依 Expression/bbox 查出 IDs，再套用明確選取模式。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        expression_text = require_string(params, "expression", allow_empty=True)
        rectangle = require_bbox(params.get("bbox"))
        if not expression_text and rectangle is None:
            raise BridgeError("INVALID_PARAMETERS", "expression 與 bbox 至少需要提供一項。")
        request = self._feature_request(layer, expression_text, rectangle, "")
        matching_ids = [feature.id() for feature in layer.getFeatures(request)]
        mode = params.get("mode", "replace")
        behavior_map = {
            "replace": Qgis.SelectBehavior.SetSelection,
            "add": Qgis.SelectBehavior.AddToSelection,
            "remove": Qgis.SelectBehavior.RemoveFromSelection,
            "intersect": Qgis.SelectBehavior.IntersectSelection,
        }
        if mode not in behavior_map:
            raise BridgeError("INVALID_PARAMETERS", "mode 必須是 replace、add、remove 或 intersect。")
        layer.selectByIds(matching_ids, behavior_map[mode])
        return {
            "layer_id": layer.id(),
            "matched_count": len(matching_ids),
            "selected_count": layer.selectedFeatureCount(),
            "mode": mode,
        }

    def op_clear_selection(self, params):
        """清除指定圖層目前選取。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        previous_count = layer.selectedFeatureCount()
        layer.removeSelection()
        return {"layer_id": layer.id(), "cleared_count": previous_count}

    def op_get_selected_features(self, params):
        """以 feature ID 穩定排序後分頁回傳選取圖徵。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        page, page_size, geometry_format = self._pagination_params(params)
        selected_ids = sorted(layer.selectedFeatureIds())
        offset = (page - 1) * page_size
        page_ids = selected_ids[offset : offset + page_size]
        request = QgsFeatureRequest().setFilterFids(page_ids)
        feature_by_id = {feature.id(): feature for feature in layer.getFeatures(request)}
        features = [
            self._serialize_feature(layer, feature_by_id[feature_id], geometry_format)
            for feature_id in page_ids
            if feature_id in feature_by_id
        ]
        return self._page_result(features, len(selected_ids), page, page_size)

    def op_query_features(self, params):
        """依條件與可選排序遍歷一次，僅保存指定頁內容。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        expression_text = require_string(params, "expression", allow_empty=True)
        rectangle = require_bbox(params.get("bbox"))
        order_by = require_string(params, "order_by", allow_empty=True)
        page, page_size, geometry_format = self._pagination_params(params)
        request = self._feature_request(layer, expression_text, rectangle, order_by)
        offset = (page - 1) * page_size
        end_offset = offset + page_size
        features = []
        total_count = 0
        for feature in layer.getFeatures(request):
            if offset <= total_count < end_offset:
                features.append(self._serialize_feature(layer, feature, geometry_format))
            total_count += 1
        return self._page_result(features, total_count, page, page_size)

    def op_export_feature_query(self, params):
        """以串流寫入大量 JSON/GeoJSON，避免把所有圖徵保存在記憶體或 MCP 回應。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        output_format = params.get("output_format", "geojson")
        if output_format not in {"json", "geojson"}:
            raise BridgeError("INVALID_PARAMETERS", "output_format 必須是 json 或 geojson。")
        allowed_suffix = {".json"} if output_format == "json" else {".json", ".geojson"}
        output_path = absolute_output_path(require_string(params, "output_path"), allowed_suffix)
        expression_text = require_string(params, "expression", allow_empty=True)
        rectangle = require_bbox(params.get("bbox"))
        self.confirm_overwrite(output_path, "覆寫圖徵查詢輸出")
        request = self._feature_request(layer, expression_text, rectangle, "")
        temporary_path = output_path.with_name(f".{output_path.name}.{uuid.uuid4().hex}.tmp")
        count = 0
        exporter = QgsJsonExporter(layer)
        try:
            with temporary_path.open("w", encoding="utf-8", newline="") as output_file:
                output_file.write(
                    '{"type":"FeatureCollection","features":[' if output_format == "geojson" else "["
                )
                first = True
                for feature in layer.getFeatures(request):
                    if not first:
                        output_file.write(",")
                    if output_format == "geojson":
                        output_file.write(exporter.exportFeature(feature))
                    else:
                        record = {
                            field.name(): json_safe(feature.attribute(field.name()))
                            for field in layer.fields()
                        }
                        output_file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                    first = False
                    count += 1
                output_file.write("]}" if output_format == "geojson" else "]")
            os.replace(temporary_path, output_path)
        except Exception:
            try:
                if temporary_path.is_file():
                    temporary_path.unlink()
            except OSError:
                pass
            raise
        return {
            "output_path": str(output_path),
            "output_format": output_format,
            "feature_count": count,
            "size_bytes": output_path.stat().st_size,
        }

    def op_zoom_to_features(self, params):
        """縮放至選取圖徵；若未要求選取則縮放整個圖層。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        selected_only = require_bool(params, "selected_only", True)
        if selected_only:
            if layer.selectedFeatureCount() == 0:
                raise BridgeError("INVALID_PARAMETERS", "指定圖層目前沒有選取圖徵。")
            self.iface.mapCanvas().zoomToSelected(layer)
        else:
            self.iface.setActiveLayer(layer)
            self.iface.zoomToActiveLayer()
        self.iface.mapCanvas().refresh()
        return {"layer_id": layer.id(), "selected_only": selected_only}

    def _prepared_expression(self, layer, expression_text):
        """建立包含 global/project/layer scopes 的已 prepare Expression。"""
        expression = QgsExpression(expression_text)
        if expression.hasParserError():
            raise BridgeError(
                "INVALID_EXPRESSION",
                "QGIS Expression 語法錯誤。",
                {"error": expression.parserErrorString()},
            )
        context = QgsExpressionContext()
        context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        if not expression.prepare(context):
            raise BridgeError(
                "INVALID_EXPRESSION",
                "QGIS Expression 無法準備執行。",
                {"error": expression.evalErrorString()},
            )
        return expression, context

    def _feature_request(self, layer, expression_text, rectangle, order_by):
        """建立同時支援 Expression、bbox 與穩定排序的 QgsFeatureRequest。"""
        request = QgsFeatureRequest()
        if expression_text:
            self._prepared_expression(layer, expression_text)
            request.setFilterExpression(expression_text)
        if rectangle is not None:
            request.setFilterRect(rectangle)
        if order_by:
            order_expression = QgsExpression(order_by)
            if order_expression.hasParserError():
                raise BridgeError(
                    "INVALID_EXPRESSION",
                    "order_by Expression 語法錯誤。",
                    {"error": order_expression.parserErrorString()},
                )
            clause = QgsFeatureRequest.OrderByClause(order_expression, True, True)
            request.setOrderBy(QgsFeatureRequest.OrderBy([clause]))
        return request

    @staticmethod
    def _serialize_feature(layer, feature, geometry_format):
        """依明確要求回傳屬性及有限幾何表示。"""
        attributes = {field.name(): json_safe(feature.attribute(field.name())) for field in layer.fields()}
        payload = {"feature_id": feature.id(), "attributes": attributes}
        geometry = feature.geometry()
        if geometry_format == "summary":
            payload["geometry"] = {
                "is_empty": geometry.isEmpty(),
                "wkb_type": QgsWkbTypes.displayString(geometry.wkbType()),
                "bbox": rectangle_dict(geometry.boundingBox()) if not geometry.isEmpty() else None,
                "area": geometry.area() if not geometry.isEmpty() else 0.0,
                "length": geometry.length() if not geometry.isEmpty() else 0.0,
            }
        elif geometry_format == "wkt":
            payload["geometry"] = geometry.asWkt() if not geometry.isEmpty() else None
        elif geometry_format == "geojson":
            payload["geometry"] = json.loads(geometry.asJson()) if not geometry.isEmpty() else None
        return payload

    @staticmethod
    def _page_result(features, total_count, page, page_size):
        """建立一致的分頁資訊，讓 AI 知道是否需要續取。"""
        return {
            "features": features,
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "returned_count": len(features),
            "has_more": page * page_size < total_count,
        }

    @staticmethod
    def _pagination_params(params):
        """驗證頁碼、硬上限與 geometry_format。"""
        page = require_int(params, "page", 1, minimum=1)
        page_size = require_int(params, "page_size", 100, minimum=1, maximum=MAX_PAGE_SIZE)
        geometry_format = params.get("geometry_format", "none")
        if geometry_format not in {"none", "summary", "wkt", "geojson"}:
            raise BridgeError("INVALID_PARAMETERS", "geometry_format 格式無效。")
        return page, page_size, geometry_format

    @staticmethod
    def _field_details(layer, field, index):
        """回傳欄位來源、型別與限制的 JSON 摘要。"""
        constraints = field.constraints()
        return {
            "index": index,
            "name": field.name(),
            "alias": field.alias(),
            "type_name": field.typeName(),
            "length": field.length(),
            "precision": field.precision(),
            "comment": field.comment(),
            "is_read_only": field.isReadOnly(),
            "origin": json_safe(layer.fields().fieldOrigin(index)),
            "constraints": json_safe(constraints.constraints()),
        }

    @staticmethod
    def _field_from_spec(spec):
        """將允許的欄位型別轉成 Qt5/Qt6 共通 QMetaType。"""
        if not isinstance(spec, dict):
            raise BridgeError("INVALID_PARAMETERS", "每個 field spec 都必須是 object。")
        name = spec.get("name")
        type_name = spec.get("type")
        if not isinstance(name, str) or not name.strip():
            raise BridgeError("INVALID_PARAMETERS", "field name 不可為空。")
        if not isinstance(type_name, str):
            raise BridgeError("INVALID_PARAMETERS", "field type 必須是字串。")
        meta_types = getattr(QMetaType, "Type", QMetaType)
        type_map = {
            "string": meta_types.QString,
            "integer": meta_types.Int,
            "int64": meta_types.LongLong,
            "double": meta_types.Double,
            "boolean": meta_types.Bool,
            "date": meta_types.QDate,
            "datetime": meta_types.QDateTime,
        }
        normalized_type = type_name.strip().lower()
        if normalized_type not in type_map:
            raise BridgeError(
                "INVALID_PARAMETERS",
                f"不支援欄位型別：{type_name}",
                {"allowed": sorted(type_map)},
            )
        length = spec.get("length", 0)
        precision = spec.get("precision", 0)
        if isinstance(length, bool) or not isinstance(length, int) or length < 0:
            raise BridgeError("INVALID_PARAMETERS", "field length 必須是非負整數。")
        if isinstance(precision, bool) or not isinstance(precision, int) or precision < 0:
            raise BridgeError("INVALID_PARAMETERS", "field precision 必須是非負整數。")
        return QgsField(name.strip(), type_map[normalized_type], len=length, prec=precision)

    @staticmethod
    def _begin_edit(layer, command_name):
        """保留既有編輯工作階段；只有 MCP 自己開啟時才在完成後 commit。"""
        started_here = not layer.isEditable()
        if started_here:
            if not layer.startEditing():
                raise BridgeError("FILE_ACCESS_DENIED", "資料提供者無法開始編輯工作階段。")
        else:
            layer.beginEditCommand(command_name)
        return started_here

    @staticmethod
    def _finish_edit(layer, started_here):
        """只提交 MCP 自己開始的交易，既有工作階段則保留 undo stack。"""
        if started_here:
            if not layer.commitChanges():
                errors = layer.commitErrors()
                layer.rollBack()
                raise BridgeError("PROCESSING_FAILED", "圖層提交失敗。", {"errors": errors[:20]})
        else:
            layer.endEditCommand()

    @staticmethod
    def _abort_edit(layer, started_here):
        """失敗時只回復此次 MCP 編輯，不清除使用者先前的編輯歷史。"""
        if started_here:
            layer.rollBack()
        else:
            layer.destroyEditCommand()
