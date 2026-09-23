# QGIS MCP 開發需求規格書

> 文件狀態：需求已核准；V1 已實作，V1.1 第一批本機遙測影像分析已完成自動驗證  
> 目標平台：Windows 11  
> QGIS 正式測試版本：3.44 LTR、4.2  
> 文件日期：2026-08-12

## 1. 文件目的

本文件定義 QGIS MCP 的產品範圍、系統架構、功能需求、安全規則、分階段交付內容與驗收標準。需求獲得確認前，不進入程式實作。

## 2. 產品目標

建立一套不綁定特定 AI 供應商、相容標準 MCP Client 的本機整合系統，讓 AI 能以結構化 MCP 工具控制使用者已開啟且可見的 QGIS Desktop，進行圖層管理、空間分析、欄位計算、樣式調整、資料轉換、影像分析、圖面配置與自動圖片對位。

自然語言理解由 MCP Client 所使用的 AI 模型負責；QGIS MCP 負責提供定義明確、可驗證、可追蹤且具安全確認機制的結構化操作工具。

## 3. 目標使用者與使用情境

### 3.1 目標使用者

- 使用 QGIS Desktop 的都市計畫、國土規劃、測量、環境、工程與 GIS 分析人員。
- 使用不同 AI 系統或標準 MCP Client，希望以自然語言操作 QGIS 的使用者。
- 需要保留人工確認、可追蹤操作紀錄與原始資料安全性的專業使用者。

### 3.2 核心使用情境

- 使用 QGIS Expression 計算或批次更新欄位。
- 依使用者提供的都市計畫或國土計畫色碼表，寫入 R、G、B 欄位並產生分類樣式。
- 執行 Clip、Buffer、Intersection 等 QGIS Processing 演算法。
- 進行 NDVI、Raster 色彩、DEM 坡度、坡向與陰影分析。
- 進行 CRS 設定、座標轉換、Raster 重投影與圖片自動對位。
- 依屬性值、Expression、地圖範圍或空間關係搜尋及選取圖徵。
- 建立或套用圖面配置樣板，調整圖例、比例尺、指北針等項目並輸出 PNG。
- 檢查幾何有效性、封閉性、自相交或其他幾何問題，建立錯誤結果並選擇性修復。
- 將含座標的 JSON、CSV 等結構化資料轉為 SHP 或 GeoPackage。
- 讀取 DEM GRD 網格資料並轉換或分析。

## 4. 範圍與限制

### 4.1 納入範圍

- Windows 11。
- 使用者已開啟、具有可見 GUI 的 QGIS Desktop。
- QGIS 3.44 LTR 與 QGIS 4.2 的正式相容測試。
- 後續 QGIS 4.x 版本提供持續相容性維護，但不預先保證尚未發布版本零修改即可使用。
- MCP `stdio` 與本機 Streamable HTTP 傳輸。
- SHP、GeoPackage、GeoJSON、CSV、WMS、WFS、常見 Raster，以及可由 QGIS/GDAL 辨識的 DEM GRD。
- 對 QGIS 專案及資料的完整控制，但危險操作受確認機制保護。
- 執行目前 QGIS 實例中所有已註冊的 Processing 演算法與提供者。

### 4.2 第一階段不納入範圍

- Headless QGIS、QGIS Server 或遠端主機控制。
- macOS、Linux。
- 內建臺灣法定分區色碼資料庫；色碼由使用者以 CSV 或 JSON 提供。
- 直接讓 AI 執行任意 Python、PyQGIS、Shell 或系統命令。
- 遙測、雲端資料上傳或將圖層內容傳送至第三方服務。
- PDF、JPEG、SVG 或 Atlas 批次出圖；初始配置輸出格式為 PNG。
- 保證所有影像皆可成功自動對位；低信心或特徵不足時必須明確失敗並改由人工處理。

## 5. 系統架構

系統採雙元件架構：

1. **QGIS Bridge Plugin**
   - 安裝並執行於 QGIS Desktop。
   - 取得 QGIS 專案、圖層、Processing、樣式、Raster、配置與畫布 API。
   - 將需要 QGIS 主執行緒的操作安全派送到主執行緒。
   - 顯示危險操作確認視窗、工作進度、取消控制與自動對位控制點檢視。

