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

& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "The shortcut test suite failed." }

& .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm shortcut.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller could not build shortcut." }

& .\.venv\Scripts\python.exe tests\smoke_packaged_exe.py
if ($LASTEXITCODE -ne 0) { throw "The packaged shortcut startup check failed." }

if (-not (Test-Path -LiteralPath $ISCCPath)) {
    throw "Inno Setup compiler not found at $ISCCPath. Pass -ISCCPath with the ISCC.exe location."
}
& $ISCCPath installer\shortcut.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup could not build the installer." }

Write-Output "Installer: dist\release\shortcut-1.0.0.exe"
