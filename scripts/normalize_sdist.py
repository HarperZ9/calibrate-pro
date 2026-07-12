"""Rewrite a built ``.tar.gz`` sdist with canonical metadata and ordering."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import tarfile
import tempfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

_VOLATILE_PAX_KEYS = frozenset({"atime", "ctime", "gid", "gname", "mtime", "uid", "uname"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validated_members(source: Path, expected_root: str, *, epoch: int) -> list[tuple[tarfile.TarInfo, bytes]]:
    members: list[tuple[tarfile.TarInfo, bytes]] = []
    observed: set[str] = set()
    with tarfile.open(source, mode="r:gz") as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if (
                not member.name
                or "\\" in member.name
                or path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] != expected_root
            ):
                raise ValueError(f"unsafe or unexpected sdist root path: {member.name!r}")
            name = path.as_posix()
            if name in observed:
                raise ValueError(f"duplicate sdist member: {name}")
            observed.add(name)
            if not member.isfile() and not member.isdir():
                raise ValueError(f"unsupported sdist member type: {name}")

            payload = b""
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError(f"missing sdist member payload: {name}")
                payload = stream.read()
                if len(payload) != member.size:
                    raise ValueError(f"truncated sdist member payload: {name}")

            canonical = tarfile.TarInfo(name)
            canonical.type = tarfile.DIRTYPE if member.isdir() else tarfile.REGTYPE
            canonical.mode = 0o755 if member.isdir() else 0o644
            canonical.uid = 0
            canonical.gid = 0
            canonical.uname = ""
            canonical.gname = ""
            canonical.mtime = epoch
            canonical.size = len(payload)
            canonical.pax_headers = {
                key: value for key, value in member.pax_headers.items() if key not in _VOLATILE_PAX_KEYS
            }
            members.append((canonical, payload))

    if expected_root not in observed:
        raise ValueError(f"sdist is missing its root directory: {expected_root}")
    return sorted(members, key=lambda item: item[0].name)


def normalize_sdist(path: str | Path, *, epoch: int) -> str:
    """Atomically normalize one source distribution and return its SHA-256."""
    source = Path(path).resolve()
    if not source.is_file() or not source.name.endswith(".tar.gz"):
        raise ValueError(f"expected an existing .tar.gz sdist: {source}")
    if not 0 <= int(epoch) <= 0xFFFFFFFF:
        raise ValueError("source date epoch is outside the gzip timestamp range")
    epoch = int(epoch)
    expected_root = source.name.removesuffix(".tar.gz")
    members = _validated_members(source, expected_root, epoch=epoch)

    handle = tempfile.NamedTemporaryFile(
        dir=source.parent,
        prefix=f".{source.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    handle.close()
    try:
        with temporary.open("wb") as output:
            with gzip.GzipFile(filename="", mode="wb", fileobj=output, compresslevel=9, mtime=epoch) as compressed:
                with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                    for member, payload in members:
                        archive.addfile(member, io.BytesIO(payload) if member.isfile() else None)
        temporary.replace(source)
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256(source)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sdist")
    parser.add_argument("--source-date-epoch", required=True, type=int)
    args = parser.parse_args(argv)
    digest = normalize_sdist(args.sdist, epoch=args.source_date_epoch)
    print(f"sdist-normalized=pass sha256={digest}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
