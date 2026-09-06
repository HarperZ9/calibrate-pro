"""Fake-only and import-only regression tests for shared Win32 ctypes contracts."""

from __future__ import annotations

import dis
import os
import subprocess
import sys
import threading
from ctypes import wintypes
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace

import pytest

from calibrate_pro.adapters import windows_display_state as windows_state
from calibrate_pro.panels import detection

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Win32 ctypes contracts")

_SHARED_ABI_MODULES = (
    "calibrate_pro.profiles.profile_installer",
    "calibrate_pro.panels.detection",
    "calibrate_pro.lut_system.vcgt_calibration",
)


@pytest.fixture(autouse=True)
def isolate_retained_display_dc_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep deliberately retained fake HDC owners from crossing test boundaries."""
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", [])


class BombUser32:
    """Prevent a regression from reaching the real display DC entrypoints."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"display DC call incorrectly routed through user32.{name}")


class FakeGdi32:
    def __init__(
        self,
        *,
        cancellation: BaseException | None = None,
        delete_success: bool = True,
        delete_exception: BaseException | None = None,
    ) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.native_threads: list[tuple[str, int]] = []
        self.cancellation = cancellation
        self.delete_success = delete_success
        self.delete_exception = delete_exception

    def CreateDCW(self, driver: str, device: str, port: object, devmode: object) -> int:
        self.native_threads.append(("create", threading.get_ident()))
        self.calls.append(("create", driver, device, port, devmode))
        return 77

    def DeleteDC(self, dc: int) -> bool:
        self.native_threads.append(("delete", threading.get_ident()))
        self.calls.append(("delete", dc))
        if self.delete_exception is not None:
            raise self.delete_exception
        return self.delete_success

    def GetICMProfileW(self, dc: int, _size: object, buffer: object) -> bool:
        self.calls.append(("get-profile", dc))
        if self.cancellation is not None:
            raise self.cancellation
        buffer.value = r"C:\Color\prior.icc"  # type: ignore[attr-defined]
        return True

    def SetICMProfileW(self, dc: int, path: str) -> bool:
        self.calls.append(("set-profile", dc, path))
        return True

    def GetDeviceGammaRamp(self, dc: int, ramp_pointer: object) -> bool:
        self.calls.append(("get-gamma", dc))
        ramp = ramp_pointer._obj  # type: ignore[attr-defined]
        for index in range(256):
            ramp.Red[index] = index
            ramp.Green[index] = index + 1
            ramp.Blue[index] = index + 2
        return True

    def SetDeviceGammaRamp(self, dc: int, _ramp_pointer: object) -> bool:
        self.calls.append(("set-gamma", dc))
        return True


class FakeKernelFunction:
    """Callable Win32 stand-in whose configured ABI remains inspectable."""

    argtypes: object = None
    restype: object = None

    def __init__(self, callback: object) -> None:
        self.callback = callback

    def __call__(self, *args: object) -> object:
        return self.callback(*args)  # type: ignore[operator]


def interrupt_at_opcode(function: object, offset: int, interruption: BaseException) -> object:
    fired = False

    def trace(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if event == "call" and frame.f_code is function.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
            return trace
        if (
            not fired
            and event == "opcode"
            and frame.f_code is function.__code__  # type: ignore[attr-defined]
            and frame.f_lasti == offset  # type: ignore[attr-defined]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return trace

    return trace


def test_detection_profile_calls_use_gdi32_and_close_each_dc(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGdi32()
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "user32", BombUser32())

    assert detection.get_display_profile(r"\\.\DISPLAY1") == r"C:\Color\prior.icc"
    assert detection.set_display_profile(r"\\.\DISPLAY1", r"C:\Color\target.icc") is True
    assert fake.calls == [
        ("create", "DISPLAY", r"\\.\DISPLAY1", None, None),
        ("get-profile", 77),
        ("delete", 77),
        ("create", "DISPLAY", r"\\.\DISPLAY1", None, None),
        ("set-profile", 77, r"C:\Color\target.icc"),
        ("delete", 77),
    ]


def test_detection_gamma_calls_use_gdi32_and_close_each_dc(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGdi32()
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "user32", BombUser32())

    ramp = detection.get_gamma_ramp(r"\\.\DISPLAY1")
    assert ramp is not None
    red, green, blue = ramp
    assert (int(red[5]), int(green[5]), int(blue[5])) == (5, 6, 7)
    assert detection.set_gamma_ramp(r"\\.\DISPLAY1", red, green, blue) is True
    assert [call[0] for call in fake.calls] == ["create", "get-gamma", "delete", "create", "set-gamma", "delete"]


def test_detection_profile_cancellation_closes_dc_and_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    cancellation = KeyboardInterrupt("cancelled during profile read")
    fake = FakeGdi32(cancellation=cancellation)
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "user32", BombUser32())

    with pytest.raises(KeyboardInterrupt) as caught:
        detection.get_display_profile(r"\\.\DISPLAY1")

    assert caught.value is cancellation
    assert fake.calls[-1] == ("delete", 77)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("post-create cancellation"), SystemExit(41)])
