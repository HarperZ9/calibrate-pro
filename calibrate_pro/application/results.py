"""Immutable values the one-session service hands back, one per action.

A result is separate from the session that produced it. A surface renders what
it is given and cannot reach through it into mutable state, and the action
boundary reads publication evidence off a result without the service passing it
anything it could change afterwards.

Every result in this module describes work that stayed inside this process or
inside a directory the operator chose. None of them describes a change to a
display, because no composition in this phase makes one.
"""

from __future__ import annotations

from dataclasses import dataclass

from calibrate_pro.application.contracts import CharacterizationKind, DashboardModel
from calibrate_pro.application.measurement import MeasuredCharacterization
from calibrate_pro.recovery import ApplyReceipt
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue
from calibrate_pro.workflow import ApplyPlan, CalibrationMethod, WorkflowStage


@dataclass(frozen=True)
class DetectionSummary:
    """What one detection pass observed, including the displays it refused."""

    dashboard: DashboardModel
    rejected: tuple[tuple[str, str], ...]
    capability_generation: int

    @property
    def selected_display_id(self) -> str | None:
        return self.dashboard.selected_display_id


@dataclass(frozen=True)
class DisplaySelection:
    """The display this session is working on and how it was characterized."""

    display_id: str
    safe_label: str
    panel_key: str
    characterization_kind: CharacterizationKind


@dataclass(frozen=True)
class MethodSelection:
    """The evidence path the session committed to."""

    method: CalibrationMethod
    stage: WorkflowStage


@dataclass(frozen=True)
class TargetSelection:
    """The calibration target, spelled out rather than left as a preset id."""

    preset_id: str
    gamut: str
    white_point: str
    tone_response: str


@dataclass(frozen=True)
class GenerationResult:
    """A sealed bundle held in memory, named by digest and by file.

    ``apply_note`` carries why the sealed plan requests no display route,
    and is None when it requests one. A session that only publishes files
    leaves it None too, because nothing was withheld there: no route was
    ever asked for.
    """

    plan_sha256: str
    filenames: tuple[str, ...]
    panel_name: str
    characterization_kind: CharacterizationKind
    evidence_kind: EvidenceKind
    apply_note: str | None = None


@dataclass(frozen=True)
class MeasurementSummary:
    """One instrument run of one display, and the state it was taken in.

    ``characterization`` is the record itself rather than a copy of its
    numbers, so a surface rendering a run and the generator building from it
    read the same values. It is frozen, which is what lets it leave the session
    without giving a surface a way back into one.

    ``correction_state`` is what qualified the run. A measurement is only
    reproducible next to what the display was loading when it was taken, so the
    sentence that established it travels with the result instead of being left
    in a log the report cannot reach.
    """

    display_id: str
    characterization: MeasuredCharacterization
    correction_state: str

    @property
    def instrument(self) -> str:
        return self.characterization.instrument

    @property
    def summary(self) -> str:
        """One line naming the instrument and what it read."""
        return self.characterization.summary


@dataclass(frozen=True)
class PlanPreview:
    """The exact proposal shown to the operator before any decision."""

    plan: ApplyPlan
    plan_sha256: str
    physical_apply_performed: bool = False


@dataclass(frozen=True)
class PlanDecision:
    """The operator's answer to a preview, and what it did."""

    accepted: bool
    plan_sha256: str
    physical_apply_performed: bool = False


@dataclass(frozen=True)
class FakeApplyResult:
    """A fake-composed apply, reporting the receipt exactly as it came back.

    ``apply_phase_flags`` and ``recovery_guarantee`` exist because the action
    boundary reads them off the returned value to journal what the apply
    actually reached. They restate the receipt rather than summarizing it, so
    the journal and the receipt cannot disagree.
    """

    plan_sha256: str
    receipt: ApplyReceipt
    physical_apply_performed: bool = False

    @property
    def apply_phase_flags(self) -> tuple[tuple[str, bool], ...]:
        return (
            ("captured", self.receipt.captured),
            ("applied", self.receipt.applied),
            ("verified", self.receipt.verified),
            ("restore_attempted", self.receipt.restore_attempted),
            ("restored", self.receipt.restored),
        )

    @property
    def recovery_guarantee(self) -> str:
        return self.receipt.recovery_guarantee.value


@dataclass(frozen=True)
class AppliedPlanResult:
    """A physical apply, reporting the receipt exactly as it came back.

    ``physical_apply_performed`` reads the receipt rather than the composition.
    A session built to drive a display still returns False for an apply that
    refused before the write, because what the field answers is whether this
    display was changed and not whether this session was able to change one.

    ``routes`` names what the plan requested, so a report can say a compositor
    LUT was loaded without re-deriving that from the plan it no longer holds.
    """

    plan_sha256: str
    receipt: ApplyReceipt
    routes: tuple[str, ...] = ()

    @property
    def physical_apply_performed(self) -> bool:
        return self.receipt.applied

    @property
    def apply_phase_flags(self) -> tuple[tuple[str, bool], ...]:
        return (
            ("captured", self.receipt.captured),
            ("applied", self.receipt.applied),
            ("verified", self.receipt.verified),
            ("restore_attempted", self.receipt.restore_attempted),
            ("restored", self.receipt.restored),
        )

    @property
    def recovery_guarantee(self) -> str:
        return self.receipt.recovery_guarantee.value


