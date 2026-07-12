[CmdletBinding()]
param(
    [switch]$KeepOnFailure
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$roots = @(
    (Join-Path $tempRoot ('calibrate-pro-output-' + [guid]::NewGuid().ToString('N'))),
    (Join-Path $tempRoot ('calibrate-pro-output-' + [guid]::NewGuid().ToString('N')))
)
$succeeded = $false

function Assert-SafeReproRoot([string]$Path) {
    $resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $parent = [IO.Path]::GetFullPath((Split-Path $resolved -Parent)).TrimEnd('\')
    $leaf = Split-Path $resolved -Leaf
    if (-not [string]::Equals($parent, $tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe reproducibility root parent: $resolved"
    }
    if (-not $leaf.StartsWith('calibrate-pro-output-', [StringComparison]::Ordinal)) {
        throw "Unsafe reproducibility root leaf: $leaf"
    }
}

try {
    & (Join-Path $PSScriptRoot 'build_windows.ps1') -Unsigned -SkipInstaller -SkipSourceProvenance -OutputRoot $roots[0]
    & (Join-Path $PSScriptRoot 'build_windows.ps1') -Unsigned -SkipInstaller -SkipSourceProvenance -OutputRoot $roots[1]

    $artifactHashes = @{}
    foreach ($name in @(
        'CalibratePro-1.1.0-win64.zip',
        'calibrate_pro-1.1.0-py3-none-any.whl',
        'calibrate_pro-1.1.0.tar.gz'
    )) {
        $pathA = Join-Path $roots[0] "release\$name"
        $pathB = Join-Path $roots[1] "release\$name"
        $hashA = (Get-FileHash -LiteralPath $pathA -Algorithm SHA256).Hash
        $hashB = (Get-FileHash -LiteralPath $pathB -Algorithm SHA256).Hash
        if ($hashA -ne $hashB) { throw "$name mismatch: $hashA != $hashB" }
        $artifactHashes[$name] = $hashA
    }

    $inventoryA = Get-Content -Raw -LiteralPath (Join-Path $roots[0] 'release\staged-inventory.json')
    $inventoryB = Get-Content -Raw -LiteralPath (Join-Path $roots[1] 'release\staged-inventory.json')
    if ($inventoryA -cne $inventoryB) { throw 'Canonical staged-inventory.json bytes differ' }
    Write-Output (
        'reproducibility=pass portable_sha256={0} wheel_sha256={1} sdist_sha256={2}' -f
        $artifactHashes['CalibratePro-1.1.0-win64.zip'],
        $artifactHashes['calibrate_pro-1.1.0-py3-none-any.whl'],
        $artifactHashes['calibrate_pro-1.1.0.tar.gz']
    )
    $succeeded = $true
}
finally {
    if ($KeepOnFailure -and -not $succeeded) {
        foreach ($root in $roots) {
            Assert-SafeReproRoot $root
            Write-Warning "Preserved failed reproducibility root for diagnosis: $root"
        }
    }
    else {
        foreach ($root in $roots) {
            Assert-SafeReproRoot $root
            if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
        }
    }
}
