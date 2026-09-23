# 參與開發

本專案使用 GPL-2.0-or-later 授權。提出 Issue 或 Pull Request 前，請先閱讀 [開發需求](DEVELOPMENT_REQUIREMENTS.md)、[安全模型](docs/SECURITY.md)及[測試說明](docs/TESTING.md)。回報問題時請勿附上真實 token、密碼、私人 GIS 資料或含敏感屬性的日誌。

## 本機環境

在 Windows PowerShell 與 Python 3.12 環境中執行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\ruff.exe check src qgis_plugin tests scripts
.\.venv\Scripts\pytest.exe -q
```

修改 QGIS 外掛或 Raster 操作時，另依 [測試與驗收](docs/TESTING.md)執行真實 QGIS smoke test。請在 Pull Request 描述修改目的、驗證結果與尚未覆蓋的 QGIS／資料來源情境。

版本號需同步更新 `pyproject.toml`、`qgis_plugin/qgis_mcp_bridge/metadata.txt`、打包腳本與文件中的發行檔名。
