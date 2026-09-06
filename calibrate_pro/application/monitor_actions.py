"""The session actions that read and change the display's own controls.

This is the one lane in the product that changes the display rather than the
signal sent to it, and it is the lane a calibration starts in. Setting the
panel's brightness to the target luminance and its RGB gains to a rough white
balance is what a colorimeter run is taken against; doing it afterwards would
invalidate the run it was supposed to serve.

So a write here invalidates everything downstream of it. A sealed plan was
built against a drive state that no longer exists. An instrument run is light
read at a drive state that no longer exists. Both are dropped, by the same hook
the service uses when hardware is re-detected, and the operator is told the plan
expired rather than finding it silently reset.

Every port opened here is closed here. Windows hands out a physical monitor
handle and expects it back, so each action opens one port inside a try/finally
and holds it for the whole transaction rather than reacquiring per code.

Nothing in this module decides whether an action is offered. The manifest and
the resolver do that, and every method routes through the runner for it.
"""

from __future__ import annotations

from collections.abc import Callable
from time import sleep
from typing import TypeVar

from calibrate_pro.application.control_results import (
    ControlRestore,
    ControlTransaction,
    StagedControl,
)
from calibrate_pro.application.control_transactions import (
    apply_controls,
    read_controls,
    read_raw,
    restore_factory_defaults,
)
from calibrate_pro.application.monitor_controls import (
    SETTLE_SECONDS,
    STAGE_ACTION_CODES,
    MonitorControlError,
    MonitorControlPort,
    MonitorControlSource,
    MonitorControlUnavailable,
    MonitorReading,
    label_for,
    validate_code,
)
from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.refusals import (
    monitor_control_refused,
    monitor_value_rejected,
    no_display_selected,
    no_handler,
    no_monitor_reading,
    no_staged_control,
)
from calibrate_pro.application.runner import SessionActionRunner
from calibrate_pro.application.session import SessionState

T = TypeVar("T")


def _settle() -> None:
    """Give the display time to act on a write before it is read back.

    A plain sleep is right here, unlike the measurement path where settling has
    to pump a window's event loop. Nothing is being painted: the value travels
    over the display's own control bus and the panel applies it over several
    frames with no involvement from this process.
    """
    sleep(SETTLE_SECONDS)


