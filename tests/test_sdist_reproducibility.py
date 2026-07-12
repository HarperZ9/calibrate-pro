"""Deterministic and fail-closed source-distribution normalization tests."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

import pytest

from scripts.normalize_sdist import normalize_sdist

EPOCH = 315532800
SDIST_NAME = "calibrate_pro-1.1.0.tar.gz"
ROOT_NAME = "calibrate_pro-1.1.0"


def _write_sdist(path: Path, *, mtime: int, reverse: bool = False) -> None:
    path.parent.mkdir(parents=True)
    entries = [
        (ROOT_NAME, None),
        (f"{ROOT_NAME}/package", None),
        (f"{ROOT_NAME}/package/__init__.py", b'VERSION = "1.1.0"\n'),
        (f"{ROOT_NAME}/pyproject.toml", b"[build-system]\n"),
        (f"{ROOT_NAME}/PKG-INFO", b"Metadata-Version: 2.4\nName: calibrate-pro\nVersion: 1.1.0\n"),
    ]
    if reverse:
        entries.reverse()
    with path.open("wb") as output:
        with gzip.GzipFile(filename=path.name, mode="wb", fileobj=output, mtime=mtime) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for name, payload in entries:
                    info = tarfile.TarInfo(name)
                    info.mtime = mtime + len(name) / 1000
                    info.mode = 0o755 if payload is None else 0o644
                    if payload is None:
                        info.type = tarfile.DIRTYPE
                        archive.addfile(info)
                    else:
                        info.size = len(payload)
                        archive.addfile(info, io.BytesIO(payload))


def test_normalize_sdist_makes_order_and_timestamps_reproducible(tmp_path: Path) -> None:
    left = tmp_path / "left" / SDIST_NAME
    right = tmp_path / "right" / SDIST_NAME
    _write_sdist(left, mtime=1_700_000_001)
    _write_sdist(right, mtime=1_800_000_009, reverse=True)

    left_hash = normalize_sdist(left, epoch=EPOCH)
    right_hash = normalize_sdist(right, epoch=EPOCH)

    assert left_hash == right_hash
    assert left.read_bytes() == right.read_bytes()
    assert int.from_bytes(left.read_bytes()[4:8], "little") == EPOCH
    with tarfile.open(left, "r:gz") as archive:
        members = archive.getmembers()
        assert [member.name for member in members] == sorted(member.name for member in members)
        assert all(member.mtime == EPOCH for member in members)
        assert all(not ({"mtime", "atime", "ctime"} & member.pax_headers.keys()) for member in members)
        assert archive.extractfile(f"{ROOT_NAME}/package/__init__.py").read() == b'VERSION = "1.1.0"\n'


def test_normalize_sdist_rejects_unsafe_member_paths(tmp_path: Path) -> None:
    path = tmp_path / SDIST_NAME
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo(f"{ROOT_NAME}/../escape.txt")
        payload = b"escape"
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    with pytest.raises(ValueError, match="unsafe|root"):
        normalize_sdist(path, epoch=EPOCH)