2. **Local MCP Server**
   - 對 MCP Client 提供標準 MCP Tools，並可選擇性提供 Resources。
   - 支援 `stdio` 及僅限本機的 Streamable HTTP。
   - 驗證所有工具參數，管理 QGIS 實例、工作佇列、結果分頁及錯誤格式。
   - 不直接操作 QGIS 專案檔，而是透過已驗證的本機 Bridge 通訊。

### 5.1 QGIS 實例管理

- 每個開啟且已啟用外掛的 QGIS 實例產生唯一 `instance_id`。
- MCP 可列出所有可用實例及其 QGIS 版本、程序 ID、專案名稱、專案路徑與目前狀態。
- 除列出實例的工具外，所有 QGIS 操作必須明確帶入 `instance_id`。
- 不以「最近使用視窗」作為隱性目標，避免改錯專案。
- 同一實例的修改型工作必須依序執行；唯讀工作可在確認執行緒安全後並行。
- 實例離線或重新啟動後，舊的 `instance_id` 不得自動指向另一個實例。

### 5.2 本機通訊安全

- Bridge 與 HTTP 服務僅綁定 loopback，不監聽外部網路介面。
- 每次啟動產生高熵連線權杖；不得將權杖寫入一般日誌或 MCP 回應。
- Streamable HTTP 驗證 Origin、Content-Type、協定版本與請求大小。
- Bridge 僅接受符合 schema、已認證且來自本機的命令。
- 所有檔案路徑必須正規化，並在覆寫前顯示完整目標路徑供使用者確認。

## 6. MCP 設計原則

- 主要能力以 Tools 提供，以相容未完整支援 MCP Resources、Tasks 或互動擴充的 Client。
- 工具名稱與參數保持供應商中立，不包含特定 AI 品牌概念。
- 每個工具使用 JSON Schema 定義必填欄位、型別、列舉、範圍與互斥條件。
- 工具說明必須清楚標示是否為唯讀、建立新產物、修改現有資料或可能覆寫資料。
- 對長時間工作回傳 `job_id`，搭配工作狀態與取消工具，不只依賴 MCP Tasks 擴充。
- 不提供任意程式碼執行工具。
- 通用 Processing 工具可執行所有已安裝演算法，但仍需完整參數驗證、安全分類與確認。

## 7. 共通回應格式

所有工具至少回傳：

- `success`：是否成功。
- `operation_id`：單次操作追蹤識別碼。
- `instance_id`：目標 QGIS 實例。
- `status`：`completed`、`queued`、`running`、`cancelled`、`failed`、`confirmation_required`。
- `message`：適合使用者閱讀的繁體中文或英文訊息。
- `warnings`：非致命警告陣列。
- `duration_ms`：已完成工作耗時。
- `result`：工具專屬結構化結果。
- `error`：失敗時包含穩定錯誤碼、摘要、可採取的修正建議及安全的技術細節。

圖層產出結果應盡可能包含：

- 圖層 ID、名稱、類型、資料來源、CRS。
- 圖徵數或 Raster 尺寸、波段數。
- 範圍、欄位摘要。
- 輸出檔案路徑及是否已加入專案。

## 8. 工作與取消機制

- 可能耗時的 Processing、Raster、幾何檢查、轉換、配置輸出與對位工作採非同步工作模式。
- `start_*` 或通用執行工具可回傳 `job_id`。
- 提供 `get_job_status`、`get_job_result`、`cancel_job`。
- 工作狀態至少包含排隊、執行中、等待確認、完成、失敗、取消中與已取消。
- 狀態包含 0–100 進度（若底層演算法可提供）、目前階段與可讀訊息。
- 對不支援安全取消的底層演算法，必須回報「無法立即取消」，不得假裝已取消。
- MCP Client 中斷連線不應自動終止已開始的 QGIS 工作；結果可用 `job_id` 重新查詢。

## 9. 功能需求

