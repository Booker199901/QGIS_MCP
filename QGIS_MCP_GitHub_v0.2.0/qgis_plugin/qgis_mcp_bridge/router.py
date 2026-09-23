"""驗證 Bridge 命令並建立一致的 OperationResponse。"""

import re
import time
import uuid
from collections import OrderedDict

from qgis.core import Qgis, QgsMessageLog

from .constants import MAX_RECENT_REQUEST_IDS, REQUEST_REPLAY_TTL_SECONDS
from .errors import BridgeError
from .utils import json_safe, redact_sensitive_text, redact_sensitive_value

ACTION_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


class CommandRouter:
    """只允許 OperationHandler 明確公布的 action。"""

    def __init__(self, instance_id, operations):
        self._instance_id = instance_id
        self._operations = operations
        self._recent_requests = OrderedDict()

    def dispatch(self, payload):
        """驗證 envelope，執行 action 並把錯誤轉為安全回應。"""
        started = time.perf_counter()
        operation_id = str(uuid.uuid4())
        try:
            if not isinstance(payload, dict):
                raise BridgeError("INVALID_PARAMETERS", "Bridge request 必須是 JSON object。")
            request_id = payload.get("request_id")
            if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
                raise BridgeError("INVALID_PARAMETERS", "request_id 格式無效。")
            operation_id = request_id
            self._register_request(request_id)
            action = payload.get("action")
            if not isinstance(action, str) or not ACTION_PATTERN.fullmatch(action):
                raise BridgeError("INVALID_PARAMETERS", "action 格式無效。")
            params = payload.get("params", {})
            if not isinstance(params, dict):
                raise BridgeError("INVALID_PARAMETERS", "params 必須是 JSON object。")
            handler = self._operations.action_handler(action)
            if handler is None:
                raise BridgeError("INVALID_PARAMETERS", f"不支援的 Bridge action：{action}")
            result = handler(params)
            duration_ms = int((time.perf_counter() - started) * 1000)
            status = (
                "queued" if isinstance(result, dict) and result.get("status") == "queued" else "completed"
            )
            return self._response(
                True,
                operation_id,
                status,
                "操作已排入工作佇列。" if status == "queued" else "操作成功完成。",
                duration_ms,
                json_safe(result),
                None,
            )
        except BridgeError as error:
            duration_ms = int((time.perf_counter() - started) * 1000)
            safe_message = redact_sensitive_text(error.message)
            return self._response(
                False,
                operation_id,
                "failed",
                safe_message,
                duration_ms,
                None,
                {
                    "code": error.code,
                    "message": safe_message,
                    "details": redact_sensitive_value(error.details),
                },
            )
        except Exception as error:  # 非預期例外留在本機 QGIS log，MCP 只得到泛化錯誤。
            QgsMessageLog.logMessage(
                f"Bridge operation failed: {type(error).__name__}: {redact_sensitive_text(error)}",
                "QGIS MCP",
                Qgis.Critical,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            return self._response(
                False,
                operation_id,
                "failed",
                "QGIS Bridge 發生未預期錯誤，請查看 QGIS 訊息日誌。",
                duration_ms,
                None,
                {"code": "INTERNAL_ERROR", "message": "Internal bridge error", "details": {}},
            )

    def _register_request(self, request_id):
        """拒絕近期重複 ID，避免 Client 重放危險操作。"""
        now = time.monotonic()
        cutoff = now - REQUEST_REPLAY_TTL_SECONDS
        while self._recent_requests:
            _oldest_id, oldest_time = next(iter(self._recent_requests.items()))
            if oldest_time >= cutoff:
                break
            self._recent_requests.popitem(last=False)
        if request_id in self._recent_requests:
            raise BridgeError("REQUEST_REPLAYED", "相同 request_id 已處理，拒絕重複執行。")
        self._recent_requests[request_id] = now
        while len(self._recent_requests) > MAX_RECENT_REQUEST_IDS:
            self._recent_requests.popitem(last=False)

    def _response(self, success, operation_id, status, message, duration_ms, result, error):
        """建立與 DEVELOPMENT_REQUIREMENTS.md 一致的共通回應。"""
        return {
            "success": bool(success),
            "operation_id": operation_id,
            "instance_id": self._instance_id,
            "status": status,
            "message": message,
            "warnings": [],
            "duration_ms": duration_ms,
            "result": result,
            "error": error,
        }
