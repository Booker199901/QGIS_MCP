"""安全讀取由 QGIS Bridge Plugin 維護的本機實例登錄檔。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .constants import BRIDGE_API_VERSION
from .errors import InstanceNotFoundError, QgisMcpError
from .models import InstanceRecord


class InstanceRegistry:
    """提供多 QGIS 實例列舉與精確解析。"""

    def __init__(self, registry_dir: Path, ttl_seconds: int) -> None:
        self._registry_dir = registry_dir  # 保留集中設定的登錄路徑。
        self._ttl_seconds = ttl_seconds  # 使用 heartbeat 判斷殭屍登錄資料。

    def _is_online(self, record: InstanceRecord) -> bool:
        """以 UTC heartbeat 年齡判斷實例是否仍可能在線。"""
        heartbeat = record.heartbeat_at
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        age_seconds = (datetime.now(timezone.utc) - heartbeat.astimezone(timezone.utc)).total_seconds()
        return -5 <= age_seconds <= self._ttl_seconds

    def _load_file(self, path: Path) -> InstanceRecord | None:
        """讀取單一登錄檔；破損檔案被略過但不刪除使用者資料。"""
        try:
            raw_data = json.loads(path.read_text(encoding="utf-8"))
            record = InstanceRecord.model_validate(raw_data)
        except (OSError, json.JSONDecodeError, ValidationError):
            return None
        if record.api_version != BRIDGE_API_VERSION:
            return None
        if path.stem != record.instance_id:
            return None
        return record

    def list_records(self, *, include_offline: bool = False) -> list[tuple[InstanceRecord, bool]]:
        """以 instance_id 穩定排序回傳有效的 QGIS 實例。"""
        if not self._registry_dir.exists():
            return []
        records: list[tuple[InstanceRecord, bool]] = []
        for path in sorted(self._registry_dir.glob("*.json")):
            record = self._load_file(path)
            if record is None:
                continue
            online = self._is_online(record)
            if online or include_offline:
                records.append((record, online))
        return sorted(records, key=lambda item: item[0].instance_id)

    def get_online(self, instance_id: str) -> InstanceRecord:
        """取得明確指定且 heartbeat 有效的實例，絕不退回最近使用實例。"""
        if not instance_id or not all(
            character.isalnum() or character in {"-", "_"} for character in instance_id
        ):
            raise QgisMcpError("INVALID_PARAMETERS", "instance_id 格式無效。")
        candidate = self._registry_dir / f"{instance_id}.json"
        try:
            resolved_candidate = candidate.resolve()
        except OSError as exc:
            raise InstanceNotFoundError(instance_id) from exc
        if resolved_candidate.parent != self._registry_dir.resolve():
            raise QgisMcpError("INVALID_PARAMETERS", "instance_id 不可指向登錄資料夾外部。")
        if not resolved_candidate.is_file():
            raise InstanceNotFoundError(instance_id)
        record = self._load_file(resolved_candidate)
        if record is None or not self._is_online(record):
            raise InstanceNotFoundError(instance_id)
        return record