### 9.1 系統與專案

建議工具：

- `list_qgis_instances`
- `get_qgis_status`
- `get_project_info`
- `save_project`
- `save_project_as`

需求：

- 取得 QGIS、Qt、Python、GDAL、外掛及 MCP Bridge 版本。
- 取得專案名稱、路徑、CRS、圖層數、是否有未儲存變更。
- 支援儲存及另存專案。
- 覆寫既有專案檔必須確認。
- 尚未命名的專案執行儲存時必須提供路徑，不允許猜測路徑。

### 9.2 圖層管理

建議工具：

- `list_layers`
- `get_layer_info`
- `add_layer`
- `remove_layer`
- `set_layer_visibility`
- `reorder_layers`
- `rename_layer`
- `export_layer`

需求：

- 支援向量、Raster、WMS、WFS 與 QGIS 可辨識的資料來源。
- 圖層操作一律使用穩定的 `layer_id`，名稱只作顯示或搜尋用途。
- 同名圖層存在時不得自行猜測。
- 移除圖層、覆寫匯出檔案需確認。
- WMS/WFS 連線錯誤不得包含明文憑證。

### 9.3 欄位與 QGIS Expression

建議工具：

- `list_fields`
- `validate_expression`
- `add_fields`
- `calculate_field`
- `delete_fields`

需求：

- 支援 QGIS Expression 的語法預檢、參照欄位解析及錯誤位置回報。
- 計算前回報目標圖徵數、目標欄位、欄位型別及是否會覆寫現值。
- 批次更新原始圖層必須確認。
- 使用資料提供者的交易或編輯緩衝機制；失敗時應盡可能回復完整操作。
- 回傳更新、略過及失敗筆數與代表性錯誤，不回傳無上限錯誤清單。

### 9.4 搜尋、選取與完整屬性

建議工具：

- `select_features`
- `clear_selection`
- `get_selected_features`
- `query_features`
- `zoom_to_features`

需求：

- 支援 QGIS Expression、欄位條件、地圖範圍、輸入 bbox、距離與空間謂詞。
- 支援取代、加入、移除與交集等選取模式。
- 完整圖徵回傳預設每頁 100 筆，並有可設定但受伺服器上限保護的 `page_size`。
- 回傳 `total_count`、`page`、`page_size`、`has_more` 及續取游標或穩定排序資訊。
- 可選擇只取屬性、幾何摘要、WKT 或完整 GeoJSON geometry。
- 大量結果支援匯出 JSON/GeoJSON 並只回傳檔案路徑與摘要。
- 不允許以單次 MCP 回應無限制回傳所有圖徵，避免超出 AI 上下文額度。

### 9.5 QGIS Processing

建議工具：

- `list_processing_providers`
- `search_processing_algorithms`
- `get_processing_algorithm_help`
- `run_processing_algorithm`
- `get_job_status`
- `get_job_result`
- `cancel_job`

需求：

- 可列出並搜尋目前實例已註冊的全部 Processing 演算法，包括 QGIS 原生、GDAL、GRASS、外掛提供者與其他使用者已安裝提供者。
- 執行前依演算法 metadata 與參數建立 schema、檢查必填值、圖層型別、CRS、輸出目的地及數值範圍。
- 若演算法或提供者無法可靠判斷副作用，預設以較高風險處理並要求確認。
- 預設優先建立新輸出，不覆寫輸入資料。
- 回傳演算法 ID、實際參數摘要、輸出、訊息、警告、耗時及錯誤。
- 不得因開放 Processing 而旁路檔案覆寫確認或執行任意程式碼。

### 9.6 樣式與使用者色碼

建議工具：

- `get_layer_style_info`
- `apply_single_style`
- `apply_categorized_style`
- `apply_graduated_style`
- `apply_rgb_field_style`
- `apply_color_mapping`
- `import_qml_style`
- `export_qml_style`

需求：

