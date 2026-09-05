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
    """A sealed bundle held in memory, named by digest and by file."""

    plan_sha256: str
    filenames: tuple[str, ...]
    panel_name: str
    characterization_kind: CharacterizationKind
    evidence_kind: EvidenceKind


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
class PredictedPatch:
    """One reference patch as the accuracy model simulated it.

    ``reference_srgb`` is the ColorChecker swatch, ``displayed_lab`` is where
    the simulated correction chain landed, and ``delta_e`` is the difference the
    model reported between them. The delta is carried rather than derived
    because a surface that recomputed it would be showing its own arithmetic
    under the model's name.
    """

    name: str
    reference_srgb: tuple[float, float, float]
    displayed_lab: tuple[float, float, float]
    delta_e: MetricValue


@dataclass(frozen=True)
class VerificationResult:
    """Accuracy figures and the plain statement of where they came from.

    ``source`` names what was examined. Nothing in this phase examines a
    display, so the value is the generated plan and the numbers are model
    output. A target the model does not cover reports no number at all rather
    than a number carrying a caveat.

    ``patches`` carries what the model produced per patch. A surface that shows
    a patch grid draws it from here, which is what keeps the grid describing
    this result instead of a second simulation the surface ran on its own.
    """

    source: str
    evidence: EvidenceKind
    average_delta_e: MetricValue
    maximum_delta_e: MetricValue
    patches: tuple[PredictedPatch, ...]
    limitation: str | None = None

    @property
    def covered(self) -> bool:
        return self.evidence is not EvidenceKind.NOT_MEASURED

    @property
    def patch_count(self) -> int:
        return len(self.patches)


def verification_note(result: VerificationResult) -> str:
    """One sentence saying what produced these figures, for any surface.

    A figure carries its limitation when the result records one. Otherwise the
    sentence names the model and says plainly that nothing was measured, which
    is the statement that has to sit beside a predicted number wherever it is
    rendered. Keeping it here is what stops a window and a terminal from
    wording the same disclosure two ways.
    """
    if result.limitation:
        return result.limitation
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
    "DetectionSummary",
    "DisplaySelection",
    "ExportDirectory",
    "FakeApplyResult",
    "GenerationResult",
    "HdrDisplayState",
    "HdrStatus",
    "MethodSelection",
    "PlanDecision",
    "PlanPreview",
    "PredictedPatch",
    "TargetSelection",
    "VerificationResult",
    "verification_note",
]