def test_detection_dc_handoff_closes_on_first_post_create_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    fake = FakeGdi32()
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "user32", BombUser32())
    display_dc_code = detection._display_dc.__wrapped__.__code__  # type: ignore[attr-defined]
    fired = False

    def interrupt_after_create(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        frame_code = frame.f_code  # type: ignore[attr-defined]
        frame_locals = frame.f_locals  # type: ignore[attr-defined]
        if (
            not fired
            and event == "line"
            and frame_code is display_dc_code
            and frame_locals.get("dc") == 77
            and fake.calls == [("create", "DISPLAY", r"\\.\DISPLAY1", None, None)]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_after_create

    sys.settrace(interrupt_after_create)
    try:
        with pytest.raises(type(interruption)) as caught:
            detection.get_display_profile(r"\\.\DISPLAY1")
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert fake.calls[-1] == ("delete", 77)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("CreateDC store"), SystemExit(64)])
def test_detection_dc_acquisition_survives_call_to_store_fast_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    """Caller-local tracing cannot interrupt the exact native worker's publication."""
    fake = FakeGdi32()
    caller_thread = threading.get_ident()
    retained: list[object] = []
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "user32", BombUser32())
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)
    # CPython 3.12 does not emit generator opcode events on this frame's first
    # traced activation; prime the fake-only frame before the fault injection.
    function = detection._display_dc.__wrapped__  # type: ignore[attr-defined]

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is function.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    sys.settrace(prime_opcode_tracing)
    try:
        with detection._display_dc(r"\\.\DISPLAY1") as dc:
            assert dc == 77
    finally:
        sys.settrace(None)
    fake.calls.clear()
    fake.native_threads.clear()
    instructions = tuple(dis.get_instructions(function))
    target = next(
        instruction.offset
        for index, instruction in enumerate(instructions)
        if instruction.opname == "STORE_FAST"
        and instruction.argval == "owner"
        and any(previous.argval == "_acquire_display_dc" for previous in instructions[max(0, index - 8) : index])
    )

    sys.settrace(interrupt_at_opcode(function, target, interruption))
    try:
        with pytest.raises(type(interruption)) as caught:
            detection.get_display_profile(r"\\.\DISPLAY1")
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert ("delete", 77) in fake.calls or any(getattr(record, "dc", None) == 77 for record in retained)
    assert [action for action, _thread in fake.native_threads] == ["create", "delete"]
    assert all(thread != caller_thread for _action, thread in fake.native_threads)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("cleanup boundary"), SystemExit(44)])
def test_detection_dc_cleanup_starts_when_resumption_from_yield_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    fake = FakeGdi32()
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "user32", BombUser32())
    display_dc_code = detection._display_dc.__wrapped__.__code__  # type: ignore[attr-defined]
    fired = False

    def interrupt_on_context_resumption(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is display_dc_code  # type: ignore[attr-defined]
            and ("get-profile", 77) in fake.calls
            and ("delete", 77) not in fake.calls
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_on_context_resumption

    sys.settrace(interrupt_on_context_resumption)
    try:
        with pytest.raises(type(interruption)) as caught:
            detection.get_display_profile(r"\\.\DISPLAY1")
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert fake.calls[-1] == ("delete", 77)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("delete cancellation"), SystemExit(42)])
def test_detection_dc_delete_preserves_control_flow_exception(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    fake = FakeGdi32(delete_exception=interruption)
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "user32", BombUser32())

    with pytest.raises(type(interruption)) as caught:
        detection.get_display_profile(r"\\.\DISPLAY1")

    assert caught.value is interruption
    assert fake.calls[-1] == ("delete", 77)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("pre-delete"), SystemExit(43)])
