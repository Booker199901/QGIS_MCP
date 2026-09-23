"""驗證多 QGIS 實例 registry 的 schema、TTL 與 token 隱藏。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from qgis_mcp.errors import InstanceNotFoundError
from qgis_mcp.registry import InstanceRegistry


def _write_record(path: Path, instance_id: str, heartbeat_at: datetime) -> None:
    """寫入符合 Bridge API v1 的測試登錄資料。"""
    payload = {
        "api_version": 1,
        "instance_id": instance_id,
        "pid": 1234,
        "host": "127.0.0.1",
        "port": 23456,
        "token": "x" * 48,
        "qgis_version": "3.44.13",
        "plugin_version": "0.1.0",
        "project_name": "Test",
        "project_path": "C:/data/test.qgz",
        "locale": "zh_TW",
        "started_at": (heartbeat_at - timedelta(seconds=1)).isoformat(),
        "heartbeat_at": heartbeat_at.isoformat(),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_registry_lists_online_instance_without_exposing_token(tmp_path: Path) -> None:
    """有效 heartbeat 應被列出，但 public_dict 不得包含 token 或 port。"""
    instance_id = "instance-1234"
    _write_record(tmp_path / f"{instance_id}.json", instance_id, datetime.now(timezone.utc))
    registry = InstanceRegistry(tmp_path, ttl_seconds=30)
    records = registry.list_records()
    assert len(records) == 1
    public = records[0][0].public_dict(online=records[0][1])
    assert public["instance_id"] == instance_id
    assert "token" not in public
    assert "port" not in public


def test_registry_rejects_stale_instance(tmp_path: Path) -> None:
    """超過 TTL 的登錄不得被任何操作解析成線上實例。"""
    instance_id = "instance-stale"
    _write_record(
        tmp_path / f"{instance_id}.json",
        instance_id,
        datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    registry = InstanceRegistry(tmp_path, ttl_seconds=30)
    assert registry.list_records() == []
    with pytest.raises(InstanceNotFoundError):
        registry.get_online(instance_id)


def test_registry_ignores_mismatched_filename(tmp_path: Path) -> None:
    """檔名與內容 instance_id 不一致時不可被接受。"""
    _write_record(tmp_path / "wrong-name.json", "actual-instance", datetime.now(timezone.utc))
    registry = InstanceRegistry(tmp_path, ttl_seconds=30)
    assert registry.list_records(include_offline=True) == []
