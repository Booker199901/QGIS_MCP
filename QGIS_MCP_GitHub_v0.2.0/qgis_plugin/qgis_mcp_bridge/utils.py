"""QGIS Bridge 各操作共用的驗證與 JSON 序列化工具。"""

import math
import re
from pathlib import Path

from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle
from qgis.PyQt.QtCore import QDate, QDateTime, QTime

from .errors import BridgeError

SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|token|api[_-]?key|access[_-]?token|authcfg)\s*=\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^&\s;|]+)"
)
BEARER_PATTERN = re.compile(r"(?i)(\bauthorization\s*:\s*bearer\s+)\S+")


def json_safe(value, depth=0):
    """把常見 QGIS/Qt/Python 值轉為有限深度的 JSON 相容資料。"""
    if depth > 10:
        return "<maximum depth reached>"
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (QDate, QTime, QDateTime)):
        return value.toString("yyyy-MM-ddTHH:mm:ss.zzz")
    if isinstance(value, QgsRectangle):
        return rectangle_dict(value)
    if isinstance(value, QgsCoordinateReferenceSystem):
        return crs_dict(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item, depth + 1) for item in value]
    try:
        return int(value)  # QGIS/Qt IntEnum 優先保留穩定的數值。
    except (TypeError, ValueError, OverflowError):
        return str(value)


def redact_sensitive_text(value):
    """移除常見連線字串與 HTTP 認證秘密，保留診斷所需欄位名稱。"""
    text = str(value)
    text = SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1[REDACTED]", text)
    return BEARER_PATTERN.sub(r"\1[REDACTED]", text)


def redact_sensitive_value(value, depth=0):
    """遞迴去敏 Processing 結果／錯誤，不改一般工具的完整圖徵回傳。"""
    if depth > 10:
        return "<maximum depth reached>"
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {
            str(key): redact_sensitive_value(item, depth + 1)
            for key, item in value.items()
            if str(key).casefold()
            not in {"password", "passwd", "pwd", "token", "api_key", "apikey", "access_token"}
        }
    if isinstance(value, (list, tuple, set)):
        return [redact_sensitive_value(item, depth + 1) for item in value]
    return json_safe(value, depth)


def rectangle_dict(rectangle):
    """以固定欄位回傳 bbox，避免列表順序產生誤解。"""
    if rectangle is None or rectangle.isNull():
        return None
    return {
        "xmin": rectangle.xMinimum(),
        "ymin": rectangle.yMinimum(),
        "xmax": rectangle.xMaximum(),
        "ymax": rectangle.yMaximum(),
    }


def crs_dict(crs):
    """回傳 CRS 的權威 ID、名稱與有效性。"""
    return {
        "authid": crs.authid() if crs else "",
        "description": crs.description() if crs else "",
        "is_valid": bool(crs and crs.isValid()),
        "is_geographic": bool(crs and crs.isGeographic()),
    }


def require_string(params, name, allow_empty=False):
    """取得字串參數並限制空值。"""
    value = params.get(name)
    if not isinstance(value, str):
        raise BridgeError("INVALID_PARAMETERS", f"{name} 必須是字串。", {"parameter": name})
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise BridgeError("INVALID_PARAMETERS", f"{name} 不可為空。", {"parameter": name})
    return normalized


def require_bool(params, name, default=False):
    """取得嚴格布林值，避免字串 'false' 被 Python 視為 True。"""
    value = params.get(name, default)
    if not isinstance(value, bool):
        raise BridgeError("INVALID_PARAMETERS", f"{name} 必須是布林值。", {"parameter": name})
    return value


def require_int(params, name, default=None, minimum=None, maximum=None):
    """取得受範圍限制且拒絕 bool 的整數。"""
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BridgeError("INVALID_PARAMETERS", f"{name} 必須是整數。", {"parameter": name})
    if minimum is not None and value < minimum:
        raise BridgeError("INVALID_PARAMETERS", f"{name} 不可小於 {minimum}。")
    if maximum is not None and value > maximum:
        raise BridgeError("INVALID_PARAMETERS", f"{name} 不可大於 {maximum}。")
    return value