def test_detection_dc_cleanup_retries_when_cancellation_prevents_delete_dc_entry(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    fake = FakeGdi32()
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    helper = detection._close_claimed_display_dc
    helper_code = helper.__code__
    source_lines = Path(helper_code.co_filename).read_text(encoding="utf-8").splitlines()
    fired = False

    def interrupt_before_delete(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is helper_code  # type: ignore[attr-defined]
            and "DeleteDC" in source_lines[frame.f_lineno - 1]  # type: ignore[attr-defined]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_before_delete

    sys.settrace(interrupt_before_delete)
    try:
        with pytest.raises(type(interruption)) as caught:
            detection.get_display_profile(r"\\.\DISPLAY1")
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert fake.calls[-1] == ("delete", 77)


def test_detection_gamma_fails_closed_when_dc_release_remains_open(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeGdi32(delete_success=False)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "user32", BombUser32())

    ramp = detection.get_gamma_ramp(r"\\.\DISPLAY1")
    assert ramp is None

    channel = __import__("numpy").arange(256, dtype="uint16")
    assert detection.set_gamma_ramp(r"\\.\DISPLAY1", channel, channel, channel) is False
    assert [call[0] for call in fake.calls] == [
        "create",
        "get-gamma",
        "delete",
        "delete",
        "delete",
        "delete",
    ]


def test_detection_dc_release_retries_a_proven_open_false_result(monkeypatch: pytest.MonkeyPatch) -> None:
    class RetryableDeleteGdi(FakeGdi32):
        def __init__(self) -> None:
            super().__init__()
            self.delete_results = iter((False, True))

        def DeleteDC(self, dc: int) -> bool:
            self.calls.append(("delete", dc))
            return next(self.delete_results)

    fake = RetryableDeleteGdi()
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "user32", BombUser32())

    assert detection.get_display_profile(r"\\.\DISPLAY1") == r"C:\Color\prior.icc"
    assert fake.calls[-2:] == [("delete", 77), ("delete", 77)]


def test_detection_dc_release_retains_a_still_open_dc_after_bounded_false_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeGdi32(delete_success=False)
    retained: list[object] = []
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "user32", BombUser32())
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained, raising=False)

    assert detection.get_display_profile(r"\\.\DISPLAY1") is None
    assert [call for call in fake.calls if call[0] == "delete"] == [("delete", 77), ("delete", 77)]
    assert len(retained) == 1
    assert getattr(retained[0], "dc", None) == 77
    assert getattr(retained[0], "outcome", None) == "open"


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("between DeleteDC attempts"), SystemExit(65)])
def test_detection_dc_release_retains_or_retries_when_cancelled_between_false_attempts(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    class RetryableDeleteGdi(FakeGdi32):
        def __init__(self) -> None:
            super().__init__()
            self.delete_results = iter((False, True))

        def DeleteDC(self, dc: int) -> bool:
            self.calls.append(("delete", dc))
            return next(self.delete_results)

    fake = RetryableDeleteGdi()
    retained: list[object] = []
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)
    function = detection._close_claimed_display_dc
    fired = False

    def interrupt_between_attempts(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is function.__code__  # type: ignore[attr-defined]
            and [call for call in fake.calls if call[0] == "delete"] == [("delete", 77)]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_between_attempts

    sys.settrace(interrupt_between_attempts)
    try:
        with pytest.raises(type(interruption)) as caught:
            detection.get_display_profile(r"\\.\DISPLAY1")
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    deletes = [call for call in fake.calls if call[0] == "delete"]
    assert deletes == [("delete", 77), ("delete", 77)] or any(
        getattr(record, "dc", None) == 77 and getattr(record, "outcome", None) == "open" for record in retained
    )


def test_retained_display_dc_drain_uses_bound_api_and_removes_closed_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeGdi32(delete_success=False)
    retained: list[object] = []
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)

    assert detection.get_display_profile(r"\\.\DISPLAY1") is None
    assert retained
    fake.delete_success = True
    monkeypatch.setattr(detection, "gdi32", SimpleNamespace(DeleteDC=lambda *_args: False))
    drain = getattr(detection, "_drain_retained_display_dcs", None)

    assert callable(drain)
    drain()

    assert retained == []
    assert fake.calls[-1] == ("delete", 77)


def test_delete_dc_allows_only_one_worker_for_one_open_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingDeleteGdi(FakeGdi32):
        def __init__(self) -> None:
            super().__init__()
            self.call_count = 0
            self.call_lock = threading.Lock()
            self.first_entered = threading.Event()
            self.second_entered = threading.Event()
            self.release = threading.Event()

        def DeleteDC(self, dc: int) -> bool:
            with self.call_lock:
                self.call_count += 1
                call_number = self.call_count
            self.calls.append(("delete", dc, call_number))
            if call_number == 1:
                self.first_entered.set()
            else:
                self.second_entered.set()
            assert self.release.wait(timeout=2)
            return True

    fake = BlockingDeleteGdi()
    owner = detection._RetainedDisplayDc(
        api=fake,
        device_name=r"\\.\DISPLAY1",
        dc=77,
        outcome="open",
    )
    retained: list[object] = [owner]
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)
    callers_ready = threading.Barrier(3)
    results: list[BaseException | None] = []

    def close_owner() -> None:
        callers_ready.wait()
        try:
            results.append(detection._close_display_dc(owner))
        except BaseException as error:
            results.append(error)

    callers = [threading.Thread(target=close_owner) for _ in range(2)]
    for caller in callers:
        caller.start()
    callers_ready.wait()
    assert fake.first_entered.wait(timeout=1)
    try:
        assert not fake.second_entered.wait(timeout=0.2)
    finally:
        fake.release.set()
    for caller in callers:
        caller.join(timeout=2)

    assert all(not caller.is_alive() for caller in callers)
    assert fake.call_count == 1
    assert results == [None, None]
    assert retained == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("display claim handoff"), SystemExit(71)])
