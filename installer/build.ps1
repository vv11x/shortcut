param(
    [string]$CompilerPath,
    [string]$DistributionDirectory = 'F:\shortcut-output\dist\shortcut',
    [string]$OutputDirectory = 'F:\shortcut-output\dist'
)

$DistributionDirectory = [System.IO.Path]::GetFullPath($DistributionDirectory)
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
$application = Join-Path $DistributionDirectory 'shortcut.exe'
if (-not (Test-Path -LiteralPath $application -PathType Leaf)) {
    throw "Build the distribution first; missing $application"
}

if ([string]::IsNullOrWhiteSpace($CompilerPath)) {
    $CompilerPath = (Get-Command ISCC.exe -ErrorAction Stop).Source
}

& $CompilerPath ('/DDistributionDirectory=' + $DistributionDirectory) ('/O' + $OutputDirectory) (Join-Path $PSScriptRoot 'shortcut.iss')
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Output (Join-Path $OutputDirectory 'shortcut-v1.1.41.exe')
