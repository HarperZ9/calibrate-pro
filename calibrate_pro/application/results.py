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
class VerificationResult:
    """Accuracy figures and the plain statement of where they came from.

    ``source`` names what was examined. Nothing in this phase examines a
    display, so the value is the generated plan and the numbers are model
    output. A target the model does not cover reports no number at all rather
    than a number carrying a caveat.
    """

    source: str
    evidence: EvidenceKind
    average_delta_e: MetricValue
    maximum_delta_e: MetricValue
    patch_count: int
    limitation: str | None = None

    @property
    def covered(self) -> bool:
        return self.evidence is not EvidenceKind.NOT_MEASURED


@dataclass(frozen=True)
class ExportDirectory:
    """The directory later exports will publish into."""

    directory: str
    valid: bool


__all__ = [
    "DetectionSummary",
    "DisplaySelection",
    "ExportDirectory",
    "FakeApplyResult",
    "GenerationResult",
    "MethodSelection",
    "PlanDecision",
    "PlanPreview",
    "TargetSelection",
    "VerificationResult",
]
