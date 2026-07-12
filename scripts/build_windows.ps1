[CmdletBinding()]
param(
    [switch]$Unsigned,
    [switch]$SkipInstaller,
    [switch]$SkipSourceProvenance,
    [string]$OutputRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Canonical final-byte order contract:
# release_artifacts.py stage -> Sign-StagedExecutables -> release_artifacts.py package -> ISCC.exe -> release_artifacts.py finalize

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).ProviderPath
$toolchainPath = Join-Path $repoRoot 'packaging\toolchain-win64.json'
$lockPath = Join-Path $repoRoot 'packaging\requirements-win64-py312.lock'
$toolchain = Get-Content -Raw -LiteralPath $toolchainPath | ConvertFrom-Json
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')
$callerOwnsOutput = -not [string]::IsNullOrWhiteSpace($OutputRoot)
$venvRoot = Join-Path $tempRoot ('calibrate-pro-venv-' + [guid]::NewGuid().ToString('N'))
$temporaryOutput = $false

function Assert-EmptyOutput([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        if (Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1) {
            throw "Output root must be empty: $Path"
        }
    }
    else {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Assert-SafeTemporaryPath([string]$Path, [string[]]$Prefixes) {
    $resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\')
    $parent = [IO.Path]::GetFullPath((Split-Path $resolved -Parent)).TrimEnd('\')
    $leaf = Split-Path $resolved -Leaf
    if (-not [string]::Equals($parent, $tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing unsafe temporary path outside $tempRoot`: $resolved"
    }
    if (-not ($Prefixes | Where-Object { $leaf.StartsWith($_, [StringComparison]::Ordinal) })) {
        throw "Refusing unexpected temporary leaf: $leaf"
    }
}

function Sign-One([string]$Path) {
    if ($Unsigned) { return }
    $signTool = $env:CALIBRATE_PRO_SIGNTOOL
    $thumbprint = $env:CALIBRATE_PRO_SIGNING_THUMBPRINT
    if (-not $signTool -or -not $thumbprint) {
        throw 'Signing was requested but CALIBRATE_PRO_SIGNTOOL/CALIBRATE_PRO_SIGNING_THUMBPRINT are not configured'
    }
    & $signTool sign /sha1 $thumbprint /fd SHA256 /tr 'http://timestamp.digicert.com' /td SHA256 $Path
    if ($LASTEXITCODE -ne 0) { throw "Signing failed: $Path" }
}

function Sign-StagedExecutables([string]$StagedDir) {
    Sign-One (Join-Path $StagedDir 'CalibratePro.exe')
    Sign-One (Join-Path $StagedDir 'CalibrateProCLI.exe')
}

function Resolve-InnoCompiler {
    $candidates = @(
        $env:CALIBRATE_PRO_ISCC,
        'C:\dev\release-tools\inno-6.7.3\ISCC.exe',
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe'
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    $iscc = $candidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
    if (-not $iscc) { throw 'Inno Setup 6 ISCC.exe was not found' }
    $hash = (Get-FileHash -LiteralPath $iscc -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -ne [string]$toolchain.inno_setup_iscc_sha256) {
        throw "Unexpected ISCC.exe hash $hash; expected $($toolchain.inno_setup_iscc_sha256) for Inno $($toolchain.inno_setup)"
    }
    return $iscc
}

$savedEnvironment = @{}
foreach ($name in @('SOURCE_DATE_EPOCH', 'PYTHONHASHSEED', 'PYTHONUTF8', 'TZ', 'LANG', 'PIP_NO_INDEX', 'QT_API', 'QT_QPA_PLATFORM', 'CALIBRATE_PRO_FREEZE_PACKAGE_ROOT')) {
    $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

try {
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitProcess) { throw 'Windows x64 is required' }
    if ($SkipSourceProvenance -and (-not $Unsigned -or -not $SkipInstaller)) {
        throw 'Source provenance may be skipped only for unsigned installer-free reproducibility builds'
    }
    $hostVersion = (& python -c "import platform; print(platform.python_version())").Trim()
    if ($hostVersion -ne [string]$toolchain.python) { throw "Python $($toolchain.python) is required; found $hostVersion" }

    $env:SOURCE_DATE_EPOCH = [string]$toolchain.source_date_epoch
    $env:PYTHONHASHSEED = '0'
    $env:PYTHONUTF8 = '1'
    $env:TZ = 'UTC'
    $env:LANG = 'C'
    $env:QT_API = 'pyside6'
    $env:QT_QPA_PLATFORM = 'offscreen'

    if ($callerOwnsOutput) {
        $OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
    }
    else {
        $OutputRoot = Join-Path $tempRoot ('calibrate-pro-output-' + [guid]::NewGuid().ToString('N'))
        $temporaryOutput = $true
    }
    Assert-EmptyOutput $OutputRoot

    Push-Location $repoRoot
    try {
        foreach ($requiredInput in @(
            'calibrate-pro.spec',
            'packaging\binary-provenance.lock.json',
            'packaging\components-win64.json',
            'packaging\qt-components.json',
            'packaging\frozen-modules.json',
            'packaging\source-provenance.lock.json',
            'scripts\normalize_sdist.py',
            'THIRD_PARTY_LICENSES'
        )) {
            if (-not (Test-Path -LiteralPath (Join-Path $repoRoot $requiredInput))) {
                throw "Required release input is missing: $requiredInput"
            }
        }

        python -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'Source verification failed' }

        python -m venv $venvRoot
        $releasePython = Join-Path $venvRoot 'Scripts\python.exe'
        & $releasePython -m pip install --require-hashes -r $lockPath
        if ($LASTEXITCODE -ne 0) { throw 'Hash-locked dependency installation failed' }
        & $releasePython -m pip check
        if ($LASTEXITCODE -ne 0) { throw 'Hash-locked environment is inconsistent' }

        $env:PIP_NO_INDEX = '1'
        $pythonDistDir = Join-Path $OutputRoot 'python-dist'
        New-Item -ItemType Directory -Path $pythonDistDir | Out-Null
        & $releasePython -m build --sdist --wheel --no-isolation --outdir $pythonDistDir
        if ($LASTEXITCODE -ne 0) { throw 'Calibrate Python distribution build failed' }
        $wheel = @(Get-ChildItem -LiteralPath $pythonDistDir -Filter 'calibrate_pro-1.1.0-*.whl')
        $sdist = @(Get-ChildItem -LiteralPath $pythonDistDir -Filter 'calibrate_pro-1.1.0.tar.gz')
        if ($wheel.Count -ne 1) { throw "Expected one Calibrate Pro 1.1.0 wheel; found $($wheel.Count)" }
        if ($sdist.Count -ne 1) { throw "Expected one Calibrate Pro 1.1.0 sdist; found $($sdist.Count)" }
        & $releasePython (Join-Path $repoRoot 'scripts\normalize_sdist.py') $sdist[0].FullName `
            --source-date-epoch $toolchain.source_date_epoch
        if ($LASTEXITCODE -ne 0) { throw 'Calibrate source distribution normalization failed' }
        & $releasePython -m twine check $wheel[0].FullName $sdist[0].FullName
        if ($LASTEXITCODE -ne 0) { throw 'Calibrate Python distribution metadata check failed' }
        & $releasePython -m pip install --no-deps --no-index $wheel[0].FullName
        if ($LASTEXITCODE -ne 0) { throw 'Calibrate wheel install failed' }

        $freezePackageRoot = (& $releasePython -I -c "import pathlib, calibrate_pro; print(pathlib.Path(calibrate_pro.__file__).resolve().parent)").Trim()
        $resolvedFreezePackageRoot = [IO.Path]::GetFullPath($freezePackageRoot).TrimEnd('\')
        $resolvedVenvRoot = [IO.Path]::GetFullPath($venvRoot).TrimEnd('\')
        if (-not $resolvedFreezePackageRoot.StartsWith($resolvedVenvRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Installed wheel resolved outside the locked environment: $resolvedFreezePackageRoot"
        }
        $env:CALIBRATE_PRO_FREEZE_PACKAGE_ROOT = $resolvedFreezePackageRoot
        & $releasePython -I -c "import calibrate_pro; assert calibrate_pro.__version__ == '1.1.0'"
        if ($LASTEXITCODE -ne 0) { throw 'Isolated installed-wheel smoke failed' }
        if (-not $SkipSourceProvenance) {
            & $releasePython (Join-Path $repoRoot 'scripts\verify_source_provenance.py') `
                (Join-Path $repoRoot 'packaging\source-provenance.lock.json')
            if ($LASTEXITCODE -ne 0) { throw 'Source provenance verification failed' }
            & $releasePython (Join-Path $repoRoot 'scripts\verify_binary_provenance.py') `
                (Join-Path $repoRoot 'packaging\binary-provenance.lock.json')
            if ($LASTEXITCODE -ne 0) { throw 'Binary provenance verification failed' }
        }

        $buildDir = Join-Path $OutputRoot 'build'
        $distDir = Join-Path $OutputRoot 'dist'
        & $releasePython -m PyInstaller --clean --noconfirm --workpath $buildDir --distpath $distDir 'calibrate-pro.spec'
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }

        $stagedDir = Join-Path $distDir 'CalibratePro'
        $releaseDir = Join-Path $OutputRoot 'release'
        New-Item -ItemType Directory -Path $releaseDir | Out-Null
        Copy-Item -LiteralPath $wheel[0].FullName -Destination $releaseDir
        Copy-Item -LiteralPath $sdist[0].FullName -Destination $releaseDir
        $artifactTool = Join-Path $repoRoot 'scripts\release_artifacts.py'
        $analysisToc = Join-Path $buildDir 'calibrate-pro\Analysis-00.toc'
        $policyArgs = @(
            '--analysis-toc', $analysisToc,
            '--binary-policy', (Join-Path $repoRoot 'packaging\binary-provenance.lock.json'),
            '--component-policy', (Join-Path $repoRoot 'packaging\components-win64.json'),
            '--qt-policy', (Join-Path $repoRoot 'packaging\qt-components.json'),
            '--module-policy', (Join-Path $repoRoot 'packaging\frozen-modules.json'),
            '--source-policy', (Join-Path $repoRoot 'packaging\source-provenance.lock.json'),
            '--notice-dir', (Join-Path $repoRoot 'THIRD_PARTY_LICENSES')
        )

        & $releasePython $artifactTool stage --staged-dir $stagedDir --release-dir $releaseDir @policyArgs
        if ($LASTEXITCODE -ne 0) { throw 'release_artifacts.py stage failed' }
        & (Join-Path $stagedDir 'CalibrateProCLI.exe') doctor --json
        if ($LASTEXITCODE -ne 0) { throw 'Frozen doctor failed' }
        Sign-StagedExecutables $stagedDir

        & $releasePython (Join-Path $repoRoot 'scripts\verify_pe_manifest.py') `
            (Join-Path $stagedDir 'CalibratePro.exe') (Join-Path $stagedDir 'CalibrateProCLI.exe') `
            --output (Join-Path $releaseDir 'pe-manifest-inventory.json')
        if ($LASTEXITCODE -ne 0) { throw 'PE manifest verification failed' }
        & (Join-Path $repoRoot 'scripts\smoke_frozen.ps1') -StagedDir $stagedDir
        if ($LASTEXITCODE -ne 0) { throw 'Frozen application smoke failed' }

        & $releasePython $artifactTool package --staged-dir $stagedDir --release-dir $releaseDir `
            --source-date-epoch $toolchain.source_date_epoch @policyArgs
        if ($LASTEXITCODE -ne 0) { throw 'release_artifacts.py package failed' }

        $installer = $null
        if (-not $SkipInstaller) {
            $iscc = Resolve-InnoCompiler
            & $iscc "/DAppVersion=1.1.0" "/DStagedDir=$stagedDir" "/DReleaseDir=$releaseDir" `
                (Join-Path $repoRoot 'installer\CalibratePro.iss')
            if ($LASTEXITCODE -ne 0) { throw 'ISCC.exe installer build failed' }
            $installer = Join-Path $releaseDir 'CalibratePro-1.1.0-Setup.exe'
            Sign-One $installer
        }

        [ordered]@{
            schema_version = 1
            version = '1.1.0'
            toolchain = $toolchain
            unsigned = [bool]$Unsigned
            installer_skipped = [bool]$SkipInstaller
            python_distributions = @(
                [ordered]@{ name = $wheel[0].Name; sha256 = (Get-FileHash -LiteralPath $wheel[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant() },
                [ordered]@{ name = $sdist[0].Name; sha256 = (Get-FileHash -LiteralPath $sdist[0].FullName -Algorithm SHA256).Hash.ToLowerInvariant() }
            )
        } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $releaseDir 'build-receipt.json') -Encoding utf8

        $finalizeArgs = @('--staged-dir', $stagedDir, '--release-dir', $releaseDir)
        if ($installer) { $finalizeArgs += @('--installer', $installer) }
        if (-not $Unsigned) { $finalizeArgs += @('--expected-signer-thumbprint', $env:CALIBRATE_PRO_SIGNING_THUMBPRINT) }
        & $releasePython $artifactTool finalize @finalizeArgs
        if ($LASTEXITCODE -ne 0) { throw 'release_artifacts.py finalize failed' }
        if (-not $SkipInstaller) {
            & $releasePython (Join-Path $repoRoot 'scripts\verify_release_asset_set.py') $releaseDir
            if ($LASTEXITCODE -ne 0) { throw 'Final release asset-set verification failed' }
        }

        if (-not $callerOwnsOutput) {
            $destination = Join-Path $repoRoot 'release'
            $incoming = Join-Path $repoRoot ('release.incoming.' + [guid]::NewGuid().ToString('N'))
            Move-Item -LiteralPath $releaseDir -Destination $incoming
            if (Test-Path -LiteralPath $destination) {
                throw "Repository release directory already exists; verified output remains at $incoming"
            }
            Move-Item -LiteralPath $incoming -Destination $destination
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    foreach ($entry in $savedEnvironment.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
    }
    Assert-SafeTemporaryPath $venvRoot @('calibrate-pro-venv-')
    if (Test-Path -LiteralPath $venvRoot) { Remove-Item -LiteralPath $venvRoot -Recurse -Force }
    if ($temporaryOutput) {
        Assert-SafeTemporaryPath $OutputRoot @('calibrate-pro-output-')
        if (Test-Path -LiteralPath $OutputRoot) { Remove-Item -LiteralPath $OutputRoot -Recurse -Force }
    }
}
