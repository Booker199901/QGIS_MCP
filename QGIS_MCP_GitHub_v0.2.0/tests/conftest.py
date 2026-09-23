"""測試共用路徑設定。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # 以測試檔位置穩定解析專案根目錄。
PLUGIN_ROOT = PROJECT_ROOT / "qgis_plugin"  # 讓不依賴 QGIS 的外掛純函式可單獨測試。
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
