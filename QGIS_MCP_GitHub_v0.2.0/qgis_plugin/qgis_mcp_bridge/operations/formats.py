"""實作 CSV/JSON 座標檢查、點圖層建立與向量格式轉換。"""

import csv
import json
import math

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QMetaType

from ..errors import BridgeError
from ..utils import (
    absolute_output_path,
    input_file_path,
    json_safe,
    require_bool,
    require_int,
    require_string,
)


class FormatOperations:
    """將使用者明確指定座標與 CRS 的表格安全轉為向量資料。"""

    def op_inspect_tabular_coordinates(self, params):
        """回傳欄位、樣本與低信心 CRS 提示，不把推測當成來源 CRS。"""
        input_path = input_file_path(require_string(params, "input_path"), {".csv", ".json"})
        sample_size = require_int(params, "sample_size", 20, minimum=1, maximum=200)
        records = self._read_tabular_records(input_path)
        if not records:
            raise BridgeError("INVALID_PARAMETERS", "輸入檔沒有可用資料列。")
        field_names = self._ordered_field_names(records)
        coordinate_candidates = self._coordinate_candidates(records, field_names)
        samples = [
            {name: json_safe(record.get(name)) for name in field_names} for record in records[:sample_size]
        ]
        return {
            "input_path": str(input_path),
            "record_count": len(records),
            "fields": [
                {
                    "name": name,
                    "inferred_type": self._infer_field_kind([record.get(name) for record in records]),
                }
                for name in field_names
            ],
            "coordinate_candidates": coordinate_candidates,
            "samples": samples,
            "samples_truncated": len(records) > sample_size,
            "crs_warning": "CRS 只可由使用者明確指定；候選值不是自動判定結果。",
        }

    def op_table_to_vector(self, params):
        """將 CSV/JSON 每列明確 X/Y 建為點，並以使用者指定 CRS 匯出。"""
        input_path = input_file_path(require_string(params, "input_path"), {".csv", ".json"})
        output_path = absolute_output_path(
            require_string(params, "output_path"),
            {".shp", ".gpkg", ".geojson", ".json"},
        )
        x_field = require_string(params, "x_field")
        y_field = require_string(params, "y_field")
        source_crs_text = require_string(params, "source_crs")
        output_crs_text = require_string(params, "output_crs", allow_empty=True)
        add_to_project = require_bool(params, "add_to_project", True)
        source_crs = QgsCoordinateReferenceSystem(source_crs_text)
        if not source_crs.isValid():
            raise BridgeError("CRS_REQUIRED", f"無效來源 CRS：{source_crs_text}")
        if output_crs_text and not QgsCoordinateReferenceSystem(output_crs_text).isValid():
            raise BridgeError("INVALID_PARAMETERS", f"無效輸出 CRS：{output_crs_text}")
        records = self._read_tabular_records(input_path)
        if not records:
            raise BridgeError("INVALID_PARAMETERS", "輸入檔沒有可用資料列。")
        field_names = self._ordered_field_names(records)
        missing_fields = [name for name in [x_field, y_field] if name not in field_names]
        if missing_fields:
            raise BridgeError("INVALID_PARAMETERS", "找不到座標欄位。", {"missing": missing_fields})
        self.confirm_overwrite(output_path, "覆寫向量轉換輸出")
        memory_layer = QgsVectorLayer(f"Point?crs={source_crs.authid()}", input_path.stem, "memory")
        if not memory_layer.isValid():
            raise BridgeError("PROCESSING_FAILED", "無法建立暫存點圖層。")
        qgis_fields = [
            self._field_for_values(name, [record.get(name) for record in records]) for name in field_names
        ]
        if not memory_layer.dataProvider().addAttributes(qgis_fields):
            raise BridgeError("PROCESSING_FAILED", "無法建立輸出欄位。")
        memory_layer.updateFields()
        features = []
        invalid_rows = []
        for row_number, record in enumerate(records, start=1):
            try:
                x_value = float(record.get(x_field))
                y_value = float(record.get(y_field))
                if not math.isfinite(x_value) or not math.isfinite(y_value):
                    raise ValueError("coordinate is not finite")
            except (TypeError, ValueError):
                if len(invalid_rows) < 100:
                    invalid_rows.append(row_number)
                continue
            feature = QgsFeature(memory_layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x_value, y_value)))
            feature.setAttributes(
                [
                    self._convert_attribute(record.get(name), field)
                    for name, field in zip(field_names, qgis_fields, strict=True)
                ]
            )
            features.append(feature)
        if not features:
            raise BridgeError("INVALID_PARAMETERS", "所有資料列的 X/Y 座標皆無效。")
        if not memory_layer.dataProvider().addFeatures(features)[0]:
            raise BridgeError("PROCESSING_FAILED", "將點圖徵加入暫存圖層時失敗。")
        export_result = self._export_vector_layer(
            memory_layer,
            output_path,
            output_crs_text,
            False,
            add_to_project,
        )
        warnings = []
        if output_path.suffix.lower() == ".shp":
            warnings.append("Shapefile 可能截短欄位名稱，且欄位型別與文字編碼能力有限。")
        if invalid_rows:
            warnings.append("部分資料列因座標無效而略過；invalid_row_sample 最多回傳 100 筆。")
        return {
            **export_result,
            "source_record_count": len(records),
            "created_feature_count": len(features),
            "invalid_row_count": len(records) - len(features),
            "invalid_row_sample": invalid_rows,
            "warnings": warnings,
            "source_crs": source_crs.authid() or source_crs_text,
            "output_crs": output_crs_text or source_crs.authid(),
        }

    def op_convert_vector_format(self, params):
        """重用同一安全 writer 將現有向量圖層轉檔與可選重投影。"""
        layer = self.layer(require_string(params, "layer_id"), vector=True)
        output_path = absolute_output_path(
            require_string(params, "output_path"),
            {".shp", ".gpkg", ".geojson", ".json"},
        )
        output_crs = require_string(params, "output_crs", allow_empty=True)
        only_selected = require_bool(params, "only_selected", False)
        add_to_project = require_bool(params, "add_to_project", True)
        self.confirm_overwrite(output_path, "覆寫向量格式轉換輸出")
        result = self._export_vector_layer(layer, output_path, output_crs, only_selected, add_to_project)
        result["only_selected"] = only_selected
        if output_path.suffix.lower() == ".shp":
            result["warnings"] = ["Shapefile 可能截短欄位名稱，且欄位型別與文字編碼能力有限。"]
        return result

    @staticmethod
    def _read_tabular_records(path):
        """以 deterministic 欄位順序讀取 CSV 或常見 JSON records 結構。"""
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as input_file:
                return [dict(row) for row in csv.DictReader(input_file)]
        raw_data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(raw_data, list):
            records = raw_data
        elif isinstance(raw_data, dict) and isinstance(raw_data.get("records"), list):
            records = raw_data["records"]
        elif isinstance(raw_data, dict) and raw_data.get("type") == "FeatureCollection":
            records = []
            for feature in raw_data.get("features", []):
                if not isinstance(feature, dict):
                    continue
                record = dict(feature.get("properties") or {})
                geometry = feature.get("geometry") or {}
                coordinates = geometry.get("coordinates")
                if (
                    geometry.get("type") == "Point"
                    and isinstance(coordinates, list)
                    and len(coordinates) >= 2
                ):
                    record.setdefault("x", coordinates[0])
                    record.setdefault("y", coordinates[1])
                records.append(record)
        else:
            raise BridgeError("INVALID_PARAMETERS", "JSON 必須是 array、records array 或 FeatureCollection。")
        if any(not isinstance(record, dict) for record in records):
            raise BridgeError("INVALID_PARAMETERS", "每個 JSON 資料列都必須是 object。")
        return [dict(record) for record in records]

    @staticmethod
    def _ordered_field_names(records):
        """依首次出現順序蒐集欄位，讓重複執行結果一致。"""
        names = []
        seen = set()
        for record in records:
            for name in record:
                normalized = str(name)
                if normalized not in seen:
                    seen.add(normalized)
                    names.append(normalized)
        return names

    @staticmethod
    def _infer_field_kind(values):
        """忽略空值後判斷 integer、double、boolean 或 string。"""
        non_empty = [value for value in values if value is not None and value != ""]
        if not non_empty:
            return "string"
        lowered = {str(value).strip().casefold() for value in non_empty}
        if lowered <= {"true", "false", "0", "1"}:
            return "boolean"
        try:
            if all(float(value).is_integer() for value in non_empty):
                return "int64"
            if all(math.isfinite(float(value)) for value in non_empty):
                return "double"
        except (TypeError, ValueError, OverflowError):
            pass
        return "string"

    def _field_for_values(self, name, values):
        """將推定型別轉為 QMetaType，保留原始欄位名稱。"""
        meta_types = getattr(QMetaType, "Type", QMetaType)
        kind = self._infer_field_kind(values)
        type_map = {
            "string": meta_types.QString,
            "int64": meta_types.LongLong,
            "double": meta_types.Double,
            "boolean": meta_types.Bool,
        }
        return QgsField(name, type_map[kind])

    @staticmethod
    def _convert_attribute(value, field):
        """依欄位 typeName 做保守轉換；失敗時留字串交給 provider 驗證。"""
        if value is None or value == "":
            return None
        type_name = field.typeName().casefold()
        try:
            if "int" in type_name:
                return int(value)
            if "double" in type_name or "real" in type_name or "float" in type_name:
                return float(value)
            if "bool" in type_name:
                return str(value).strip().casefold() in {"true", "1"}
        except (TypeError, ValueError):
            return str(value)
        return str(value) if not isinstance(value, (str, int, float, bool)) else value

    def _coordinate_candidates(self, records, field_names):
        """依欄位名稱與數值範圍提出候選，但明確標示低信心。"""
        normalized_names = {name.casefold(): name for name in field_names}
        name_pairs = [
            ("x", "y"),
            ("lon", "lat"),
            ("lng", "lat"),
            ("longitude", "latitude"),
            ("easting", "northing"),
        ]
        candidates = []
        for x_name, y_name in name_pairs:
            if x_name not in normalized_names or y_name not in normalized_names:
                continue
            actual_x = normalized_names[x_name]
            actual_y = normalized_names[y_name]
            numeric_pairs = []
            for record in records[:1000]:
                try:
                    numeric_pairs.append((float(record.get(actual_x)), float(record.get(actual_y))))
                except (TypeError, ValueError):
                    continue
            geographic_range = bool(numeric_pairs) and all(
                -180 <= x_value <= 180 and -90 <= y_value <= 90 for x_value, y_value in numeric_pairs
            )
            candidates.append(
                {
                    "x_field": actual_x,
                    "y_field": actual_y,
                    "numeric_sample_count": len(numeric_pairs),
                    "possible_crs": "EPSG:4326" if geographic_range else None,
                    "confidence": "low",
                    "requires_user_confirmation": True,
                }
            )
        return candidates
