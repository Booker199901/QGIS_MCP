"""以不包含圖徵內容或權杖的 JSON Lines 保存本機操作稽核紀錄。"""

from __future__ import annotations

import json
from contextlib import suppress
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    """集中寫入有限欄位，避免一般 application log 意外記錄敏感參數。"""

    _TARGET_KEYS = (
        "layer_id",
        "job_id",
        "algorithm_id",
        "field_name",
        "output_path",
        "input_path",
    )

    def __init__(self, log_dir: Path, retention_days: int) -> None:
        self._log_dir = log_dir
        self._retention_days = retention_days
        self._log_path = self._today_log_path()
        self._prepared = False

    @property
    def log_path(self) -> Path:
        """提供 doctor 與清理命令顯示實際日誌路徑。"""
        return self._log_path

    def record(
        self,
        *,
        operation_id: str,
        instance_id: str,
        action: str,
        status: str,
        duration_ms: int,
        params: dict[str, Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        """只保存允許清單中的目標識別欄位與結果，不保存 expression 或 attributes。"""
        try:
            self._prepare()
            self._log_path = self._today_log_path()
            targets = {
                key: self._safe_scalar((params or {}).get(key))
                for key in self._TARGET_KEYS
                if self._safe_scalar((params or {}).get(key)) is not None
            }
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "operation_id": str(operation_id),
                "instance_id": str(instance_id),
                "action": str(action),
                "targets": targets,
                "status": str(status),
                "duration_ms": max(0, int(duration_ms)),
                "error_code": str(error_code) if error_code else None,
            }
            with self._log_path.open("a", encoding="utf-8", newline="\n") as log_file:
                log_file.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            # 稽核磁碟故障不得使 QGIS 操作本身失敗，也不向 MCP 回傳本機目錄細節。
            return

    def clear(self) -> bool:
        """刪除本元件自己的精確日誌檔；不存在視為已清除。"""
        removed = False
        if self._log_dir.is_dir():
            for log_path in self._log_dir.glob("operations-????-??-??.jsonl"):
                if log_path.is_file() and log_path.parent == self._log_dir:
                    log_path.unlink()
                    removed = True
        self._prepared = False
        return removed

    def _prepare(self) -> None:
        """首次使用時建立私有目錄並依最後修改時間執行保存期限輪替。"""
        if self._prepared:
            return
        self._log_dir.mkdir(parents=True, exist_ok=True)
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=self._retention_days)
        for log_path in self._log_dir.glob("operations-????-??-??.jsonl"):
            with suppress(OSError, ValueError):
                log_date = date.fromisoformat(log_path.stem.removeprefix("operations-"))
                if log_date < cutoff and log_path.is_file() and log_path.parent == self._log_dir:
                    log_path.unlink()
        self._prepared = True

    def _today_log_path(self) -> Path:
        """每天獨立一檔，才能在持續使用時仍確實套用保存期限。"""
        day = datetime.now(timezone.utc).date().isoformat()
        return self._log_dir / f"operations-{day}.jsonl"

    @staticmethod
    def _safe_scalar(value: Any) -> str | int | float | bool | None:
        """只允許短純量；連線 URI、集合與任意物件一律不寫入。"""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str) and len(value) <= 1024:
            lowered = value.casefold()
            if any(secret_marker in lowered for secret_marker in ("password=", "token=", "authcfg=")):
                return "[REDACTED]"
            return value
        return None
