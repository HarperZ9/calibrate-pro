"""Verify the exact, fully checksummed Calibrate Pro GitHub asset set."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

try:  # imported as `scripts.verify_release_asset_set` from the test suite
    from scripts.product_version import INSTALLER_NAME, PORTABLE_NAME, SDIST_NAME, WHEEL_NAME
except ModuleNotFoundError:  # run as `python scripts/verify_release_asset_set.py`
    from product_version import INSTALLER_NAME, PORTABLE_NAME, SDIST_NAME, WHEEL_NAME

REQUIRED_RELEASE_ASSETS = frozenset(
    {
        INSTALLER_NAME,
        PORTABLE_NAME,
        WHEEL_NAME,
        SDIST_NAME,
        "binary-provenance.json",
        "build-receipt.json",
        "component-inventory.json",
        "package-receipt.json",
        "pe-manifest-inventory.json",
        "pre-sign-audit.json",
        "qt-module-inventory.json",
        "signature-inventory.json",
        "source-provenance.json",
        "staged-inventory.json",
    }
)
CHECKSUM_NAME = "SHA256SUMS.txt"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_release_asset_set(release_dir: str | Path) -> list[dict[str, object]]:
    """Require exactly the approved assets and verify every byte against SHA256SUMS."""
    release = Path(release_dir).resolve()
    if not release.is_dir():
        raise FileNotFoundError(release)
    checksum_path = release / CHECKSUM_NAME
    if not checksum_path.is_file():
        raise FileNotFoundError(checksum_path)

    records: dict[str, str] = {}
    for line_number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            digest, name = line.split("  ", 1)
        except ValueError as exc:
            raise ValueError(f"invalid checksum line {line_number}") from exc
        path = PurePosixPath(name)
        if path.is_absolute() or len(path.parts) != 1 or ".." in path.parts:
            raise ValueError(f"unsafe release asset name: {name}")
        if len(digest) != 64:
            raise ValueError(f"invalid SHA-256 on line {line_number}")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise ValueError(f"invalid SHA-256 on line {line_number}") from exc
        if name in records:
            raise ValueError(f"duplicate checksum entry: {name}")
        records[name] = digest.lower()

    actual_names = {path.name for path in release.iterdir() if path.is_file() and path.name != CHECKSUM_NAME}
    if actual_names != REQUIRED_RELEASE_ASSETS:
        missing = sorted(REQUIRED_RELEASE_ASSETS - actual_names)
        unexpected = sorted(actual_names - REQUIRED_RELEASE_ASSETS)
        raise RuntimeError(f"release asset set mismatch; missing={missing!r}; unexpected={unexpected!r}")
    if set(records) != actual_names:
        missing = sorted(actual_names - set(records))
        stale = sorted(set(records) - actual_names)
        raise RuntimeError(f"checksum inventory mismatch; missing={missing!r}; stale={stale!r}")

    verified: list[dict[str, object]] = []
    for name in sorted(records):
        path = release / name
        actual = _sha256(path)
        if actual != records[name]:
            raise RuntimeError(f"SHA-256 mismatch for {name}: expected {records[name]}, got {actual}")
        verified.append({"name": name, "size": path.stat().st_size, "sha256": actual})
    return verified


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_dir")
    args = parser.parse_args(argv)
    verified = verify_release_asset_set(args.release_dir)
    print(f"release-assets=pass count={len(verified)}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
