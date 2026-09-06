"""One calibration session's state, and the context the resolver reads from it.

The action resolver decides what an operator may do from an immutable
``ActionContext``. This module owns the mutable state behind that context and
performs the conversion in exactly one place, so no surface can assemble a
context that flatters the session it came from.

Sealing is the pivot. Generation seals a plan digest together with the
capability generation that was current when the plan was built. Anything
downstream of generation, including every export, is allowed only while those
two still agree. Re-detecting hardware bumps the generation and therefore
breaks the seal, because a plan built against one machine state is not evidence
about another.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Literal

from calibrate_pro.application.actions import ActionContext, ExportFormat, RuntimeMode
from calibrate_pro.application.assets import AssetFormat, GeneratedAssets
from calibrate_pro.application.contracts import CharacterizationKind, DashboardModel, EvidenceKind
from calibrate_pro.application.profiles import ProfileInspection, ProfileRecord
from calibrate_pro.workflow import CalibrationMethod, CapabilityState, WorkflowStage

ConfirmationState = Literal["none", "live", "confirmed", "consumed", "expired"]
AssetKind = Literal["ICC", "CUBE"]

#: Every asset format that has its own export action, keyed by the format the
#: generator produces. Formats absent from this map ship inside a bundle but
#: are not separately exportable, so they never widen the export surface.
EXPORTABLE_FORMATS: dict[AssetFormat, ExportFormat] = {
    AssetFormat.ICC: "icc",
    AssetFormat.CUBE: "cube",
    AssetFormat.MADVR: "3dlut",
    AssetFormat.RESHADE_PNG: "png",
    AssetFormat.MPV: "mpv",
    AssetFormat.OBS: "obs",
}

#: Preview, and therefore everything after it, requires both anchor artifacts.
#: A bundle missing either one is not a calibration the operator can act on.
REQUIRED_ASSET_KINDS: frozenset[AssetKind] = frozenset({"ICC", "CUBE"})

_ASSET_KIND_BY_FORMAT: dict[AssetFormat, AssetKind] = {
    AssetFormat.ICC: "ICC",
    AssetFormat.CUBE: "CUBE",
}


def current_runtime_mode() -> RuntimeMode:
    """Report whether this process runs from source or from a frozen build."""
    return "frozen" if getattr(sys, "frozen", False) else "source"


@dataclass
class SessionState:
    """Everything one session knows, and nothing a surface may set directly."""

    fake_acceptance: bool = False
    runtime_mode: RuntimeMode = field(default_factory=current_runtime_mode)
    stage: WorkflowStage = WorkflowStage.DETECT
    dashboard: DashboardModel | None = None
    capabilities: CapabilityState | None = None
    capability_generation: int = 0
    selected_display_id: str | None = None
    characterization_kind: CharacterizationKind | None = None
    selected_panel_key: str | None = None
    selected_method: CalibrationMethod | None = None
    selected_preset_id: str | None = None
    generated: GeneratedAssets | None = None
    sealed_plan_sha256: str | None = None

    #: Whether the sealed plan requests a route the adapter would take. A
    #: bundle can seal cleanly and still ask for nothing, either because the
    #: characterization already matches the target or because no route this
    #: build can capture and restore was detected. Apply reads this rather
    #: than the capability state, so a control is offered for a plan that
    #: would change an output code and for no other.
    sealed_plan_actuatable: bool = False
    sealed_capability_generation: int | None = None
    confirmation_state: ConfirmationState = "none"
    fake_applied_plan_sha256: str | None = None
    #: Digest of the plan this session applied to a display, once one has
    #: been applied. Kept apart from the fake composition's answer so a
    #: condition asking whether a display was changed cannot be satisfied by a
    #: recorded apply.
    applied_plan_sha256: str | None = None
    verification_evidence: EvidenceKind | None = None
    export_directory: str | None = None
    export_directory_valid: bool = False
    journal_ready: bool = False
    diagnostic_bundle_preview_live: bool = False
    profiles: tuple[ProfileRecord, ...] = ()
    selected_profile: ProfileInspection | None = None
    validated_import_ready: bool = False
    supported_vcp_codes: frozenset[int] = frozenset()
    actuation_route: bool = False
    measurement_route: bool = False
    instrument_identity: str | None = None

    def __post_init__(self) -> None:
        if type(self.fake_acceptance) is not bool:
            raise TypeError("fake_acceptance must be an exact boolean")
        for name in ("actuation_route", "measurement_route"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be an exact boolean")
        if self.instrument_identity is not None and (
            type(self.instrument_identity) is not str or not self.instrument_identity.strip()
        ):
            raise TypeError("instrument_identity must be a nonblank exact string or None")
        if self.runtime_mode not in {"source", "frozen"}:
            raise ValueError("runtime_mode must be source or frozen")

    @property
    def selected_profile_reparsed(self) -> bool:
        """Report whether a published profile was read back and still matches.

        Profile export is gated on this. Deriving it from the inspection rather
        than storing a flag means the answer cannot outlive the reading that
        produced it: clearing the selection closes the gate, and an inspection
        that found a changed file never opens it.
        """
        return self.selected_profile is not None and self.selected_profile.sealed

    @property
    def target_hdr(self) -> bool:
        """Report whether the selected preset targets HDR.

        No shipped preset does. The value is read from the preset table rather
        than hard-coded, so adding an HDR preset cannot silently pass a target
        the sensorless path was never qualified for.
        """
        from calibrate_pro.application.actions import PRESET_TARGETS

        if self.selected_preset_id is None:
            return False
        target = PRESET_TARGETS.get(self.selected_preset_id)
        return bool(target[3]) if target is not None else False

    @property
    def target_valid(self) -> bool:
        """A target is valid once a known preset has been chosen."""
        from calibrate_pro.application.actions import PRESET_TARGETS

        return self.selected_preset_id in PRESET_TARGETS

    @property
    def generated_asset_kinds(self) -> frozenset[AssetKind]:
        """Name the anchor artifacts actually held in memory right now."""
        if self.generated is None:
            return frozenset()
        kinds = {_ASSET_KIND_BY_FORMAT[fmt] for fmt in self.generated.assets if fmt in _ASSET_KIND_BY_FORMAT}
        return frozenset(kinds)

    @property
    def available_export_formats(self) -> frozenset[ExportFormat]:
        """Name only the formats this session has already generated."""
        if self.generated is None:
            return frozenset()
        formats = {EXPORTABLE_FORMATS[fmt] for fmt in self.generated.assets if fmt in EXPORTABLE_FORMATS}
        return frozenset(formats)

    @property
    def export_source_ready(self) -> bool:
        """Report whether a sealed bundle is still in memory to export from."""
        return self.generated is not None and self.sealed_plan_sha256 is not None

    @property
    def physical_apply_qualified(self) -> bool:
        """Report whether this session may change the display it selected.

        Two facts have to hold together. The session must hold an actuation
        route, which only a composition that wired a display adapter sets, and
        the selected display must have reported at least one detected write.
        A read-only session answers False because it has no route, and a
        session whose probe proved nothing answers False because it has no
        capability. Neither answer is a setting a surface can reach.
        """
        return self.actuation_route and self.capabilities is not None and self.capabilities.writes_available

    @property
    def measured_qualified(self) -> bool:
        """Report whether this session may take an instrument measurement.

        The route says a measurement port was wired. `sensor_available` says a
        probe opened a device and found one. Requiring both is what keeps a
        MEASURED evidence kind attached to a reading a device produced rather
        than to the intention to take one.
        """
        return self.measurement_route and self.capabilities is not None and self.capabilities.sensor_available

    @property
    def seal_intact(self) -> bool:
        """Report whether the sealed plan still matches the current machine."""
        return (
            self.sealed_capability_generation is not None
            and self.capability_generation == self.sealed_capability_generation
        )

    def invalidate_seal(self) -> None:
        """Drop a sealed plan and everything derived from it.

        Called whenever the machine or the target changes underneath a plan.
        The generated bytes go with the seal: keeping them would leave an
        exportable artifact that no longer describes the current session. An
        operator who had reached confirmation is told the plan expired rather
        than finding the state silently reset.
        """
        had_seal = self.sealed_plan_sha256 is not None
        self.generated = None
        self.sealed_plan_sha256 = None
        self.sealed_plan_actuatable = False
        self.sealed_capability_generation = None
        self.fake_applied_plan_sha256 = None
        self.applied_plan_sha256 = None
        self.verification_evidence = None
        self.confirmation_state = "expired" if had_seal else "none"

    def to_context(self) -> ActionContext:
        """Convert this session into the immutable context the resolver reads."""
        return ActionContext(
            stage=self.stage,
            runtime_mode=self.runtime_mode,
            fake_acceptance=self.fake_acceptance,
            selected_display_id=self.selected_display_id,
            characterization_kind=self.characterization_kind,
            selected_method=self.selected_method,
            target_valid=self.target_valid,
            selected_preset_id=self.selected_preset_id,
            target_hdr=self.target_hdr,
            generated_asset_kinds=self.generated_asset_kinds,
            sealed_plan_sha256=self.sealed_plan_sha256,
            sealed_plan_actuatable=self.sealed_plan_actuatable,
            confirmation_state=self.confirmation_state,
            fake_applied_plan_sha256=self.fake_applied_plan_sha256,
            applied_plan_sha256=self.applied_plan_sha256,
            capability_generation=self.capability_generation,
            sealed_capability_generation=self.sealed_capability_generation,
            verification_evidence=self.verification_evidence,
            export_source_ready=self.export_source_ready,
            configured_export_directory_valid=self.export_directory_valid,
            available_export_formats=self.available_export_formats,
            selected_profile_reparsed=self.selected_profile_reparsed,
            validated_import_ready=self.validated_import_ready,
            supported_vcp_codes=self.supported_vcp_codes,
            diagnostic_bundle_preview_live=self.diagnostic_bundle_preview_live,
            journal_ready=self.journal_ready,
            # Both qualifications are derived, never set. Each requires a
            # wired route and a capability a probe actually proved, so a
            # session that holds neither answers False for the same reason it
            # always did rather than because the value was hardcoded.
            physical_apply_qualified=self.physical_apply_qualified,
            measured_qualified=self.measured_qualified,
        )


__all__ = [
    "EXPORTABLE_FORMATS",
    "REQUIRED_ASSET_KINDS",
    "AssetKind",
    "ConfirmationState",
    "SessionState",
    "current_runtime_mode",
]
