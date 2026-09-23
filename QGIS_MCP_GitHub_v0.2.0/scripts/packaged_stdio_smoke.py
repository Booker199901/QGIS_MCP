"""以官方 MCP Client 對 PyInstaller Windows 執行檔做 stdio 協定驗證。"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # 從腳本位置解析，避免依賴 shell cwd。
INPUT_DIR = PROJECT_ROOT / "build" / "release" / "windows" / "qgis-mcp-0.2.0"
OUTPUT_DIR = PROJECT_ROOT / "build" / "release" / "test-reports"
SERVER_EXE = INPUT_DIR / "qgis-mcp-0.2.0.exe"
REPORT_PATH = OUTPUT_DIR / "packaged-stdio.json"


async def run_smoke() -> dict:
    """初始化正式 stdio session、列出工具並呼叫安全的實例列舉。"""
    if not SERVER_EXE.is_file():
        raise FileNotFoundError(f"找不到 Windows bundle 執行檔：{SERVER_EXE}")
    parameters = StdioServerParameters(
        command=str(SERVER_EXE),
        args=["stdio"],
        cwd=str(PROJECT_ROOT),
    )
    async with stdio_client(parameters) as streams, ClientSession(*streams) as session:
        initialize_result = await session.initialize()
        tools_result = await session.list_tools()
        instances_result = await session.call_tool("list_qgis_instances", {"include_offline": False})
    tool_names = sorted(tool.name for tool in tools_result.tools)
    structured = instances_result.structured_content
    return {
        "server_name": initialize_result.server_info.name,
        "server_version": initialize_result.server_info.version,
        "tool_count": len(tool_names),
        "required_tools_present": all(
            name in tool_names
            for name in [
                "list_qgis_instances",
                "calculate_field",
                "run_processing_algorithm",
                "apply_color_mapping",
                "calculate_ndvi",
                "run_zonal_statistics",
            ]
        ),
        "list_instances_success": bool(structured and structured.get("success")),
        "success": len(tool_names) >= 58
        and bool(structured and structured.get("success"))
        and instances_result.is_error is False,
    }


def main() -> int:
    """保存正式 bundle smoke report，供發行稽核重現。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = anyio.run(run_smoke)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(REPORT_PATH), **report}, ensure_ascii=True))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