def test_display_claim_guard_rolls_back_cancellation_before_body(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    owner = detection._RetainedDisplayDc(
        api=FakeGdi32(),
        device_name=r"\\.\DISPLAY1",
        dc=77,
        outcome="open",
    )
    retained: list[object] = [owner]
    token = object()
    body_entered: list[bool] = []
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)

    def claim_then_enter_body() -> None:
        with detection._claim_display_dc_owner(owner, token) as claim:
            assert claim.acquired
            body_entered.append(True)

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is claim_then_enter_body.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    sys.settrace(prime_opcode_tracing)
    try:
        claim_then_enter_body()
    finally:
        sys.settrace(None)
    body_entered.clear()

    def interrupt_before_body(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and frame.f_code is claim_then_enter_body.__code__  # type: ignore[attr-defined]
            and owner.claim is detection._OwnerClaim.CLAIMED
            and body_entered == []
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_before_body

    sys.settrace(interrupt_before_body)
    try:
        with pytest.raises(type(interruption)) as caught:
            claim_then_enter_body()
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert body_entered == []
    assert owner.claim is detection._OwnerClaim.RETAINED
    assert owner.claimant is None
    assert retained == [owner]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("display guard return"), SystemExit(75)])
def test_display_claim_guard_return_cancellation_cannot_strand_claim(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    owner = detection._RetainedDisplayDc(
        api=FakeGdi32(),
        device_name=r"\\.\DISPLAY1",
        dc=77,
        outcome="open",
    )
    retained: list[object] = [owner]
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)
    guard = detection._claim_display_dc_owner(owner, object())
    function = type(guard).__enter__

    priming_guard = detection._claim_display_dc_owner(owner, object())

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is function.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    sys.settrace(prime_opcode_tracing)
    try:
        priming_guard.__enter__()
    finally:
        sys.settrace(None)
        priming_guard.__exit__(None, None, None)
    returns = [
        instruction.offset for instruction in dis.get_instructions(function) if instruction.opname.startswith("RETURN")
    ]
    sys.settrace(interrupt_at_opcode(function, returns[-1], interruption))
    try:
        with pytest.raises(type(interruption)) as caught:
            guard.__enter__()
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert owner.claim is detection._OwnerClaim.RETAINED
    assert owner.claimant is None
    assert retained == [owner]


@pytest.mark.parametrize("assignment", ["claimant", "claim"])
def test_display_claim_publication_cancellation_rolls_back_from_shared_token(
    monkeypatch: pytest.MonkeyPatch,
    assignment: str,
    unmeasured_tracing: None,
) -> None:
    fake = FakeGdi32()
    owner = detection._RetainedDisplayDc(
        api=fake,
        device_name=r"\\.\DISPLAY1",
        dc=77,
        outcome="open",
    )
    retained: list[object] = [owner]
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)
    monkeypatch.setattr(detection, "_NATIVE_WORKER_JOIN_SECONDS", 0.01)
    guard = detection._claim_display_dc_owner(owner, object())
    function = type(guard)._acquire

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is function.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    priming_guard = detection._claim_display_dc_owner(owner, object())
    sys.settrace(prime_opcode_tracing)
    try:
        with priming_guard as claim:
            assert claim.acquired
    finally:
        sys.settrace(None)
    instructions = tuple(dis.get_instructions(function))
    store_index = next(
        index
        for index, instruction in enumerate(instructions)
        if instruction.opname == "STORE_ATTR" and instruction.argval == assignment
    )
    interruption = KeyboardInterrupt(f"display {assignment} publication")
    sys.settrace(interrupt_at_opcode(function, instructions[store_index + 1].offset, interruption))
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            with guard as claim:
                assert claim.acquired
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert owner.claim is detection._OwnerClaim.RETAINED
    assert owner.claimant is None
    assert detection._close_display_dc(owner) is None
    assert fake.calls == [("delete", 77)]
    assert retained == []


def test_display_owner_cannot_be_drained_between_acquisition_and_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeGdi32()
    acquired = threading.Event()
    release_activation = threading.Event()
    original_acquire = detection._acquire_display_dc
    result: list[object] = []
    errors: list[BaseException] = []
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)

    def pause_after_acquisition(
        device_name: str,
        *,
        owner: object | None = None,
    ) -> object:
        acquired_owner = original_acquire(device_name, owner=owner)  # type: ignore[arg-type]
        acquired.set()
        assert release_activation.wait(timeout=2)
        return acquired_owner

    monkeypatch.setattr(detection, "_acquire_display_dc", pause_after_acquisition)

    def read_profile() -> None:
        try:
            result.append(detection.get_display_profile(r"\\.\DISPLAY1"))
        except BaseException as error:
            errors.append(error)

    reader = threading.Thread(target=read_profile)
    reader.start()
    assert acquired.wait(timeout=1)
    try:
        detection._drain_retained_display_dcs()
        assert [call for call in fake.calls if call[0] == "delete"] == []
    finally:
        release_activation.set()
        reader.join(timeout=2)

    assert not reader.is_alive()
    assert errors == []
    assert result == [r"C:\Color\prior.icc"]
    assert [call for call in fake.calls if call[0] == "delete"] == [("delete", 77)]


