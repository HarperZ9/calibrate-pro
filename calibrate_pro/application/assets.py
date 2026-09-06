"""Deterministic calibration asset generation and all-or-nothing publication.

Two properties are load bearing here.

Determinism: one request produces one exact byte sequence per format. No wall
clock, no random identifier, and no absolute path reaches an artifact, so a
digest recorded in a manifest stays checkable later and on another machine.

Atomicity: a publish either places every requested file plus its manifest, or
it places nothing. Files are staged inside the destination, renamed into place,
and rolled back when any rename fails. A caller never sees a half-written
bundle reported as a success.

Evidence follows the characterization, not the request. A bundle built from a
panel record is labeled ``EvidenceKind.ESTIMATED``, because the record
describes a product rather than the unit in front of the operator. A bundle
built from a display's own descriptor is labeled ``ESTIMATED`` too: the
primaries came off the display, but they are what the manufacturer wrote for
the model rather than what this unit emits. A bundle built from an instrument
run is labeled ``MEASURED``, and the only way to reach that label is to hand
``generate`` the measurement itself. The manifest then carries what the run
read, so a measured bundle can be told from a sensorless one by its contents
and not only by a word, and a declared bundle carries the numbers the display
declared for the same reason.
"""

from __future__ import annotations

import hashlib
import importlib
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
from typing import TYPE_CHECKING

from calibrate_pro import __version__
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.declaration import DeclaredCharacterization
from calibrate_pro.application.measurement import MeasuredCharacterization
from calibrate_pro.application.target_selection import (
    CalibrationTarget,
    is_target_id,
    resolve_target,
)
from calibrate_pro.core.lut_engine import LUT3D, LUTFormat
from calibrate_pro.panels.database import (
    GENERIC_PANEL_KEY,
    PanelCharacterization,
    PanelDatabase,
    get_database,
)
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.targets.coverage import GamutContainment
from calibrate_pro.targets.gamut import reach_of_gamut_mode
from calibrate_pro.verification.provenance import EvidenceKind

if TYPE_CHECKING:  # pragma: no cover - import cost is paid by the writers, not here
    from calibrate_pro.core.icc_profile import ICCProfile
    from calibrate_pro.core.vcgt import VCGTTable

#: ICC profiles carry a creation stamp. A wall-clock value would make every
#: generated profile a different file, so the stamp is fixed and the real
#: publication time is recorded by the diagnostic journal instead.
FIXED_ICC_CREATION_DATE = datetime(2026, 1, 1, 0, 0, 0)

SUPPORTED_LUT_SIZES = frozenset({17, 33, 65})
MANIFEST_FILENAME = "calibrate-pro-manifest.json"
MANIFEST_SCHEMA = 1

_STAGING_PREFIX = ".calibrate-pro-staging-"

#: Entries in the gamma table an apply loads, before the platform resamples it.
_GAMMA_TABLE_ENTRIES = 1024

