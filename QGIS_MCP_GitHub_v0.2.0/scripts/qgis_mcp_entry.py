"""供 Windows PyInstaller 建立不依賴系統 Python 的入口。"""

from qgis_mcp.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
