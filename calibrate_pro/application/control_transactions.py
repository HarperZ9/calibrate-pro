"""The procedure that changes a display's own controls, and checks that it did.

Every operation here reads before it writes and reads again afterwards. That is
not caution about the code, it is the only way to learn what a display did: the
write call reports whether the request reached the panel, and says nothing about
whether the panel acted on it. A display that silently ignores a gain write and
one that applies it return the same success.

So a write is staged against a value the display reported, refused if it falls
outside the range the display reported, and reported by the value the display
reads at afterwards. A read that will not answer stops the write rather than
proceeding without a way to check it.

When a write raises partway through a set, every code already written is put
back to the value read before the set began, and the result says so. A rollback
that itself fails is reported rather than absorbed, because a display left half
changed is the one state an operator has to be told about.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from calibrate_pro.application.control_results import (
    ControlRestore,
    ControlTransaction,
    ControlWrite,
)
from calibrate_pro.application.monitor_controls import (
    RESTORE_FACTORY_DEFAULTS,
    STAGEABLE_CODES,
    MonitorControl,
    MonitorControlError,
    MonitorControlPort,
    MonitorReading,
    RefusedControl,
    label_for,
)


def _reason(exc: BaseException) -> str:
    """Name a driver failure by its own message, or by its type when it gave none."""
    text = str(exc).strip()
    return text if text else type(exc).__name__


def _read_one(port: MonitorControlPort, code: int) -> MonitorControl:
    """Read one control, refusing an answer this build cannot make sense of."""
    try:
        current, maximum = port.read(code)
    except Exception as exc:
        raise MonitorControlError(f"{label_for(code)} did not answer: {_reason(exc)}") from exc
    return MonitorControl(code=code, label=label_for(code), current=int(current), maximum=int(maximum))


def read_controls(
    port: MonitorControlPort,
    display_id: str,
    codes: tuple[int, ...] = STAGEABLE_CODES,
) -> MonitorReading:
    """Read every named control, keeping the ones that did not answer.

    A display that drives six of these eight is normal, and the two that refuse
    are as much a part of the reading as the six that answer. Dropping them
    silently would leave a surface unable to say why a control it knows about
    is not on screen.
    """
    answered: list[MonitorControl] = []
    refused: list[RefusedControl] = []
    for code in codes:
        try:
            answered.append(_read_one(port, code))
        except MonitorControlError as exc:
            refused.append(RefusedControl(code=code, label=label_for(code), reason=_reason(exc)))
    return MonitorReading(
        display_id=display_id,
        instrument=port.identity(),
        controls=tuple(answered),
        refused=tuple(refused),
    )


def _ordered(requests: Mapping[int, int]) -> tuple[int, ...]:
    """Order the codes a set will write, so two identical sets write identically."""
    known = [code for code in STAGEABLE_CODES if code in requests]
    other = sorted(code for code in requests if code not in STAGEABLE_CODES)
    return tuple(known + other)


def _stage(port: MonitorControlPort, requests: Mapping[int, int]) -> dict[int, MonitorControl]:
    """Read what each requested code holds now, refusing a request it cannot take."""
    if not requests:
        raise MonitorControlError("no control value was staged for this display")
    before: dict[int, MonitorControl] = {}
    for code in _ordered(requests):
        value = requests[code]
        if isinstance(value, bool) or not isinstance(value, int):
            raise MonitorControlError(f"the value staged for {label_for(code)} must be an exact integer")
        control = _read_one(port, code)
        if value < 0 or value > control.maximum:
            raise MonitorControlError(
                f"{control.label} accepts 0 through {control.maximum}, and {value} was staged for it"
            )
        before[code] = control
    return before


def _roll_back(
    port: MonitorControlPort,
    before: Mapping[int, MonitorControl],
    written: tuple[int, ...],
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    """Put back every code already written, reporting any that would not go back."""
    restored: list[int] = []
    stuck: list[str] = []
    for code in reversed(written):
        try:
            port.write(code, before[code].current)
        except Exception as exc:
            stuck.append(f"{label_for(code)} would not go back to {before[code].current}: {_reason(exc)}")
            continue
        restored.append(code)
    return tuple(reversed(restored)), tuple(stuck)


def apply_controls(
    port: MonitorControlPort,
    display_id: str,
    requests: Mapping[int, int],
    *,
    settle: Callable[[], None],
) -> ControlTransaction:
    """Write a set of staged values and report what the display reads afterwards."""
    before = _stage(port, requests)
    order = _ordered(requests)
    written: list[int] = []
    for code in order:
        try:
            port.write(code, requests[code])
        except Exception as exc:
            failure = f"{label_for(code)} refused the write: {_reason(exc)}"
            restored, stuck = _roll_back(port, before, tuple(written))
            if stuck:
                failure += ". " + ". ".join(stuck)
            return ControlTransaction(display_id=display_id, writes=(), restored=restored, failure=failure)
        written.append(code)
    settle()
    return ControlTransaction(
        display_id=display_id,
        writes=tuple(_read_back(port, before, requests, code) for code in order),
        restored=(),
        failure=None,
    )


def _read_back(
    port: MonitorControlPort,
    before: Mapping[int, MonitorControl],
    requests: Mapping[int, int],
    code: int,
) -> ControlWrite:
    """Report one written code by the value the display reads at now.

    A read-back that fails is reported as the display still holding the value
    it held. That is the conservative answer: the write is not called accepted
    on the strength of a read nobody got.
    """
    try:
        after = _read_one(port, code).current
    except MonitorControlError:
        after = before[code].current
    return ControlWrite(
        code=code,
        label=before[code].label,
        before=before[code].current,
        requested=requests[code],
        after=after,
    )


def write_raw(
    port: MonitorControlPort,
    display_id: str,
    code: int,
    value: int,
    *,
    settle: Callable[[], None],
) -> ControlTransaction:
    """Write one arbitrary VCP code, after proving the code can be read back.

    A code that will not read is refused. Writing one would leave an operator
    holding a request with no way to learn whether the display took it, on the
    protocol where a display most often takes nothing and says it did.
    """
    return apply_controls(port, display_id, {code: value}, settle=settle)


def read_raw(port: MonitorControlPort, display_id: str, code: int) -> MonitorReading:
    """Read one arbitrary VCP code, reporting a refusal rather than raising."""
    return read_controls(port, display_id, codes=(code,))


def restore_factory_defaults(
    port: MonitorControlPort,
    display_id: str,
    *,
    settle: Callable[[], None],
) -> ControlRestore:
    """Ask a display to restore its own factory settings, and read what moved.

    The restore code cannot be read, so the display's answer is not available.
    What is available is the two readings around the request, which is what
    this reports. A display that implements nothing here produces a restore
    whose readings match, and the summary says exactly that.
    """
    before = read_controls(port, display_id)
    try:
        port.write(RESTORE_FACTORY_DEFAULTS, 1)
    except Exception as exc:
        raise MonitorControlError(f"the display refused the factory restore: {_reason(exc)}") from exc
    settle()
    return ControlRestore(display_id=display_id, before=before, after=read_controls(port, display_id))


__all__ = [
    "apply_controls",
    "read_controls",
    "read_raw",
    "restore_factory_defaults",
    "write_raw",
]