def test_retained_display_dc_drain_does_not_close_an_active_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeGdi32()
    owner = detection._RetainedDisplayDc(
        api=fake,
        device_name=r"\\.\DISPLAY1",
        dc=77,
        outcome="open",
        active=True,
    )
    retained: list[object] = [owner]
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)

    detection._drain_retained_display_dcs()

    assert fake.calls == []
    assert retained == [owner]
    owner.active = False
    detection._drain_retained_display_dcs()
    assert fake.calls == [("delete", 77)]
    assert retained == []


def test_closed_display_owner_is_retired_from_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeGdi32()
    owner = detection._RetainedDisplayDc(
        api=fake,
        device_name=r"\\.\DISPLAY1",
        dc=77,
        outcome="closed",
    )
    retained: list[object] = [owner]
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)

    detection._drain_retained_display_dcs()

    assert retained == []
    assert fake.calls == []


def test_display_registry_capacity_counts_pending_ingress_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingCreateGdi(FakeGdi32):
        def __init__(self) -> None:
            super().__init__()
            self.call_count = 0
            self.call_lock = threading.Lock()
            self.first_entered = threading.Event()
            self.second_entered = threading.Event()
            self.release = threading.Event()

        def CreateDCW(self, driver: str, device: str, port: object, devmode: object) -> int:
            with self.call_lock:
                self.call_count += 1
                call_number = self.call_count
            self.calls.append(("create", driver, device, port, devmode, call_number))
            if call_number == 1:
                self.first_entered.set()
            else:
                self.second_entered.set()
            assert self.release.wait(timeout=2)
            return 77

    fake = BlockingCreateGdi()
    retained: list[object] = []
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)
    monkeypatch.setattr(detection, "_DISPLAY_DC_REGISTRY_CAP", 1, raising=False)
    acquired: list[object] = []
    errors: list[BaseException] = []
    second_done = threading.Event()

    def acquire(*, mark_done: bool = False) -> None:
        try:
            owner = detection._acquire_display_dc(r"\\.\DISPLAY1")
            acquired.append(owner)
        except BaseException as error:
            errors.append(error)
        finally:
            if mark_done:
                second_done.set()

    first = threading.Thread(target=acquire)
    second = threading.Thread(target=lambda: acquire(mark_done=True))
    first.start()
    assert fake.first_entered.wait(timeout=1)
    second.start()
    try:
        assert not fake.second_entered.wait(timeout=0.2)
        assert second_done.wait(timeout=1)
    finally:
        fake.release.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert fake.call_count == 1
    assert len(acquired) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)
    assert "capacity" in str(errors[0]).casefold()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("display ingress handoff"), SystemExit(73)])
def test_cancelled_display_ingress_publishes_attempt_and_drain_retires_ghost(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    fake = FakeGdi32()
    owner = detection._RetainedDisplayDc(api=fake, device_name=r"\\.\DISPLAY1")
    retained: list[object] = []
    function = detection._reserve_display_dc_owner
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is function.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    priming_owner = detection._RetainedDisplayDc(api=fake, device_name=r"\\.\DISPLAY0")
    sys.settrace(prime_opcode_tracing)
    try:
        function(priming_owner)
    finally:
        sys.settrace(None)
        detection._remove_display_dc_owner(priming_owner)
    returns = [
        instruction.offset for instruction in dis.get_instructions(function) if instruction.opname.startswith("RETURN")
    ]
    target = returns[-2]
    sys.settrace(interrupt_at_opcode(function, target, interruption))
    try:
        with pytest.raises(type(interruption)) as caught:
            detection._acquire_display_dc(r"\\.\DISPLAY1", owner=owner)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert owner.attempt is not None
    assert owner.attempt.worker.ident is None
    assert owner.claim is detection._OwnerClaim.RETAINED
    assert owner.dc is None
    detection._drain_retained_display_dcs()
    assert retained == []
    assert fake.calls == []


def test_late_display_acquisition_auto_cleans_after_incomplete_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingCreateGdi(FakeGdi32):
        def __init__(self) -> None:
            super().__init__()
            self.create_entered = threading.Event()
            self.release_create = threading.Event()
            self.deleted = threading.Event()

        def CreateDCW(self, driver: str, device: str, port: object, devmode: object) -> int:
            self.calls.append(("create", driver, device, port, devmode))
            self.create_entered.set()
            assert self.release_create.wait(timeout=2)
            return 77

        def DeleteDC(self, dc: int) -> bool:
            self.calls.append(("delete", dc))
            self.deleted.set()
            return True

    fake = BlockingCreateGdi()
    owner = detection._RetainedDisplayDc(api=fake, device_name=r"\\.\DISPLAY1")
    retained: list[object] = []
    caller_errors: list[BaseException] = []
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)
    monkeypatch.setattr(detection, "_NATIVE_WORKER_JOIN_SECONDS", 0.01)

    def acquire() -> None:
        try:
            detection._acquire_display_dc(r"\\.\DISPLAY1", owner=owner)
        except BaseException as error:
            caller_errors.append(error)

    caller = threading.Thread(target=acquire)
    caller.start()
    assert fake.create_entered.wait(timeout=1)
    caller.join(timeout=1)
    assert not caller.is_alive()
    assert len(caller_errors) == 1
    try:
        with pytest.raises(RuntimeError, match="incomplete|terminal|running"):
            detection._drain_retained_display_dcs()
    finally:
        fake.release_create.set()
    assert fake.deleted.wait(timeout=2)
    with detection._DISPLAY_DC_REGISTRY_CHANGED:
        assert detection._DISPLAY_DC_REGISTRY_CHANGED.wait_for(lambda: owner not in retained, timeout=2)
    assert fake.calls == [
        ("create", "DISPLAY", r"\\.\DISPLAY1", None, None),
        ("delete", 77),
    ]


