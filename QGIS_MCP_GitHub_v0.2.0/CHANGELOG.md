# 版本紀錄

## 0.2.0（V1.1 第一批）

- 提供 58 個 MCP 工具，新增本機 Raster metadata、網格對齊、重投影、NDVI、抽樣統計、樣式、分區統計與 COG 輸出。
- 維持 QGIS 視窗內的危險操作確認、逐一指定 `instance_id`、本機連線驗證與去敏稽核日誌。
- Windows 11 上已對 QGIS 3.44.13 與 4.2.1 執行專案所列驗證；範圍與限制見 [測試與驗收](docs/TESTING.md)。

## 0.1.0（V1）

- 建立 QGIS Bridge 外掛與標準 MCP Server，支援 `stdio` 和本機 Streamable HTTP。
- 提供向量、Processing、樣式、畫布及基本專案操作；詳見 [V1 實作報告](docs/V1_IMPLEMENTATION.md)。
