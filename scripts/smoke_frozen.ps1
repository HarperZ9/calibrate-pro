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

function Start-Probe {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [string[]]$Arguments = @(),
        [string]$OutPath,
        [string]$ErrPath
    )

    $start = @{
        FilePath = $File
        PassThru = $true
        WindowStyle = 'Hidden'
    }
    if ($Arguments.Count -gt 0) { $start.ArgumentList = $Arguments }
    # A windowed PyInstaller executable is given no standard streams unless it
    # inherits usable handles, so the graded launch is the one with none. The
    # redirected launch below is the diagnostic re-run, and it is deliberately
    # not what the gate measures.
    if ($OutPath) { $start.RedirectStandardOutput = $OutPath }
    if ($ErrPath) { $start.RedirectStandardError = $ErrPath }
    $process = Start-Process @start
    # Reading Handle here is what keeps ExitCode readable afterwards. A redirected
    # Start-Process hands back an object that closes its handle when the process
    # ends, and the exit code goes with it, so the diagnostic re-run reported
    # "Re-run exit code ." with the number missing. Touching it while the process
    # is alive caches the handle for the lifetime of the object.
    $null = $process.Handle
    return $process
}

function Read-ProbeStreams {
    param(
        [Parameter(Mandatory = $true)][string]$OutPath,
        [Parameter(Mandatory = $true)][string]$ErrPath
    )

    $sections = @()
    foreach ($stream in @(@('stdout', $OutPath), @('stderr', $ErrPath))) {
        if (-not (Test-Path -LiteralPath $stream[1] -PathType Leaf)) { continue }
        $text = Get-Content -LiteralPath $stream[1] -Raw
        if ($text) { $sections += "--- $($stream[0]) ---"; $sections += $text.TrimEnd() }
    }
    if ($sections.Count -eq 0) {
        return 'The re-run wrote nothing to either standard stream.'
    }
    return ($sections -join [Environment]::NewLine)
}

function Get-ProbeFailureReason {
    <#
    .SYNOPSIS
    Re-run a probe that exited early, this time with streams to read.

    .DESCRIPTION
    An early exit used to be reported as a number. The reason for it was
    written to a stream nobody was holding, so a build failed here saying only
    that the executable had stopped, and finding out why meant reproducing the
    whole packaged graph by hand. This runs the same command once more with
    both streams captured and returns what it said. The re-run is reporting
    only: whatever it does, the gate has already failed.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [string[]]$Arguments = @()
    )

    $root = Join-Path ([IO.Path]::GetTempPath()) ('calibrate-frozen-smoke-' + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $root | Out-Null
    try {
        $outPath = Join-Path $root 'probe.out'
        $errPath = Join-Path $root 'probe.err'
        $process = Start-Probe -File $File -Arguments $Arguments -OutPath $outPath -ErrPath $errPath
        try {
            if (-not $process.WaitForExit(10000)) {
                return 'The re-run with captured streams did not exit, so the early exit did not reproduce.'
            }
        }
        finally {
            if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
        }
        return "Re-run exit code $($process.ExitCode)." + [Environment]::NewLine + (Read-ProbeStreams -OutPath $outPath -ErrPath $errPath)
    }
    finally {
        Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
    }
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
        $process = Start-Probe -File $probe.File -Arguments $probe.Arguments
        $exitedEarly = $false
        $exitCode = 0
        try {
            if ($process.WaitForExit(3000)) {
                $exitedEarly = $true
                $exitCode = $process.ExitCode
            }
        }
        finally {
            if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
        }
        if ($exitedEarly) {
            $reason = Get-ProbeFailureReason -File $probe.File -Arguments $probe.Arguments
            throw "Frozen GUI probe exited early with code ${exitCode}: $($probe.File)" + [Environment]::NewLine + $reason
        }
    }
}
finally {
    $env:QT_QPA_PLATFORM = $priorQpa
}

Write-Output 'frozen-smoke=pass'
