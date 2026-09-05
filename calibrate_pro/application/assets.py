"""Deterministic calibration asset generation and all-or-nothing publication.

Two properties are load bearing here.

Determinism: one request produces one exact byte sequence per format. No wall
clock, no random identifier, and no absolute path reaches an artifact, so a
digest recorded in a manifest stays checkable later and on another machine.

Atomicity: a publish either places every requested file plus its manifest, or
it places nothing. Files are staged inside the destination, renamed into place,
and rolled back when any rename fails. A caller never sees a half-written
bundle reported as a success.

The generated model is sensorless. Every artifact this module produces is
labeled ``EvidenceKind.ESTIMATED`` and never ``MEASURED``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from calibrate_pro import __version__
from calibrate_pro.application.actions import PRESET_TARGETS
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.core.lut_engine import LUT3D, LUTFormat
from calibrate_pro.panels.database import (
    GENERIC_PANEL_KEY,
    PanelCharacterization,
    PanelDatabase,
    get_database,
)
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.verification.provenance import EvidenceKind

#: ICC profiles carry a creation stamp. A wall-clock value would make every
#: generated profile a different file, so the stamp is fixed and the real
#: publication time is recorded by the diagnostic journal instead.
FIXED_ICC_CREATION_DATE = datetime(2026, 1, 1, 0, 0, 0)

SUPPORTED_LUT_SIZES = frozenset({17, 33, 65})
MANIFEST_FILENAME = "calibrate-pro-manifest.json"
MANIFEST_SCHEMA = 1

_STAGING_PREFIX = ".calibrate-pro-staging-"
_BACKUP_DIRNAME = "replaced"


class AssetFormat(str, Enum):
    """A calibration artifact this application can generate end to end."""

    ICC = "icc"
    CUBE = "cube"
    THREE_DL = "3dl"
    CSP = "csp"
    CLF = "clf"
    MADVR = "3dlut"
    RESHADE_PNG = "png"
    MPV = "mpv"
    OBS = "obs"

    @classmethod
    def text_formats(cls) -> frozenset[AssetFormat]:
        """Formats whose bytes are newline-normalized before publication."""
        return frozenset({cls.CUBE, cls.THREE_DL, cls.CSP, cls.CLF, cls.MPV, cls.OBS})


_SUFFIXES: Mapping[AssetFormat, str] = MappingProxyType(
    {
        AssetFormat.ICC: ".icc",
        AssetFormat.CUBE: ".cube",
        AssetFormat.THREE_DL: ".3dl",
        AssetFormat.CSP: ".csp",
        AssetFormat.CLF: ".clf",
        AssetFormat.MADVR: ".3dlut",
        AssetFormat.RESHADE_PNG: ".png",
        AssetFormat.MPV: ".conf",
        AssetFormat.OBS: "_obs.cube",
    }
)

#: Preset gamut label to the gamut mode understood by the sensorless engine.
_GAMUT_MODES: Mapping[str, str] = MappingProxyType(
    {
        "sRGB": "sRGB",
        "Rec.709": "sRGB",
        "DCI-P3": "p3",
        "Native": "native",
    }
)

#: Preset tone-response label to the power-law exponent actually applied.
#: BT.1886 with a zero black level reduces to a 2.4 power law.
_TONE_RESPONSE_EXPONENTS: Mapping[str, float] = MappingProxyType(
    {
        "2.2": 2.2,
        "2.4": 2.4,
        "BT.1886": 2.4,
    }
)


class BundlePublishError(Exception):
    """A publish was refused or rolled back; no partial output was left."""


class AssetGenerationError(Exception):
    """A requested artifact could not be generated from the given inputs."""


def _require_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a nonblank string")
    return value


@dataclass(frozen=True)
class AssetRequest:
    """Everything needed to reproduce one bundle, and nothing else."""

    display_id: str
    panel_key: str
    preset_id: str
    formats: tuple[AssetFormat, ...]
    lut_size: int = 33
    basename: str = "Calibrate_Pro"

    def __post_init__(self) -> None:
        _require_text(self.display_id, field_name="display_id")
        _require_text(self.panel_key, field_name="panel_key")
        _require_text(self.basename, field_name="basename")
        if self.preset_id not in PRESET_TARGETS:
            raise ValueError(f"unknown calibration preset: {self.preset_id!r}")
        if not isinstance(self.formats, tuple) or not self.formats:
            raise TypeError("formats must be a nonempty tuple of AssetFormat members")
        for member in self.formats:
            if type(member) is not AssetFormat:
                raise TypeError(f"formats must contain AssetFormat members; found {member!r}")
        if len(set(self.formats)) != len(self.formats):
            raise ValueError("formats must not repeat a member")
        if self.lut_size not in SUPPORTED_LUT_SIZES:
            raise ValueError(f"lut_size must be one of {sorted(SUPPORTED_LUT_SIZES)}")
        if Path(self.basename).name != self.basename or self.basename in {".", ".."}:
            raise ValueError("basename must be a plain file name without a path")

    def filename_for(self, fmt: AssetFormat) -> str:
        return f"{self.basename}{_SUFFIXES[fmt]}"


@dataclass(frozen=True)
class GeneratedAssets:
    """In-memory artifacts plus the evidence labels that describe them."""

    request: AssetRequest
    assets: Mapping[AssetFormat, bytes]
    panel_name: str
    characterization_kind: CharacterizationKind
    evidence_kind: EvidenceKind
    gamut_mode: str
    tone_response: str
    applied_gamma_exponent: float
    white_point: str

    def digest_for(self, fmt: AssetFormat) -> str:
        return hashlib.sha256(self.assets[fmt]).hexdigest()


@dataclass(frozen=True)
class PublishedAsset:
    """One file as it exists on disk after a successful publish."""

    format: str
    filename: str
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class ExportBundle:
    """The result of one atomic publish."""

    directory: str
    assets: tuple[PublishedAsset, ...]
    manifest_filename: str
    manifest_sha256: str
    evidence_kind: str
    characterization_kind: str

    @property
    def published_artifact(self) -> tuple[str, str]:
        """Name the one file that seals this publish, with its digest.

        The action journal records a local write as an effect only when the
        outcome can name what landed on disk. The manifest carries the digest of
        every asset in the bundle, so its own digest changes whenever any asset
        changes. That makes the manifest the honest single witness for the whole
        publish, and it is a filename rather than a path, so no export location
        reaches the journal.
        """
        return (self.manifest_filename, self.manifest_sha256)


class AssetGenerator:
    """Turn a request into byte-exact artifacts without touching a display."""

    def __init__(
        self,
        engine: SensorlessEngine | None = None,
        database: PanelDatabase | None = None,
    ) -> None:
        self._database = database or get_database()
        self._engine = engine or SensorlessEngine(self._database)

    def resolve_panel(self, panel_key: str) -> tuple[PanelCharacterization, CharacterizationKind]:
        """Return a characterization and say plainly where it came from.

        Asking for the generic key by name is a deliberate generic choice, so it
        answers EXPLICIT_GENERIC even though the database holds a record under
        that key. Reporting it as MATCHED would let a session that never
        recognized its display claim a characterized panel.
        """
        if panel_key == GENERIC_PANEL_KEY:
            return self._database.get_fallback(), CharacterizationKind.EXPLICIT_GENERIC
        panel = self._database.get_panel(panel_key) or self._database.find_panel(panel_key)
        if panel is not None:
            return panel, CharacterizationKind.MATCHED
        return self._database.get_fallback(), CharacterizationKind.EXPLICIT_GENERIC

    def generate(self, request: AssetRequest) -> GeneratedAssets:
        """Generate every requested format from one characterization."""
        if not isinstance(request, AssetRequest):
            raise TypeError("request must be an AssetRequest")

        panel, characterization_kind = self.resolve_panel(request.panel_key)
        gamut_label, white_point, tone_response, target_hdr = PRESET_TARGETS[request.preset_id]
        gamut_mode = _GAMUT_MODES.get(gamut_label, "native")
        exponent = _TONE_RESPONSE_EXPONENTS.get(tone_response, 2.2)

        lut = self._engine.create_3d_lut(
            panel,
            size=request.lut_size,
            lut_name=f"Calibrate Pro - {panel.name} ({gamut_label} {tone_response})",
            hdr_mode=bool(target_hdr),
            target=gamut_mode,
            target_gamma=exponent,
        )

        payloads = self._render(request, panel, lut)
        return GeneratedAssets(
            request=request,
            assets=MappingProxyType(payloads),
            panel_name=panel.name,
            characterization_kind=characterization_kind,
            evidence_kind=EvidenceKind.ESTIMATED,
            gamut_mode=gamut_mode,
            tone_response=tone_response,
            applied_gamma_exponent=exponent,
            white_point=white_point,
        )

    def _render(
        self,
        request: AssetRequest,
        panel: PanelCharacterization,
        lut: LUT3D,
    ) -> dict[AssetFormat, bytes]:
        """Write each format through its tested writer, then read it back."""
        payloads: dict[AssetFormat, bytes] = {}
        staging = Path(tempfile.mkdtemp(prefix="calibrate-pro-render-"))
        try:
            for fmt in request.formats:
                path = staging / request.filename_for(fmt)
                self._write_one(fmt, path, request, panel, lut)
                if not path.is_file():
                    raise AssetGenerationError(f"{fmt.value} writer produced no file")
                raw = path.read_bytes()
                if not raw:
                    raise AssetGenerationError(f"{fmt.value} writer produced an empty file")
                payloads[fmt] = _normalize(fmt, raw)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return payloads

    def _write_one(
        self,
        fmt: AssetFormat,
        path: Path,
        request: AssetRequest,
        panel: PanelCharacterization,
        lut: LUT3D,
    ) -> None:
        if fmt is AssetFormat.ICC:
            profile = self._engine.create_icc_profile(panel)
            profile.header.creation_date = FIXED_ICC_CREATION_DATE
            profile.save(path)
        elif fmt is AssetFormat.CUBE:
            lut.save(path, LUTFormat.CUBE)
        elif fmt is AssetFormat.THREE_DL:
            lut.save(path, LUTFormat.DL3)
        elif fmt is AssetFormat.CSP:
            lut.save(path, LUTFormat.CSP)
        elif fmt is AssetFormat.CLF:
            lut.save_clf(path)
        elif fmt is AssetFormat.MADVR:
            lut.save_madvr_3dlut(path)
        elif fmt is AssetFormat.RESHADE_PNG:
            lut.save_reshade_png(path)
        elif fmt is AssetFormat.OBS:
            lut.save_obs_lut(path)
        elif fmt is AssetFormat.MPV:
            # Reference the sibling files by name so the snippet keeps working
            # wherever the bundle is copied, and so no local path is embedded.
            lut.save_mpv_config(
                lut_path=request.filename_for(AssetFormat.CUBE),
                icc_path=request.filename_for(AssetFormat.ICC),
                output_path=path,
            )
        else:  # pragma: no cover - the enum is closed and validated on request
            raise AssetGenerationError(f"no writer is registered for {fmt!r}")


def _normalize(fmt: AssetFormat, raw: bytes) -> bytes:
    """Give text artifacts one newline convention so digests travel."""
    if fmt not in AssetFormat.text_formats():
        return raw
    return raw.replace(b"\r\n", b"\n")


def build_manifest(generated: GeneratedAssets) -> bytes:
    """Serialize the bundle description. Deterministic, no wall clock."""
    request = generated.request
    document = {
        "schema": MANIFEST_SCHEMA,
        "generator": "calibrate-pro",
        "generator_version": __version__,
        "display_id": request.display_id,
        "panel_key": request.panel_key,
        "panel_name": generated.panel_name,
        "characterization_kind": generated.characterization_kind.value,
        "evidence_kind": generated.evidence_kind.value,
        "preset_id": request.preset_id,
        "target": {
            "gamut_mode": generated.gamut_mode,
            "white_point": generated.white_point,
            "tone_response": generated.tone_response,
            "applied_gamma_exponent": generated.applied_gamma_exponent,
        },
        "lut_size": request.lut_size,
        "assets": [
            {
                "format": fmt.value,
                "filename": request.filename_for(fmt),
                "sha256": generated.digest_for(fmt),
                "bytes": len(generated.assets[fmt]),
            }
            for fmt in sorted(generated.assets, key=lambda member: member.value)
        ],
    }
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_durable(path: Path, payload: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def publish_bundle(
    generated: GeneratedAssets,
    directory: str | Path,
    *,
    overwrite: bool = False,
) -> ExportBundle:
    """Place every artifact and its manifest, or place nothing at all."""
    if not isinstance(generated, GeneratedAssets):
        raise TypeError("generated must be a GeneratedAssets value")

    destination = Path(directory)
    if destination.exists() and not destination.is_dir():
        raise BundlePublishError(f"export destination is not a directory: {destination}")

    request = generated.request
    payloads: dict[str, bytes] = {request.filename_for(fmt): generated.assets[fmt] for fmt in generated.assets}
    manifest = build_manifest(generated)
    payloads[MANIFEST_FILENAME] = manifest

    created_destination = not destination.exists()
    if created_destination:
        try:
            destination.mkdir(parents=True)
        except OSError as exc:
            raise BundlePublishError(f"export directory could not be created: {exc}") from exc

    collisions = sorted(name for name in payloads if (destination / name).exists())
    if collisions and not overwrite:
        if created_destination:
            _remove_quietly(destination)
        raise BundlePublishError(
            "refusing to replace files that already exist in the export directory: " + ", ".join(collisions)
        )

    staging = Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=destination))
    backups = staging / _BACKUP_DIRNAME
    moved: list[str] = []
    replaced: list[str] = []
    try:
        backups.mkdir()
        for name, payload in sorted(payloads.items()):
            _write_durable(staging / name, payload)
        for name in sorted(payloads):
            target = destination / name
            if target.exists():
                os.replace(target, backups / name)
                replaced.append(name)
            os.replace(staging / name, target)
            moved.append(name)
    except Exception as exc:
        _roll_back(destination, backups, moved, replaced)
        _remove_quietly(staging)
        if created_destination:
            _remove_quietly(destination)
        raise BundlePublishError(f"export was rolled back: {exc}") from exc

    _remove_quietly(staging)
    published = tuple(
        PublishedAsset(
            format=fmt.value,
            filename=request.filename_for(fmt),
            sha256=generated.digest_for(fmt),
            byte_count=len(generated.assets[fmt]),
        )
        for fmt in sorted(generated.assets, key=lambda member: member.value)
    )
    return ExportBundle(
        directory=str(destination),
        assets=published,
        manifest_filename=MANIFEST_FILENAME,
        manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        evidence_kind=generated.evidence_kind.value,
        characterization_kind=generated.characterization_kind.value,
    )


def _roll_back(
    destination: Path,
    backups: Path,
    moved: list[str],
    replaced: list[str],
) -> None:
    """Undo a partial publish. Best effort, and it never raises."""
    for name in moved:
        try:
            (destination / name).unlink()
        except OSError:
            pass
    for name in replaced:
        try:
            os.replace(backups / name, destination / name)
        except OSError:
            pass


def _remove_quietly(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "FIXED_ICC_CREATION_DATE",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA",
    "SUPPORTED_LUT_SIZES",
    "AssetFormat",
    "AssetGenerationError",
    "AssetGenerator",
    "AssetRequest",
    "BundlePublishError",
    "ExportBundle",
    "GeneratedAssets",
    "PublishedAsset",
    "build_manifest",
    "publish_bundle",
]
