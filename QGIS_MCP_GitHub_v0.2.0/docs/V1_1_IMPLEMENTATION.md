# QGIS MCP V1.1 第一批實作報告

狀態：本機遙測影像分析已實作並完成自動驗證  
版本：0.2.0  
日期：2026-09-14

## 已完成能力

- `get_raster_info`：回傳本機 Raster 的 driver、尺寸、CRS、extent、geotransform，以及各 band 的資料型別、NoData、scale、offset、名稱與 metadata。
- `prepare_raster`：依參考 Raster 的 CRS、原點、解析度和尺寸建立精確對齊的 COG；可使用參考 CRS 的 bbox 裁切。
- `reproject_raster`：以明確目標 CRS、解析度、bbox、重採樣和 NoData 建立 COG。
- `calculate_ndvi`：支援相同或不同圖層的明確 Red／NIR band、反射率／metadata／explicit 校正模式，以及明確品質遮罩有效值。
- `analyze_raster_colors`：以有限抽樣回傳有效像元比例、基本統計、分位數與直方圖，並標明結果是原始 band 值。
- `apply_raster_style`：支援 RGB、灰階，以及值域明確且不可重疊的手動單波段色階。
- `run_zonal_statistics`：以多邊形和完整 Raster 像元計算指定統計，原子輸出 GeoPackage。
- `convert_raster_format`：輸出 COG 或 tiled GeoTIFF，支援明確壓縮與 block size。

所有檔案型分析成果均附加 `<output>.manifest.json`，記錄來源圖層、路徑、driver、網格、CRS、參數、GDAL 與 Bridge 版本。Manifest 不包含 Raster 像元、向量圖徵或連線秘密。

## 正確性與安全邊界

- NDVI 使用分塊 Float64 中間計算及 Float32 輸出；Red／NIR 任一 NoData、mask 無效、非有限值或分母為零時輸出 NoData。
- 不猜測 band 或校正。來源未宣告 scale／offset 時，`metadata` 模式回傳 `CALIBRATION_REQUIRED`；explicit 值與來源 metadata 不同時回傳 `CALIBRATION_CONFLICT`。
- 跨圖層像元運算會比較 CRS、width、height 與完整 geotransform；不一致時回傳 `RASTER_ALIGNMENT_REQUIRED`。
- 連續影像的前處理預設 bilinear；分類或品質遮罩應明確選擇 nearest。NoData 未完整宣告時，前處理和重投影要求呼叫者明確指定。
- GDAL 工作只在背景執行緒使用已驗證的本機路徑和純資料參數；QGIS 圖層的讀取、樣式與加入專案仍在主執行緒完成。
- 新 Raster 工作與 Processing 共用單一實例佇列。取消請求先回報 `cancelling`，實際停止後才回報 `cancelled`。
- Raster 和 GPKG 先寫至目標資料夾內的唯一暫存路徑，完成並重新開啟驗證後才原子替換；既有輸出仍須 QGIS GUI 真人確認。

## 自動驗證

| 層級 | 驗證內容 |
|---|---|
| Python tests | 18 項通過；包含 58 個 MCP tools 與 NDVI schema 契約。 |
| Ruff／compileall | 通過。 |
| QGIS 3.44.13／Qt5 | 完整 Raster smoke test 通過。 |
| QGIS 4.2.1／Qt6 | 完整 Raster smoke test 通過。 |

真實 QGIS smoke test 使用 2×2 Float32 GeoTIFF，驗證 NIR=0.6、Red=0.2 的 NDVI 為 0.5，並涵蓋 NoData、品質遮罩、網格對齊、EPSG:3857 重投影、手動色階、COG、manifest 和多邊形分區統計。

## 已知限制

- 第一批只支援已載入 QGIS 且 GDAL 可由本機檔案路徑開啟的 Raster；WMS、雲端 URI、虛擬 Raster 子資料集與記憶體 Raster 不在此批專用工具範圍。
- 品質遮罩由呼叫者提供圖層、band 與有效值；尚未自動解析 Sentinel-2 SCL 或 Landsat QA bit flags。
- 不自動判斷影像是否為 TOA／BOA、處理基線、sensor 或季節，也不提供跨日期變遷判讀。
- `analyze_raster_colors` 是有限均勻抽樣；正式區域統計由 `run_zonal_statistics` 處理完整像元。
- DEM／GRD 地形分析、完整向量座標工具與圖面配置留待 V1.1 後續批次；圖片自動對位仍屬 V1.2。
