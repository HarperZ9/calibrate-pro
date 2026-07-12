"""Exact public release-asset contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.release_artifacts import write_sha256s
from scripts.verify_release_asset_set import REQUIRED_RELEASE_ASSETS, verify_release_asset_set


def complete_release(tmp_path: Path) -> Path:
    release = tmp_path / "release"
    release.mkdir()
    for name in REQUIRED_RELEASE_ASSETS:
        (release / name).write_bytes((name + "\n").encode("utf-8"))
    write_sha256s(release)
    return release


def test_exact_release_asset_set_passes(tmp_path: Path) -> None:
    release = complete_release(tmp_path)

    verified = verify_release_asset_set(release)

    assert {item["name"] for item in verified} == REQUIRED_RELEASE_ASSETS


def test_unexpected_or_missing_asset_fails_closed(tmp_path: Path) -> None:
    release = complete_release(tmp_path)
    (release / "unexpected.bin").write_bytes(b"unexpected")

    with pytest.raises(RuntimeError, match="asset set mismatch"):
        verify_release_asset_set(release)


def test_unlisted_or_tampered_asset_fails_closed(tmp_path: Path) -> None:
    release = complete_release(tmp_path)
    checksum = release / "SHA256SUMS.txt"
    lines = checksum.read_text(encoding="utf-8").splitlines()
    checksum.write_text("\n".join(lines[1:]) + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="checksum inventory"):
        verify_release_asset_set(release)

    write_sha256s(release)
    target = release / "build-receipt.json"
    target.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        verify_release_asset_set(release)
