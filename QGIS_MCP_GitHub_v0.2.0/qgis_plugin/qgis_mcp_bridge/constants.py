"""QGIS Bridge 外掛的集中常數。"""

PLUGIN_VERSION = "0.2.0"  # 與 metadata.txt 及外部 MCP Server 同步。
BRIDGE_API_VERSION = 1  # 本機 JSON Bridge 協定主要版本。
MAX_REQUEST_BYTES = 4 * 1024 * 1024  # 拒絕超過 4 MiB 的單一 HTTP 請求。
MAX_HEADER_BYTES = 64 * 1024  # HTTP header 硬上限，防止記憶體濫用。
HEARTBEAT_INTERVAL_MS = 5_000  # 每五秒刷新一次實例 heartbeat。
JOB_RETENTION_SECONDS = 3_600  # 已完成工作保留一小時供 MCP Client 重新查詢。
REQUEST_REPLAY_TTL_SECONDS = 600  # 近期 request_id 十分鐘內不得重複執行。
MAX_RECENT_REQUEST_IDS = 2048  # 限制 replay cache 記憶體占用。
DEFAULT_PAGE_SIZE = 100  # 圖徵查詢的預設分頁大小。
MAX_PAGE_SIZE = 1000  # 圖徵回應的硬上限。
