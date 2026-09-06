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
from calibrate_pro.application.contracts import (
    CharacterizationKind,
    DashboardModel,
    EvidenceKind,
    PanelCharacterization,
)
from calibrate_pro.application.control_session import MonitorControlSession
from calibrate_pro.application.declaration import DeclaredCharacterization
from calibrate_pro.application.measurement import MeasuredCharacterization
from calibrate_pro.application.profiles import ProfileInspection, ProfileRecord
from calibrate_pro.application.system_profile_session import SystemProfileSession
from calibrate_pro.application.system_profiles import SystemProfileError, installed_name_for
from calibrate_pro.panels.database import GENERIC_PANEL_KEY
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
    actuation_route: bool = False
    measurement_route: bool = False

    #: Whether a pattern surface was wired into this session. No capability
    #: probe sits beside this route, because a display has nothing to be asked
    #: about a window before one is opened. What a surface can claim about
    #: scaling is established from the surface itself and travels with the
    #: pattern shown on it.
    patterns_route: bool = False
    instrument_identity: str | None = None

    #: The instrument run this session took, and the display it was taken on.
    #: The pair is stored rather than the record alone because a measurement
    #: describes one unit. Carrying the display id alongside it is what lets a
    #: later generate refuse to build measured artifacts for a display the
    #: instrument never saw.
    measured_characterization: MeasuredCharacterization | None = None
    measured_display_id: str | None = None

    #: The declaration this session accepted, and the display it was read from.
    #: Paired for the reason the measurement is paired: a descriptor describes
    #: one display's claim about its model, so carrying the id beside it is what
    #: lets a later selection drop a declaration another monitor made.
    declared_characterization: DeclaredCharacterization | None = None
    declared_display_id: str | None = None

    #: What this session has read off the selected display's own controls, and
    #: what it means to write back. Held in its own record rather than spread
    #: across this dataclass, because a reading, the values staged against it
    #: and the transaction that wrote them are only meaningful together.
    monitor_controls: MonitorControlSession = field(default_factory=MonitorControlSession)

    #: What this session has read out of the machine's colour profile store for
    #: the selected display, and whichever write it performed against that
    #: reading. Kept apart from the bundles on disk, because a published bundle
    #: and an installed profile are different objects and an operator acts on
    #: the difference.
    system_profiles: SystemProfileSession = field(default_factory=SystemProfileSession)

    def __post_init__(self) -> None:
        if type(self.fake_acceptance) is not bool:
            raise TypeError("fake_acceptance must be an exact boolean")
        for name in ("actuation_route", "measurement_route", "patterns_route"):
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
        """A target is valid once a preset or a composed target has been chosen.

        Reading only the preset table refused every target an operator composed
        from the axis controls. The gamut, white point and tone response
        selections each answered with a composed id and each reported success,
        and then generation reported that the session held no valid target, so
        the eleven gamuts and seven white points the catalogue offers reached
        nothing. The two kinds of id are told apart by
        :func:`~calibrate_pro.application.target_selection.is_target_id`, which
        is what the generate gate beside this already asks.
        """
        from calibrate_pro.application.target_selection import is_target_id

        return self.selected_preset_id is not None and is_target_id(self.selected_preset_id)

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
    def patterns_qualified(self) -> bool:
        """Report whether this session may put a pattern on a display.

        Only two facts, and neither of them is a probe. A pattern surface has
        to have been wired, and a display has to have been selected for the
        window to open on. There is no third condition of the kind the other
        lanes carry because there is nothing to ask a display beforehand: a
        control bus either answers or it does not, an instrument is either
        present or it is not, and a window is neither until it exists. What a
        surface turns out to be able to carry is established from the surface
        once it is open, and refused there.
        """
        return self.patterns_route and self.selected_display_id is not None

    @property
    def supported_vcp_codes(self) -> frozenset[int]:
        """The codes the selected display answered when its controls were read.

        Derived from the reading rather than stored, so it empties the moment
        the reading is dropped. A capability string can list a control the
        panel refuses; this reports the codes that answered.
        """
        return self.monitor_controls.supported_codes

    @property
    def monitor_controls_qualified(self) -> bool:
        """Report whether this session may read the display's own controls.

        The route says a control port was wired. `ddc_available` says a probe
        opened a display and it answered. Requiring both keeps a reported
        control value attached to a display that produced one.
        """
        return self.monitor_controls.route and self.capabilities is not None and self.capabilities.ddc_available

    @property
    def monitor_writes_qualified(self) -> bool:
        """Report whether this session may write the display's own controls.

        A write is checked against the range the display reported, and read
        back against the value it held. Both come from the reading, so a
        session without one is offered nothing to write.
        """
        return self.monitor_controls_qualified and self.monitor_controls.reading is not None

    @property
    def system_profiles_qualified(self) -> bool:
        """Report whether this session may read the machine's colour profile store.

        The route says a profile port was wired. `profile_write_available` says
        a probe found the colour directory this build would write into. A
        session missing either has proved nothing about what the machine holds,
        and is offered no reading it could then act on.
        """
        return (
            self.system_profiles.route and self.capabilities is not None and self.capabilities.profile_write_available
        )

    @property
    def system_profile_writes_qualified(self) -> bool:
        """Report whether this session may change the store.

        Every profile write is reported by comparing the store before it with
        the store after it, and the first of those has to already be in hand.
        A session that has not read is offered nothing to write, for the same
        reason a display whose controls were never read is offered no stage.
        """
        return self.system_profiles_qualified and self.system_profiles.reading is not None

    @property
    def selected_profile_installed_name(self) -> str | None:
        """The name the inspected bundle installs under, when one is sealed.

        Derived from the manifest digest rather than from the bundle's
        filename, because every bundle this build publishes carries the same
        filename. A selection that is missing or has drifted names nothing,
        which closes every action that would act on the machine's copy.
        """
        inspection = self.selected_profile
        if inspection is None or not inspection.sealed:
            return None
        try:
            return installed_name_for(inspection.record.manifest_sha256)
        except SystemProfileError:
            return None

    @property
    def selected_profile_installed(self) -> bool:
        """Whether the machine holds the inspected bundle's profile."""
        name = self.selected_profile_installed_name
        return name is not None and self.system_profiles.holds(name)

    @property
    def selected_profile_active(self) -> bool:
        """Whether the selected display hands the inspected bundle out."""
        name = self.selected_profile_installed_name
        return name is not None and self.system_profiles.is_default(name)

    @property
    def restorable_system_profiles(self) -> bool:
        """Whether the selected display carries anything this product attached."""
        return bool(self.system_profiles.ours)

    @property
    def switchable_system_profiles(self) -> bool:
        """Whether the machine holds any profile a display could be switched to."""
        return bool(self.system_profiles.installed)

    @property
    def measurement_matches_selection(self) -> bool:
        """Report whether this session holds a run of the display it selected."""
        return (
            self.measured_characterization is not None
            and self.measured_display_id is not None
            and self.measured_display_id == self.selected_display_id
        )

    def record_measurement(self, measured: MeasuredCharacterization) -> None:
        """Take an instrument run as this session's characterization.

        The record, the display it belongs to and the characterization kind are
        set together, because any two of them without the third describe a
        session that measured one display and claims another. The seal breaks
        for the same reason a target change breaks it: whatever was generated
        before this run described the panel record, not the unit.
        """
        if type(measured) is not MeasuredCharacterization:
            raise TypeError("measured must be a MeasuredCharacterization")
        if self.selected_display_id is None:
            raise ValueError("a measurement cannot be recorded before a display is selected")
        self.measured_characterization = measured
        self.measured_display_id = self.selected_display_id
        self.characterization_kind = CharacterizationKind.MEASURED
        self.invalidate_seal()

    def discard_measurement(self) -> None:
        """Forget a run, used when the display it described is no longer selected."""
        self.measured_characterization = None
        self.measured_display_id = None

    @property
    def declaration_matches_selection(self) -> bool:
        """Report whether this session holds a declaration by the display it selected."""
        return (
            self.declared_characterization is not None
            and self.declared_display_id is not None
            and self.declared_display_id == self.selected_display_id
        )

    @property
    def declaration_offer(self) -> PanelCharacterization | None:
        """What the selected display declared about itself, where it declared anything.

        Read off the detection result rather than stored, because it describes
        the display and not a choice the session made. Accepting it is the
        choice, and ``record_declaration`` is where that gets written down.
        """
        if self.dashboard is None or self.selected_display_id is None:
            return None
        for observation in self.dashboard.displays:
            if observation.platform_display_id == self.selected_display_id:
                return observation.edid_characterization
        return None

    def record_declaration(self, declared: DeclaredCharacterization) -> None:
        """Take a display's own declaration as this session's characterization.

        The record, the display it came from and the kind are set together for
        the reason a measurement sets its three together: any two without the
        third describe a session that read one display and claims another. The
        seal breaks because whatever was generated before was built from a
        different starting point.
        """
        if type(declared) is not DeclaredCharacterization:
            raise TypeError("declared must be a DeclaredCharacterization")
        if self.selected_display_id is None:
            raise ValueError("a declaration cannot be recorded before a display is selected")
        self.declared_characterization = declared
        self.declared_display_id = self.selected_display_id
        self.characterization_kind = CharacterizationKind.EDID_DECLARED
        self.invalidate_seal()

    def discard_declaration(self) -> None:
        """Forget a declaration, used when what it described is no longer selected."""
        self.declared_characterization = None
        self.declared_display_id = None

    @property
    def characterization_without_measurement(self) -> CharacterizationKind | None:
        """What this session would report about the panel with no run in hand.

        Derived rather than remembered, because the parts are set together
        everywhere else: accepting the generic record sets the key and the kind,
        accepting a declaration sets the record and the kind, and so does
        adopting a display that matched. A session that drops a run therefore
        lands back on the answer it would have given had the run never been
        taken.

        A declaration outranks the panel key because it is the more specific
        thing the operator accepted. The key on a declared session is whatever
        detection left there, and answering with it would report a nominal panel
        for a display whose own numbers this session is holding.
        """
        if self.declaration_matches_selection:
            return CharacterizationKind.EDID_DECLARED
        if self.selected_panel_key is None:
            return CharacterizationKind.UNKNOWN if self.selected_display_id is not None else None
        if self.selected_panel_key == GENERIC_PANEL_KEY:
            return CharacterizationKind.EXPLICIT_GENERIC
        return CharacterizationKind.MATCHED

    def invalidate_measurement(self) -> None:
        """Drop a run the display no longer matches, and the kind that claimed it.

        Discarding the record alone would leave the session reporting MEASURED
        with nothing behind it, which is the one claim this build must never
        make. The kind goes back to what the panel record says on its own.
        """
        if self.measured_characterization is None:
            return
        self.discard_measurement()
        self.characterization_kind = self.characterization_without_measurement

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
            edid_declaration_available=self.declaration_offer is not None,
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
            staged_vcp_codes=self.monitor_controls.staged_codes,
            diagnostic_bundle_preview_live=self.diagnostic_bundle_preview_live,
            journal_ready=self.journal_ready,
            # Both qualifications are derived, never set. Each requires a
            # wired route and a capability a probe actually proved, so a
            # session that holds neither answers False for the same reason it
            # always did rather than because the value was hardcoded.
            physical_apply_qualified=self.physical_apply_qualified,
            measured_qualified=self.measured_qualified,
            patterns_qualified=self.patterns_qualified,
            monitor_controls_qualified=self.monitor_controls_qualified,
            monitor_writes_qualified=self.monitor_writes_qualified,
            system_profiles_qualified=self.system_profiles_qualified,
            system_profile_writes_qualified=self.system_profile_writes_qualified,
            selected_profile_installed=self.selected_profile_installed,
            restorable_system_profiles=self.restorable_system_profiles,
            switchable_system_profiles=self.switchable_system_profiles,
        )


__all__ = [
    "EXPORTABLE_FORMATS",
    "REQUIRED_ASSET_KINDS",
    "AssetKind",
    "ConfirmationState",
    "SessionState",
    "current_runtime_mode",
]
