"""Materialize a generated bundle on disk so an apply plan can pin it.

An apply plan names external files by path and digest, and the actuator reads
those files back and refuses any whose bytes moved between the confirmation and
the write. Nothing can pin what has not been written, so a bundle a session
holds in memory has to reach the filesystem before a plan can request it. This
module is that step, and it owns where those files live: a directory beside the
diagnostics root, never the working directory and never a temporary path a
cleaner may reclaim while a confirmation is still outstanding.

Staging writes. It decides nothing. Which of the written files a plan requests
is planning's answer, because that depends on what the bundle changes and on
what the machine was detected to support.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from calibrate_pro.application.assets import AssetFormat, GeneratedAssets
from calibrate_pro.application.journal import resolve_diagnostic_root

__all__ = [
    "STAGING_DIRECTORIES_RETAINED",
    "StagedBundle",
    "StagingError",
    "prune_staging_root",
    "resolve_staging_root",
    "stage_bundle",
]

#: Ceilings the actuator enforces when it reads a confirmed asset back. Refusing
#: an oversized file here reports the problem while the session can still act on
#: it, rather than at the moment a display is about to be written.
_SIZE_CEILINGS = {
    "icc": 64 * 1024 * 1024,
    "cube": 64 * 1024 * 1024,
    "vcgt": 16 * 1024 * 1024,
}

#: Staged bundles kept before the oldest are removed. A confirmation outstanding
#: against a pruned directory fails closed at the digest check, so this bound
#: costs a refusal at worst and never a wrong write.
STAGING_DIRECTORIES_RETAINED = 16

_TOKEN_LENGTH = 16


class StagingError(RuntimeError):
    """A bundle could not be written where an apply plan could pin it."""


@dataclass(frozen=True)
class StagedBundle:
    """Where each staged file landed, with the digest of the bytes on disk."""

    root: Path
    icc_profile_path: str
    icc_profile_sha256: str
    dwm_lut_path: str
    dwm_lut_sha256: str
    vcgt_path: str
    vcgt_sha256: str


def resolve_staging_root() -> Path:
    """Resolve the staging root as a sibling of the diagnostics inventory.

    Staged calibration files are inputs to a write, not diagnostic evidence, so
    they stay out of the directory a diagnostics bundle collects.
    """
    return resolve_diagnostic_root().parent / "Staging"


def stage_bundle(assets: GeneratedAssets, *, root: Path | None = None) -> StagedBundle:
    """Write one bundle's ICC, cube, and gamma table, then read each back.

    The directory name is derived from the bundle's own bytes, so staging the
    same bundle twice lands on the same files and a differing bundle can never
    overwrite a directory a pending confirmation still points at.
    """
    if not isinstance(assets, GeneratedAssets):
        raise TypeError("assets must be a GeneratedAssets")
    payloads = {
        "icc": _require_format(assets, AssetFormat.ICC),
        "cube": _require_format(assets, AssetFormat.CUBE),
        "vcgt": assets.gamma_table,
    }
    if not payloads["vcgt"]:
        raise StagingError("this bundle carries no gamma table")
    for label, payload in payloads.items():
        ceiling = _SIZE_CEILINGS[label]
        if len(payload) > ceiling:
            raise StagingError(f"staged {label} exceeds the supported {ceiling}-byte size limit")

    base = resolve_staging_root() if root is None else Path(root)
    if not base.is_absolute():
        raise StagingError("staging root must be an absolute path")
    directory = base / _token_for(assets, payloads)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StagingError(f"staging directory could not be created: {exc}") from exc

    basename = assets.request.basename
    names = {
        "icc": f"{basename}.icc",
        "cube": f"{basename}.cube",
        "vcgt": f"{basename}.cal",
    }
    written: dict[str, tuple[str, str]] = {}
    for label, payload in payloads.items():
        path = directory / names[label]
        written[label] = (str(path), _write_and_verify(path, payload))

    prune_staging_root(base, keep=STAGING_DIRECTORIES_RETAINED, protect=directory)
    return StagedBundle(
        root=directory,
        icc_profile_path=written["icc"][0],
        icc_profile_sha256=written["icc"][1],
        dwm_lut_path=written["cube"][0],
        dwm_lut_sha256=written["cube"][1],
        vcgt_path=written["vcgt"][0],
        vcgt_sha256=written["vcgt"][1],
    )


def prune_staging_root(
    root: Path,
    *,
    keep: int = STAGING_DIRECTORIES_RETAINED,
    protect: Path | None = None,
) -> int:
    """Remove the oldest staged directories beyond the retention bound.

    Returns how many were removed. A directory that resists removal is left
    where it is, because failing a staging call over an unreclaimed byte would
    block a calibration the operator asked for.
    """
    if keep < 1:
        raise ValueError("keep must be at least one directory")
    base = Path(root)
    if not base.is_dir():
        return 0
    entries = []
    for child in base.iterdir():
        if not child.is_dir() or (protect is not None and child == protect):
            continue
        try:
            entries.append((child.stat().st_mtime, child))
        except OSError:
            continue
    entries.sort(key=lambda item: item[0], reverse=True)
    removed = 0
    for _, child in entries[max(keep - 1, 0) :]:
        try:
            shutil.rmtree(child)
        except OSError:
            continue
        removed += 1
    return removed


def _require_format(assets: GeneratedAssets, fmt: AssetFormat) -> bytes:
    payload = assets.assets.get(fmt)
    if not payload:
        raise StagingError(f"this bundle carries no {fmt.value} payload")
    return payload


def _token_for(assets: GeneratedAssets, payloads: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    request = assets.request
    for part in (request.display_id, request.panel_key, request.preset_id, str(request.lut_size)):
        digest.update(part.encode("utf-8"))
        digest.update(bytes([0]))
    for label in sorted(payloads):
        digest.update(label.encode("ascii"))
        digest.update(hashlib.sha256(payloads[label]).digest())
    return digest.hexdigest()[:_TOKEN_LENGTH]


def _write_and_verify(path: Path, payload: bytes) -> str:
    """Write bytes durably, then digest what the filesystem hands back.

    Digesting the buffer that was written would certify the caller's own
    variable. The actuator reads this file, so the digest a plan pins has to be
    the digest of the file.
    """
    temporary = path.with_name(f"{path.name}.partial")
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise StagingError(f"{path.name} could not be staged: {exc}") from exc
    readback = path.read_bytes()
    if readback != payload:
        raise StagingError(f"{path.name} did not read back as written")
    return hashlib.sha256(readback).hexdigest()