- 使用者色碼表可為 CSV 或 JSON。
- 色碼表至少包含分類鍵與 R、G、B，並可選擇包含分類顯示名稱與透明度。
- 必須驗證 RGB 為 0–255、分類鍵唯一性、缺漏值及無法配對值。
- 由使用者指定來源分類欄位，以及要建立或更新的 R、G、B 欄位名稱。
- 支援先預覽配對摘要：成功、未匹配、重複與無效色碼數量。
- 寫入 R、G、B 欄位及修改原始圖層前必須確認。
- 套用以 R、G、B 欄位驅動的圖徵色彩，並可保留其他符號設定。
- 可選擇將樣式保存至專案或匯出 QML。

### 9.7 格式轉換

建議工具：

- `inspect_tabular_coordinates`
- `table_to_vector`
- `convert_vector_format`
- `convert_raster_format`

需求：

- CSV/JSON 座標資料需由使用者或 AI 明確指定 X、Y 欄位、來源 CRS 與輸出 CRS。
- 不可僅依數值範圍默認來源 CRS；可提供推測，但必須標示為推測並等待確認。
- 支援點資料建立，並可依明確的群組、順序或幾何欄位規則建立線或面。
- 支援輸出 SHP、GeoPackage、GeoJSON，以及 QGIS/GDAL 支援的適用 Raster 格式。
- SHP 欄位名稱、文字編碼、欄位型別限制必須產生警告。
- 覆寫既有輸出需確認。

### 9.8 幾何檢查與修復

建議工具：

- `check_geometry_validity`
- `check_polygon_closedness`
- `find_geometry_issues`
- `fix_geometries`

需求：

- 檢查無效幾何、自相交、空幾何、重複節點、環方向或未封閉等適用問題。
- 產生結構化摘要及可選的錯誤點／錯誤圖徵圖層。
- 可定位並縮放到問題位置。
- 幾何修復預設輸出新圖層；修改原始圖層時必須確認。
- 修復後重新驗證，回傳已修復、仍失敗、幾何型別改變及空幾何數量。

### 9.9 Raster、NDVI 與 DEM（V1.1）

建議工具：

- `get_raster_info`
- `calculate_ndvi`
- `analyze_raster_colors`
- `run_dem_analysis`
- `reproject_raster`

需求：

- 取得 Raster 尺寸、CRS、範圍、波段、資料型別、NoData 及基本統計。
- NDVI 必須明確指定 NIR 與 Red 波段；僅可提出波段推測，不可無提示執行。
- 處理除以零、NoData、輸出資料型別與值域。
- 色彩分析可提供色帶／波段統計、直方圖摘要與分類結果，不在單次回應傳回完整像素資料。
- DEM GRD 由 QGIS/GDAL 成功辨識後，可執行轉檔、坡度、坡向及陰影等分析。
- 無法識別的 GRD 需回傳驅動程式與格式診斷，不得猜測解碼。

### 9.10 座標轉換（V1.1）

建議工具：

- `set_layer_crs`
- `reproject_layer`
- `transform_coordinates`

需求：

- 明確區分「指定/修正來源 CRS」與「實際重投影」。
- 執行前回傳來源、目標 CRS 與可能的 datum transformation。
- 多個可用 datum transformation 存在時，要求明確選擇，不靜默選用可能造成位移的轉換。
- 支援 EPSG、WKT 或 QGIS 可解析的 CRS 定義。

### 9.11 圖面配置與 PNG 輸出（V1.1）

建議工具：

- `list_layouts`
- `create_layout`
- `create_layout_from_template`
- `get_layout_items`
- `update_layout_item`
- `add_layout_item`
- `remove_layout_item`
- `preview_layout`
- `export_layout_png`

需求：

- 可自動建立新配置，或由使用者指定既有 `.qpt` 樣板。
- 支援地圖、標題、文字、圖例、比例尺、指北針與圖片等常用項目。
- 使用穩定的配置及項目 ID，避免因同名項目修改錯誤。
- 支援修改位置、尺寸、顯示文字及常用樣式屬性。
- 預覽以低至中解析度 PNG 回傳路徑與尺寸，不直接在 JSON 嵌入大型 base64。
- 正式輸出可指定路徑、像素尺寸或 DPI、背景及裁切選項。
- 覆寫 PNG 需確認。

