"""Windows release-root and toolchain contracts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

APPROVED_RELEASE_ROOTS = (
    "build-color==1.0.2",
    "build-ui==2.0.0",
    "QtPy==2.4.3",
    "PySide6-Essentials==6.11.1",
    "numpy==2.5.1",
    "scipy==1.18.0",
    "hidapi==0.15.0",
    "pyinstaller==6.21.0",
    "build==1.5.1",
    "setuptools==83.0.0",
    "wheel==0.47.0",
    "pefile==2024.8.26",
    "twine==6.2.0",
)

APPROVED_TOOLCHAIN = {
    "schema_version": 1,
    "python": "3.12.10",
    "architecture": "x86_64-pc-windows-msvc",
    "uv": "0.11.28",
    "pyinstaller": "6.21.0",
    "build": "1.5.1",
    "setuptools": "83.0.0",
    "wheel": "0.47.0",
    "twine": "6.2.0",
    "source_date_epoch": 315532800,
    "inno_setup": "6.7.3",
    "inno_setup_installer_sha256": "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732",
    "inno_setup_iscc_sha256": "0a8757031b33777e4c9cbffee40f11a5062b36d25cbe144c1db73b6102b80ad7",
}


def test_release_roots_match_the_approved_windows_input_exactly() -> None:
    path = ROOT / "packaging" / "requirements-win64.in"

    assert path.read_text(encoding="utf-8") == "\n".join(APPROVED_RELEASE_ROOTS) + "\n"


def test_windows_toolchain_matches_the_approved_contract_exactly() -> None:
    path = ROOT / "packaging" / "toolchain-win64.json"

    assert json.loads(path.read_text(encoding="utf-8")) == APPROVED_TOOLCHAIN


def test_legacy_release_paths_are_removed() -> None:
    assert not (ROOT / "requirements.txt").exists()
    assert not (ROOT / "build_installer.bat").exists()


def test_release_lock_is_hashed_public_and_pyside_only() -> None:
    lock = (ROOT / "packaging/requirements-win64-py312.lock").read_text(encoding="utf-8")
    for name in (
        "build-color",
        "build-ui",
        "qtpy",
        "pyside6-essentials",
        "shiboken6",
        "numpy",
        "scipy",
        "hidapi",
        "pyinstaller",
        "build",
        "setuptools",
        "wheel",
        "pefile",
        "twine",
    ):
        assert f"{name}==" in lock.lower()
    assert "pyqt5" not in lock.lower()
    assert "pyqt6" not in lock.lower()
    assert "pyside6-addons" not in lock.lower()
    assert "pyside6==" not in lock.lower()
    assert "file://" not in lock.lower()
    assert "git+" not in lock.lower()
    requirement_blocks = [block for block in lock.split("\n\n") if "==" in block]
    assert requirement_blocks
    assert all("--hash=sha256:" in block for block in requirement_blocks)
    assert "bfb261851badc03b9b276c17f93e61a1fee4e86ee58d60960b1f130cfa8b7d1e" in lock