#: One 8-bit output code. A correction smaller than this is lost when the
#: display pipeline quantizes, so a table or cube that stays inside it changes
#: no pixel a viewer can see.
_ONE_OUTPUT_CODE = 1.0 / 255.0
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
        if not is_target_id(self.preset_id):
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
    gamma_table: bytes = b""
    cube_changes_output: bool = False
    gamma_table_changes_output: bool = False

    #: Which family of curve the target asked for: ``power`` for an exponent,
    #: or ``srgb``, ``l_star``, ``bt1886`` for a curve that is not one. A
    #: reader holding only ``applied_gamma_exponent`` would read a piecewise
    #: sRGB bundle as a 2.2 power law, which is the target described as
    #: something the artifacts do not do.
    tone_response_kind: str = "power"

    #: The instrument run these artifacts were computed from, when there was
    #: one. Held rather than summarized so the manifest can name the sensor,
    #: the patch count and the geometry that produced every measured number.
    measurement: MeasuredCharacterization | None = None

    #: The display's own declaration these artifacts were computed from, when
    #: the operator accepted one. Held for the same reason the measurement is:
    #: the manifest names the primaries and the gamma the display claimed, so a
    #: reader can check the correction against what it was built from instead of
    #: taking the label's word for it.
    declaration: DeclaredCharacterization | None = None

    #: How much of the named gamut this display's primaries actually enclose,
    #: computed from the panel record the artifacts were built from. A cube can
    #: be aimed at BT.2020 from an sRGB panel, and the arithmetic will clamp the
    #: out-of-reach corners onto the panel's own, which is a legitimate and
    #: common request. What is not legitimate is a bundle that answers
    #: ``BT.2020`` and nothing else, because then a target the operator declared
    #: is being read as a property of the artifact. None where the target is the
    #: display's native gamut: there is no second triangle to compare against,
    #: so there is no coverage figure to report rather than a figure of 100%.
    gamut_reach: GamutContainment | None = None

    def __post_init__(self) -> None:
        """Keep the two measured labels and the measurement itself together.

        A bundle can be labeled measured, be labeled estimated, or carry a
        measurement. Left independent, a caller assembling this value by hand
        could set the labels without the run, which is exactly the claim the
        product must not be able to make. Binding all three here means the
        label cannot exist without the reading behind it.
        """
        measured = self.measurement is not None
        if measured and type(self.measurement) is not MeasuredCharacterization:
            raise TypeError("measurement must be a MeasuredCharacterization or None")
        if (self.characterization_kind is CharacterizationKind.MEASURED) != measured:
            raise ValueError(
                "a MEASURED characterization requires the measurement it came from, and nothing else may carry one"
            )
        if (self.evidence_kind is EvidenceKind.MEASURED) != measured:
            raise ValueError("MEASURED evidence requires the measurement it came from, and nothing else may claim it")
        declared = self.declaration is not None
        if declared and type(self.declaration) is not DeclaredCharacterization:
            raise TypeError("declaration must be a DeclaredCharacterization or None")
        if (self.characterization_kind is CharacterizationKind.EDID_DECLARED) != declared:
            raise ValueError(
                "an EDID_DECLARED characterization requires the declaration it came from, and nothing else may carry one"
            )

    def digest_for(self, fmt: AssetFormat) -> str:
        return hashlib.sha256(self.assets[fmt]).hexdigest()

    @property
    def gamma_table_sha256(self) -> str:
        """Digest the gamma table, refusing to digest an absent one.

        A caller reaching for this is about to pin the table into an apply plan.
        Answering the digest of empty bytes would seal a plan whose gamma file
        holds nothing, so the absence is raised where it can still be handled.
        """
        if not self.gamma_table:
            raise AssetGenerationError("this bundle carries no gamma table")
        return hashlib.sha256(self.gamma_table).hexdigest()


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