### 9.12 自動圖片對位（V1.2）

建議工具：

- `start_auto_georeference`
- `get_georeference_candidates`
- `update_ground_control_points`
- `approve_georeference`
- `export_georeferenced_raster`

需求：

- 輸入為未定位影像，以及已載入 QGIS 的指定參考 Raster 或目前畫布的明確參考資料。
- 使用本機電腦視覺方法尋找候選共同點；不將影像上傳到外部服務。
- 回傳控制點座標、匹配信心、殘差、整體誤差與預覽疊圖。
- 允許使用者在 QGIS 視窗接受、刪除、移動或新增控制點。
- 使用者必須在 QGIS 視窗確認控制點與轉換設定，才可輸出定位成果。
- 依控制點數量與分布，只提供適用的仿射、投影或其他 QGIS/GDAL 支援模型。
- 控制點不足、空間分布不佳、誤差過高或匹配信心不足時，阻止自動核准並說明原因。
- 輸出為新的 GeoTIFF，絕不覆寫來源影像。
- 覆寫既有目標 GeoTIFF 必須再次確認。

### 9.13 地圖畫布

建議工具：

- `get_canvas_state`
- `set_canvas_extent`
- `zoom_to_layer`
- `zoom_to_selection`
- `capture_canvas`

需求：

- 取得畫布 CRS、範圍、尺寸、比例尺與可見圖層。
- 截圖輸出至本機 PNG，回傳路徑、尺寸及時間。
- 不在 MCP JSON 回應中嵌入無上限圖片資料。

## 10. 安全確認規則

### 10.1 不需確認

- 取得狀態、metadata、欄位或圖層清單。
- 查詢、選取、清除選取、縮放與畫布截圖。
- 預覽樣式、色碼匹配、配置或自動對位候選點。
- 建立不覆寫既有檔案的新分析產物。

### 10.2 必須在 QGIS GUI 確認

- 覆寫或刪除檔案、專案或既有輸出。
- 移除圖層。
- 修改或刪除原始圖徵。
- 批次更新欄位或寫入 R、G、B 欄位。
- 刪除欄位。
- 幾何自動修復原始圖層。
- Processing 演算法會修改原始資料，或無法可靠判斷副作用。
- 儲存或覆寫 QGIS 專案。
- 核准自動對位控制點並正式輸出。

### 10.3 確認視窗內容

- AI/MCP 要求的操作名稱與摘要。
- 目標 `instance_id`、專案、圖層或完整檔案路徑。
- 預估影響的圖徵數、欄位、資料來源或輸出。
- 是否可復原以及預計採用的復原方式。
- 明確的「允許」與「拒絕」按鈕，預設焦點不得放在允許。
- 確認逾時視同拒絕；不得由 MCP Client 代替使用者點選確認。
- 拒絕後回傳穩定的 `USER_DENIED`，不得重複自動彈出。

## 11. 交易、復原與資料完整性

- 修改向量資料時優先使用 QGIS 編輯緩衝、資料提供者交易或可回復機制。
- 多步驟操作應先完成驗證與暫存輸出，再以最小提交範圍完成變更。
- 若資料提供者不支援交易，確認視窗必須說明無法完整回復。
- 新檔輸出先寫入同目的地的暫存檔，成功關閉並驗證後再完成最終替換。
- 不得在部分失敗後回報完整成功。
- 專案未儲存變更、圖層編輯模式與現有 undo stack 不得被無提示清除。

## 12. 錯誤處理

至少定義以下穩定錯誤類別：