def test_display_boundary_arms_late_cleanup_without_a_later_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BlockingCreateGdi(FakeGdi32):
        def __init__(self) -> None:
            super().__init__()
            self.create_entered = threading.Event()
            self.release_create = threading.Event()
            self.deleted = threading.Event()

        def CreateDCW(self, driver: str, device: str, port: object, devmode: object) -> int:
            self.calls.append(("create", driver, device, port, devmode))
            self.create_entered.set()
            assert self.release_create.wait(timeout=2)
            return 77

        def DeleteDC(self, dc: int) -> bool:
            self.calls.append(("delete", dc))
            self.deleted.set()
            return True

    fake = BlockingCreateGdi()
    retained: list[object] = []
    caller_errors: list[BaseException] = []
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)
    monkeypatch.setattr(detection, "_NATIVE_WORKER_JOIN_SECONDS", 0.01)

    def enter_boundary() -> None:
        try:
            with detection._display_dc(r"\\.\DISPLAY1"):
                raise AssertionError("late acquisition must not enter the display body")
        except BaseException as error:
            caller_errors.append(error)

    caller = threading.Thread(target=enter_boundary)
    caller.start()
    assert fake.create_entered.wait(timeout=1)
    caller.join(timeout=1)
    assert not caller.is_alive()
    assert len(caller_errors) == 1
    try:
        with detection._DISPLAY_DC_REGISTRY_CHANGED:
            assert len(retained) == 1
            owner = retained[0]
            assert owner.attempt is not None
            assert owner.terminal_cleanup_token is owner.attempt.token
    finally:
        fake.release_create.set()
    assert fake.deleted.wait(timeout=2)
    with detection._DISPLAY_DC_REGISTRY_CHANGED:
        assert detection._DISPLAY_DC_REGISTRY_CHANGED.wait_for(lambda: retained == [], timeout=2)
    assert fake.calls == [
        ("create", "DISPLAY", r"\\.\DISPLAY1", None, None),
        ("delete", 77),
    ]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("claimed close entry"), SystemExit(77)])
def test_display_boundary_reclaims_cleanup_after_claimed_close_entry_control_error(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    fake = FakeGdi32()
    retained: list[object] = []
    cleanup_entries: list[tuple[object, object | None]] = []
    original_close = detection._close_claimed_display_dc
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)

    def interrupt_first_cleanup(owner: object) -> BaseException | None:
        cleanup_entries.append((owner, owner.claimant))  # type: ignore[attr-defined]
        if len(cleanup_entries) == 1:
            raise interruption
        return original_close(owner)  # type: ignore[arg-type]

    monkeypatch.setattr(detection, "_close_claimed_display_dc", interrupt_first_cleanup)

    with pytest.raises(type(interruption)) as caught:
        with detection._display_dc(r"\\.\DISPLAY1") as dc:
            assert dc == 77

    assert caught.value is interruption
    assert len(cleanup_entries) == 2
    assert cleanup_entries[0][0] is cleanup_entries[1][0]
    assert cleanup_entries[0][1] is not cleanup_entries[1][1]
    assert [call for call in fake.calls if call[0] == "delete"] == [("delete", 77)]
    assert retained == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("delete attempt publication"), SystemExit(78)])
def test_display_boundary_starts_exact_delete_attempt_after_publication_control_error(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    fake = FakeGdi32()
    retained: list[object] = []
    published_attempts: list[object] = []
    original_publish = detection._new_display_dc_attempt_locked
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)

    def publish_then_interrupt(owner: object, action: object) -> object:
        attempt = original_publish(owner, action)  # type: ignore[arg-type]
        if action is detection._NativeAction.DELETE and not published_attempts:
            published_attempts.append(attempt)
            raise interruption
        return attempt

    monkeypatch.setattr(detection, "_new_display_dc_attempt_locked", publish_then_interrupt)

    with pytest.raises(type(interruption)) as caught:
        with detection._display_dc(r"\\.\DISPLAY1") as dc:
            assert dc == 77

    assert caught.value is interruption
    assert len(published_attempts) == 1
    published = published_attempts[0]
    assert published.started.is_set()  # type: ignore[attr-defined]
    assert published.done.is_set()  # type: ignore[attr-defined]
    assert [call for call in fake.calls if call[0] == "delete"] == [("delete", 77)]
    assert retained == []


