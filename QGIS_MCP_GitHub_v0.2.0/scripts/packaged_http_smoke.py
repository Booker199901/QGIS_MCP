"""驗證 Windows bundle 的 Bearer／Origin 與 Streamable HTTP MCP session。"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
from pathlib import Path

import anyio
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # 由腳本位置解析，不依賴 shell cwd。
INPUT_DIR = PROJECT_ROOT / "build" / "release" / "windows" / "qgis-mcp-0.2.0"
OUTPUT_DIR = PROJECT_ROOT / "build" / "release" / "test-reports"
SERVER_EXE = INPUT_DIR / "qgis-mcp-0.2.0.exe"
REPORT_PATH = OUTPUT_DIR / "packaged-http.json"
HTTP_PORT = 18765  # 使用非預設測試 port，避免影響使用者可能執行中的正式 Server。
HTTP_TOKEN = secrets.token_urlsafe(48)  # 每次測試產生新 token，原始碼不保存憑證。
HTTP_URL = f"http://127.0.0.1:{HTTP_PORT}/mcp"


async def _wait_until_listening(process: subprocess.Popen) -> None:
    """等待認證 middleware 回應 401，證明正式 exe 已完成監聽。"""
    async with httpx2.AsyncClient(timeout=1, trust_env=False) as client:
        for _attempt in range(100):
            if process.poll() is not None:
                raise RuntimeError("Packaged HTTP server exited before listening")
            try:
                response = await client.post(HTTP_URL, json={})
                if response.status_code == 401:
                    return
            except httpx2.HTTPError:
                pass
            await anyio.sleep(0.05)
    raise TimeoutError("Packaged HTTP server did not start within five seconds")


async def run_smoke() -> dict:
    """啟動隱藏子程序，驗證安全拒絕與完整 MCP 初始化。"""
    if not SERVER_EXE.is_file():
        raise FileNotFoundError(f"找不到 Windows bundle 執行檔：{SERVER_EXE}")
    child_env = os.environ.copy()
    child_env["QGIS_MCP_HTTP_PORT"] = str(HTTP_PORT)
    child_env["QGIS_MCP_HTTP_TOKEN"] = HTTP_TOKEN
    process = subprocess.Popen(
        [str(SERVER_EXE), "http"],
        cwd=str(PROJECT_ROOT),
        env=child_env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        await _wait_until_listening(process)
        async with httpx2.AsyncClient(timeout=5, trust_env=False) as unauthenticated_client:
            unauthorized = await unauthenticated_client.post(HTTP_URL, json={})
            remote_origin = await unauthenticated_client.post(
                HTTP_URL,
                json={},
                headers={
                    "Authorization": f"Bearer {HTTP_TOKEN}",
                    "Origin": "https://attacker.example",
                },
            )
        async with (
            httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {HTTP_TOKEN}"},
                timeout=10,
                trust_env=False,
            ) as authenticated_client,
            streamable_http_client(HTTP_URL, http_client=authenticated_client) as streams,
            ClientSession(*streams) as session,
        ):
            initialize_result = await session.initialize()
            tools_result = await session.list_tools()
        report = {
            "unauthorized_status": unauthorized.status_code,
            "remote_origin_status": remote_origin.status_code,
            "server_name": initialize_result.server_info.name,
            "server_version": initialize_result.server_info.version,
            "tool_count": len(tools_result.tools),
        }
        report["success"] = (
            report["unauthorized_status"] == 401
            and report["remote_origin_status"] == 403
            and report["server_name"] == "QGIS MCP"
            and report["tool_count"] >= 58
        )
        return report
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> int:
    """保存 HTTP bundle smoke report，並以 exit code 呈現結果。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report = anyio.run(run_smoke)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(REPORT_PATH), **report}, ensure_ascii=True))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
