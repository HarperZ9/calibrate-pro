"""Reading and writing a display's own controls from a terminal.

This is the one command family that changes the display rather than the signal
sent to it, so it is the one place a terminal run needs an explicit word from
the operator before anything moves. A run with no ``--confirm`` reads the
display, stages what was asked for, prints both numbers per control, and stops.
The same run with ``--confirm`` writes.

Every value is checked against the range the display reported in this run, by
the session rather than by the parser. A panel decides what its own brightness
scale means, and no table in this build can stand in for the answer it gave.

Nothing here decides whether a control may be written. The manifest and the
resolver do that, and a refusal printed by this command is the sentence the
window would have shown for the same session.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from calibrate_pro.application.control_results import ControlTransaction
    from calibrate_pro.application.monitor_controls import MonitorReading
    from calibrate_pro.application.service import FunctionalRecoveryService

#: Every staging action id begins with this, and the rest of it is the flag the
#: command line offers. Deriving the flags from the actions is what keeps the
#: parser from carrying a second copy of the control table to drift against.
STAGE_PREFIX = "ddc.stage."


def control_flags() -> tuple[str, ...]:
    """The flag each stageable control is named by on the command line."""
    from calibrate_pro.application.monitor_controls import STAGE_ACTION_CODES

    return tuple(f"--{action_id[len(STAGE_PREFIX) :].replace('_', '-')}" for action_id in STAGE_ACTION_CODES)


def _flag_for(action_id: str) -> str:
    return f"--{action_id[len(STAGE_PREFIX) :].replace('_', '-')}"


def _print_reading(reading: MonitorReading) -> None:
    """Print what the display answered, and name the flag that writes each control.

    The code is printed beside the label because a display's own menu names
    these differently than this build does, and the number is what the two have
    in common. A control that did not answer is listed with the reason rather
    than left out, so an operator can tell a control this build never asked for
    from one the display declined.
    """
    from calibrate_pro.application.monitor_controls import CONTROL_ACTIONS

    print(f"{reading.instrument} on {reading.display_id}")
    for control in reading.controls:
        flag = _flag_for(CONTROL_ACTIONS[control.code])
        print(f"  0x{control.code:02X}  {control.line:<34s} {flag}")
    for refused in reading.refused:
        print(f"  0x{refused.code:02X}  {refused.label}: not answered ({refused.reason})")


def _read_display(service: FunctionalRecoveryService, args: Any) -> MonitorReading:
    """Detect, select the display the operator named, and read its controls."""
    from calibrate_pro.commands.session import value

    value(service.detect())
    display_id = getattr(args, "display", None)
    if display_id:
        value(service.select_display(display_id))
    reading = value(service.read_monitor_controls())
    _print_reading(reading)
    return reading


def ddc_info(service: FunctionalRecoveryService, args: Any) -> int:
    """Report the controls the selected display answered for, writing nothing."""
    _read_display(service, args)
    return 0


def _requested_values(args: Any) -> tuple[tuple[str, int], ...]:
    """Pair each control the operator named with the action that stages it.

    The order is the order a reading lists, so a run that sets brightness and a
    channel gain prints the two in the sequence the panel's own menu shows them
    rather than the sequence they were typed in.
    """
    from calibrate_pro.application.monitor_controls import STAGE_ACTION_CODES

    named = []
    for action_id in STAGE_ACTION_CODES:
        requested = getattr(args, action_id[len(STAGE_PREFIX) :], None)
        if requested is not None:
            named.append((action_id, int(requested)))
    return tuple(named)


def _print_transaction(transaction: ControlTransaction) -> int:
    """Print what each code reads at after the write, and say whether it took.

    A display answers a write it ignored the same way it answers one it took,
    so the exit code is decided by the read-back rather than by the call
    returning. A run whose controls all landed elsewhere exits nonzero, which
    is what lets a script tell a working panel from one that is refusing.
    """
    for write in transaction.writes:
        print(f"  {write.line}")
    print("")
    print(transaction.summary)
    return 0 if transaction.accepted else 1


def _stage(service: FunctionalRecoveryService, requests: tuple[tuple[str, int], ...]) -> None:
    """Hold each named value against the reading, printing both numbers per control."""
    from calibrate_pro.commands.session import value

    for action_id, requested in requests:
        print(f"  {value(service.stage_monitor_control(action_id, requested)).line}")


def ddc_calibrate(service: FunctionalRecoveryService, args: Any) -> int:
    """Set the display's own controls, after reading what they currently hold.

    A restore is refused alongside staged values because the two disagree about
    what the run is for: the staged numbers were checked against a reading the
    restore is about to invalidate, and writing them afterwards would set the
    panel to values chosen against a state it no longer holds.
    """
    from calibrate_pro.commands.session import CommandError, value

    requests = _requested_values(args)
    restore = bool(getattr(args, "restore_defaults", False))
    if restore and requests:
        raise CommandError("--restore-defaults asks the display to choose its own values, so it takes no others.")
    if not restore and not requests:
        raise CommandError(f"Name at least one control to set, or pass --restore-defaults. {_flag_list()}")
    _read_display(service, args)
    print("")
    if not restore:
        _stage(service, requests)
    if not getattr(args, "confirm", False):
        print("")
        print("Nothing was written. Pass --confirm to change the display.")
        return 0
    print("")
    if restore:
        print(value(service.restore_monitor_defaults()).summary)
        return 0
    return _print_transaction(value(service.apply_monitor_controls()))


def _flag_list() -> str:
    return "Controls: " + ", ".join(control_flags()) + "."


__all__ = ["STAGE_PREFIX", "control_flags", "ddc_calibrate", "ddc_info"]