@pytest.mark.parametrize(
    ("initial_interruption", "recovery_interruption"),
    [
        (KeyboardInterrupt("initial display cleanup"), SystemExit(81)),
        (SystemExit(82), KeyboardInterrupt("recovery display cleanup")),
    ],
)
def test_display_boundary_double_cleanup_control_errors_demote_only_stale_owner_for_drain(
    monkeypatch: pytest.MonkeyPatch,
    initial_interruption: BaseException,
    recovery_interruption: BaseException,
) -> None:
    fake = FakeGdi32()
    newer_fake = FakeGdi32()
    retained: list[object] = []
    cleanup_entries: list[tuple[object, object | None]] = []
    original_close = detection._close_claimed_display_dc
    newer_owner = detection._RetainedDisplayDc(
        api=newer_fake,
        device_name=r"\\.\DISPLAY2",
        dc=88,
        outcome="open",
        active=True,
    )
    blocked_owner = detection._RetainedDisplayDc(api=FakeGdi32(), device_name=r"\\.\DISPLAY3")
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)
    monkeypatch.setattr(detection, "_DISPLAY_DC_REGISTRY_CAP", 2)

    def interrupt_both_cleanup_claims(owner: object) -> BaseException | None:
        cleanup_entries.append((owner, owner.claimant))  # type: ignore[attr-defined]
        if len(cleanup_entries) == 1:
            raise initial_interruption
        if len(cleanup_entries) == 2:
            retained.append(newer_owner)
            raise recovery_interruption
        return original_close(owner)  # type: ignore[arg-type]

    monkeypatch.setattr(detection, "_close_claimed_display_dc", interrupt_both_cleanup_claims)

    with pytest.raises(type(initial_interruption)) as caught:
        with detection._display_dc(r"\\.\DISPLAY1") as dc:
            assert dc == 77

    assert caught.value is initial_interruption
    assert len(cleanup_entries) == 2
    stale_owner = cleanup_entries[0][0]
    assert cleanup_entries[1][0] is stale_owner
    assert cleanup_entries[0][1] is not cleanup_entries[1][1]
    assert stale_owner.claim is detection._OwnerClaim.RETAINED  # type: ignore[attr-defined]
    assert stale_owner.state is detection._NativeState.OPEN  # type: ignore[attr-defined]
    assert stale_owner.claimant is None  # type: ignore[attr-defined]
    assert stale_owner.terminal_cleanup_token is None  # type: ignore[attr-defined]
    assert newer_owner.claim is detection._OwnerClaim.ACTIVE
    assert retained == [stale_owner, newer_owner]
    with pytest.raises(RuntimeError, match="capacity"):
        detection._reserve_display_dc_owner(blocked_owner)

    detection._drain_retained_display_dcs()
    detection._drain_retained_display_dcs()

    assert [call for call in fake.calls if call[0] == "delete"] == [("delete", 77)]
    assert newer_fake.calls == []
    assert newer_owner.claim is detection._OwnerClaim.ACTIVE
    assert retained == [newer_owner]
    detection._reserve_display_dc_owner(blocked_owner)
    detection._remove_display_dc_owner(blocked_owner)
    assert retained == [newer_owner]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("drain cancelled"), SystemExit(68)])
def test_retained_display_dc_drain_propagates_control_after_successful_retry(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    fake = FakeGdi32(delete_success=False)
    retained: list[object] = []
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "gdi32", fake)
    monkeypatch.setattr(detection, "_RETAINED_DISPLAY_DCS", retained)

    assert detection.get_display_profile(r"\\.\DISPLAY1") is None
    assert retained
    fake.delete_success = True
    function = detection._close_claimed_display_dc
    source_lines = Path(function.__code__.co_filename).read_text(encoding="utf-8").splitlines()
    fired = False

    def interrupt_before_retry(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if (
            not fired
            and event == "line"
            and frame.f_code is function.__code__  # type: ignore[attr-defined]
            and "DeleteDC" in source_lines[frame.f_lineno - 1]  # type: ignore[attr-defined]
        ):
            fired = True
            sys.settrace(None)
            raise interruption
        return interrupt_before_retry

    sys.settrace(interrupt_before_retry)
    try:
        with pytest.raises(type(interruption)) as caught:
            detection._drain_retained_display_dcs()
    finally:
        sys.settrace(None)

    assert fired is True
    assert caught.value is interruption
    assert retained == []
    assert [call for call in fake.calls if call[0] == "delete"] == [
        ("delete", 77),
        ("delete", 77),
        ("delete", 77),
    ]


def test_detection_legacy_install_refuses_reserved_product_cache_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = tmp_path / f"CALIBRATE-PRO-{'A' * 64}.ICC"
    profile.write_bytes(b"profile")

    class FakeMscms:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def InstallColorProfileW(self, _machine: object, path: str) -> bool:
            self.calls.append(path)
            return True

    native = FakeMscms()
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "mscms", native)

    assert detection.install_profile(str(profile)) is False
    assert native.calls == []


