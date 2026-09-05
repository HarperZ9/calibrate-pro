"""Publishing a sealed bundle to disk, and the rules a directory must pass.

Everything here writes files and nothing here writes to a display. That is the
whole of the local_file_write surface: a directory the session chose, bytes the
generator already produced, and a manifest that seals exactly what was placed.

A publish is refused rather than guessed at. No directory, no generated bundle,
or no asset in the requested format each produce a stated refusal, so an
operator is never shown a success for a file that does not exist.
"""

from __future__ import annotations

from pathlib import Path

from calibrate_pro.application.assets import AssetFormat, ExportBundle, GeneratedAssets, publish_bundle
from calibrate_pro.application.planning import restrict_assets
from calibrate_pro.application.refusals import (
    export_failed,
    no_export_directory,
    no_sealed_plan,
    no_such_asset,
)
from calibrate_pro.application.results import ExportDirectory
from calibrate_pro.application.session import EXPORTABLE_FORMATS, SessionState

#: Reverse of the session's export map, so an export action id names the format
#: it publishes without a second table that could drift from the first.
FORMAT_BY_EXPORT_NAME: dict[str, AssetFormat] = {name: fmt for fmt, name in EXPORTABLE_FORMATS.items()}


def choose_directory(state: SessionState, directory: str | Path) -> ExportDirectory:
    """Record an export directory and whether it can be written to.

    A path that does not exist yet is accepted when its parent is a directory,
    because publishing creates the leaf. Anything else is recorded as invalid,
    and the resolver disables every export action while it stays that way.
    """
    path = Path(directory)
    valid = path.is_dir() or (not path.exists() and path.parent.is_dir())
    state.export_directory = str(path)
    state.export_directory_valid = valid
    return ExportDirectory(directory=str(path), valid=valid)


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
    except OSError as exc:
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


__all__ = [
    "FORMAT_BY_EXPORT_NAME",
    "choose_directory",
    "export_bundle",
    "export_single_format",
    "publish",
    "require_directory",
]
