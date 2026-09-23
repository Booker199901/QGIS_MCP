"""驗證 Processing 與輸出檔的保守風險分類。"""

from __future__ import annotations

from qgis_mcp_bridge.risk import processing_requires_confirmation


def test_new_native_output_does_not_require_confirmation(tmp_path) -> None:
    """已知 provider 建立全新輸出時不需多餘確認。"""
    output_path = tmp_path / "new.gpkg"
    required, reason = processing_requires_confirmation(
        "native:buffer",
        {"INPUT": "layer-id", "OUTPUT": str(output_path)},
        {"OUTPUT"},
    )
    assert required is False
    assert reason == "new_output"


def test_existing_output_requires_confirmation(tmp_path) -> None:
    """任何既有輸出路徑都必須確認。"""
    output_path = tmp_path / "existing.gpkg"
    output_path.write_bytes(b"existing")
    required, reason = processing_requires_confirmation(
        "native:buffer",
        {"INPUT": "layer-id", "OUTPUT": str(output_path)},
        {"OUTPUT"},
    )
    assert required is True
    assert reason == "output_exists"


def test_unknown_provider_requires_confirmation() -> None:
    """無法可靠判斷副作用的第三方 provider 採高風險處理。"""
    required, reason = processing_requires_confirmation(
        "thirdparty:custom",
        {"INPUT": "layer-id", "OUTPUT": "TEMPORARY_OUTPUT"},
        {"OUTPUT"},
    )
    assert required is True
    assert reason == "unknown_provider"
