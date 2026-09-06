"""The Windows source that satisfies the monitor control port.

Opening DDC/CI on Windows means acquiring a physical monitor handle from the
display driver, and that handle has to be given back. Every other route in this
build acquires one, does a single thing, and releases it. That is right for a
one-shot capture and wrong here: reading the eight controls this product stages
would acquire and release eight times, and applying a set would do it two dozen
times, on a bus that answers slowly and rate limits its own traffic.

So this source acquires once. A port holds one controller and one physical
monitor for as long as the caller holds the port, and closing the port destroys
the handle. A caller that never closes leaks a driver handle, which is why the
service layer opens a port inside a try/finally and nothing else opens one.

Reads accept any code the protocol can address, because a read changes nothing
and reporting what a display answers is the whole point of the raw read. Writes
are held to a short allowlist named here. That list is a second gate behind the
action manifest rather than a copy of it, and it is what stops a defect upstream
from turning into a write to a code this build cannot name or undo.

The brightness WMI fallback is refused on both paths. It reports a different
number in a different range than the DDC/CI control does, so a session that read
through it would compare a write against a value the write never touched.
"""

from __future__ import annotations

from typing import Any

from calibrate_pro.application.detection import CapabilityUnavailable
from calibrate_pro.application.monitor_controls import (
    NO_MONITOR_REASON,
    RESTORE_FACTORY_DEFAULTS,
    STAGEABLE_CODES,
    MonitorControlError,
    MonitorControlPort,
    MonitorControlUnavailable,
    label_for,
    validate_code,
)
from calibrate_pro.panels.detection import DisplayInfo

#: The codes this port will write. The eight staged controls plus the factory
#: restore request, which is a write with no readable value of its own.
WRITABLE_CODES: frozenset[int] = frozenset(STAGEABLE_CODES) | {RESTORE_FACTORY_DEFAULTS}

#: What the source reports when the driver layer is absent, which is every
#: machine that is not Windows and any Windows machine missing dxva2.
NO_DRIVER_REASON = "this machine exposes no DDC/CI driver"


def _load_ddc_module() -> Any:
    """Import the DDC/CI driver, naming the failure rather than passing it on."""
    try:
        from calibrate_pro.hardware import ddc_ci
    except Exception as exc:
        raise MonitorControlUnavailable(f"{NO_DRIVER_REASON}: {exc}") from exc
    return ddc_ci


def _display_name(hmonitor: object) -> str | None:
    """Name the logical display one physical monitor hangs off, or None.

    This is the only identity a physical monitor handle and a display id share.
    A monitor whose owning display cannot be named is skipped rather than
    guessed at, because guessing here would open a write channel to a panel the
    operator did not select.
    """
    import ctypes

    from calibrate_pro.panels import detection

    layout = getattr(detection, "MONITORINFOEX", None)
    if layout is None:
        return None
    info = layout()
    info.cbSize = ctypes.sizeof(info)
    if not detection.user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
        return None
    return str(info.szDevice)


def _monitor_label(monitor: dict[str, Any]) -> str:
    """Name one physical monitor by what the driver called it."""
    described = str(monitor.get("name") or "").strip()
    return described if described else "DDC/CI display"


def _close_quietly(controller: Any) -> None:
    """Give a handle back while a failure is already travelling."""
    close = getattr(controller, "close", None)
    if callable(close):
        close()