class MonitorControlActions:
    """Reading, staging, writing, and restoring one display's own controls."""

    _state: SessionState
    _runner: SessionActionRunner
    _monitor_controls: MonitorControlSource

    def _invalidate_after_monitor_write(self) -> None:
        """Drop what a change to the panel's own drive state invalidated.

        Supplied by the session service, which owns the sealed plan and the
        workflow state machine this has to move. Declared here so a reader of
        the lane can see that every write goes through it.
        """
        raise NotImplementedError

    # -- reading ------------------------------------------------------------

    def read_monitor_controls(self) -> ActionOutcome[MonitorReading]:
        """Read the selected display's own controls and hold what it answered.

        The reading is what everything else in this lane is checked against: a
        staged value is judged by the range it reports, and a write is judged
        by the value it held beforehand. Controls the display refused are kept
        in the reading rather than dropped, so a surface can say why a control
        it knows about is not on screen.
        """
        return self._runner.run("ddc.read_current", self._read_monitor_controls)

    def _read_monitor_controls(self) -> MonitorReading:
        display_id = self._require_display()
        reading = self._with_port(display_id, lambda port: read_controls(port, display_id))
        self._state.monitor_controls.record_reading(reading)
        return reading

    def read_raw_vcp(self, code: int) -> ActionOutcome[MonitorReading]:
        """Read one arbitrary control code and report what the display said.

        The answer is returned and not recorded. A raw read asks about one code,
        and taking it as the session's reading would drop the full set the rest
        of this lane stages against, leaving a surface with one control and no
        way to write it.
        """
        return self._runner.run("ddc.raw_read", lambda: self._read_raw_vcp(code))

    def _read_raw_vcp(self, code: int) -> MonitorReading:
        display_id = self._require_display()
        try:
            validate_code(code, "code")
        except MonitorControlError as exc:
            raise monitor_value_rejected(str(exc)) from exc
        return self._with_port(display_id, lambda port: read_raw(port, display_id, code))

    # -- staging ------------------------------------------------------------

    def stage_monitor_control(self, action_id: str, value: int) -> ActionOutcome[StagedControl]:
        """Hold one value for a later write, checked against what was read.

        Staging touches no display. It is the step that lets an operator set
        several controls and write them as one transaction, which matters
        because a half applied set is the state this lane exists to avoid.

        The control is named by its action rather than by its code, so the id a
        surface binds a slider to is the id the resolver answered for.
        """
        return self._runner.run(action_id, lambda: self._stage_monitor_control(action_id, value))

    def _stage_monitor_control(self, action_id: str, value: int) -> StagedControl:
        code = STAGE_ACTION_CODES.get(action_id)
        if code is None:
            raise no_handler(action_id)
        reading = self._state.monitor_controls.reading
        if reading is None:
            raise no_monitor_reading()
        control = reading.control(code)
        if control is None:
            raise monitor_value_rejected(f"{label_for(code)} was not answered by {reading.instrument}.")
        try:
            self._state.monitor_controls.stage(code, value)
        except MonitorControlError as exc:
            raise monitor_value_rejected(str(exc)) from exc
        return StagedControl(
            code=code,
            label=control.label,
            current=control.current,
            requested=value,
            maximum=control.maximum,
        )

    # -- writing ------------------------------------------------------------

    def apply_monitor_controls(self) -> ActionOutcome[ControlTransaction]:
        """Write every staged value as one transaction and read back each code.

        A display answers a write it ignored the same way it answers one it
        took, so the result reports the number each control reads at afterwards
        beside the number it was asked for. A write that raises partway puts
        back every code already written and says so.
        """
        return self._runner.run("ddc.apply", self._apply_monitor_controls)

    def _apply_monitor_controls(self) -> ControlTransaction:
        display_id = self._require_display()
        session = self._state.monitor_controls
        requests = dict(session.staged)
        if not requests:
            raise no_staged_control()
        transaction = self._with_port(
            display_id,
            lambda port: apply_controls(port, display_id, requests, settle=_settle),
        )
        session.record_apply(transaction)
        self._invalidate_after_monitor_write()
        return transaction

    def restore_monitor_defaults(self) -> ActionOutcome[ControlRestore]:
        """Ask the display to restore its own factory settings, and read what moved.

        The restore code cannot be read back, so the display never says whether
        it did anything. What this reports is the two readings around the
        request. A panel that implements nothing here produces a restore whose
        readings match, and the summary says exactly that rather than claiming
        a reset happened.
        """
        return self._runner.run("ddc.restore_defaults", self._restore_monitor_defaults)

    def _restore_monitor_defaults(self) -> ControlRestore:
        display_id = self._require_display()
        restore = self._with_port(
            display_id,
            lambda port: restore_factory_defaults(port, display_id, settle=_settle),
        )
        self._state.monitor_controls.record_reading(restore.after)
        self._invalidate_after_monitor_write()
        return restore

    # -- shared helpers -----------------------------------------------------

    def _require_display(self) -> str:
        display_id = self._state.selected_display_id
        if display_id is None:
            raise no_display_selected()
        return display_id

    def _with_port(self, display_id: str, work: Callable[[MonitorControlPort], T]) -> T:
        """Hold one control port for one transaction, and close it however it ends.

        A driver failure inside the transaction becomes a retryable refusal
        rather than an unexpected error, because a display with DDC/CI switched
        off in its own menu is a state of the machine, not a defect in the
        program.
        """
        try:
            port = self._monitor_controls.open(display_id)
        except MonitorControlUnavailable as exc:
            raise monitor_control_refused(str(exc)) from exc
        try:
            return work(port)
        except (MonitorControlError, MonitorControlUnavailable) as exc:
            raise monitor_control_refused(str(exc)) from exc
        finally:
            port.close()


__all__ = ["MonitorControlActions"]
