# QGIS MCP

QGIS MCP 是供應商中立的本機 MCP Server，讓支援標準 MCP 的 AI Client 控制使用者已開啟且可見的 QGIS Desktop。V1.1 第一批提供 58 個工具，除原有向量、Processing、樣式與畫布能力外，新增本機 Raster 檢查、網格對齊、重投影、NDVI、抽樣統計、Raster 樣式、分區統計與 COG 輸出。

目前版本：`0.2.0`（V1.1 本機遙測影像分析）  
正式測試：Windows 11、QGIS 3.44.13、QGIS 4.2.1  
授權：GPL-2.0-or-later

本儲存庫保存原始碼、測試與文件。可安裝的 Plugin ZIP、Windows Server ZIP 與 SHA-256 檔案應作為 GitHub Release 附件發布，請勿直接提交到原始碼庫。發布步驟見 [GitHub 上傳與發行說明](docs/GITHUB_PUBLISHING.md)，版本變更見 [CHANGELOG.md](CHANGELOG.md)。

## 系統組成

1. `QGIS MCP Bridge` 外掛在 QGIS 主執行緒操作目前專案，並顯示危險操作確認視窗。
2. `qgis-mcp` 本機 Server 向任何標準 MCP Client 提供 `stdio` 或帶驗證的 Streamable HTTP。
3. 每次 QGIS 外掛啟動會產生新的 `instance_id` 與高熵 Bridge token。Client 只能看到 `instance_id`，不會取得 token。

自然語言理解由使用者選擇的 AI Client 負責；本專案只執行 schema 明確的工具，不提供任意 Python、PyQGIS、Shell 或系統命令。

## 快速安裝

### 1. 安裝 QGIS 外掛

使用發行產物 `qgis_mcp_bridge-0.2.0.zip`：

1. 開啟 QGIS。
2. 選擇「附加元件 → 管理與安裝附加元件 → 從 ZIP 安裝」。
3. 選取 ZIP 並啟用 `QGIS MCP Bridge`。
4. 從 QGIS 的 `QGIS MCP` 選單開啟狀態視窗，確認 Bridge 正在執行。

QGIS 3.44 與 4.2 需分別安裝／啟用此外掛。每個開啟的 QGIS 視窗會有不同 `instance_id`。

### 2. 安裝 MCP Server

一般 Windows 使用者可解壓縮 `qgis-mcp-server-windows-x64-0.2.0.zip`，直接使用其中的 `qgis-mcp-0.2.0.exe`，不需另外安裝 Python。

目前候選版尚未使用商業 code-signing 憑證簽章，Windows SmartScreen 可能顯示未知發行者；請先用同目錄 `.sha256` 核對下載檔，再決定是否執行。

開發環境也可使用：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\qgis-mcp.exe doctor
```

`doctor` 會顯示目前線上／離線實例與本機 registry、稽核日誌位置，但不顯示 Bridge token。

### 3. 設定標準 MCP Client

最常見的 `stdio` 設定如下；不同 Client 的外層設定名稱可能不同：

```json
{
  "mcpServers": {
    "qgis": {
      "command": "C:\\Tools\\qgis-mcp-server-windows-x64-0.2.0\\qgis-mcp-0.2.0.exe",
      "args": ["stdio"]
    }
  }
}
```

開發版可把 `command` 改為工作區內 `.venv\Scripts\qgis-mcp.exe`。完整範例位於 `examples`。

連線後先呼叫 `list_qgis_instances`，再把選定的 `instance_id` 明確傳給每個 QGIS 工具。系統不會自動猜測「目前作用中」或「最近使用」的 QGIS 視窗。

## Streamable HTTP

`stdio` 是預設且最簡單的模式。只有需要多個本機 Client 共用 Server 時才建議使用 HTTP：

```powershell
$env:QGIS_MCP_HTTP_TOKEN = & 'C:\Tools\qgis-mcp-server-windows-x64-0.2.0\qgis-mcp-0.2.0.exe' generate-token
& 'C:\Tools\qgis-mcp-server-windows-x64-0.2.0\qgis-mcp-0.2.0.exe' http
```

端點預設為 `http://127.0.0.1:8765/mcp`。Client 必須送出 `Authorization: Bearer <token>`。Server 只允許 loopback host；若請求帶有 `Origin`，也只接受 localhost／loopback Origin，並限制單次 request body 為 4 MiB。

可用環境變數：

