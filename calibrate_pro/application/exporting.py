"""Publishing a sealed bundle to disk, and the rules a directory must pass.

Everything here writes files and nothing here writes to a display. That is the
whole of the local_file_write surface: a directory the session chose, bytes the
generator already produced, and a manifest that seals exactly what was placed.

A publish is refused rather than guessed at. No directory, no generated bundle,
or no asset in the requested format each produce a stated refusal, so an
operator is never shown a success for a file that does not exist.

Copying a bundle that was already published is the same kind of write, and it
keeps the same guarantee: the copy carries the original manifest, every file is
re-hashed on the way out, and a bundle that has drifted from its manifest is
refused instead of duplicated.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from calibrate_pro.application.assets import (
    MANIFEST_FILENAME,
    AssetFormat,
    BundlePublishError,
    ExportBundle,
    GeneratedAssets,
    PublishedAsset,
    place_atomically,
    publish_bundle,
)
from calibrate_pro.application.planning import restrict_assets
from calibrate_pro.application.profiles import ProfileRecord
from calibrate_pro.application.refusals import (
    export_failed,
    no_export_directory,
    no_sealed_plan,
    no_such_asset,
    no_verified_profile,
    profile_seal_broken,
)
from calibrate_pro.application.results import ExportDirectory
from calibrate_pro.application.session import EXPORTABLE_FORMATS, SessionState

#: Reverse of the session's export map, so an export action id names the format
#: it publishes without a second table that could drift from the first.
FORMAT_BY_EXPORT_NAME: dict[str, AssetFormat] = {name: fmt for fmt, name in EXPORTABLE_FORMATS.items()}


def _writable(path: Path) -> bool:
    """Report whether a publish could place files at this path.

    A path that does not exist yet passes when its parent is a directory,
    because publishing creates the leaf.
    """
    return path.is_dir() or (not path.exists() and path.parent.is_dir())


def choose_directory(state: SessionState, directory: str | Path) -> ExportDirectory:
    """Record an export directory and whether it can be written to.

    A path that fails the check is still recorded, as invalid, and the resolver
    disables every export action while it stays that way.
    """
    path = Path(directory)
    valid = _writable(path)
    state.export_directory = str(path)
    state.export_directory_valid = valid
    return ExportDirectory(directory=str(path), valid=valid)


def writable_directory(directory: str | Path) -> Path:
    """Apply the same rule to a directory given as an argument, recording none.

    An action that takes its destination as an argument needs the check without
    the recording, so both paths read one predicate and cannot disagree.
    """
    path = Path(directory)
    if not _writable(path):
        raise no_export_directory()
    return path


def require_directory(state: SessionState) -> Path:
    """Read the chosen directory, refusing when none has passed the check."""
    if state.export_directory is None or not state.export_directory_valid:
        raise no_export_directory()
    return Path(state.export_directory)


def publish(generated: GeneratedAssets | None, directory: Path) -> ExportBundle:
    """Write one bundle, converting a filesystem refusal into a retryable one."""
    if generated is None:
        raise no_sealed_plan()
    try:
        return publish_bundle(generated, directory, overwrite=True)
    except (OSError, BundlePublishError) as exc:
        raise export_failed() from exc


def export_bundle(state: SessionState) -> ExportBundle:
    """Publish every generated asset into the chosen directory."""
    return publish(state.generated, require_directory(state))


def export_single_format(state: SessionState, export_name: str) -> ExportBundle:
    """Publish one generated format into a subdirectory named for it.

    Each publish writes a manifest sealing exactly what it placed. Two publishes
    into one directory would leave a manifest describing only the later of them,
    so a single-format export gets a directory of its own.
    """
    fmt = FORMAT_BY_EXPORT_NAME.get(export_name)
    generated = state.generated
    if fmt is None or generated is None or fmt not in generated.assets:
        raise no_such_asset()
    return publish(restrict_assets(generated, fmt), require_directory(state) / export_name)


def copy_selected_profile(state: SessionState, directory: str | Path) -> ExportBundle:
    """Copy the profile this session inspected into a directory it is given.

    The copy carries the manifest bytes of the original rather than a manifest
    written here, so the digest that seals the source seals the copy and both
    can be checked against the same record. Every file is re-hashed as it is
    read; one that no longer matches stops the copy before anything is placed.
    """
    inspection = state.selected_profile
    if inspection is None:
        raise no_verified_profile()
    record = inspection.record
    destination = writable_directory(directory) / record.name
    try:
        place_atomically(destination, _sealed_payloads(record), overwrite=True)
    except (OSError, BundlePublishError) as exc:
        raise export_failed() from exc
    return _copied_bundle(record, destination)


def _sealed_payloads(record: ProfileRecord) -> dict[str, bytes]:
    """Read every file the manifest names, refusing any one that has changed."""
    source = Path(record.directory)
    payloads: dict[str, bytes] = {}
    for asset in record.assets:
        payload = (source / asset.filename).read_bytes()
        if hashlib.sha256(payload).hexdigest() != asset.sha256:
            raise profile_seal_broken()
        payloads[asset.filename] = payload
    manifest = (source / MANIFEST_FILENAME).read_bytes()
    if hashlib.sha256(manifest).hexdigest() != record.manifest_sha256:
        raise profile_seal_broken()
    payloads[MANIFEST_FILENAME] = manifest
    return payloads


def _copied_bundle(record: ProfileRecord, destination: Path) -> ExportBundle:
    """Describe the copy using the digests its own manifest already records."""
    return ExportBundle(
        directory=str(destination),
        assets=tuple(
            PublishedAsset(
                format=asset.format,
                filename=asset.filename,
                sha256=asset.sha256,
                byte_count=asset.byte_count,
            )
            for asset in record.assets
        ),
        manifest_filename=MANIFEST_FILENAME,
        manifest_sha256=record.manifest_sha256,
        evidence_kind=record.evidence_kind,
        characterization_kind=record.characterization_kind,
    )


__all__ = [
    "FORMAT_BY_EXPORT_NAME",
    "choose_directory",
    "copy_selected_profile",
    "export_bundle",
    "export_single_format",
    "publish",
    "require_directory",
    "writable_directory",
]
