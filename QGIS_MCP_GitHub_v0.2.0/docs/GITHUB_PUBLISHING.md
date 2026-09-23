# GitHub 上傳與發行說明

## 原始碼庫內容

此資料夾是 0.2.0 的乾淨原始碼副本，包含 `src/` MCP Server、`qgis_plugin/` QGIS Bridge 外掛、`tests/`、`scripts/`、`examples/`、文件、`pyproject.toml`、`.gitignore` 與 GPL 授權。上傳時以此資料夾內容作為儲存庫根目錄。

`.venv/`、快取、`*.egg-info/`、`build/`、執行日誌、暫存 GIS 資料及個人認證資訊不應提交。`.gitignore` 已排除常見產物；提交前仍需人工檢查 `git status`。

## 建立 GitHub 儲存庫

1. 在 GitHub 建立空白儲存庫，先不要讓 GitHub 額外產生 README、`.gitignore` 或 LICENSE；本資料夾已有這些檔案。
2. 於本資料夾開啟 PowerShell，執行下列命令。將 `<你的儲存庫網址>` 替換成實際的 HTTPS 或 SSH URL。

```powershell
git init
git branch -M main
git add .
git status --short
git diff --cached --stat
git commit -m "chore: publish QGIS MCP 0.2.0 source"
git remote add origin "https://github.com/ACCOUNT/REPOSITORY.git"
git push -u origin main
```

將 `ACCOUNT/REPOSITORY` 換成實際帳號與儲存庫名稱；也可以改用自己的 SSH URL。提交前請確認清單不含虛擬環境、建置目錄、`.pyc`、本機 token、真實 GIS 資料或個人路徑。若 GitHub 儲存庫已有初始提交，應先取回並合併，勿強制推送覆蓋。

GitHub 網頁版也可上傳，但須將本資料夾**內部**檔案與資料夾上傳到儲存庫根目錄，包含 `.github/` 和 `.gitignore`。網頁上傳不適合大量檔案；建議使用上述 Git 命令。

## 發布 0.2.0 安裝檔

確認原始碼提交與自動檢查成功後，可建立標籤 `v0.2.0` 與同名 GitHub Release。Windows PowerShell 的本機建置命令為：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,release]"
.\scripts\build_release.ps1
```

從 `build/release/` 取得下列檔案，作為 Release 附件，不提交到 Git 歷史：

- `qgis_mcp_bridge-0.2.0.zip` 與對應 `.sha256`
- `qgis-mcp-server-windows-x64-0.2.0.zip` 與對應 `.sha256`
- 如需 Python 發行：`python/qgis_mcp-0.2.0-py3-none-any.whl` 與對應 `.sha256`

Release 說明可引用 [版本紀錄](../CHANGELOG.md)、[安裝方法](../README.md)及[已知限制](TESTING.md)。目前 Windows 執行檔未經商業 code-signing；下載者應核對 SHA-256。`build_release.ps1` 需要 Windows、Python 虛擬環境及 `.[dev,release]` 相依套件；單純 `.[dev]` 安裝不足以建置 Windows bundle。

發布後可將實際 GitHub 網址填入 QGIS 外掛 `metadata.txt` 的 `repository`、`tracker` 與 `homepage` 欄位，再於下一次外掛發行時更新。
