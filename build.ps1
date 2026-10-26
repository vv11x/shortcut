param(
    [string]$ISCCPath = (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    py -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
}

& .\.venv\Scripts\python.exe -m pip install -e . -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "Could not install the build dependencies." }

& .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm shortcut.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not build shortcut." }

if (-not (Test-Path -LiteralPath $ISCCPath)) {
    throw "Inno Setup 6 compiler not found at $ISCCPath. Pass -ISCCPath with the ISCC.exe location."
}
& $ISCCPath installer\shortcut.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup could not build the installer." }

Write-Output "Installer: dist\release\shortcut-1.0.0.exe"
