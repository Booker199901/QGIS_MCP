"""以官方 MCP v2 in-memory Client 驗證工具發現與結構化回應。"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from qgis_mcp.config import ServerSettings
from qgis_mcp.server import create_server


def _settings(registry_dir: Path) -> ServerSettings:
    """建立不啟動 HTTP port 的測試設定。"""
    return ServerSettings(
        registry_dir=registry_dir,
        bridge_timeout_seconds=5.0,
        registry_ttl_seconds=30,
        http_host="127.0.0.1",
        http_port=8765,
        http_token=None,
        log_dir=registry_dir / "logs",
        log_retention_days=14,
    )


@pytest.mark.asyncio
async def test_server_advertises_core_v1_tools(tmp_path: Path) -> None:
    """核心 V1 工具名稱應能被任何標準 MCP Client 發現。"""
    server = create_server(_settings(tmp_path))
    async with Client(server) as client:
        tools_result = await client.list_tools()
    names = {tool.name for tool in tools_result.tools}
    expected = {
        "list_qgis_instances",
        "get_project_info",
        "calculate_field",
        "query_features",
        "run_processing_algorithm",
        "apply_color_mapping",
        "table_to_vector",
        "check_geometry_validity",
        "capture_canvas",
        "get_raster_info",
        "prepare_raster",
        "reproject_raster",
        "calculate_ndvi",
        "analyze_raster_colors",
        "apply_raster_style",
        "run_zonal_statistics",
        "convert_raster_format",
    }
    assert expected <= names
    assert len(names) >= 58


@pytest.mark.asyncio
async def test_ndvi_tool_exposes_explicit_calibration_and_mask_contract(tmp_path: Path) -> None:
    """NDVI schema 必須要求 band，並公開校正與品質遮罩參數。"""
    server = create_server(_settings(tmp_path))
    async with Client(server) as client:
        tools_result = await client.list_tools()
    ndvi_tool = next(tool for tool in tools_result.tools if tool.name == "calculate_ndvi")
    properties = ndvi_tool.input_schema["properties"]
    required = set(ndvi_tool.input_schema["required"])
    assert {"red_layer_id", "red_band", "nir_layer_id", "nir_band", "output_path"} <= required
    assert {
        "calibration_mode",
        "red_scale",
        "red_offset",
        "nir_scale",
        "nir_offset",
        "mask_layer_id",
        "mask_valid_values",
    } <= set(properties)


@pytest.mark.asyncio
async def test_list_instances_returns_structured_content(tmp_path: Path) -> None:
    """沒有 QGIS 開啟時仍應回傳成功的空列表，而不是 protocol error。"""
    server = create_server(_settings(tmp_path))
    async with Client(server) as client:
        result = await client.call_tool("list_qgis_instances", {"include_offline": False})
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["success"] is True
    assert result.structured_content["result"]["instances"] == []
