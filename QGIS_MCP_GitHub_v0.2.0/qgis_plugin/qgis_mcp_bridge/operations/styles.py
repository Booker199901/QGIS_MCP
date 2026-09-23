"""實作單一、分類、漸層、RGB 欄位與使用者色碼表樣式 actions。"""

import csv
import json

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsExpression,
    QgsField,
    QgsGraduatedSymbolRenderer,
    QgsProperty,
    QgsRenderContext,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsStyle,
    QgsSymbol,
    QgsSymbolLayer,
)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor

from ..errors import BridgeError
from ..utils import (
    absolute_output_path,
    input_file_path,
    json_safe,
    require_float,
    require_int,
    require_string,
)


class StyleOperations:
    """提供樣式變更及由使用者資料驅動的 R/G/B 寫入流程。"""

    def op_get_layer_style_info(self, params):
        """回傳 renderer 類型與有限分類/範圍摘要。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        renderer = layer.renderer()
        result = {
            "layer_id": layer.id(),
            "renderer_type": renderer.type() if renderer else None,
            "labels_enabled": layer.labelsEnabled(),
            "opacity": layer.opacity(),
        }
        if isinstance(renderer, QgsSingleSymbolRenderer):
            symbol = renderer.symbol()
            result["single_symbol"] = self._symbol_summary(symbol)
        elif isinstance(renderer, QgsCategorizedSymbolRenderer):
            result["classification_field"] = renderer.classAttribute()
            result["categories"] = [
                {
                    "value": json_safe(category.value()),
                    "label": category.label(),
                    "render": category.renderState(),
                    "symbol": self._symbol_summary(category.symbol()),
                }
                for category in renderer.categories()[:500]
            ]
            result["categories_truncated"] = len(renderer.categories()) > 500
        elif isinstance(renderer, QgsGraduatedSymbolRenderer):
            result["classification_field"] = renderer.classAttribute()
            result["ranges"] = [
                {
                    "lower": range_item.lowerValue(),
                    "upper": range_item.upperValue(),
                    "label": range_item.label(),
                    "render": range_item.renderState(),
                    "symbol": self._symbol_summary(range_item.symbol()),
                }
                for range_item in renderer.ranges()[:500]
            ]
            result["ranges_truncated"] = len(renderer.ranges()) > 500
        return result

    def op_apply_single_style(self, params):
        """建立符合圖層幾何型別的單一符號。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        fill_color = self._validated_color(require_string(params, "fill_color"), "fill_color")
        outline_color = self._validated_color(require_string(params, "outline_color"), "outline_color")
        opacity = require_float(params, "opacity", 1.0, minimum=0.0, maximum=1.0)
        size = require_float(params, "size", 2.0, minimum=0.0, maximum=100000.0)
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        if symbol is None:
            raise BridgeError("PROCESSING_FAILED", "無法為此幾何類型建立預設符號。")
        symbol.setColor(fill_color)
        symbol.setOpacity(opacity)
        if hasattr(symbol, "setSize"):
            symbol.setSize(size)
        if hasattr(symbol, "setWidth"):
            symbol.setWidth(size)
        for symbol_layer in symbol.symbolLayers():
            if hasattr(symbol_layer, "setStrokeColor"):
                symbol_layer.setStrokeColor(outline_color)
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        self._refresh_style(layer)
        return {
            "layer_id": layer.id(),
            "renderer_type": "singleSymbol",
            "symbol": self._symbol_summary(symbol),
        }

    def op_apply_categorized_style(self, params):
        """依使用者指定的 value/color/label 建立分類 renderer。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        field_name = require_string(params, "field_name")
        if layer.fields().indexOf(field_name) < 0:
            raise BridgeError("INVALID_PARAMETERS", f"找不到分類欄位：{field_name}")
        category_specs = params.get("categories")
        if not isinstance(category_specs, list) or not category_specs:
            raise BridgeError("INVALID_PARAMETERS", "categories 必須是非空列表。")
        categories = []
        seen_values = set()
        for spec in category_specs:
            if not isinstance(spec, dict) or "value" not in spec or "color" not in spec:
                raise BridgeError("INVALID_PARAMETERS", "每個 category 必須包含 value 與 color。")
            stable_value = json.dumps(json_safe(spec["value"]), ensure_ascii=False, sort_keys=True)
            if stable_value in seen_values:
                raise BridgeError("INVALID_PARAMETERS", "分類值不可重複。", {"value": spec["value"]})
            seen_values.add(stable_value)
            color = self._validated_color(str(spec["color"]), "category.color")
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            if symbol is None:
                raise BridgeError("PROCESSING_FAILED", "無法建立分類符號。")
            symbol.setColor(color)
            label = str(spec.get("label", spec["value"]))
            categories.append(QgsRendererCategory(spec["value"], symbol, label))
        layer.setRenderer(QgsCategorizedSymbolRenderer(field_name, categories))
        self._refresh_style(layer)
        return {"layer_id": layer.id(), "field_name": field_name, "category_count": len(categories)}

    def op_apply_graduated_style(self, params):
        """使用 QGIS 內建分類模式建立漸層 renderer。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        field_name = require_string(params, "field_name")
        if layer.fields().indexOf(field_name) < 0:
            raise BridgeError("INVALID_PARAMETERS", f"找不到漸層欄位：{field_name}")
        classes = require_int(params, "classes", 5, minimum=2, maximum=100)
        mode_name = params.get("mode", "equal_interval")
        mode_map = {
            "equal_interval": QgsGraduatedSymbolRenderer.Mode.EqualInterval,
            "quantile": QgsGraduatedSymbolRenderer.Mode.Quantile,
            "jenks": QgsGraduatedSymbolRenderer.Mode.Jenks,
            "stddev": QgsGraduatedSymbolRenderer.Mode.StdDev,
            "pretty": QgsGraduatedSymbolRenderer.Mode.Pretty,
        }
        if mode_name not in mode_map:
            raise BridgeError("INVALID_PARAMETERS", "不支援的 graduated mode。")
        color_ramp_name = require_string(params, "color_ramp")
        color_ramp = QgsStyle.defaultStyle().colorRamp(color_ramp_name)
        if color_ramp is None:
            raise BridgeError("INVALID_PARAMETERS", f"找不到色帶：{color_ramp_name}")
        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
        renderer = QgsGraduatedSymbolRenderer.createRenderer(
            layer,
            field_name,
            classes,
            mode_map[mode_name],
            symbol,
            color_ramp,
        )
        if renderer is None:
            raise BridgeError("PROCESSING_FAILED", "QGIS 無法建立漸層 renderer。")
        layer.setRenderer(renderer)
        self._refresh_style(layer)
        return {
            "layer_id": layer.id(),
            "field_name": field_name,
            "classes": len(renderer.ranges()),
            "mode": mode_name,
            "color_ramp": color_ramp_name,
        }

    def op_apply_rgb_field_style(self, params):
        """保留現有 renderer，對每個 symbol layer 套用 RGB data-defined property。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        red_field = require_string(params, "red_field")
        green_field = require_string(params, "green_field")
        blue_field = require_string(params, "blue_field")
        self._require_fields(layer, [red_field, green_field, blue_field])
        expression = self._rgb_expression(red_field, green_field, blue_field)
        changed_symbol_layers = self._apply_rgb_expression(layer, expression)
        return {
            "layer_id": layer.id(),
            "red_field": red_field,
            "green_field": green_field,
            "blue_field": blue_field,
            "expression": expression,
            "changed_symbol_layers": changed_symbol_layers,
        }

    def op_preview_color_mapping(self, params):
        """解析色碼表並比較圖層分類值，不寫入任何欄位。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        category_field = require_string(params, "category_field")
        mapping_path = input_file_path(require_string(params, "mapping_path"), {".csv", ".json"})
        mapping_key_field = require_string(params, "mapping_key_field")
        self._require_fields(layer, [category_field])
        mapping = self._load_color_mapping(mapping_path, mapping_key_field)
        return self._color_mapping_summary(layer, category_field, mapping, mapping_path)

    def op_apply_color_mapping(self, params):
        """經 GUI 確認後新增/更新 R、G、B 欄位並套用 data-defined 色彩。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        category_field = require_string(params, "category_field")
        mapping_path = input_file_path(require_string(params, "mapping_path"), {".csv", ".json"})
        mapping_key_field = require_string(params, "mapping_key_field")
        red_field = require_string(params, "red_field")
        green_field = require_string(params, "green_field")
        blue_field = require_string(params, "blue_field")
        self._require_fields(layer, [category_field])
        mapping = self._load_color_mapping(mapping_path, mapping_key_field)
        summary = self._color_mapping_summary(layer, category_field, mapping, mapping_path)
        self.confirmation.require(
            "寫入 R、G、B 色碼欄位",
            "即將依使用者色碼表更新原始圖層欄位並套用樣式。",
            "圖層：{}\n分類欄位：{}\n色碼檔：{}\n匹配分類：{}\n未匹配分類：{}\n目標欄位：{}, {}, {}".format(
                layer.name(),
                category_field,
                mapping_path,
                summary["matched_category_count"],
                summary["unmatched_category_count"],
                red_field,
                green_field,
                blue_field,
            ),
        )
        started_here = self._begin_edit(layer, "QGIS MCP 套用色碼表")
        updated = 0
        unmatched_features = 0
        try:
            self._ensure_integer_fields(layer, [red_field, green_field, blue_field])
            field_indices = [layer.fields().indexOf(name) for name in [red_field, green_field, blue_field]]
            category_index = layer.fields().indexOf(category_field)
            for feature in layer.getFeatures():
                key = self._mapping_key(feature.attribute(category_index))
                color = mapping.get(key)
                if color is None:
                    unmatched_features += 1
                    continue
                for field_index, component in zip(field_indices, color, strict=True):
                    if not layer.changeAttributeValue(feature.id(), field_index, component):
                        raise BridgeError(
                            "PROCESSING_FAILED",
                            "寫入 RGB 欄位失敗。",
                            {"feature_id": feature.id(), "field_index": field_index},
                        )
                updated += 1
            self._finish_edit(layer, started_here)
        except Exception:
            self._abort_edit(layer, started_here)
            raise
        expression = self._rgb_expression(red_field, green_field, blue_field)
        changed_symbol_layers = self._apply_rgb_expression(layer, expression)
        return {
            **summary,
            "updated_feature_count": updated,
            "unmatched_feature_count": unmatched_features,
            "changed_symbol_layers": changed_symbol_layers,
            "red_field": red_field,
            "green_field": green_field,
            "blue_field": blue_field,
        }

    def op_import_qml_style(self, params):
        """載入本機 QML 並在成功後刷新圖層與圖例。"""
        layer = self.layer(require_string(params, "layer_id"))
        qml_path = input_file_path(require_string(params, "qml_path"), {".qml"})
        message, success = layer.loadNamedStyle(str(qml_path))
        if not success:
            raise BridgeError("PROCESSING_FAILED", "QML 樣式載入失敗。", {"message": message})
        self._refresh_style(layer)
        return {"layer_id": layer.id(), "qml_path": str(qml_path), "message": message}

    def op_export_qml_style(self, params):
        """匯出 QML；既有檔案需真人確認。"""
        layer = self.layer(require_string(params, "layer_id"))
        output_path = absolute_output_path(require_string(params, "output_path"), {".qml"})
        self.confirm_overwrite(output_path, "覆寫 QML 樣式檔")
        message, success = layer.saveNamedStyle(str(output_path))
        if not success:
            raise BridgeError("PROCESSING_FAILED", "QML 樣式匯出失敗。", {"message": message})
        return {"layer_id": layer.id(), "output_path": str(output_path), "message": message}

    def _apply_rgb_expression(self, layer, expression):
        """把同一 RGB expression 套到 renderer 所有符號的填色與線色 property。"""
        renderer = layer.renderer()
        if renderer is None:
            raise BridgeError("PROCESSING_FAILED", "圖層沒有可用 renderer。")
        symbols = renderer.symbols(QgsRenderContext())
        if not symbols:
            default_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            if default_symbol is None:
                raise BridgeError("PROCESSING_FAILED", "無法建立可套用 RGB 的符號。")
            renderer = QgsSingleSymbolRenderer(default_symbol)
            layer.setRenderer(renderer)
            symbols = [default_symbol]
        color_property = QgsProperty.fromExpression(expression)
        changed = 0
        for symbol in symbols:
            for symbol_layer in symbol.symbolLayers():
                symbol_layer.setDataDefinedProperty(QgsSymbolLayer.Property.FillColor, color_property)
                symbol_layer.setDataDefinedProperty(QgsSymbolLayer.Property.StrokeColor, color_property)
                changed += 1
        self._refresh_style(layer)
        return changed

    @staticmethod
    def _rgb_expression(red_field, green_field, blue_field):
        """以 QGIS 欄位 quoting 建立安全的 color_rgb expression。"""
        red_column = QgsExpression.quotedColumnRef(red_field)
        green_column = QgsExpression.quotedColumnRef(green_field)
        blue_column = QgsExpression.quotedColumnRef(blue_field)
        return f"color_rgb({red_column}, {green_column}, {blue_column})"

    @staticmethod
    def _validated_color(value, parameter_name):
        """只接受可由 QColor 完整解析的顏色字串。"""
        color = QColor(value)
        if not color.isValid():
            raise BridgeError("INVALID_PARAMETERS", f"{parameter_name} 不是有效顏色：{value}")
        return color

    @staticmethod
    def _symbol_summary(symbol):
        """回傳符號色彩、透明度與 layer 數量。"""
        if symbol is None:
            return None
        name_format = getattr(QColor, "NameFormat", QColor)
        return {
            "color": symbol.color().name(name_format.HexArgb),
            "opacity": symbol.opacity(),
            "symbol_layer_count": symbol.symbolLayerCount(),
        }

    def _refresh_style(self, layer):
        """刷新 renderer 與圖層樹圖例。"""
        layer.triggerRepaint()
        self.iface.layerTreeView().refreshLayerSymbology(layer.id())
        self.iface.mapCanvas().refresh()

    @staticmethod
    def _require_fields(layer, field_names):
        """在任何寫入前一次列出所有缺少欄位。"""
        missing = [name for name in field_names if layer.fields().indexOf(name) < 0]
        if missing:
            raise BridgeError("INVALID_PARAMETERS", "圖層缺少必要欄位。", {"missing": missing})

    @staticmethod
    def _mapping_key(value):
        """以去除首尾空白的字串統一 CSV/JSON 與圖層分類鍵。"""
        return "" if value is None else str(value).strip()

    def _load_color_mapping(self, path, key_field):
        """解析 CSV/JSON、驗證唯一鍵與 0–255 RGB。"""
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as input_file:
                records = list(csv.DictReader(input_file))
        else:
            raw_data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(raw_data, list):
                records = raw_data
            elif isinstance(raw_data, dict):
                if all(isinstance(value, dict) for value in raw_data.values()):
                    records = [{key_field: key, **value} for key, value in raw_data.items()]
                else:
                    raise BridgeError("INVALID_PARAMETERS", "JSON 色碼表 object 的每個值都必須是 object。")
            else:
                raise BridgeError("INVALID_PARAMETERS", "JSON 色碼表必須是 array 或 object。")
        if not records:
            raise BridgeError("INVALID_PARAMETERS", "色碼表沒有資料列。")
        mapping = {}
        for row_index, record in enumerate(records, start=1):
            if not isinstance(record, dict) or key_field not in record:
                raise BridgeError(
                    "INVALID_PARAMETERS",
                    f"色碼表缺少鍵欄位：{key_field}",
                    {"row": row_index},
                )
            component_fields = {str(name).casefold(): name for name in record}
            missing_components = [name for name in ["r", "g", "b"] if name not in component_fields]
            if missing_components:
                raise BridgeError(
                    "INVALID_PARAMETERS",
                    "色碼表必須包含 R、G、B 欄位。",
                    {"row": row_index, "missing": missing_components},
                )
            key = self._mapping_key(record[key_field])
            if not key:
                raise BridgeError("INVALID_PARAMETERS", "色碼表分類鍵不可為空。", {"row": row_index})
            if key in mapping:
                raise BridgeError("INVALID_PARAMETERS", "色碼表分類鍵重複。", {"key": key})
            components = []
            for component in ["r", "g", "b"]:
                raw_value = record[component_fields[component]]
                try:
                    numeric = int(raw_value)
                except (TypeError, ValueError) as error:
                    raise BridgeError(
                        "INVALID_PARAMETERS",
                        "RGB 必須是整數。",
                        {"row": row_index, "component": component, "value": raw_value},
                    ) from error
                if not 0 <= numeric <= 255:
                    raise BridgeError(
                        "INVALID_PARAMETERS",
                        "RGB 必須介於 0 與 255。",
                        {"row": row_index, "component": component, "value": numeric},
                    )
                components.append(numeric)
            mapping[key] = tuple(components)
        return mapping

    def _color_mapping_summary(self, layer, category_field, mapping, mapping_path):
        """比較唯一分類值，回傳有限未匹配樣本而非整份大量清單。"""
        category_index = layer.fields().indexOf(category_field)
        category_values = {
            self._mapping_key(feature.attribute(category_index)) for feature in layer.getFeatures()
        }
        matched = sorted(value for value in category_values if value in mapping)
        unmatched = sorted(value for value in category_values if value not in mapping)
        unused = sorted(value for value in mapping if value not in category_values)
        return {
            "layer_id": layer.id(),
            "mapping_path": str(mapping_path),
            "mapping_entry_count": len(mapping),
            "layer_category_count": len(category_values),
            "matched_category_count": len(matched),
            "unmatched_category_count": len(unmatched),
            "unused_mapping_count": len(unused),
            "unmatched_sample": unmatched[:100],
            "unused_mapping_sample": unused[:100],
            "samples_truncated": len(unmatched) > 100 or len(unused) > 100,
        }

    @staticmethod
    def _ensure_integer_fields(layer, field_names):
        """在目前 edit session 中補上缺少的 RGB 整數欄位。"""
        meta_types = getattr(QMetaType, "Type", QMetaType)
        integer_type = meta_types.Int
        for field_name in field_names:
            if layer.fields().indexOf(field_name) < 0 and not layer.addAttribute(
                QgsField(field_name, integer_type)
            ):
                raise BridgeError("PROCESSING_FAILED", f"無法新增 RGB 欄位：{field_name}")
        layer.updateFields()
