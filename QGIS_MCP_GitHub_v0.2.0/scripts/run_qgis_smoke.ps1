$ErrorActionPreference = 'Stop'

# Central QGIS installation configuration; update only this block after upgrades.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SmokeScript = Join-Path $PSScriptRoot 'qgis_runtime_smoke.py'
$QgisInstallations = @(
    @{
        Name = 'QGIS 3.44.13'
        Root = 'C:\Program Files\QGIS 3.44.13'
        QgisApp = 'qgis-ltr'
        QtApp = 'qt5'
    },
    @{
        Name = 'QGIS 4.2.1'
        Root = 'C:\Program Files\QGIS 4.2.1'
        QgisApp = 'qgis'
        QtApp = 'qt6'
    }
)

foreach ($QgisInstall in $QgisInstallations) {
    $QgisRoot = $QgisInstall.Root
    $QgisAppPath = Join-Path $QgisRoot ("apps\" + $QgisInstall.QgisApp)
    $QtAppPath = Join-Path $QgisRoot ("apps\" + $QgisInstall.QtApp)
    $PythonExe = Join-Path $QgisRoot 'apps\Python312\python.exe'
    foreach ($RequiredPath in @($QgisRoot, $QgisAppPath, $QtAppPath, $PythonExe, $SmokeScript)) {
        if (-not (Test-Path -LiteralPath $RequiredPath)) {
            throw "Required path not found: $RequiredPath"
        }
    }

    Write-Host ("Starting " + $QgisInstall.Name + " runtime smoke test...")
    $env:QGIS_PREFIX_PATH = $QgisAppPath
    $env:QT_PLUGIN_PATH = (Join-Path $QgisAppPath 'qtplugins') + ';' + (Join-Path $QtAppPath 'plugins')
    $env:PYTHONPATH = (Join-Path $QgisAppPath 'python') + ';' + (Join-Path $QgisAppPath 'python\plugins')
    $env:PROJ_DATA = Join-Path $QgisRoot 'share\proj'
    $env:GDAL_DATA = Join-Path $QgisRoot 'share\gdal'
    $env:QT_QPA_PLATFORM = 'offscreen'

    # QGIS Python on Windows requires explicit Qt/QGIS DLL directories before import.
    $DllRoot = Join-Path $QgisRoot 'bin'
    $QtBin = Join-Path $QtAppPath 'bin'
    $QgisBin = Join-Path $QgisAppPath 'bin'
    $Bootstrap = "import os,runpy; handles=[os.add_dll_directory(path) for path in [r'$DllRoot',r'$QtBin',r'$QgisBin']]; runpy.run_path(r'$SmokeScript',run_name='__main__')"
    & $PythonExe -c $Bootstrap
    if ($LASTEXITCODE -ne 0) {
        throw ($QgisInstall.Name + ' runtime smoke test failed.')
    }
}

Write-Host "QGIS 3.44.13 and 4.2.1 runtime smoke tests passed."