def test_detection_legacy_install_delegates_to_hardened_profile_installer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from calibrate_pro.profiles import profile_installer

    profile = tmp_path / "ordinary.icc"
    profile.write_bytes(b"profile")
    calls: list[Path] = []

    def install_exact(path: str | Path) -> tuple[bool, str]:
        calls.append(Path(path))
        return True, "installed safely"

    class BombMscms:
        def InstallColorProfileW(self, *_args: object) -> bool:
            raise AssertionError("detection must not bypass the hardened profile installer")

    monkeypatch.setattr(profile_installer, "install_profile", install_exact)
    monkeypatch.setattr(detection, "HAS_MSCMS", True)
    monkeypatch.setattr(detection, "mscms", BombMscms())

    assert detection.install_profile(str(profile)) is True
    assert calls == [profile.absolute()]


@pytest.mark.parametrize(
    "module_order",
    tuple(permutations(_SHARED_ABI_MODULES)),
)
def test_clean_import_orders_preserve_shared_win32_pointer_abis(module_order: tuple[str, ...]) -> None:
    root = Path(__file__).resolve().parents[1]
    script = f"""
import ctypes
import importlib
from ctypes import wintypes

for module_name in {module_order!r}:
    importlib.import_module(module_name)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
assert user32.EnumDisplayDevicesW.argtypes[2] is ctypes.c_void_p
assert gdi32.CreateDCW.argtypes == [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
assert gdi32.DeleteDC.argtypes == [wintypes.HDC]
assert gdi32.GetICMProfileW.argtypes == [wintypes.HDC, ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR]
assert gdi32.SetICMProfileW.argtypes == [wintypes.HDC, wintypes.LPWSTR]
assert gdi32.GetDeviceGammaRamp.argtypes == [wintypes.HDC, ctypes.c_void_p]
assert gdi32.SetDeviceGammaRamp.argtypes == [wintypes.HDC, ctypes.c_void_p]
mscms = ctypes.windll.mscms
assert mscms.InstallColorProfileW.argtypes == [wintypes.LPCWSTR, wintypes.LPCWSTR]
assert mscms.InstallColorProfileW.restype is wintypes.BOOL
assert mscms.UninstallColorProfileW.argtypes == [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.BOOL]
assert mscms.UninstallColorProfileW.restype is wintypes.BOOL
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "function_name",
    (
        "GetFileSizeEx",
        "ReadFile",
        "SetFilePointerEx",
        "GetFileInformationByHandle",
        "CloseHandle",
    ),
)
def test_windows_icc_lease_binds_every_kernel32_bool_result_as_win32_bool(function_name: str) -> None:
    succeeds = FakeKernelFunction(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=FakeKernelFunction(lambda *_args: 123),
        GetFileSizeEx=FakeKernelFunction(lambda *_args: True),
        ReadFile=FakeKernelFunction(lambda *_args: True),
        SetFilePointerEx=FakeKernelFunction(lambda *_args: True),
        GetFileInformationByHandle=FakeKernelFunction(lambda *_args: True),
        GetFileType=FakeKernelFunction(lambda *_args: 1),
        GetFinalPathNameByHandleW=FakeKernelFunction(lambda *_args: 1),
        CloseHandle=succeeds,
    )
    lease = windows_state._WindowsIccFileLease("cache.icc", kernel32_loader=lambda: kernel32)
    try:
        assert getattr(kernel32, function_name).restype is wintypes.BOOL, function_name
    finally:
        lease.close()


@pytest.mark.parametrize(
    ("function_name", "argument_index"),
    (
        ("CreateMutexW", 1),
        ("ReleaseMutex", None),
        ("CloseHandle", None),
    ),
)
def test_windows_named_mutex_binds_every_kernel32_bool_contract_as_win32_bool(
    function_name: str,
    argument_index: int | None,
) -> None:
    kernel32 = SimpleNamespace(
        CreateMutexW=FakeKernelFunction(lambda *_args: 123),
        WaitForSingleObject=FakeKernelFunction(lambda *_args: 0),
        ReleaseMutex=FakeKernelFunction(lambda *_args: True),
        CloseHandle=FakeKernelFunction(lambda *_args: True),
    )
    mutex = windows_state.WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    lease = mutex.acquire("abi-contract")
    try:
        function = getattr(kernel32, function_name)
        actual = function.restype if argument_index is None else function.argtypes[argument_index]
        assert actual is wintypes.BOOL, function_name
    finally:
        mutex.release(lease)