class WindowsMonitorControlPort:
    """One physical monitor's control channel, held open by its caller.

    The controller owns the handle and destroys it on close. Close is safe to
    call twice, and every operation after the first close is refused rather
    than sent to a handle the driver has already taken back.
    """

    def __init__(self, controller: Any, monitor: dict[str, Any], identity: str) -> None:
        if type(identity) is not str or not identity.strip():
            raise TypeError("identity must be a nonblank exact string")
        self._controller = controller
        self._monitor = monitor
        self._identity = identity
        self._open = True

    def identity(self) -> str:
        return self._identity

    def _handle(self) -> dict[str, Any]:
        if not self._open:
            raise MonitorControlError("this monitor control session is already closed")
        return self._monitor

    def read(self, code: int) -> tuple[int, int]:
        """Read one code, reporting the value and the maximum the display gave."""
        validate_code(code, "code")
        monitor = self._handle()
        current, maximum = self._controller.get_vcp(monitor, code, allow_wmi_fallback=False)
        return (int(current), int(maximum))

    def write(self, code: int, value: int) -> None:
        """Write one allowlisted code, refusing anything outside the list."""
        validate_code(code, "code")
        if code not in WRITABLE_CODES:
            raise MonitorControlError(f"{label_for(code)} is outside the codes this build writes")
        if isinstance(value, bool) or not isinstance(value, int):
            raise MonitorControlError(f"the value written to {label_for(code)} must be an exact integer")
        monitor = self._handle()
        if not self._controller.set_vcp(monitor, code, value, allow_wmi_fallback=False):
            raise MonitorControlError(f"the display refused the write to {label_for(code)}")

    def close(self) -> None:
        """Give the physical monitor handle back to the driver, once."""
        if not self._open:
            return
        self._open = False
        self._controller.close()


class WindowsMonitorControlSource:
    """Find one display on DDC/CI and open a port over it.

    Describing and counting displays both acquire handles and give them back
    inside the call. Only :meth:`open` hands a live handle to a caller, which
    is what makes the port's lifetime something a reader can follow.
    """

    def describe(self) -> str:
        """Name what answered on DDC/CI, or say that nothing did."""
        try:
            answered = self._enumerate()
        except MonitorControlUnavailable as exc:
            return str(exc)
        if not answered:
            return NO_MONITOR_REASON
        return ", ".join(answered)

    def present(self) -> bool:
        """Whether any display answered, without leaving a handle held."""
        try:
            return bool(self._enumerate())
        except MonitorControlUnavailable:
            return False

    def _enumerate(self) -> tuple[str, ...]:
        """Name every physical monitor DDC/CI answered with, holding nothing."""
        module = _load_ddc_module()
        controller = module.DDCCIController()
        try:
            return tuple(_monitor_label(monitor) for monitor in controller.enumerate_monitors())
        finally:
            _close_quietly(controller)

    def open(self, display_id: str) -> MonitorControlPort:
        """Open a port over the physical monitor that owns one display.

        A display id that matches more than one physical monitor is refused.
        Picking one would write to a panel the operator did not select, and on
        this protocol the operator has no way to see which one took the value.
        """
        if type(display_id) is not str or not display_id.strip():
            raise MonitorControlUnavailable("a display id is required to open a monitor control port")
        module = _load_ddc_module()
        controller = module.DDCCIController()
        try:
            matches = [
                monitor
                for monitor in controller.enumerate_monitors()
                if (_display_name(monitor.get("hmonitor")) or "").casefold() == display_id.casefold()
            ]
            if not matches:
                raise MonitorControlUnavailable(f"{NO_MONITOR_REASON} ({display_id})")
            if len(matches) > 1:
                raise MonitorControlUnavailable(
                    f"{display_id} answered as {len(matches)} physical monitors, and this build will not choose one"
                )
            return WindowsMonitorControlPort(controller, matches[0], _monitor_label(matches[0]))
        except BaseException:
            _close_quietly(controller)
            raise


def ddc_control_present(display: DisplayInfo) -> bool:
    """Answer the DDC/CI capability by opening the display and reading one code.

    This costs a device session, which is why the read-only probe does not wire
    it and a composition passes it in by name. Nothing cheaper answers the
    question: a display can enumerate on the bus, report a capability string
    listing brightness, and then refuse to read it.

    The port is closed before this returns, so the answer never leaves a handle
    held on a display the session may not go on to use.
    """
    source = WindowsMonitorControlSource()
    try:
        port = source.open(str(display.device_name))
    except MonitorControlUnavailable as exc:
        raise CapabilityUnavailable(str(exc)) from exc
    try:
        port.read(STAGEABLE_CODES[0])
    except Exception as exc:
        detail = str(exc).strip() or type(exc).__name__
        raise CapabilityUnavailable(f"{display.device_name} opened on DDC/CI and would not answer: {detail}") from exc
    finally:
        port.close()
    return True


__all__ = [
    "NO_DRIVER_REASON",
    "WRITABLE_CODES",
    "WindowsMonitorControlPort",
    "WindowsMonitorControlSource",
    "ddc_control_present",
]
