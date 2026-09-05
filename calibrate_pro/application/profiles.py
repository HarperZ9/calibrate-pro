"""Reading back the bundles this application published, and proving they hold.

The profiles surface used to list files it found by globbing a folder this
application never writes to, and it described each one with figures nobody
recorded: a white point and a gamma printed as facts, and a gamut guessed from
the filename. None of that came from the bundle being described.

A published bundle already describes itself. ``publish_bundle`` writes a
manifest naming every file, the digest of each one, and the target the assets
were generated for, so reading that manifest back is enough. What a surface
shows is then what the generator recorded, rather than what the surface assumed.

Re-hashing turns a listing into a claim. A bundle is intact when every file its
manifest names is present and still hashes to the digest the manifest recorded,
and it is that answer, per file, that this module reports. A directory holding a
manifest this build cannot read stays in the listing with the reason attached,
because a bundle that has become unreadable is something an operator needs to
see.

Nothing here writes. Copying a bundle somewhere else is an action, and it goes
through the exporter.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from calibrate_pro.application.assets import MANIFEST_FILENAME, MANIFEST_SCHEMA


class ManifestError(ValueError):
    """A manifest was missing a field, or was not one this build can read."""


@dataclass(frozen=True)
class ProfileAsset:
    """One file a manifest names, with the digest recorded when it was written."""

    format: str
    filename: str
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class ProfileTarget:
    """The target a bundle was generated for, as its manifest recorded it."""

    preset_id: str
    gamut_mode: str
    white_point: str
    tone_response: str
    applied_gamma_exponent: float


@dataclass(frozen=True)
class ProfileRecord:
    """One published bundle, described entirely by its own manifest."""

    name: str
    directory: str
    manifest_sha256: str
    display_id: str
    panel_key: str
    panel_name: str
    characterization_kind: str
    evidence_kind: str
    lut_size: int
    target: ProfileTarget
    assets: tuple[ProfileAsset, ...]

    @property
    def byte_count(self) -> int:
        """Total size of the named files, as the manifest recorded them."""
        return sum(asset.byte_count for asset in self.assets)


@dataclass(frozen=True)
class UnreadableProfile:
    """A directory holding a manifest this build could not read, and why."""

    name: str
    directory: str
    reason: str


@dataclass(frozen=True)
class ProfileListing:
    """Every bundle found under one directory, readable or not.

    Three answers end in no profiles and they are not the same answer.
    ``directory`` is ``None`` when the session has nowhere to look, so nobody
    ever said where the bundles were. ``existed`` is false when a directory was
    named and there was nothing at that path to read. Both differ from a
    directory that was read and held none, and a surface reporting them alike
    tells an operator their bundles are gone.
    """

    directory: str | None
    profiles: tuple[ProfileRecord, ...]
    unreadable: tuple[UnreadableProfile, ...]
    existed: bool

    @property
    def searched(self) -> bool:
        return self.directory is not None


@dataclass(frozen=True)
class AssetCheck:
    """One named file, re-hashed and compared against its recorded digest."""

    filename: str
    expected_sha256: str
    actual_sha256: str | None
    matched: bool

    @property
    def present(self) -> bool:
        return self.actual_sha256 is not None


@dataclass(frozen=True)
class ProfileInspection:
    """The result of re-hashing every file one manifest names."""

    record: ProfileRecord
    checks: tuple[AssetCheck, ...]

    @property
    def sealed(self) -> bool:
        """Report whether every named file is present and unchanged."""
        return bool(self.checks) and all(check.matched for check in self.checks)

    @property
    def broken(self) -> tuple[AssetCheck, ...]:
        """Name the files that are missing or no longer match."""
        return tuple(check for check in self.checks if not check.matched)


def read_manifest(directory: str | Path) -> ProfileRecord:
    """Read one bundle's manifest, refusing anything this build cannot read.

    Every field is required. A manifest missing one is reported as unreadable
    rather than filled in with a default, because a default here would reach a
    surface as a figure presented as recorded when nobody recorded it.
    """
    path = Path(directory)
    raw = (path / MANIFEST_FILENAME).read_bytes()
    document = json.loads(raw.decode("utf-8"))
    if not isinstance(document, dict):
        raise ManifestError("the manifest is not a JSON object")
    schema = document.get("schema")
    if schema != MANIFEST_SCHEMA:
        raise ManifestError(f"the manifest declares schema {schema!r}, and this build reads {MANIFEST_SCHEMA}")
    assets = document.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ManifestError("the manifest names no assets")
    return ProfileRecord(
        name=path.name,
        directory=str(path),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        display_id=_text(document, "display_id"),
        panel_key=_text(document, "panel_key"),
        panel_name=_text(document, "panel_name"),
        characterization_kind=_text(document, "characterization_kind"),
        evidence_kind=_text(document, "evidence_kind"),
        lut_size=_whole(document, "lut_size"),
        target=_target(document),
        assets=tuple(_asset(entry) for entry in assets),
    )


def discover_profiles(directory: str | Path | None) -> ProfileListing:
    """List every bundle published at or one level below one directory.

    One level is the depth this application writes: a whole-bundle export puts
    its manifest in the chosen directory, and a single-format export puts one in
    a subdirectory named for the format. Walking deeper would list bundles this
    application did not produce and cannot describe.
    """
    if directory is None:
        return ProfileListing(directory=None, profiles=(), unreadable=(), existed=False)
    root = Path(directory)
    existed = root.is_dir()
    found: list[ProfileRecord] = []
    unreadable: list[UnreadableProfile] = []
    for candidate in _bundle_directories(root):
        try:
            found.append(read_manifest(candidate))
        except (OSError, ValueError) as exc:
            unreadable.append(UnreadableProfile(name=candidate.name, directory=str(candidate), reason=str(exc)))
    found.sort(key=lambda record: record.directory)
    unreadable.sort(key=lambda entry: entry.directory)
    return ProfileListing(directory=str(root), profiles=tuple(found), unreadable=tuple(unreadable), existed=existed)


def reparse_profile(record: ProfileRecord) -> ProfileInspection:
    """Re-hash every file the manifest names and report each answer."""
    directory = Path(record.directory)
    checks = tuple(_check(directory / asset.filename, asset.sha256) for asset in record.assets)
    return ProfileInspection(record=record, checks=checks)


def _bundle_directories(root: Path) -> list[Path]:
    """Name the directories holding a manifest, at the depth this build writes."""
    if not root.is_dir():
        return []
    found = [root] if (root / MANIFEST_FILENAME).is_file() else []
    try:
        children = sorted(root.iterdir())
    except OSError:
        return found
    found.extend(child for child in children if (child / MANIFEST_FILENAME).is_file())
    return found


def _check(path: Path, expected: str) -> AssetCheck:
    """Compare one file against its recorded digest, or report it missing."""
    try:
        actual: str | None = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        actual = None
    return AssetCheck(
        filename=path.name,
        expected_sha256=expected,
        actual_sha256=actual,
        matched=actual == expected,
    )


def _target(document: Mapping[str, object]) -> ProfileTarget:
    target = document.get("target")
    if not isinstance(target, dict):
        raise ManifestError("the manifest records no target")
    return ProfileTarget(
        preset_id=_text(document, "preset_id"),
        gamut_mode=_text(target, "gamut_mode"),
        white_point=_text(target, "white_point"),
        tone_response=_text(target, "tone_response"),
        applied_gamma_exponent=_real(target, "applied_gamma_exponent"),
    )


def _asset(entry: object) -> ProfileAsset:
    if not isinstance(entry, dict):
        raise ManifestError("an asset entry is not a JSON object")
    return ProfileAsset(
        format=_text(entry, "format"),
        filename=_text(entry, "filename"),
        sha256=_text(entry, "sha256"),
        byte_count=_whole(entry, "bytes"),
    )


def _text(document: Mapping[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise ManifestError(f"the manifest records no {key}")
    return value


def _whole(document: Mapping[str, object], key: str) -> int:
    value = document.get(key)
    if type(value) is not int or value < 0:
        raise ManifestError(f"the manifest records no {key}")
    return value


def _real(document: Mapping[str, object], key: str) -> float:
    value = document.get(key)
    if type(value) is int or type(value) is float:
        return float(value)
    raise ManifestError(f"the manifest records no {key}")


__all__ = [
    "AssetCheck",
    "ManifestError",
    "ProfileAsset",
    "ProfileInspection",
    "ProfileListing",
    "ProfileRecord",
    "ProfileTarget",
    "UnreadableProfile",
    "discover_profiles",
    "read_manifest",
    "reparse_profile",
]
