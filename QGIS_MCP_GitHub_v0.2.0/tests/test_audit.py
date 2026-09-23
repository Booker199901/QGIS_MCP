"""驗證操作稽核只記錄有限目標欄位與保存期限。"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from qgis_mcp.audit import AuditLogger


def test_audit_omits_attributes_expressions_and_tokens(tmp_path: Path) -> None:
    """完整屬性、Expression 與 token 不得進入一般稽核日誌。"""
    audit = AuditLogger(tmp_path, 14)
    audit.record(
        operation_id="operation-1",
        instance_id="instance-1",
        action="query_features",
        status="completed",
        duration_ms=12,
        params={
            "layer_id": "layer-1",
            "expression": '"secret_field" = 123',
            "attributes": {"private": "value"},
            "token": "never-log-this",
        },
    )
    event = json.loads(audit.log_path.read_text(encoding="utf-8").strip())
    serialized = json.dumps(event)
    assert event["targets"] == {"layer_id": "layer-1"}
    assert "secret_field" not in serialized
    assert "never-log-this" not in serialized


def test_audit_removes_expired_daily_file(tmp_path: Path) -> None:
    """持續使用時也會依日期移除超過保存天數的舊檔。"""
    old_day = date.today() - timedelta(days=30)
    old_path = tmp_path / f"operations-{old_day.isoformat()}.jsonl"
    old_path.write_text("{}\n", encoding="utf-8")
    audit = AuditLogger(tmp_path, 14)
    audit.record(
        operation_id="operation-2",
        instance_id="server",
        action="list_qgis_instances",
        status="completed",
        duration_ms=0,
    )
    assert not old_path.exists()
    assert audit.log_path.exists()
