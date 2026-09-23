$ErrorActionPreference = 'Stop'

# ASCII-only source keeps this runner compatible with Windows PowerShell 5.1.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SmokeScript = Join-Path $PSScriptRoot 'qgis_gui_plugin_smoke.py'
$RuntimeRoot = Join-Path $ProjectRoot 'build\qgis-gui-smoke'
$ProfilesRoot = Join-Path $RuntimeRoot 'profiles'
$RegistryRoot = Join-Path $RuntimeRoot 'instances'
$QgisInstallations = @(
    @{
        Label = 'qgis_3_44_13'
        Executable = 'C:\Program Files\QGIS 3.44.13\bin\qgis-ltr-bin.exe'
    },
    @{
        Label = 'qgis_4_2_1'
        Executable = 'C:\Program Files\QGIS 4.2.1\bin\qgis-bin.exe'
    }
)

New-Item -ItemType Directory -Path $ProfilesRoot -Force | Out-Null
New-Item -ItemType Directory -Path $RegistryRoot -Force | Out-Null
foreach ($QgisInstall in $QgisInstallations) {
    if (-not (Test-Path -LiteralPath $QgisInstall.Executable -PathType Leaf)) {
        throw ("QGIS executable not found: " + $QgisInstall.Executable)
    }
    $env:QGIS_MCP_GUI_SMOKE_LABEL = $QgisInstall.Label
    $env:QGIS_MCP_GUI_SMOKE_ROOT = $ProjectRoot
    $env:QGIS_MCP_REGISTRY_DIR = $RegistryRoot
    $env:QT_QPA_PLATFORM = 'offscreen'
    $ProfileName = 'smoke_' + $QgisInstall.Label
    $Arguments = @(
        '--nologo',
        '--noversioncheck',
        '--profiles-path',
        ('"' + $ProfilesRoot + '"'),
        '--profile',
        $ProfileName,
        '--code',
        ('"' + $SmokeScript + '"')
    )
    Write-Host ("Starting GUI plugin smoke: " + $QgisInstall.Label)
    $StartedAt = Get-Date
    $Process = Start-Process `
        -FilePath $QgisInstall.Executable `
        -ArgumentList $Arguments `
        -WindowStyle Hidden `
        -PassThru
    if (-not $Process.WaitForExit(90000)) {
        Stop-Process -Id $Process.Id -Force
        throw ("QGIS GUI process timed out after 90 seconds: " + $QgisInstall.Label)
    }
    if ($Process.ExitCode -ne 0) {
        throw ("QGIS GUI process failed with exit code " + $Process.ExitCode)
    }
    $ReportPath = Join-Path $RuntimeRoot ("reports\" + $QgisInstall.Label + '.json')
    if (-not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) {
        throw ("GUI smoke report not found: " + $ReportPath)
    }
    if ((Get-Item -LiteralPath $ReportPath).LastWriteTime -lt $StartedAt) {
        throw ("GUI smoke report is stale: " + $ReportPath)
    }
    $Report = Get-Content -LiteralPath $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $Report.success) {
        throw ("GUI plugin smoke failed: " + $QgisInstall.Label)
    }
}

Write-Host 'QGIS GUI plugin lifecycle smoke tests passed.'
