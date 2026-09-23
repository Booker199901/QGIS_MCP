# QGIS MCP V1 實作報告

狀態：V1 候選版已完成實作與自動化驗證，待需求方使用正式測試資料執行人工驗收。  
版本：0.1.0  
日期：2026-08-12

## 已完成範圍

- 採雙元件架構：QGIS Bridge Plugin + 供應商中立 Local MCP Server。
- 支援標準 MCP `stdio` 與帶 Bearer token 的本機 Streamable HTTP。
- 每次 QGIS 外掛啟動由外掛產生新的 `instance_id`；所有 QGIS 工具需明確指定實例。
- Bridge 僅綁定 `127.0.0.1` 隨機 port，高熵 token 不出現在 MCP 回應或一般日誌。
- 危險操作使用 QGIS modal GUI 真人確認，預設取消，MCP 無核准工具。
- 共 50 個 V1 MCP tools：專案、圖層、欄位／Expression、查詢／分頁、完整 Processing、工作狀態、樣式／RGB、格式轉換、幾何、畫布。
- 同一實例的 Processing 工作依序排隊；context／feedback／task 保留到工作紀錄過期，符合 QGIS Task 生命週期要求。
- 圖徵預設每頁 100、硬上限 1000；geometry 需明確指定，並提供大量查詢檔案匯出。
- HTTP Origin、request size、Bridge request replay、modal 重入、既有輸出與未知 provider 均有保守防護。
- 每日 JSON Lines 稽核日誌採允許清單欄位，完整 attributes、geometry、Expression、token 與 Processing 認證內容會省略或去敏。
- 已產生 QGIS Plugin ZIP、Python wheel 與不需要系統 Python 的 Windows x64 bundle。

## 自動化證據

| 層級 | 結果 |
|---|---|
| Ruff 靜態檢查 | 通過 |
| Python 單元／MCP in-memory tests | 17/17 通過 |
| Python compileall | 通過 |
| QGIS 3.44.13 真實 PyQGIS runtime | 通過 |
| QGIS 4.2.1 真實 PyQGIS runtime | 通過 |
| QGIS 3.44.13 完整 Plugin／真實 iface 生命週期 | 通過 |
| QGIS 4.2.1 完整 Plugin／真實 iface 生命週期 | 通過 |
| PyInstaller `.exe` doctor／token | 通過 |
| PyInstaller `.exe` 標準 MCP stdio session | 50 tools，通過 |
| PyInstaller `.exe` Streamable HTTP session | 50 tools，通過 |
| HTTP 未認證／遠端 Origin | 401／403，通過 |

真實 QGIS runtime 測試包含：Bridge Bearer 與 replay、秘密去敏、欄位列舉、Expression、欄位計算、分頁查詢、單一樣式、CSV 色碼寫入 R/G/B、幾何有效性，以及兩筆序列 `native:buffer`。測試只使用記憶體圖層與暫存輸出。

## 發行產物

- `build/release/qgis_mcp_bridge-0.1.0.zip`
- `build/release/qgis-mcp-server-windows-x64-0.1.0.zip`
- `build/release/python/qgis_mcp-0.1.0-py3-none-any.whl`
- 同目錄 `.sha256` sidecar（ZIP 產物）

## 尚需需求方人工驗收

- 在 QGIS 3.44／4.2 各使用一份可拋棄測試 GPKG，實際拒絕與允許欄位計算、RGB 寫入、專案保存、圖層移除與檔案覆寫。
- 使用實際 WMS／WFS、SHP、GeoPackage、GeoJSON、CSV 與第三方 Processing provider 驗證組織環境差異。
- 驗證各 AI／MCP Client 對長時間 GUI 確認的 timeout 行為；Server 預設 Bridge timeout 為五分鐘，但 Client 可能有自己的較短 timeout。
- 按 `docs/TESTING.md` 的 V1 人工 GUI 清單完成簽核。
- 候選版 Windows `.exe` 尚未 code-sign；正式對外散布前建議加入組織憑證簽章與 SmartScreen reputation 流程。

## 後續版本

- V1.1：Raster／DEM GRD、NDVI、專用 CRS 轉換與圖面配置／PNG。
- V1.2：本機共同點偵測、控制點 GUI 編修與 GeoTIFF 圖片對位。
