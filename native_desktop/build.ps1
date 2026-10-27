param([string]$OutputDirectory = $PSScriptRoot, [string]$CompilerPath)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$buildOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($buildOutput) | Out-Null
if ($CompilerPath) {
    $toolchainRoot = (Split-Path -Parent (Split-Path -Parent $CompilerPath)) -replace '\\', '/'
    $compileFlags = @('-std=c++17', '-Wall', '-Wextra', '-Werror', '-O2', '-shared', '-static', '-s', ('-ffile-prefix-map=' + $toolchainRoot + '=toolchain'))
    & $CompilerPath @compileFlags -o (Join-Path $buildOutput 'ShortcutDesktop.dll') (Join-Path $PSScriptRoot 'filter.cpp') (Join-Path $PSScriptRoot 'bridge.cpp') (Join-Path $PSScriptRoot 'recycle.cpp') -lshell32 -lole32 -luser32 -lcomctl32 -luuid
    if ($LASTEXITCODE -ne 0) { throw 'Native desktop component build failed.' }
    & $CompilerPath @compileFlags -o (Join-Path $buildOutput 'ShortcutShell.dll') (Join-Path $PSScriptRoot 'shell_menu.cpp') -lshell32 -lole32 -luser32 -luuid
    if ($LASTEXITCODE -ne 0) { throw 'Native shell menu component build failed.' }
    exit 0
}
$vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$compilerRoot = & $vswherePath -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$compilerRoot) { throw 'MSVC x64 Build Tools are required.' }
$buildCommand = 'call "{0}\Common7\Tools\VsDevCmd.bat" -arch=amd64 -host_arch=amd64 >nul && cl.exe /nologo /std:c++17 /utf-8 /W4 /WX /EHsc /O2 /MT /LD /Fo"{1}\\" /Fe"{1}\ShortcutDesktop.dll" "{2}\filter.cpp" "{2}\bridge.cpp" "{2}\recycle.cpp" /link shell32.lib ole32.lib user32.lib comctl32.lib uuid.lib' -f $compilerRoot, $buildOutput, $PSScriptRoot
$shellCommand = 'call "{0}\Common7\Tools\VsDevCmd.bat" -arch=amd64 -host_arch=amd64 >nul && cl.exe /nologo /std:c++17 /utf-8 /W4 /WX /EHsc /O2 /MT /LD /Fo"{1}\shell_menu.obj" /Fe"{1}\ShortcutShell.dll" "{2}\shell_menu.cpp" /link shell32.lib ole32.lib user32.lib uuid.lib' -f $compilerRoot, $buildOutput, $PSScriptRoot
Push-Location -LiteralPath $buildOutput
try {
    & cmd.exe /d /s /c $buildCommand
    if ($LASTEXITCODE -ne 0) { throw 'Native desktop component build failed.' }
    & cmd.exe /d /s /c $shellCommand
    if ($LASTEXITCODE -ne 0) { throw 'Native shell menu component build failed.' }
} finally {
    Pop-Location
}