def require_float(params, name, default=None, minimum=None, maximum=None):
    """取得有限且受範圍限制的數值。"""
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BridgeError("INVALID_PARAMETERS", f"{name} 必須是數值。", {"parameter": name})
    normalized = float(value)
    if not math.isfinite(normalized):
        raise BridgeError("INVALID_PARAMETERS", f"{name} 必須是有限數值。")
    if minimum is not None and normalized < minimum:
        raise BridgeError("INVALID_PARAMETERS", f"{name} 不可小於 {minimum}。")
    if maximum is not None and normalized > maximum:
        raise BridgeError("INVALID_PARAMETERS", f"{name} 不可大於 {maximum}。")
    return normalized


def require_bbox(value):
    """驗證 [xmin, ymin, xmax, ymax] 且最小值確實小於最大值。"""
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise BridgeError("INVALID_PARAMETERS", "bbox 必須是四個數值的列表。")
    coordinates = []
    for coordinate in value:
        if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
            raise BridgeError("INVALID_PARAMETERS", "bbox 每個值都必須是數值。")
        numeric = float(coordinate)
        if not math.isfinite(numeric):
            raise BridgeError("INVALID_PARAMETERS", "bbox 不可包含無限值或 NaN。")
        coordinates.append(numeric)
    if coordinates[0] >= coordinates[2] or coordinates[1] >= coordinates[3]:
        raise BridgeError("INVALID_PARAMETERS", "bbox 必須滿足 xmin < xmax 且 ymin < ymax。")
    return QgsRectangle(*coordinates)


def absolute_output_path(path_value, allowed_suffixes=None):
    """要求完整輸出路徑、現有父資料夾與允許的副檔名。"""
    if not isinstance(path_value, str) or not path_value.strip():
        raise BridgeError("INVALID_PARAMETERS", "output_path 不可為空。")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise BridgeError("INVALID_PARAMETERS", "output_path 必須是完整絕對路徑。")
    resolved = path.resolve(strict=False)
    if allowed_suffixes and resolved.suffix.lower() not in {suffix.lower() for suffix in allowed_suffixes}:
        raise BridgeError(
            "UNSUPPORTED_FORMAT",
            f"不支援輸出副檔名：{resolved.suffix}",
            {"allowed_suffixes": sorted(allowed_suffixes)},
        )
    if not resolved.parent.is_dir():
        raise BridgeError(
            "FILE_ACCESS_DENIED",
            "輸出資料夾不存在。",
            {"parent": str(resolved.parent)},
        )
    return resolved


def input_file_path(path_value, allowed_suffixes=None):
    """驗證使用者指定的本機輸入檔案，避免默默猜測或使用目錄。"""
    if not isinstance(path_value, str) or not path_value.strip():
        raise BridgeError("INVALID_PARAMETERS", "輸入路徑不可為空。")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        raise BridgeError("INVALID_PARAMETERS", "輸入路徑必須是完整絕對路徑。")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise BridgeError("FILE_ACCESS_DENIED", "指定輸入不是檔案。", {"path": str(resolved)})
    if allowed_suffixes and resolved.suffix.lower() not in {suffix.lower() for suffix in allowed_suffixes}:
        raise BridgeError(
            "UNSUPPORTED_FORMAT",
            f"不支援輸入副檔名：{resolved.suffix}",
            {"allowed_suffixes": sorted(allowed_suffixes)},
        )
    return resolved


def vector_driver_for_path(path):
    """由副檔名選擇明確的 OGR driver，避免依賴全域預設值。"""
    drivers = {
        ".shp": "ESRI Shapefile",
        ".gpkg": "GPKG",
        ".geojson": "GeoJSON",
        ".json": "GeoJSON",
    }
    driver = drivers.get(path.suffix.lower())
    if driver is None:
        raise BridgeError("UNSUPPORTED_FORMAT", f"不支援的向量輸出格式：{path.suffix}")
    return driver


def enum_int(value):
    """安全取得 SIP enum 的整數值，Qt5 與 Qt6 都可用。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value.value