- `QGIS_INSTANCE_NOT_FOUND`
- `QGIS_INSTANCE_DISCONNECTED`
- `PROJECT_NOT_FOUND`
- `LAYER_NOT_FOUND`
- `AMBIGUOUS_LAYER`
- `INVALID_PARAMETERS`
- `INVALID_EXPRESSION`
- `CRS_REQUIRED`
- `TRANSFORM_SELECTION_REQUIRED`
- `UNSUPPORTED_FORMAT`
- `PROCESSING_ALGORITHM_NOT_FOUND`
- `PROCESSING_FAILED`
- `CONFIRMATION_REQUIRED`
- `USER_DENIED`
- `CONFIRMATION_TIMEOUT`
- `OUTPUT_EXISTS`
- `FILE_ACCESS_DENIED`
- `JOB_NOT_FOUND`
- `CANCEL_NOT_SUPPORTED`
- `GEOMETRY_VALIDATION_FAILED`
- `RASTER_ALIGNMENT_REQUIRED`
- `CALIBRATION_REQUIRED`
- `CALIBRATION_CONFLICT`
- `GEOREFERENCE_LOW_CONFIDENCE`
- `INTERNAL_ERROR`

錯誤回應不得包含 MCP 權杖、資料庫密碼、完整連線字串或不必要的完整屬性內容。

## 13. 非功能需求

### 13.1 相容性

- 正式驗證 QGIS 3.44 LTR 與 QGIS 4.2 的乾淨安裝環境。
- 隔離 Qt5/Qt6、PyQt5/PyQt6 與 QGIS API 差異，避免功能模組散落版本判斷。
- MCP Server 應與特定 AI Client 解耦。
- 對後續 QGIS 4.x 建立回歸測試與相容性維護流程。

### 13.2 效能與穩定性

- metadata 與小型查詢不應阻塞 QGIS GUI。
- 長時間或大量資料工作必須呈現狀態；可取消時提供取消功能。
- 使用串流、分頁或檔案輸出處理大型結果，不將完整大型資料集載入 MCP 回應。
- 對同一 QGIS 實例的修改操作排隊，避免競態條件。
- QGIS 或 MCP Server 重新啟動後，不得錯誤重送已完成的修改命令。

### 13.3 隱私與日誌

- 預設完全本機執行且無遙測。
- 日誌記錄時間、operation ID、工具、目標 ID、結果、耗時與錯誤碼。
- 預設不記錄完整圖徵屬性、幾何、權杖、密碼或遠端資料來源憑證。
- 提供可設定的日誌保存天數與手動清除功能。

### 13.4 可用性與語言

- QGIS Plugin UI、確認視窗、錯誤訊息與安裝文件提供繁體中文及英文。
- MCP 工具名稱維持英文，description 可提供清楚的英文並附繁體中文補充。
- 確認視窗使用一般 GIS 使用者可理解的語言，不只顯示內部演算法 ID。

## 14. 安裝與交付

- 可由 ZIP 安裝的 QGIS Plugin。
- Windows MCP Server 執行檔或安裝包，不要求一般使用者自行建立 Python/Node 開發環境。
- 提供解除安裝與版本更新說明。
- 提供 `stdio` 與 Streamable HTTP 設定範例。
- 提供供應商中立設定說明，並可另附常見 MCP Client 範例。
- 提供故障排除、日誌位置、連線測試及權杖重設說明。
- 套件包含授權條款、第三方相依套件授權與版本資訊。

## 15. 分階段交付

### V1：核心向量與 Processing

- 架構、連線、安全、實例選擇及確認機制。
- 系統與專案資訊。
- 圖層管理。
- 欄位與 Expression。
- 搜尋、選取、分頁屬性與幾何資料。
- 完整 Processing 搜尋、說明、執行、工作狀態及取消。
- 樣式與使用者色碼，寫入 R、G、B 欄位。
- CSV/JSON/GeoJSON 與向量格式轉換。
- 幾何檢查與修復。
- 畫布狀態、縮放與截圖。

### V1.1：Raster、DEM、座標與配置

- Raster metadata、NDVI 與色彩分析。
- DEM GRD、坡度、坡向與陰影。
- CRS 指定、座標轉換與重投影。
- 建立配置、載入 `.qpt`、調整常用項目、預覽及 PNG 輸出。

### V1.2：自動圖片對位

- 本機共同點偵測。
- 候選控制點、殘差、信心與疊圖預覽。
- QGIS GUI 人工增刪修正及核准流程。
- 輸出新 GeoTIFF 及完整品質報告。

## 16. 測試需求