| 名稱 | 預設 | 說明 |
|---|---:|---|
| `QGIS_MCP_HTTP_HOST` | `127.0.0.1` | 只允許 loopback |
| `QGIS_MCP_HTTP_PORT` | `8765` | 1024–65535 |
| `QGIS_MCP_HTTP_TOKEN` | 無 | HTTP 必填，至少 32 字元 |
| `QGIS_MCP_BRIDGE_TIMEOUT_SECONDS` | `300` | 含真人確認等待時間，1–600 秒 |
| `QGIS_MCP_REGISTRY_TTL_SECONDS` | `30` | 判定 QGIS 實例離線的 heartbeat 秒數 |
| `QGIS_MCP_REGISTRY_DIR` | `%LOCALAPPDATA%\QGISMCP\instances` | Server 與外掛必須一致 |
| `QGIS_MCP_LOG_DIR` | `%LOCALAPPDATA%\QGISMCP\logs` | 去敏稽核日誌位置 |
| `QGIS_MCP_LOG_RETENTION_DAYS` | `14` | 每日日誌保存 1–365 天 |

## 安全與確認

會覆寫／刪除檔案、儲存專案、移除圖層、批次更新欄位、寫入 RGB、刪除欄位、原地修復幾何，或無法可靠判斷副作用的 Processing 演算法，必須由使用者在 QGIS 視窗按下允許。AI／MCP Client 沒有核准工具，關閉或取消視窗一律回傳 `USER_DENIED`。

Processing 與 Raster 工作在同一 QGIS 實例中依序排隊，回傳 `job_id`，可用 `get_job_status`、`get_job_result`、`cancel_job` 查詢。取消請求會先顯示 `cancelling`，待工作實際停止後才顯示 `cancelled`。所有圖徵回應強制分頁，預設 100、單頁上限 1000；大結果應用 `export_feature_query` 輸出檔案。

稽核日誌只保存 operation ID、instance ID、工具、有限目標 ID、結果、耗時與錯誤碼，不保存完整屬性、幾何、Expression 或 token。可執行 `qgis-mcp clear-logs` 手動清除。

## 工具範圍

- 系統／專案：狀態、專案資訊、儲存、另存。
- 圖層：列出、資訊、新增、移除、可見性、排序、改名、匯出。
- 欄位／查詢：Expression 驗證、欄位新增／計算／刪除、選取、分頁完整屬性、WKT／GeoJSON、查詢匯出。
- Processing：列出 providers、搜尋、說明、執行所有已註冊演算法、工作狀態與取消。
- 樣式：單一、分類、分級、RGB 欄位驅動、CSV／JSON 色碼預覽與寫入、QML 匯入／匯出。
- 轉換／品質：CSV／JSON 座標轉向量、向量格式轉換、幾何有效性／封閉性／修復。
- 畫布：狀態、範圍、縮放、PNG 截圖。
- Raster：metadata、精確網格對齊、重投影、NDVI、抽樣統計、RGB／灰階／手動色階樣式、分區統計與 GeoTIFF／COG 轉換。

V1.1 第一批只處理已載入 QGIS 的本機 Raster。NDVI 必須明確指定 Red／NIR band 與校正模式；不同網格需先使用 `prepare_raster`，品質遮罩若缺少會回傳警告。DEM／GRD 地形分析、完整向量座標工具與圖面配置留在 V1.1 後續批次；自動圖片對位屬於 V1.2。

## 開發與驗證

```powershell
.\.venv\Scripts\ruff.exe check src qgis_plugin tests scripts
.\.venv\Scripts\pytest.exe -q
.\scripts\run_qgis_smoke.ps1
.\scripts\build_release.ps1
```

真實 QGIS smoke test 只建立記憶體圖層、小型測試 Raster 與暫存輸出，不讀寫使用者 GIS 資料。V1.1 實作摘要見 [docs/V1_1_IMPLEMENTATION.md](docs/V1_1_IMPLEMENTATION.md)，詳細矩陣、人工驗收與已知限制見 [docs/TESTING.md](docs/TESTING.md)，安全模型見 [docs/SECURITY.md](docs/SECURITY.md)，完整核准需求見 [DEVELOPMENT_REQUIREMENTS.md](DEVELOPMENT_REQUIREMENTS.md)。

## 疑難排解

- `instances` 為空：確認 QGIS 已開啟、外掛已啟用，且 QGIS 訊息日誌沒有 `QGIS MCP` 啟動錯誤。
- 實例突然離線：外掛 reload／QGIS 重啟後會產生新 `instance_id`，請重新呼叫 `list_qgis_instances`。
- `QGIS_INSTANCE_BUSY`：QGIS 正在等待確認或處理另一個同步命令，完成後再重試。
- `PROCESSING_ALGORITHM_NOT_FOUND`：先用 `list_processing_providers` 和 `search_processing_algorithms` 確認該 QGIS 實例確實載入 provider。
- HTTP 401／403：確認 Bearer token 相同，且 Browser 型 Client 的 Origin 是 localhost。
- Windows 顯示未知發行者：目前候選版尚未 code-sign；先核對 SHA-256，不要略過來源不明檔案的警告。
- 稽核日誌不包含底層 traceback；非預期 Bridge 錯誤請同時查看 QGIS「訊息日誌 → QGIS MCP」。
