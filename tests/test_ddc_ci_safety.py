"""Fake-only safety tests for DDC/CI physical-monitor handle ownership."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from calibrate_pro.hardware import ddc_ci


class CapabilityAbort(BaseException):
    """Simulate an in-process cancellation or other non-Exception abort."""


class FakeDxva2:
    def __init__(
        self,
        handles: tuple[int, ...],
        *,
        destroy: Callable[[int], bool] | None = None,
    ) -> None:
        self.handles = handles
        self.destroyed: list[int] = []
        self._destroy = destroy or (lambda _handle: True)

    def GetNumberOfPhysicalMonitorsFromHMONITOR(self, _hmonitor: object, count: Any) -> bool:
        count._obj.value = len(self.handles)
        return True

    def GetPhysicalMonitorsFromHMONITOR(
        self,
        _hmonitor: object,
        count: int,
        monitors: Any,
    ) -> bool:
        assert count == len(self.handles)
        for index, handle in enumerate(self.handles):
            monitors[index].hPhysicalMonitor = handle
            monitors[index].szPhysicalMonitorDescription = f"Panel {index + 1}"
        return True

    def DestroyPhysicalMonitor(self, handle: object) -> bool:
        value = int(handle)
        self.destroyed.append(value)
        return self._destroy(value)


class FakeUser32:
    def __init__(self, *, result: bool = True) -> None:
        self.result = result

    def EnumDisplayMonitors(
        self,
        _hdc: object,
        _clip: object,
        callback: Callable[..., bool],
        _data: int,
    ) -> bool:
        callback_result = bool(callback(7, None, None, 0))
        return self.result and callback_result


def make_controller(
    monkeypatch: pytest.MonkeyPatch,
    handles: tuple[int, ...] = (101, 202),
    *,
    enum_result: bool = True,
    destroy: Callable[[int], bool] | None = None,
) -> ddc_ci.DDCCIController:
    monkeypatch.setattr(
        ddc_ci.ctypes,
        "WINFUNCTYPE",
        lambda *_args: lambda callback: callback,
        raising=False,
    )
    controller = object.__new__(ddc_ci.DDCCIController)
    controller._available = True
    controller._monitors = []
    controller.dxva2 = FakeDxva2(handles, destroy=destroy)
    controller.user32 = FakeUser32(result=enum_result)
    return controller


@pytest.mark.parametrize("reported_count", [0, 65, 0xFFFFFFFF])
def test_unreasonable_physical_monitor_counts_are_rejected_before_array_allocation(
    monkeypatch: pytest.MonkeyPatch,
    reported_count: int,
) -> None:
    controller = make_controller(monkeypatch, handles=())
    allocation_attempts: list[int] = []

    class AllocationProbeMeta(type):
        def __mul__(cls, count: int) -> object:
            allocation_attempts.append(count)
            raise AssertionError(f"physical-monitor array allocation attempted for {count}")

    class AllocationProbe(metaclass=AllocationProbeMeta):
        pass

    def report_count(_hmonitor: object, count: Any) -> bool:
        count._obj.value = reported_count
        return True

    monkeypatch.setattr(ddc_ci, "PHYSICAL_MONITOR", AllocationProbe)
    monkeypatch.setattr(
        controller.dxva2,
        "GetNumberOfPhysicalMonitorsFromHMONITOR",
        report_count,
    )

    with pytest.raises(
        RuntimeError,
        match=rf"physical monitor count {reported_count}.*1\.\.64",
    ):
        controller.enumerate_monitors()

    assert allocation_attempts == []
    assert controller.dxva2.destroyed == []
    assert controller._monitors == []


@pytest.mark.parametrize("reported_length", [0, 65_537, 0xFFFFFFFF])
def test_unreasonable_capabilities_lengths_are_rejected_before_buffer_allocation_and_cleaned_up(
    monkeypatch: pytest.MonkeyPatch,
    reported_length: int,
) -> None:
    controller = make_controller(monkeypatch)
    allocation_attempts: list[int] = []

    def report_length(_handle: object, length: Any) -> bool:
        length._obj.value = reported_length
        return True

    def record_allocation(size: int) -> object:
        allocation_attempts.append(size)
        raise AssertionError(f"capabilities buffer allocation attempted for {size}")

    monkeypatch.setattr(controller.dxva2, "GetCapabilitiesStringLength", report_length, raising=False)
    monkeypatch.setattr(ddc_ci.ctypes, "create_string_buffer", record_allocation)

    with pytest.raises(
        RuntimeError,
        match=rf"capabilities string length {reported_length}.*1\.\.65536",
    ):
        controller.enumerate_monitors()

    assert allocation_attempts == []
    assert controller.dxva2.destroyed == [101, 202]
    assert controller._monitors == []


@pytest.mark.parametrize(
    "interruption",
    [
        RuntimeError("capabilities allocation failed"),
        KeyboardInterrupt("capabilities allocation cancelled"),
        SystemExit(35),
    ],
)
def test_capabilities_buffer_allocation_failure_keeps_acquired_handles_cleanup_accounted(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    controller = make_controller(monkeypatch)

    def report_length(_handle: object, length: Any) -> bool:
        length._obj.value = 32
        return True

    def interrupt_allocation(_size: int) -> object:
        raise interruption

    monkeypatch.setattr(controller.dxva2, "GetCapabilitiesStringLength", report_length, raising=False)
    monkeypatch.setattr(ddc_ci.ctypes, "create_string_buffer", interrupt_allocation)

    with pytest.raises(type(interruption)) as caught:
        controller.enumerate_monitors()

    assert caught.value is interruption
    assert controller.dxva2.destroyed == [101, 202]
    assert controller._monitors == []


@pytest.mark.parametrize(
    "failure",
    (
        RuntimeError("capability parser failed"),
        CapabilityAbort("capability probing was interrupted"),
    ),
)
def test_capability_failure_cleans_the_entire_acquired_batch(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    controller = make_controller(monkeypatch)
    registry_sizes: list[int] = []

    def fail_capabilities(_handle: object) -> None:
        registry_sizes.append(len(controller._monitors))
        raise failure

    controller._get_capabilities = fail_capabilities  # type: ignore[method-assign]

    with pytest.raises(type(failure), match=str(failure)):
        controller.enumerate_monitors()

    assert registry_sizes == [2]
    assert controller.dxva2.destroyed == [101, 202]
    assert controller._monitors == []
    controller.close()
    assert controller.dxva2.destroyed == [101, 202]


def test_native_enumeration_failure_is_reported_after_handle_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = make_controller(monkeypatch, enum_result=False)
    controller._get_capabilities = lambda _handle: None  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="EnumDisplayMonitors"):
        controller.enumerate_monitors()

    assert controller.dxva2.destroyed == [101, 202]
    assert controller._monitors == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("registration cancelled"), SystemExit(31)])
@pytest.mark.parametrize("failing_record", [1, 2])
def test_native_batch_is_destroyed_if_python_registration_is_interrupted(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    failing_record: int,
) -> None:
    controller = make_controller(monkeypatch)
    controller._get_capabilities = lambda _handle: None  # type: ignore[method-assign]
    build_calls = 0

    def interrupt_registration(_hmonitor: object, physical_monitor: object) -> dict[str, object]:
        nonlocal build_calls
        build_calls += 1
        if build_calls == failing_record:
            raise interruption
        return {
            "handle": physical_monitor.hPhysicalMonitor,  # type: ignore[attr-defined]
            "name": physical_monitor.szPhysicalMonitorDescription,  # type: ignore[attr-defined]
            "hmonitor": _hmonitor,
            "capabilities": None,
        }

    monkeypatch.setattr(controller, "_build_monitor_record", interrupt_registration, raising=False)

    with pytest.raises(type(interruption)) as caught:
        controller.enumerate_monitors()

    assert caught.value is interruption
    assert controller.dxva2.destroyed == [101, 202]
    assert controller._monitors == []


def test_close_retains_uncertain_ownership_after_non_oserror_destroy_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def destroy(handle: int) -> bool:
        if handle == 101:
            raise ValueError("unexpected destroy failure")
        return True

    controller = make_controller(monkeypatch, destroy=destroy)
    controller._monitors = [
        {"handle": 101},
        {"handle": 202},
    ]

    with pytest.raises(RuntimeError, match="unexpected destroy failure"):
        controller.close()

    assert controller.dxva2.destroyed == [101, 202]
    assert controller._monitors == [{"handle": 101, "_destroy_uncertain": True}]
    with pytest.raises(RuntimeError, match="uncertain|manual recovery"):
        controller.close()
    assert controller.dxva2.destroyed == [101, 202]


def test_close_retains_a_false_destroy_for_an_authoritative_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def destroy(handle: int) -> bool:
        nonlocal attempts
        if handle == 101:
            attempts += 1
            return attempts > 1
        return True

    controller = make_controller(monkeypatch, destroy=destroy)
    controller._monitors = [{"handle": 101}, {"handle": 202}]

    with pytest.raises(RuntimeError, match="destroy|101"):
        controller.close()

    assert controller.dxva2.destroyed == [101, 202]
    assert controller._monitors == [{"handle": 101}]

    controller.close()

    assert controller.dxva2.destroyed == [101, 202, 101]
    assert controller._monitors == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("pre-destroy"), SystemExit(34)])
def test_close_retains_a_handle_when_cancellation_prevents_the_native_destroy_call(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    controller = make_controller(monkeypatch)
    controller._monitors = [{"handle": 101}, {"handle": 202}]
    destroy_code = ddc_ci.DDCCIController._destroy_monitor_handles.__code__
    source_lines = Path(destroy_code.co_filename).read_text(encoding="utf-8").splitlines()
    fired = False

    def interrupt_before_destroy(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is destroy_code  # type: ignore[attr-defined]
            and "DestroyPhysicalMonitor" in source_lines[frame.f_lineno - 1]  # type: ignore[attr-defined]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_before_destroy

    sys.settrace(interrupt_before_destroy)
    try:
        with pytest.raises(type(interruption)) as caught:
            controller.close()
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert controller.dxva2.destroyed == [202]
    assert controller._monitors == [{"handle": 101}]

    controller.close()

    assert controller.dxva2.destroyed == [202, 101]
    assert controller._monitors == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("publication cancelled"), SystemExit(32)])
def test_close_finishes_authoritative_detachment_if_publication_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    controller = make_controller(monkeypatch)
    controller._monitors = [{"handle": 101}, {"handle": 202}]
    destroy_code = ddc_ci.DDCCIController._destroy_monitor_handles.__code__
    source_lines = Path(destroy_code.co_filename).read_text(encoding="utf-8").splitlines()
    fired = False

    def interrupt_after_destroy(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is destroy_code  # type: ignore[attr-defined]
            and "self._monitors.remove" in source_lines[frame.f_lineno - 1]  # type: ignore[attr-defined]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_after_destroy

    sys.settrace(interrupt_after_destroy)
    try:
        with pytest.raises(type(interruption)) as caught:
            controller.close()
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert controller.dxva2.destroyed == [101, 202]
    assert controller._monitors == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("destroy cancelled"), SystemExit(33)])
def test_close_attempts_every_destroy_then_preserves_control_flow_exception(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    def destroy(handle: int) -> bool:
        if handle == 101:
            raise interruption
        return True

    controller = make_controller(monkeypatch, destroy=destroy)
    controller._monitors = [{"handle": 101}, {"handle": 202}]

    with pytest.raises(type(interruption)) as caught:
        controller.close()

    assert caught.value is interruption
    assert controller.dxva2.destroyed == [101, 202]
    assert controller._monitors == [{"handle": 101, "_destroy_uncertain": True}]
    with pytest.raises(RuntimeError, match="uncertain|manual recovery"):
        controller.close()
    assert controller.dxva2.destroyed == [101, 202]


def test_native_library_loading_binds_all_used_pointer_sized_abis(monkeypatch: pytest.MonkeyPatch) -> None:
    class Function:
        argtypes: object = None
        restype: object = None

        def __call__(self, *_args: object) -> bool:
            raise AssertionError("ABI binding test must not call a native function")

    dxva2_names = (
        "GetNumberOfPhysicalMonitorsFromHMONITOR",
        "GetPhysicalMonitorsFromHMONITOR",
        "GetCapabilitiesStringLength",
        "CapabilitiesRequestAndCapabilitiesReply",
        "GetVCPFeatureAndVCPFeatureReply",
        "SetVCPFeature",
        "DestroyPhysicalMonitor",
    )
    dxva2 = SimpleNamespace(**{name: Function() for name in dxva2_names})
    user32 = SimpleNamespace(EnumDisplayMonitors=Function())
    monkeypatch.setattr(ddc_ci.ctypes, "windll", SimpleNamespace(dxva2=dxva2, user32=user32))

    controller = object.__new__(ddc_ci.DDCCIController)
    controller._load_libraries()

    assert controller.available is True
    for name in dxva2_names:
        function = getattr(dxva2, name)
        assert function.argtypes is not None, name
        assert function.restype is ddc_ci.wintypes.BOOL, name
    assert dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes == [
        ddc_ci.wintypes.HMONITOR,
        ddc_ci.ctypes.POINTER(ddc_ci.wintypes.DWORD),
    ]
    assert dxva2.GetPhysicalMonitorsFromHMONITOR.argtypes == [
        ddc_ci.wintypes.HMONITOR,
        ddc_ci.wintypes.DWORD,
        ddc_ci.ctypes.POINTER(ddc_ci.PHYSICAL_MONITOR),
    ]
    assert dxva2.GetVCPFeatureAndVCPFeatureReply.argtypes == [
        ddc_ci.wintypes.HANDLE,
        ddc_ci.ctypes.c_ubyte,
        ddc_ci.ctypes.POINTER(ddc_ci.wintypes.DWORD),
        ddc_ci.ctypes.POINTER(ddc_ci.wintypes.DWORD),
        ddc_ci.ctypes.POINTER(ddc_ci.wintypes.DWORD),
    ]
    assert dxva2.SetVCPFeature.argtypes == [
        ddc_ci.wintypes.HANDLE,
        ddc_ci.ctypes.c_ubyte,
        ddc_ci.wintypes.DWORD,
    ]
    assert dxva2.DestroyPhysicalMonitor.argtypes == [ddc_ci.wintypes.HANDLE]
    assert user32.EnumDisplayMonitors.argtypes is not None
    assert user32.EnumDisplayMonitors.restype is ddc_ci.wintypes.BOOL
