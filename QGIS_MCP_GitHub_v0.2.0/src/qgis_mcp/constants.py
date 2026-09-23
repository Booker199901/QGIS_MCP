"""集中管理 MCP Server 與 QGIS Bridge 共用的穩定常數。"""

PACKAGE_VERSION = "0.2.0"  # 對外發布的 MCP Server 與外掛版本。
BRIDGE_API_VERSION = 1  # 本機 Bridge JSON API 的主要相容版本。
DEFAULT_PAGE_SIZE = 100  # 圖徵查詢預設每頁筆數，避免耗盡模型上下文。
MAX_PAGE_SIZE = 1000  # 單次圖徵回應硬上限，防止意外傳回大量資料。
MAX_REQUEST_BYTES = 4 * 1024 * 1024  # Bridge 單一 JSON 請求上限為 4 MiB。
DEFAULT_BRIDGE_TIMEOUT_SECONDS = 300.0  # 為 QGIS GUI 真人確認保留五分鐘。
DEFAULT_REGISTRY_TTL_SECONDS = 30  # 實例登錄資料多久未更新即視為過期。
