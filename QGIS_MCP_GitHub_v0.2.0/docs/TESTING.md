# QGIS MCP V1.1 測試與驗收

## 自動化測試

開發環境執行：

```powershell
.\.venv\Scripts\ruff.exe check src qgis_plugin tests scripts
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\python.exe -m compileall -q src qgis_plugin scripts
.\scripts\run_qgis_smoke.ps1
.\scripts\run_qgis_gui_smoke.ps1
.\.venv\Scripts\python.exe scripts\packaged_stdio_smoke.py
.\.venv\Scripts\python.exe scripts\packaged_http_smoke.py
```

`pytest` 驗證設定安全邊界、registry schema／TTL、HTTP Bearer／Origin、MCP v2 工具發現與結構化回應、Processing 風險判斷及日誌去敏。

`run_qgis_smoke.ps1` 使用下列正式安裝：

| QGIS | Qt | Python | 安裝目錄 |
|---|---|---|---|
| 3.44.13 | Qt 5 | 3.12 | `C:\Program Files\QGIS 3.44.13` |
| 4.2.1 | Qt 6 | 3.12 | `C:\Program Files\QGIS 4.2.1` |

每套 runtime 都執行真實 PyQGIS：既有 V1 核心能力，以及 Raster metadata、NoData 抽樣統計、手動色階、精確網格對齊、重投影、品質遮罩 NDVI、COG 和分區統計。測試資料只存在記憶體或系統暫存目錄；已知像元 NIR=0.6、Red=0.2 的 NDVI 必須等於 0.5。

## 發行驗證

```powershell
.\scripts\build_release.ps1
```

需確認：

- Plugin ZIP 最上層為 `qgis_mcp_bridge`，包含 `metadata.txt`、`__init__.py`、`LICENSE`。
- Windows bundle 解壓後可執行 `qgis-mcp-0.2.0.exe doctor` 與 `generate-token`。
- 以標準 MCP stdio Client 啟動 bundle，可列出至少 58 個工具並呼叫 `list_qgis_instances`。
- Streamable HTTP 未帶 token 為 401、遠端 Origin 為 403、正確本機 Client 可初始化 MCP session。

## 人工 GUI 驗收

以下需在乾淨測試專案執行，不應使用唯一一份正式資料：

1. 同時開啟 QGIS 3.44 與 4.2，確認 `list_qgis_instances` 回傳不同 `instance_id`，並各自取得正確專案資訊。
2. 對測試 GPKG 執行欄位計算；拒絕一次確認並驗證資料未變，再允許並驗證筆數與 undo／commit 行為。
3. 以含法定分類鍵與 R/G/B 的 CSV／JSON 預覽匹配，確認未匹配摘要；允許寫入後驗證三欄與畫面色彩。
4. 搜尋、說明與執行 native、GDAL，以及至少一個已安裝第三方 provider 演算法；確認未知 provider 會提高風險。
5. 查詢超過 100 筆圖徵，驗證分頁與完整屬性；明確要求 GeoJSON geometry，確認未出現無限制回應。
6. 檢查含自相交面的測試圖層，驗證錯誤位置圖層；修復預設建立新圖層。
7. 以 CSV／JSON 明確指定 X、Y、來源 CRS，輸出 GPKG 與 SHP；驗證 SHP 限制警告。
8. 儲存、另存、移除圖層、覆寫輸出與取消確認，逐一確認目標路徑／圖層正確。
9. 建立兩筆耗時 Processing，確認第二筆排隊、狀態可查詢，並測試可取消與不可立即取消的真實回報。
10. 開啟兩個 MCP Client 嘗試同時操作，確認 modal 等待期間另一命令回傳 `QGIS_INSTANCE_BUSY`。
11. 對通用本機多波段或分波段影像執行 metadata 檢查；確認未宣告 scale／offset 時不會被標示為已校正。
12. 以不同原點或解析度影像測試 NDVI，確認系統回傳 `RASTER_ALIGNMENT_REQUIRED`；完成 `prepare_raster` 後再計算成功。
13. 使用明確反射率、metadata 與 explicit 三種校正模式；校正值衝突時確認回傳 `CALIBRATION_CONFLICT`。
14. 測試 NoData、分母為零與品質遮罩；確認無效像元維持 NoData，超出 -1 至 1 的有限值只警告而不截斷。
15. 對 NDVI 套用手動色階、執行分區統計並輸出 COG／GPKG／PNG；重新載入後核對 CRS、像元網格、統計欄位與 manifest。
16. 取消大型 Raster 工作及拒絕覆寫；確認狀態依序為 `cancelling`／`cancelled`，且不留下點號開頭的暫存成果。

## 目前已知限制

- V1.1 第一批已支援通用本機 Raster、NDVI 與分區統計；尚未解析 Sentinel-2／Landsat 產品結構或自動建立雲影遮罩。
- DEM／GRD 地形分析、完整向量座標工具與圖面配置仍屬 V1.1 後續批次。
- V1.2 自動圖片對位尚未實作。
- QGIS GUI 確認與不同資料 provider 的交易能力需要人工測試；記憶體圖層 smoke test 無法涵蓋所有 WFS、資料庫或第三方 provider 行為。
- QGIS 4.x 後續版本採回歸維護，不保證未測的新版本完全不需調整。
- Windows 候選版執行檔尚未使用商業 code-signing 憑證，SmartScreen 可能顯示未知發行者；應以 sidecar SHA-256 驗證產物。
