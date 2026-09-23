"""QGIS MCP Server 的命令列入口。"""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import sys
from collections.abc import Sequence

import uvicorn

from .audit import AuditLogger
from .config import ServerSettings
from .errors import QgisMcpError
from .http_auth import BearerTokenMiddleware
from .registry import InstanceRegistry
from .server import create_server


def _build_parser() -> argparse.ArgumentParser:
    """建立清楚且不把秘密放進命令列參數的 CLI。"""
    parser = argparse.ArgumentParser(description="控制已開啟 QGIS Desktop 的標準 MCP Server。")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("stdio", help="以 stdio 執行；這是本機 MCP Client 的預設模式。")
    subparsers.add_parser("http", help="以 localhost Streamable HTTP 執行；token 由環境變數提供。")
    subparsers.add_parser("doctor", help="檢查設定並列出可用 QGIS 實例。")
    subparsers.add_parser("generate-token", help="產生可放入 QGIS_MCP_HTTP_TOKEN 的隨機 token。")
    subparsers.add_parser("clear-logs", help="清除 QGIS MCP Server 自己的本機稽核日誌。")
    return parser


def _configure_logging() -> None:
    """將日誌送到 stderr，避免破壞 stdio MCP 的 stdout JSON-RPC。"""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _run_doctor(settings: ServerSettings) -> int:
    """執行不修改任何外部狀態的本機診斷。"""
    registry = InstanceRegistry(settings.registry_dir, settings.registry_ttl_seconds)
    instances = [
        record.public_dict(online=online) for record, online in registry.list_records(include_offline=True)
    ]
    report = {
        "registry_dir": str(settings.registry_dir),
        "registry_exists": settings.registry_dir.exists(),
        "instances": instances,
        "online_count": sum(1 for instance in instances if instance["online"]),
        "audit_log_dir": str(settings.log_dir),
        "log_retention_days": settings.log_retention_days,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """解析執行模式並啟動 stdio、HTTP 或診斷流程。"""
    _configure_logging()
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    command = args.command or "stdio"  # 未指定子命令時採最相容且不開 port 的 stdio。

    if command == "generate-token":
        print(secrets.token_urlsafe(48))  # 只在使用者明確要求時輸出新 token。
        return 0

    try:
        settings = ServerSettings.from_env()
        if command == "clear-logs":
            audit = AuditLogger(settings.log_dir, settings.log_retention_days)
            removed = audit.clear()
            print(json.dumps({"removed": removed, "log_path": str(audit.log_path)}, ensure_ascii=False))
            return 0
        if command == "doctor":
            return _run_doctor(settings)
        mcp = create_server(settings)
        if command == "stdio":
            mcp.run()  # 官方 SDK 預設使用 stdio，stdout 只會包含 MCP 訊息。
            return 0
        if command == "http":
            if settings.http_token is None:
                raise QgisMcpError(
                    "INVALID_CONFIGURATION",
                    "HTTP 模式必須設定至少 32 字元的 QGIS_MCP_HTTP_TOKEN。",
                )
            mcp_app = mcp.streamable_http_app()
            authenticated_app = BearerTokenMiddleware(mcp_app, settings.http_token)
            uvicorn.run(
                authenticated_app,
                host=settings.http_host,
                port=settings.http_port,
                log_level="info",
            )
            return 0
        parser.error(f"未知命令：{command}")
    except QgisMcpError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
