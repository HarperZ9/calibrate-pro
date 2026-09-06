"""Which display a session is about, and what that choice makes available.

Selection is where a session stops being general and becomes about one panel.
Adopting a display copies its detected capabilities into a fresh workflow
controller, so the gate a later action passes through belongs to the display
in front of the operator rather than to whichever display was selected before.

Nothing is available until a probe proved it. A session with no selected
display runs against a fully denied capability state, which makes every
capability-gated action refuse for a stated reason instead of failing late.
"""

from __future__ import annotations

from calibrate_pro.application.contracts import CharacterizationKind, DashboardModel, DisplayObservation
from calibrate_pro.application.detection import panel_key_from_provenance
from calibrate_pro.application.refusals import no_display_selected, unknown_display
from calibrate_pro.application.results import DisplaySelection
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.database import GENERIC_PANEL_KEY
from calibrate_pro.workflow import CapabilityState, WorkflowController

DENIED_CAPABILITIES = CapabilityState(
    sensor_available=False,
    ddc_available=False,
    dwm_lut_available=False,
    dwm_state_capture_available=False,
    profile_write_available=False,
    vcgt_available=False,
)


def observation_for(dashboard: DashboardModel, display_id: str) -> DisplayObservation:
    """Find one detected display, refusing an id the detection never reported."""
    for observation in dashboard.displays:
        if observation.platform_display_id == display_id:
            return observation
    raise unknown_display()


def adopt(state: SessionState, display_id: str | None) -> WorkflowController:
    """Make one display the session's subject, or none at all.

    The returned controller replaces whatever the session held. Building it here
    rather than mutating the old one means a display switch cannot leave a stage
    that the new display's capabilities would not have allowed.
    """
    state.selected_display_id = None
    state.characterization_kind = None
    state.selected_panel_key = None
    state.capabilities = None
    observation = None
    if display_id is not None and state.dashboard is not None:
        observation = observation_for(state.dashboard, display_id)
    if observation is not None:
        state.selected_display_id = observation.platform_display_id
        state.capabilities = observation.capabilities
        panel_key = panel_key_from_provenance(observation.characterization)
        # A match the session cannot name is not a match it can generate from,
        # so it is reported as unknown and offered the generic path instead.
        if observation.characterization.kind is CharacterizationKind.MATCHED and panel_key is not None:
            state.selected_panel_key = panel_key
            state.characterization_kind = CharacterizationKind.MATCHED
        else:
            state.characterization_kind = CharacterizationKind.UNKNOWN
    # Order matters. Both may hold a record for the same display, and a run
    # describes the unit while a declaration only describes the model, so the
    # measured assignment has to be the one that lands last.
    _carry_or_drop_declaration(state)
    _carry_or_drop_measurement(state)
    # A control reading belongs to one unit for the same reason a measurement
    # does, so adopting a different display drops it and everything staged
    # against the ranges it reported.
    state.monitor_controls.retain_for(state.selected_display_id)
    # The store's per-display half is the associated list and the default, and
    # neither survives adopting a different monitor. Keeping the machine-wide
    # half alone would offer an activation judged against another display.
    state.system_profiles.retain_for(state.selected_display_id)
    controller = WorkflowController(state.capabilities or DENIED_CAPABILITIES)
    if state.selected_display_id is not None:
        controller.detect_complete()
    return controller


def _carry_or_drop_declaration(state: SessionState) -> None:
    """Keep an accepted declaration only while its display is still selected.

    A descriptor is read from one display. Selecting a different monitor and
    keeping the record would build the next bundle from another panel's
    declared primaries, which is the same false claim carrying a measurement
    across displays would make, one step weaker. Re-selecting the same display
    restores the kind, because adopting a display resets the characterization
    to whatever detection alone can say.
    """
    if state.declared_characterization is None:
        return
    if state.declared_display_id == state.selected_display_id:
        state.characterization_kind = CharacterizationKind.EDID_DECLARED
        return
    state.discard_declaration()


def _carry_or_drop_measurement(state: SessionState) -> None:
    """Keep a run only while the display it was taken on is still selected.

    A measurement describes one unit. Selecting a different display and keeping
    the record would let the next bundle be built from another monitor's light
    and still be labeled measured, which is the specific false claim the
    measured path exists to make impossible. Re-selecting the same display
    keeps the run and restores the kind that goes with it, because adopting a
    display resets the characterization to whatever detection alone can say.
    """
    if state.measured_characterization is None:
        return
    if state.measured_display_id == state.selected_display_id:
        state.characterization_kind = CharacterizationKind.MEASURED
        return
    state.discard_measurement()


def current_selection(state: SessionState) -> DisplaySelection:
    """Describe the selected display for a surface to render."""
    if state.selected_display_id is None or state.dashboard is None:
        raise no_display_selected()
    observation = observation_for(state.dashboard, state.selected_display_id)
    return DisplaySelection(
        display_id=observation.platform_display_id,
        safe_label=observation.safe_label,
        panel_key=state.selected_panel_key or GENERIC_PANEL_KEY,
        characterization_kind=state.characterization_kind or CharacterizationKind.UNKNOWN,
    )


__all__ = ["DENIED_CAPABILITIES", "adopt", "current_selection", "observation_for"]
