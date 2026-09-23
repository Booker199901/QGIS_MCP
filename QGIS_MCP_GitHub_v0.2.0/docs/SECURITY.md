# QGIS MCP 安全模型

## 信任邊界

- QGIS Bridge 只綁定 `127.0.0.1` 的隨機連接埠。
- 每次外掛啟動產生新的 `instance_id` 與高熵 Bearer token；token 只存於目前 Windows 使用者的 LocalAppData registry，不回傳 MCP Client。
- 外部 Streamable HTTP 也只允許 loopback，並使用獨立、至少 32 字元的使用者 token。
- 本系統不提供任意 Python、PyQGIS、Shell 或系統命令，也不內建雲端上傳或遙測。

## 命令安全

- Bridge 只路由程式明確公布的 action，JSON envelope、參數型別、路徑、副檔名及 QGIS 物件 ID 均需驗證。
- 近期 `request_id` 不可重放；同一實例的 Processing 與 Raster 工作依序排隊。
- QGIS modal 確認造成巢狀 Qt event loop 時，Bridge 會拒絕重入命令並回傳 `QGIS_INSTANCE_BUSY`。
- 未知 Processing provider、疑似原地演算法、已存在輸出或輸入輸出同路徑採較高風險，必須確認。
- 完整 Processing 支援不等於任意程式執行；演算法仍須已在目前 QGIS Processing Registry 中註冊並通過 `checkParameterValues`。
- 專用 Raster 工具只接受已載入 QGIS 的本機檔案；背景工作只接收驗證後的路徑、網格與數值參數，不存取 GUI 物件。
- 新 Raster 成果先寫入同目錄的唯一暫存檔，成功關閉並重新開啟驗證後才原子替換目標；取消或失敗會清除暫存檔。

## 真人確認

危險操作在可見 QGIS GUI 顯示警告視窗，預設按鈕為取消。確認不可由 MCP 呼叫、token 或參數替代。使用者拒絕、關閉視窗或按 Esc 均為 `USER_DENIED`，拒絕前不提交資料變更。

## 資料量與機密

- 圖徵查詢預設 100 筆／頁、硬上限 1000；完整 geometry 需明確要求。
- Bridge 與 HTTP request 均有 4 MiB 上限。
- WMS／WFS URI、token、完整屬性、幾何與 Expression 不寫入稽核日誌。
- 非預期例外的 MCP 回應不含 traceback；本機 QGIS 訊息日誌只記錄錯誤型別及摘要。

## 維運建議

- 優先使用 `stdio`；只有本機共用需求才開啟 Streamable HTTP。
- 不要將 localhost 端點透過反向代理、port forwarding、隧道或防火牆規則暴露到其他主機。
- 若懷疑 HTTP token 外洩，停止 Server、重新執行 `generate-token` 並更新 Client 設定。
- QGIS Bridge token 每次 reload 即自動輪替；舊 registry 超過 TTL 後不再視為線上。
- 使用 `qgis-mcp clear-logs` 清除 Server 稽核日誌；QGIS 自身訊息日誌依 QGIS 設定管理。