@dataclass(frozen=True)
class VerifiedPatch:
    """One reference patch, as this verification found it.

    ``reference_srgb`` is the ColorChecker swatch and ``displayed_lab`` is where
    the display landed: simulated through the correction chain on the predicted
    path, read from the instrument on the measured one. Which of the two it is
    comes from ``delta_e.evidence`` rather than from the type, so a surface
    drawing a grid states the origin out of the same field it draws the number
    from.

    The delta is carried rather than derived because a surface that recomputed
    it would be showing its own arithmetic under the source's name.

    ``within_target_gamut`` is False for a chart patch the target cannot
    reproduce. One ColorChecker swatch sits outside sRGB, so the signal sent for
    it is the clipped one and the difference read back is a property of the
    chart rather than of the calibration. The patch is still reported, because
    dropping a named swatch would quietly change what the chart covered.
    """

    name: str
    reference_srgb: tuple[float, float, float]
    displayed_lab: tuple[float, float, float]
    delta_e: MetricValue
    within_target_gamut: bool = True


@dataclass(frozen=True)
class VerificationResult:
    """Accuracy figures and the plain statement of where they came from.

    ``source`` names what was examined. The predicted path examines the plan the
    session generated and its numbers are model output; the measured path
    examines the display itself. A target the reference does not cover reports
    no number at all rather than a number carrying a caveat.

    ``patches`` carries what the verification produced per patch. A surface that
    shows a patch grid draws it from here, which is what keeps the grid
    describing this result instead of a second computation the surface ran on
    its own.

    ``detail`` is the line a measured run needs and a predicted one does not:
    the instrument, how many patches it read, and the geometry it read them at.
    A luminance-derived figure is only reproducible next to those, so they
    travel with the result rather than being looked up afterwards from a session
    that may have moved on.
    """

    source: str
    evidence: EvidenceKind
    average_delta_e: MetricValue
    maximum_delta_e: MetricValue
    patches: tuple[VerifiedPatch, ...]
    limitation: str | None = None
    detail: str | None = None

    @property
    def covered(self) -> bool:
        return self.evidence is not EvidenceKind.NOT_MEASURED

    @property
    def patch_count(self) -> int:
        return len(self.patches)


def verification_note(result: VerificationResult) -> str:
    """One sentence saying what produced these figures, for any surface.

    A figure carries its limitation when the result records one. Otherwise the
    sentence names the origin, and on the predicted path it says plainly that
    nothing was measured. That statement has to sit beside a predicted number
    wherever it is rendered and would be a false one beside a measured number,
    so both wordings live here instead of at each surface.
    """
    if result.limitation:
        return result.limitation
    if result.evidence is EvidenceKind.MEASURED:
        instrument = result.average_delta_e.source or "an unnamed instrument"
        detail = f" {result.detail}" if result.detail else ""
        return f"Measured on this display by {instrument}.{detail}"
    model = result.average_delta_e.source or "an unnamed model"
    return f"Predicted by {model} from the plan this session generated. No display was measured and no sensor was read."


@dataclass(frozen=True)
class ExportDirectory:
    """The directory later exports will publish into."""

    directory: str
    valid: bool


@dataclass(frozen=True)
class HdrDisplayState:
    """What the last detection pass saw of one display's HDR switch."""

    display_id: str
    safe_label: str
    #: True and False are the two answers a query returned. None means the query
    #: did not run or did not answer for this display, which is not the same as
    #: HDR being off and is never rendered as if it were.
    hdr_enabled: bool | None

    @property
    def summary(self) -> str:
        if self.hdr_enabled is None:
            return "not reported"
        return "HDR on" if self.hdr_enabled else "SDR"


@dataclass(frozen=True)
class HdrStatus:
    """The HDR switch positions carried by the current dashboard snapshot.

    Reading the stored snapshot rather than querying again is deliberate. This
    action reports what the session already observed, so the answer on screen
    matches the observation every other view was built from.
    """

    displays: tuple[HdrDisplayState, ...]
    observed_utc: str

    @property
    def queried(self) -> bool:
        """Report whether any display carried an answer at all."""
        return any(entry.hdr_enabled is not None for entry in self.displays)


__all__ = [
    "AppliedPlanResult",
    "DetectionSummary",
    "DisplaySelection",
    "ExportDirectory",
    "FakeApplyResult",
    "GenerationResult",
    "HdrDisplayState",
    "HdrStatus",
    "MeasurementSummary",
    "MethodSelection",
    "PlanDecision",
    "PlanPreview",
    "TargetSelection",
    "VerificationResult",
    "VerifiedPatch",
    "verification_note",
]
