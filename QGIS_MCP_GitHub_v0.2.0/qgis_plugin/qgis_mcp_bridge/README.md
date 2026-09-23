# QGIS MCP Bridge

此外掛是 QGIS MCP 的桌面端元件。啟用後，它只在 `127.0.0.1` 隨機連接埠提供經 Bearer token 驗證的 Bridge API，並將不含對外網路能力的實例資訊寫入目前 Windows 使用者的 LocalAppData。

所有會覆寫、刪除或批次修改原始資料的操作，都必須由使用者在 QGIS 視窗中確認；MCP Client 無法代替使用者核准。

V1.1 可檢查與分析已載入的本機 Raster，包含網格對齊、重投影、NDVI、抽樣統計、Raster 樣式、分區統計與 COG。長時間 Raster 工作與 Processing 共用序列佇列及取消機制。

安裝方式請參考專案根目錄 README。不要單獨將此外掛暴露至區域網路或網際網路。