@dataclass(frozen=True)
class _Render:
    """Everything a writer is allowed to read, so each one takes the same thing.

    The gamma table rides along because two artifacts carry it: the .cal an
    apply loads, and the VCGT tag inside the profile. Handing both the same
    object is what keeps them from being two curves computed separately from
    one input.
    """

    request: AssetRequest
    panel: PanelCharacterization
    lut: LUT3D
    target: CalibrationTarget
    gamma_table: VCGTTable


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

    def generate(
        self,
        request: AssetRequest,
        *,
        measured: MeasuredCharacterization | None = None,
        declared: DeclaredCharacterization | None = None,
    ) -> GeneratedAssets:
        """Generate every requested format from one characterization.

        With neither argument the characterization comes from the panel
        database, which describes a product. With `declared` it comes from what
        the display said about itself, which describes the model its maker
        shipped. With `measured` it is the unit the instrument read.

        Each label is reachable only through the argument that carries its
        evidence, so a caller cannot ask for measured artifacts without holding
        a run, or for declared artifacts without holding the declaration. The
        two arguments are exclusive: a run that measured the display has already
        answered the question a descriptor only claims to.

        `request.panel_key` is left alone on either build. The evidence refined
        a record rather than replacing it, and the manifest naming that record is
        how a reader knows which starting point was corrected.
        """
        if not isinstance(request, AssetRequest):
            raise TypeError("request must be an AssetRequest")
        if measured is not None and type(measured) is not MeasuredCharacterization:
            raise TypeError("measured must be a MeasuredCharacterization or None")
        if declared is not None and type(declared) is not DeclaredCharacterization:
            raise TypeError("declared must be a DeclaredCharacterization or None")
        if measured is not None and declared is not None:
            raise AssetGenerationError("a measured build reads the display itself, so it takes no declaration")

        if measured is not None:
            panel = measured.panel
            # The label carries the marker, not the record. A panel's name is
            # built from its manufacturer and product fields, so writing a
            # measured suffix into the record would put it in the field that
            # names which product this is.
            panel_label = f"{panel.name} (measured)"
            characterization_kind = CharacterizationKind.MEASURED
            evidence_kind = EvidenceKind.MEASURED
        elif declared is not None:
            panel = declared.panel
            panel_label = f"{panel.name} (declared)"
            characterization_kind = CharacterizationKind.EDID_DECLARED
            # A descriptor is still not a reading, so the evidence label does not
            # move. What changed is which numbers the correction was built from.
            evidence_kind = EvidenceKind.ESTIMATED
        else:
            panel, characterization_kind = self.resolve_panel(request.panel_key)
            panel_label = panel.name
            evidence_kind = EvidenceKind.ESTIMATED
        target = resolve_target(request.preset_id)
        # Read off the same panel record the correction is computed from, so
        # the figure describes the display these artifacts were built for
        # rather than the product family the label names.
        gamut_reach = reach_of_gamut_mode(panel.native_primaries, target.gamut_mode)

        lut = self._engine.create_3d_lut(
            panel,
            size=request.lut_size,
            lut_name=f"Calibrate Pro - {panel_label} ({target.gamut_label} {target.tone_label})",
            hdr_mode=target.hdr,
            target=target.gamut_mode,
            target_gamma=target.exponent,
            target_tone=target.engine_tone,
            target_white=target.white,
        )

        table = _gamma_table(lut)
        payloads = self._render(_Render(request, panel, lut, target, table))
        return GeneratedAssets(
            request=request,
            assets=MappingProxyType(payloads),
            panel_name=panel_label,
            characterization_kind=characterization_kind,
            evidence_kind=evidence_kind,
            gamut_mode=target.gamut_mode,
            gamut_reach=gamut_reach,
            tone_response=target.tone_label,
            applied_gamma_exponent=target.exponent,
            tone_response_kind=target.tone.kind,
            white_point=target.white_label,
            gamma_table=_render_gamma_table(table),
            cube_changes_output=_cube_changes_output(lut),
            gamma_table_changes_output=_curve_changes_output(table),
            measurement=measured,
            declaration=declared,
        )

    def _render(self, inputs: _Render) -> dict[AssetFormat, bytes]:
        """Write each format through its tested writer, then read it back."""
        payloads: dict[AssetFormat, bytes] = {}
        staging = Path(tempfile.mkdtemp(prefix="calibrate-pro-render-"))
        try:
            for fmt in inputs.request.formats:
                path = staging / inputs.request.filename_for(fmt)
                self._write_one(fmt, path, inputs)
                if not path.is_file():
                    raise AssetGenerationError(f"{fmt.value} writer produced no file")
                raw = path.read_bytes()
                if not raw:
                    raise AssetGenerationError(f"{fmt.value} writer produced an empty file")
                payloads[fmt] = _normalize(fmt, raw)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return payloads

    def _write_one(self, fmt: AssetFormat, path: Path, inputs: _Render) -> None:
        lut = inputs.lut
        if fmt is AssetFormat.ICC:
            profile = self._write_profile(inputs)
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
                lut_path=inputs.request.filename_for(AssetFormat.CUBE),
                icc_path=inputs.request.filename_for(AssetFormat.ICC),
                output_path=path,
            )
        else:  # pragma: no cover - the enum is closed and validated on request
            raise AssetGenerationError(f"no writer is registered for {fmt!r}")

    def _write_profile(self, inputs: _Render) -> ICCProfile:
        """Build the profile that describes the display this bundle leaves.

        The primaries stay the panel's own, because the gamma table an apply
        loads is a per-channel curve and no per-channel curve moves a primary.
        The white and the tone response are the target's, because the curve
        does move those and lands on them. The table itself goes in as the
        VCGT, so the tag inside the profile and the .cal beside it are the
        same numbers.

        The bounded cost of describing the calibrated display rather than the
        cube: under a curve-only apply, a panel wider than its target still
        shows its own gamut, and this profile reports that gamut honestly. A
        colour-managed application then converts into it correctly. An
        application that ignores the profile stays oversaturated, which is
        what the cube in the same bundle is for.

        The description names the target as well as the display, because four
        presets for one monitor install four profiles and the operator picks
        between them by the string Windows shows.
        """
        profile = self._engine.create_icc_profile(
            inputs.panel,
            f"Calibrate Pro: {inputs.panel.name} ({inputs.target.label})",
            target_white=inputs.target.white,
            target_gamma=inputs.target.exponent,
            target_tone=inputs.target.engine_tone,
            vcgt=(inputs.gamma_table.red, inputs.gamma_table.green, inputs.gamma_table.blue),
        )
        profile.header.creation_date = FIXED_ICC_CREATION_DATE
        return profile


