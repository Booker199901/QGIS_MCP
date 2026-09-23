"""允許使用 python -m qgis_mcp 啟動伺服器。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