- 單元測試：schema、路徑、分頁、錯誤映射、風險分類、色碼驗證與版本相容層。
- 整合測試：MCP Server 與 Bridge 的認證、斷線、重連、工作狀態與取消。
- QGIS 測試矩陣：Windows 11 × QGIS 3.44 LTR、QGIS 4.2。
- 格式測試：SHP、GPKG、GeoJSON、CSV、WMS、WFS、GeoTIFF、可辨識 DEM GRD。
- 安全測試：未認證連線、非 loopback、Origin、路徑穿越、超大請求、重放、確認繞過及日誌洩漏。
- 回歸測試：專案保存、原始圖層修改、Processing 副作用、undo/rollback、同名圖層及多實例。
- 效能測試：大型圖徵選取分頁、長時間 Processing、Raster 工作與大量錯誤結果摘要。
- 人工 GUI 測試：確認視窗、繁中/英文、進度、取消、配置預覽及控制點編輯。

## 17. 階段驗收標準

### 17.1 V1 驗收

- 兩個同時開啟的 QGIS 實例可被列出並以不同 `instance_id` 精確操作。
- 標準 MCP Client 可透過 `stdio` 呼叫核心工具；本機 Streamable HTTP 可在認證後使用。
- 可對測試圖層新增欄位、預檢 Expression，經確認後完成計算並回報筆數。
- 可讀取使用者 CSV/JSON 色碼表，預覽匹配，經確認後寫入 R、G、B 欄位並套用樣式。
- 可查詢選取圖徵並分頁取得完整屬性，完整 geometry 需明確要求。
- 可搜尋、說明及執行已註冊 Processing 演算法，取得進度、結果或可信錯誤。
- 危險操作不能繞過 QGIS GUI 確認；拒絕不造成資料變更。
- 可建立幾何錯誤結果，修復預設產生新圖層。
- 可將含明確 X/Y 與 CRS 的 CSV/JSON 轉成 GPKG 或 SHP。
- QGIS 3.44 與 4.2 均通過核心自動與人工測試。

### 17.2 V1.1 驗收

- 可指定 Red/NIR 波段產生 NDVI，正確處理 NoData 與除以零。
- 可讀取測試 DEM GRD 並完成至少坡度、坡向與陰影分析。
- 可區分指定 CRS 與重投影，並在必要時要求 datum transformation 選擇。
- 可建立配置或套用 `.qpt`，加入/修改圖例、比例尺、指北針並輸出 PNG。
- 大型 Raster 結果不直接塞入 MCP JSON，QGIS GUI 保持可操作或顯示明確工作狀態。

### 17.3 V1.2 驗收

- 對具足夠共同視覺特徵的測試影像產生候選控制點、信心與殘差報告。
- 使用者可在 QGIS GUI 中接受、刪除、移動或新增控制點。
- 未經使用者核准不得輸出定位成果。
- 低信心、控制點不足或分布不良時不得宣稱成功。
- 核准後輸出新的 GeoTIFF，來源影像保持不變，並產生品質報告。

## 18. 完成定義

每個版本只有在下列條件均滿足時才算完成：

- 該版本需求與驗收案例通過。
- QGIS 3.44 與 4.2 的指定測試通過。
- 無已知可繞過確認機制、洩漏權杖或遠端存取本機 Bridge 的高風險問題。
- 安裝包、解除安裝、設定範例及繁中/英文基本文件完成。
- 已知限制、未解問題及相容性狀態已記錄。
- 使用者完成該階段驗收。

## 19. 需求核准紀錄

需求方已於 2026-08-12 確認本規格並同意開始 V1，以下事項均已核准：

1. 同意 V1、V1.1、V1.2 的分階段範圍。
2. 同意本機 `C:\Program Files\QGIS 3.44.13` 與 `C:\Program Files\QGIS 4.2.1` 為正式測試基準。
3. 同意所有危險操作均由 QGIS GUI 確認，MCP Client 不可代為核准。
4. 同意第一階段不提供任意 Python/PyQGIS/Shell 執行能力。
5. 同意第一版配置正式輸出僅要求 PNG。
