param([string]$OutputDirectory = (Join-Path ([System.IO.Path]::GetTempPath()) 'shortcut-native-tests'), [string]$CompilerPath)

$ErrorActionPreference = 'Stop'
$buildOutput = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($buildOutput) | Out-Null
if ($CompilerPath) {
    foreach ($testName in @('native_bridge_lifecycle', 'native_shell_menu')) {
        & $CompilerPath -std=c++17 -Wall -Wextra -Werror -static -o (Join-Path $buildOutput ($testName + '.exe')) (Join-Path $PSScriptRoot ($testName + '.cpp')) -lshell32 -lole32 -luser32 -luuid
        if ($LASTEXITCODE -ne 0) { throw "Native test build failed: $testName" }
        & (Join-Path $buildOutput ($testName + '.exe'))
        if ($LASTEXITCODE -ne 0) { throw "Native test failed: $testName" }
    }
    exit 0
}
$vswherePath = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$compilerRoot = & $vswherePath -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (!$compilerRoot) { throw 'MSVC x64 Build Tools are required.' }
foreach ($testName in @('native_bridge_lifecycle', 'native_shell_menu')) {
    $testSource = Join-Path $PSScriptRoot ($testName + '.cpp')
    $buildCommand = 'call "{0}\Common7\Tools\VsDevCmd.bat" -arch=amd64 -host_arch=amd64 >nul && cl.exe /nologo /std:c++17 /utf-8 /W4 /WX /EHsc /MT /Fo"{1}\{3}.obj" /Fe"{1}\{3}.exe" "{2}" /link shell32.lib ole32.lib user32.lib uuid.lib' -f $compilerRoot, $buildOutput, $testSource, $testName
    & cmd.exe /d /s /c $buildCommand
    if ($LASTEXITCODE -ne 0) { throw "Native test build failed: $testName" }
    & (Join-Path $buildOutput ($testName + '.exe'))
    if ($LASTEXITCODE -ne 0) { throw "Native test failed: $testName" }
}