def _gamma_table(lut: LUT3D) -> VCGTTable:
    """Extract the neutral axis of one 3D LUT, at the size an apply loads.

    A graphics card applies a per-channel curve, not a cube, so this table is
    what an apply actually loads. Taking it from the same LUT the bundle
    exports is what keeps the loaded curve and the published cube describing one
    calibration rather than two computed from the same inputs at different
    times. The profile writer is handed this object too, for the same reason.

    The output is 1024 entries. Windows resamples to 256 on load, and starting
    above that leaves the resample interpolating a curve rather than a curve
    already quantized to the destination grid.
    """
    vcgt = importlib.import_module("calibrate_pro.core.vcgt")
    table: VCGTTable = vcgt.lut3d_to_vcgt(lut.data, output_size=_GAMMA_TABLE_ENTRIES)
    return table


def _render_gamma_table(table: VCGTTable) -> bytes:
    """Write one gamma table out as an ArgyllCMS .cal payload."""
    vcgt = importlib.import_module("calibrate_pro.core.vcgt")
    staging = Path(tempfile.mkdtemp(prefix="calibrate-pro-gamma-"))
    try:
        path = staging / "gamma.cal"
        vcgt.export_vcgt_cal(table, str(path))
        raw = path.read_bytes()
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if not raw:
        raise AssetGenerationError("gamma table writer produced an empty file")
    return _normalize_newlines(raw)


def _curve_changes_output(table: object) -> bool:
    """Answer whether loading this curve would move any 8-bit output code.

    A gamut clamp corrects saturated colour and leaves neutral grey where it
    already sits, so the curve it yields is frequently an exact ramp. Loading
    one of those and reporting an applied calibration would claim a change the
    panel never made, which is the case this answer exists to catch.
    """
    numpy = importlib.import_module("numpy")
    for name in ("red", "green", "blue"):
        channel = numpy.asarray(getattr(table, name), dtype=float)
        reference = numpy.linspace(0.0, 1.0, channel.size)
        if float(numpy.abs(channel - reference).max()) > _ONE_OUTPUT_CODE:
            return True
    return False


def _cube_changes_output(lut: LUT3D) -> bool:
    """Answer whether loading this cube would move any 8-bit output code.

    A cube that leaves every output code alone is a calibration in name only,
    and shipping one tells an operator their display was corrected when it was
    left where it started. The generic characterization is where that arises.
    It carries exact sRGB primaries, an exact D65 white and an exact 2.2
    response, so the sRGB web target resolves to the identity cube on it. Each
    of the three other shipped targets differs from that panel somewhere and
    moves it. The same answer covers a matched panel sitting on its target.
    """
    numpy = importlib.import_module("numpy")
    axis = numpy.linspace(0.0, 1.0, lut.size)
    identity = numpy.stack(numpy.meshgrid(axis, axis, axis, indexing="ij"), axis=-1)
    measured = numpy.asarray(lut.data, dtype=float)
    return bool(float(numpy.abs(measured - identity).max()) > _ONE_OUTPUT_CODE)


def _normalize_newlines(raw: bytes) -> bytes:
    """Give one newline convention to a writer that emits the platform's own."""
    return raw.replace(bytes([13, 10]), bytes([10]))


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
            "gamut_reach": _manifest_reach(generated.gamut_reach),
            "white_point": generated.white_point,
            "tone_response": generated.tone_response,
            "tone_response_kind": generated.tone_response_kind,
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
    if generated.measurement is not None:
        document["measurement"] = _manifest_measurement(generated.measurement)
    if generated.declaration is not None:
        document["declaration"] = _manifest_declaration(generated.declaration)
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _manifest_reach(reach: GamutContainment | None) -> dict[str, object] | None:
    """Write how much of the named gamut the display reaches, beside its name.

    Null where the target is the display's own gamut. Rounded because this
    document is hashed and the digest travels between machines: one decimal on
    a percentage and four on a u'v' distance are both an order of magnitude
    finer than the agreement between two colorimeters, so the rounding costs
    nothing a reader could use and removes any last-bit difference in the
    arithmetic from the digest.
    """
    if reach is None:
        return None
    return {
        "covers": reach.covers,
        "coverage_percent": round(reach.coverage_percent, 1),
        "unreachable_corners": list(reach.deficits),
        "worst_deficit_uv": round(reach.worst_deficit_uv, 4),
    }


