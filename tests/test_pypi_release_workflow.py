"""The PyPI job must publish the exact accepted GitHub release distributions."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
WINDOWS_BUILD = ROOT / "scripts" / "build_windows.ps1"
PYPROJECT = ROOT / "pyproject.toml"
GITATTRIBUTES = ROOT / ".gitattributes"


def test_release_workflow_uses_oidc_and_an_explicit_publish_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "environment: pypi" in text
    assert "id-token: write" in text
    assert "inputs.publish" in text
    assert "release_tag" in text
    assert "types: [published]" in text


def test_pypi_job_downloads_and_verifies_exact_release_assets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'gh release download "$RELEASE_TAG"' in text
    assert "sha256sum --check SHA256SUMS.txt" in text
    assert "scripts/verify_release_asset_set.py accepted" in text
    assert "windows-release-candidate" in text
    assert "cmp --silent" in text
    assert "verified-pypi-distributions" in text
    assert "pypi-dist/" in text
    assert "packages-dir: pypi-dist/" in text
    assert "skip-existing" not in text


def test_oidc_job_only_downloads_verified_artifacts_and_publishes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    publish = text.split("\n  publish:\n", 1)[1]

    assert "needs: verify-publish-assets" in publish
    assert "id-token: write" in publish
    assert "actions/download-artifact@" in publish
    assert "pypa/gh-action-pypi-publish@" in publish
    assert "actions/checkout@" not in publish
    assert "actions/setup-python@" not in publish
    assert "pip install" not in publish
    assert "run:" not in publish


def test_release_asset_verification_has_no_oidc_permission() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    verify = text.split("\n  verify-publish-assets:\n", 1)[1].split("\n  publish:\n", 1)[0]

    assert "id-token: write" not in verify
    assert "actions: read" in verify
    assert "windows-release-candidate" in verify
    assert "verified-pypi-distributions" in verify


def test_candidate_runs_tests_builds_and_checks_distributions() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    candidate = text.split("\n  candidate:\n", 1)[1].split("\n  windows-candidate:\n", 1)[0]

    assert 'python -m pytest -q -m "not windows"' in candidate
    assert "python -m build" in text
    assert "python -m twine check dist/*" in text
    assert "scripts/verify_source_provenance.py" in text


def test_manual_and_release_candidates_checkout_the_requested_tag() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert text.count("github.event.release.tag_name || inputs.release_tag") >= 4
    assert "ref: ${{ github.event_name == 'release' && github.event.release.tag_name || inputs.release_tag }}" in text


def test_windows_candidate_runs_the_canonical_build_smoke_and_reproducibility() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    windows = text.split("\n  windows-candidate:\n", 1)[1].split("\n  verify-publish-assets:\n", 1)[0]
    build_script = WINDOWS_BUILD.read_text(encoding="utf-8")

    assert "windows-candidate:" in text
    assert "runs-on: windows-2022" in text
    assert "cpython-3.12.10-amd64-installer" in windows
    assert "scripts/build_windows.ps1" in text
    assert "scripts/verify_reproducibility.ps1" in text
    assert "windows-release-candidate" in text
    assert "needs: [candidate, windows-candidate]" in text
    assert "Start-Process -FilePath $installer" in text
    assert "-Wait -PassThru" in text
    assert "$innoInstall.ExitCode" in text
    assert "& $installer /VERYSILENT" not in text
    assert "--require-hashes -r packaging/requirements-win64-py312.lock" in windows
    assert "pytest==9.0.3" in windows
    assert windows.index("--require-hashes") < windows.index("pytest==9.0.3")
    assert windows.index("pytest==9.0.3") < windows.index("scripts/build_windows.ps1")
    assert re.search(r"(?m)^\s*& \$hostPython -m pytest -q\s*$", build_script)


def test_windows_candidate_pins_checkout_line_endings_before_checkout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    windows = text.split("\n  windows-candidate:\n", 1)[1].split("\n  verify-publish-assets:\n", 1)[0]

    assert "git config --global core.autocrlf true" in windows
    assert windows.index("git config --global core.autocrlf true") < windows.index("actions/checkout@")
    assert "* text=auto eol=lf" in GITATTRIBUTES.read_text(encoding="utf-8")


def test_windows_candidate_builds_with_the_hash_locked_official_cpython_runtime() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    windows = text.split("\n  windows-candidate:\n", 1)[1].split("\n  verify-publish-assets:\n", 1)[0]
    build_script = WINDOWS_BUILD.read_text(encoding="utf-8")

    assert "actions/setup-python@" not in windows
    assert "packaging/binary-provenance.lock.json" in windows
    assert "cpython-3.12.10-amd64-installer" in windows
    assert "Invoke-WebRequest -Uri $pythonEntry.artifact_url" in windows
    assert "$pythonEntry.sha256" in windows
    assert "Get-AuthenticodeSignature -LiteralPath $pythonInstaller" in windows
    assert "Start-Process -FilePath $pythonInstaller" in windows
    assert "'libcrypto-3.dll', 'libssl-3.dll'" in windows
    assert "libcrypto-3-x64.dll" not in windows
    assert "libssl-3-x64.dll" not in windows
    assert '"CALIBRATE_PRO_RELEASE_PYTHON=$python"' in windows
    assert "& $env:CALIBRATE_PRO_RELEASE_PYTHON -m pip" in windows
    assert "$env:CALIBRATE_PRO_RELEASE_PYTHON" in build_script
    assert "& $hostPython -m pytest -q" in build_script
    assert "& $hostPython -m venv $venvRoot" in build_script


def test_ci_runs_only_portable_tests_on_linux_and_the_complete_suite_on_windows() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")

    linux = text.split("      - name: Run portable tests with coverage\n", 1)[1].split(
        "      - name: Run complete Windows tests with coverage\n", 1
    )[0]
    windows = text.split("      - name: Run complete Windows tests with coverage\n", 1)[1]

    assert "if: runner.os == 'Linux'" in linux
    assert '-m "not windows"' in linux
    assert "if: runner.os == 'Windows'" in windows
    assert '-m "not windows"' not in windows
    assert "COVERAGE_CORE: ctrace" in windows
    assert "COVERAGE_CORE: sysmon" not in windows


def test_ci_holds_a_coverage_floor_both_lanes_clear_by_a_real_margin() -> None:
    """A floor far below the measured number cannot fail, so it measures nothing.

    Both lanes are held to the same figure. The portable lane deselects the Windows
    suite and lands lower, so it sets the ceiling on how high this can go: 37.86
    percent measured against 53.27 on the complete lane.
    """
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    floors = re.findall(r"--cov-fail-under=(\d+)", text)

    assert floors == ["30", "30"]


def test_ci_reports_every_matrix_job_rather_than_cancelling_on_the_first_red() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    strategy = text.split("    strategy:", 1)[1].split("    steps:", 1)[0]

    assert "fail-fast: false" in strategy
    assert "ubuntu-latest, windows-latest" in strategy
    assert '"3.10", "3.11", "3.12", "3.13"' in strategy


def test_ci_pins_static_analysis_and_type_checks_the_windows_target() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    pyproject = PYPROJECT.read_text(encoding="utf-8")

    assert "ruff==0.15.21" in text
    assert "mypy==2.2.0" in text
    assert "mypy --platform win32" in text
    assert 'platform = "win32"' in pyproject


def test_automation_resolves_public_dependencies_without_git_installs() -> None:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows
    offenders = [path.name for path in workflows if "git+https" in path.read_text(encoding="utf-8")]

    assert offenders == []


def test_third_party_actions_are_pinned_to_immutable_commits() -> None:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    uses = [
        line.strip()
        for path in workflows
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- uses:") or line.strip().startswith("uses:")
    ]

    assert uses
    assert all(re.search(r"@[0-9a-f]{40}(?:\s+#|$)", line) for line in uses)
