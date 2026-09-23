$ErrorActionPreference = 'Stop'

# Central release inputs and outputs. End users do not need to run this script.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$ReleaseRoot = Join-Path $ProjectRoot 'build\release'
$WindowsDist = Join-Path $ReleaseRoot 'windows'
$WheelOutput = Join-Path $ReleaseRoot 'python'
$PyInstallerWork = Join-Path $ProjectRoot 'build\pyinstaller'
$EntryScript = Join-Path $PSScriptRoot 'qgis_mcp_entry.py'
$PluginPackager = Join-Path $PSScriptRoot 'package_plugin.py'
$WindowsPackager = Join-Path $PSScriptRoot 'package_windows_bundle.py'
$Version = '0.2.0' # 與 pyproject.toml、外掛 metadata 及封裝腳本同步。
$WindowsAppDir = Join-Path $WindowsDist ("qgis-mcp-" + $Version)

if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "Development virtual environment not found: $PythonExe"
}
New-Item -ItemType Directory -Path $ReleaseRoot -Force | Out-Null
New-Item -ItemType Directory -Path $WindowsDist -Force | Out-Null
New-Item -ItemType Directory -Path $PyInstallerWork -Force | Out-Null

# 只清除本版本的可重建 onedir，避免 PyInstaller 因既有目錄等待互動確認。
$ResolvedWindowsAppDir = [System.IO.Path]::GetFullPath($WindowsAppDir)
$ResolvedWindowsDist = [System.IO.Path]::GetFullPath($WindowsDist) + [System.IO.Path]::DirectorySeparatorChar
if (-not $ResolvedWindowsAppDir.StartsWith($ResolvedWindowsDist, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clean output outside Windows release directory: $ResolvedWindowsAppDir"
}
if (Test-Path -LiteralPath $ResolvedWindowsAppDir) {
    Remove-Item -LiteralPath $ResolvedWindowsAppDir -Recurse -Force
}

& $PythonExe $PluginPackager
if ($LASTEXITCODE -ne 0) { throw 'QGIS Plugin ZIP build failed.' }

& $PythonExe -m build --wheel --no-isolation --outdir $WheelOutput $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Python wheel build failed.' }

& $PythonExe -m PyInstaller `
    --onedir `
    --name ("qgis-mcp-" + $Version) `
    --distpath $WindowsDist `
    --workpath $PyInstallerWork `
    --specpath $PyInstallerWork `
    --collect-all pydantic `
    --collect-all pydantic_core `
    $EntryScript
if ($LASTEXITCODE -ne 0) { throw 'Windows MCP Server build failed.' }

& $PythonExe $WindowsPackager
if ($LASTEXITCODE -ne 0) { throw 'Windows MCP Server ZIP build failed.' }

Write-Host "Release artifacts created: $ReleaseRoot"