def _manifest_declaration(declared: DeclaredCharacterization) -> dict[str, object]:
    """Describe the declaration a declared bundle came from, in the manifest.

    Same reason the measurement block exists. A reader gets the primaries, the
    white point and the gamma the display claimed, which is enough to check the
    correction against its input and to notice a descriptor that describes a
    different panel than the one on the desk.

    The provenance names a model and never a unit, so nothing identifying the
    operator's hardware reaches a file they may publish.
    """
    return {
        "provenance": declared.provenance,
        "red_xy": [round(value, 6) for value in declared.red_xy],
        "green_xy": [round(value, 6) for value in declared.green_xy],
        "blue_xy": [round(value, 6) for value in declared.blue_xy],
        "white_xy": [round(value, 6) for value in declared.white_xy],
        "gamma": round(declared.gamma, 4),
    }


def _manifest_measurement(measured: MeasuredCharacterization) -> dict[str, object]:
    """Describe the run a measured bundle came from, in the manifest.

    This is the difference between a bundle that says measured and a bundle
    that shows it. A reader gets the device, how many patches it read, the
    geometry those patches were shown at, and the numbers that came back, which
    is enough to repeat the run and disagree with it.

    Values are rounded because the manifest is compared by digest. Sixteen
    significant figures of sensor noise would make two runs of the same display
    differ in a field nobody reads, and the rounding keeps the precision a
    colorimeter actually delivers.
    """
    contrast = measured.contrast_ratio
    return {
        "instrument": measured.instrument,
        "ramp_steps": measured.steps,
        "patch_count": measured.patch_count,
        "patch_geometry": measured.patch_geometry,
        "white_luminance_cd_m2": round(measured.white_luminance, 4),
        "black_luminance_cd_m2": round(measured.black_luminance, 4),
        "contrast_ratio": None if contrast is None else round(contrast, 1),
        "white_xy": [round(value, 6) for value in measured.white_xy],
        "gamma": [round(value, 4) for value in measured.gamma],
    }


def _write_durable(path: Path, payload: bytes) -> None:
    with open(path, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def place_atomically(
    directory: str | Path,
    payloads: Mapping[str, bytes],
    *,
    overwrite: bool = False,
) -> Path:
    """Write a set of named files into one directory, all of them or none.

    An export that half succeeded is worse than one that failed, because what
    is left behind still looks like a bundle. Every file is written and fsynced
    into a staging directory first, then moved into place, and anything already
    there is moved aside rather than overwritten so a failure part way through
    can put it back.

    Copying a published bundle needs the same guarantee as publishing one, so
    the guarantee lives here and both paths call it.
    """
    if not payloads:
        raise BundlePublishError("no files were given to place")

    destination = Path(directory)
    if destination.exists() and not destination.is_dir():
        raise BundlePublishError(f"export destination is not a directory: {destination}")

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

    _swap_into_place(destination, payloads, created_destination=created_destination)
    return destination


def _swap_into_place(
    destination: Path,
    payloads: Mapping[str, bytes],
    *,
    created_destination: bool,
) -> None:
    """Stage every payload, then move each one in, undoing all of it on failure."""
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


def publish_bundle(
    generated: GeneratedAssets,
    directory: str | Path,
    *,
    overwrite: bool = False,
) -> ExportBundle:
    """Place every artifact and its manifest, or place nothing at all."""
    if not isinstance(generated, GeneratedAssets):
        raise TypeError("generated must be a GeneratedAssets value")

    request = generated.request
    payloads: dict[str, bytes] = {request.filename_for(fmt): generated.assets[fmt] for fmt in generated.assets}
    manifest = build_manifest(generated)
    payloads[MANIFEST_FILENAME] = manifest

    destination = place_atomically(directory, payloads, overwrite=overwrite)
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
    "place_atomically",
    "publish_bundle",
]
