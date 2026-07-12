"""Static gates for the canonical Windows release orchestration."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _executable_lines(text: str) -> str:
    """Ignore comments so order assertions describe executed statements."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_inno_is_per_user_and_version_is_injected() -> None:
    text = (ROOT / "installer/CalibratePro.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text
    assert r"DefaultDirName={localappdata}\Programs\Calibrate Pro" in text
    assert "#ifndef AppVersion" in text
    assert '#define AppVersion "1.1.0"' not in text
    assert "runatstartup" not in text.lower()


def test_build_script_uses_hash_lock_canonical_spec_and_final_byte_order() -> None:
    text = (ROOT / "scripts/build_windows.ps1").read_text(encoding="utf-8")
    executable = _executable_lines(text)
    assert "--require-hashes" in text
    assert "requirements-win64-py312.lock" in text
    assert "calibrate-pro.spec" in text
    assert "Compress-Archive" not in text
    assert "release_artifacts.py" in text
    assert "--sdist --wheel --no-isolation" in text
    assert "calibrate_pro-1.1.0.tar.gz" in text
    assert "scripts\\normalize_sdist.py" in text
    assert "Copy-Item -LiteralPath $wheel[0].FullName -Destination $releaseDir" in text
    assert "Copy-Item -LiteralPath $sdist[0].FullName -Destination $releaseDir" in text
    assert "SOURCE_DATE_EPOCH" in text and "PYTHONHASHSEED" in text
    assert executable.index("$artifactTool stage") < executable.index("Sign-StagedExecutables $stagedDir")
    assert executable.index("normalize_sdist.py") < executable.index("twine check")
    assert executable.index("Sign-StagedExecutables $stagedDir") < executable.index("verify_pe_manifest.py")
    assert executable.index("verify_pe_manifest.py") < executable.index("$artifactTool package")
    assert executable.index("$artifactTool package") < executable.index("& $iscc")
    assert executable.index("build-receipt.json") < executable.index("$artifactTool finalize")


def test_build_freezes_the_isolated_installed_wheel_and_always_finalizes() -> None:
    text = (ROOT / "scripts/build_windows.ps1").read_text(encoding="utf-8")
    executable = _executable_lines(text)

    assert "CALIBRATE_PRO_FREEZE_PACKAGE_ROOT" in text
    assert " -I -c " in text
    assert "scripts\\smoke_frozen.ps1" in text
    assert "scripts\\verify_source_provenance.py" in text
    assert "scripts\\verify_binary_provenance.py" in text
    assert "packaging\\binary-provenance.lock.json" in text
    assert "scripts\\verify_release_asset_set.py" in text
    assert "output_root = $OutputRoot" not in text
    assert executable.count("$artifactTool finalize") == 1
    assert "--expected-signer-thumbprint" in text


def test_built_pe_manifests_are_checked_not_inferred_from_spec() -> None:
    build_text = (ROOT / "scripts/build_windows.ps1").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts/verify_pe_manifest.py").read_text(encoding="utf-8")
    assert "verify_pe_manifest.py" in build_text
    assert "RT_MANIFEST" in verifier
    assert "asInvoker" in verifier
    assert "requireAdministrator" in verifier
    assert "highestAvailable" in verifier
    assert '"path": target.name' in verifier


def test_frozen_smoke_is_offscreen_and_read_only() -> None:
    text = (ROOT / "scripts/smoke_frozen.ps1").read_text(encoding="utf-8")
    assert "QT_QPA_PLATFORM" in text and "offscreen" in text
    assert "--help" in text
    assert "--version" in text
    assert "doctor" in text
    assert "if ($probe.Arguments.Count -gt 0)" in text
    assert "Start-Process @start" in text
    assert re.search(r"&\s+\$cli\s+calibrate(?:\s|$)", text, re.I) is None


def test_reproducibility_uses_two_isolated_unsigned_builds() -> None:
    text = (ROOT / "scripts/verify_reproducibility.ps1").read_text(encoding="utf-8")
    assert text.count("build_windows.ps1") >= 2
    assert text.count("-Unsigned") >= 2
    assert text.count("-SkipInstaller") >= 2
    assert text.count("-SkipSourceProvenance") >= 2
    assert "staged-inventory.json" in text
    assert "CalibratePro-1.1.0-win64.zip" in text
    assert "calibrate_pro-1.1.0-py3-none-any.whl" in text
    assert "calibrate_pro-1.1.0.tar.gz" in text
    assert "[switch]$KeepOnFailure" in text
    assert "$succeeded = $true" in text
    assert "$KeepOnFailure -and -not $succeeded" in text
