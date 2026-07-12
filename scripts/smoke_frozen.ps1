[CmdletBinding()]
param(
    [string]$StagedDir = (Join-Path (Split-Path $PSScriptRoot -Parent) 'dist\CalibratePro')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$staged = (Resolve-Path -LiteralPath $StagedDir).ProviderPath
$cli = Join-Path $staged 'CalibrateProCLI.exe'
$gui = Join-Path $staged 'CalibratePro.exe'
if (-not (Test-Path -LiteralPath $cli -PathType Leaf) -or -not (Test-Path -LiteralPath $gui -PathType Leaf)) {
    throw "Frozen executables are missing below $staged"
}

$priorQpa = $env:QT_QPA_PLATFORM
try {
    $env:QT_QPA_PLATFORM = 'offscreen'
    & $cli --help
    if ($LASTEXITCODE -ne 0) { throw 'Frozen CLI help failed' }
    & $cli --version
    if ($LASTEXITCODE -ne 0) { throw 'Frozen CLI version failed' }
    & $cli doctor --json
    if ($LASTEXITCODE -ne 0) { throw 'Frozen read-only doctor failed' }

    $probes = @(
        @{ File = $gui; Arguments = @() },
        @{ File = $cli; Arguments = @('hdr') }
    )
    foreach ($probe in $probes) {
        $start = @{
            FilePath = $probe.File
            PassThru = $true
            WindowStyle = 'Hidden'
        }
        if ($probe.Arguments.Count -gt 0) { $start.ArgumentList = $probe.Arguments }
        $process = Start-Process @start
        try {
            if ($process.WaitForExit(3000)) {
                throw "Frozen GUI probe exited early with code $($process.ExitCode): $($probe.File)"
            }
        }
        finally {
            if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
        }
    }
}
finally {
    $env:QT_QPA_PLATFORM = $priorQpa
}

Write-Output 'frozen-smoke=pass'
