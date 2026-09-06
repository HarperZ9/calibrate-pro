"""Pure workflow, confirmation, and transactional recovery contracts."""

from __future__ import annotations

import dis
import hashlib
import inspect
import json
import sys
import threading
from dataclasses import asdict, replace

import pytest

from calibrate_pro.actuation import ActuationCoordinator, canonical_plan_sha256
from calibrate_pro.recovery import (
    ApplyReceipt,
    CapturedState,
    CaptureStatus,
    DisplayStateSnapshot,
    RecoveryGuarantee,
    _apply_confirmed_with_best_effort_recovery,
    _capture_into_recovery_sink,
)
from calibrate_pro.workflow import (
    DDC_WRITE_CODES,
    ApplyPlan,
    CalibrationMethod,
    CapabilityState,
    DwmLutKind,
    WorkflowController,
    WorkflowStage,
)

SHA256_A = "a" * 64


def make_plan(**changes: object) -> ApplyPlan:
    values: dict[str, object] = {
        "display_id": "display-1",
        "method": CalibrationMethod.SENSORLESS,
        "target_whitepoint": "D65",
        "target_gamma": "2.2",
        "target_gamut": "sRGB",
    }
    values.update(changes)
    return ApplyPlan(**values)  # type: ignore[arg-type]


def all_capabilities() -> CapabilityState:
    return CapabilityState(True, True, True, True, True, True)


def all_capabilities_for(_display_id: str) -> CapabilityState:
    return all_capabilities()


def ready_controller(capabilities: CapabilityState | None = None) -> WorkflowController:
    controller = WorkflowController(capabilities or all_capabilities())
    controller.detect_complete()
    controller.select_method(CalibrationMethod.SENSORLESS)
    return controller


class FakeAdapter:
    """Complete in-memory DisplayStateAdapter with observable call order."""

    def __init__(
        self,
        *,
        capture_error: str | None = None,
        apply_error: str | None = None,
        verify_error: str | None = None,
        verify_result: object = True,
        restore_error: str | None = None,
    ) -> None:
        self.capture_error = capture_error
        self.apply_error = apply_error
        self.verify_error = verify_error
        self.verify_result = verify_result
        self.restore_error = restore_error
        self.calls: list[str] = []
        self.snapshot = DisplayStateSnapshot("display-1", (), None, None, None)

    def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
        self.calls.append("capture")
        if self.capture_error is not None:
            raise RuntimeError(self.capture_error)
        return replace(self.snapshot, display_id=plan.display_id)

    def apply(self, plan: ApplyPlan) -> None:
        self.calls.append("apply")
        if self.apply_error is not None:
            raise RuntimeError(self.apply_error)

    def verify(self, plan: ApplyPlan) -> object:
        self.calls.append("verify")
        if self.verify_error is not None:
            raise RuntimeError(self.verify_error)
        return self.verify_result

    def commit(self, plan: ApplyPlan) -> None:
        self.calls.append("commit")

    def restore(self, snapshot: DisplayStateSnapshot) -> None:
        self.calls.append("restore")
        if self.restore_error is not None:
            raise RuntimeError(self.restore_error)


def test_workflow_exposes_the_six_ordered_stages() -> None:
    assert tuple(WorkflowStage) == (
        WorkflowStage.DETECT,
        WorkflowStage.METHOD,
        WorkflowStage.PREVIEW,
        WorkflowStage.APPLY,
        WorkflowStage.VERIFY,
        WorkflowStage.SAVE_REPORT,
    )


def test_detect_method_preview_apply_verify_save_sequence() -> None:
    controller = WorkflowController(all_capabilities())
    assert controller.stage is WorkflowStage.DETECT
    controller.detect_complete()
    assert controller.stage is WorkflowStage.METHOD
    controller.select_method(CalibrationMethod.SENSORLESS)
    assert controller.stage is WorkflowStage.PREVIEW
    plan = make_plan()
    controller.set_preview(plan)
    assert controller.preview is plan
    controller.confirm_apply()
    assert controller.stage is WorkflowStage.APPLY
    controller.apply_complete()
    assert controller.stage is WorkflowStage.VERIFY
    controller.verify_complete()
    assert controller.stage is WorkflowStage.SAVE_REPORT


def test_measured_method_is_disabled_without_a_sensor() -> None:
    controller = WorkflowController(CapabilityState(False, True, True, True, True, True))
    controller.detect_complete()
    with pytest.raises(ValueError, match="supported colorimeter"):
        controller.select_method(CalibrationMethod.MEASURED)
    assert controller.stage is WorkflowStage.METHOD
    assert controller.method is None


def test_method_selection_rejects_raw_string_enum_values() -> None:
    controller = WorkflowController(all_capabilities())
    controller.detect_complete()
    with pytest.raises(TypeError, match="CalibrationMethod"):
        controller.select_method("measured")  # type: ignore[arg-type]


def test_preview_requires_the_preview_stage() -> None:
    controller = WorkflowController(all_capabilities())
    with pytest.raises(ValueError, match="preview stage"):
        controller.set_preview(make_plan())


def test_preview_method_must_match_the_selected_method() -> None:
    controller = ready_controller()
    with pytest.raises(ValueError, match="selected method"):
        controller.set_preview(make_plan(method=CalibrationMethod.MEASURED))
    assert controller.preview is None


@pytest.mark.parametrize("display_id", ["", "   "])
def test_preview_requires_a_non_empty_display_id(display_id: str) -> None:
    controller = ready_controller()
    with pytest.raises(ValueError, match="display_id"):
        controller.set_preview(make_plan(display_id=display_id))
    assert controller.preview is None


def test_preview_rejects_each_missing_write_capability() -> None:
    dwm_change = {
        "dwm_lut_path": "display.cube",
        "dwm_lut_kind": DwmLutKind.SDR,
        "dwm_lut_sha256": SHA256_A,
    }
    cases = (
        (CapabilityState(True, False, True, True, True, True), {"ddc_changes": (("BRIGHTNESS", 42),)}, "DDC/CI"),
        (CapabilityState(True, True, False, True, True, True), dwm_change, "DWM LUT"),
        (CapabilityState(True, True, True, False, True, True), dwm_change, "authoritative"),
        (
            CapabilityState(True, True, True, True, False, True),
            {"icc_profile_path": "display.icc", "icc_profile_sha256": SHA256_A},
            "profile association",
        ),
        (
            CapabilityState(True, True, True, True, True, False),
            {"vcgt_path": "display.cal", "vcgt_sha256": SHA256_A},
            "gamma ramp",
        ),
    )
    for capabilities, changes, message in cases:
        controller = ready_controller(capabilities)
        with pytest.raises(ValueError, match=message):
            controller.set_preview(make_plan(**changes))
        assert controller.preview is None


def test_dwm_clear_requires_write_and_authoritative_capture_capabilities() -> None:
    for capabilities in (
        CapabilityState(True, True, False, True, True, True),
        CapabilityState(True, True, True, False, True, True),
    ):
        controller = ready_controller(capabilities)
        with pytest.raises(ValueError, match="DWM LUT"):
            controller.set_preview(make_plan(clear_existing_lut=True))


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"icc_profile_path": "display.icc"}, "icc_profile_sha256"),
        ({"icc_profile_sha256": SHA256_A}, "icc_profile_path"),
        ({"vcgt_path": "display.cal"}, "vcgt_sha256"),
        ({"vcgt_sha256": SHA256_A}, "vcgt_path"),
        ({"dwm_lut_path": "display.cube", "dwm_lut_sha256": SHA256_A}, "dwm_lut_kind"),
        ({"dwm_lut_path": "display.cube", "dwm_lut_kind": DwmLutKind.SDR}, "dwm_lut_sha256"),
        ({"dwm_lut_kind": DwmLutKind.SDR, "dwm_lut_sha256": SHA256_A}, "dwm_lut_path"),
        (
            {
                "dwm_lut_path": "display.cube",
                "dwm_lut_kind": DwmLutKind.SDR,
                "dwm_lut_sha256": SHA256_A,
                "clear_existing_lut": True,
            },
            "clear_existing_lut",
        ),
    ),
)
def test_apply_plan_rejects_incomplete_or_conflicting_asset_evidence(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make_plan(**changes)


def test_apply_plan_rejects_noncanonical_sha256() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        make_plan(icc_profile_path="display.icc", icc_profile_sha256="ABC")


@pytest.mark.parametrize(
    ("changes", "error"),
    (
        ({"ddc_changes": [["BRIGHTNESS", 42]]}, TypeError),
        ({"ddc_changes": (["BRIGHTNESS", 42],)}, TypeError),
        ({"ddc_changes": (("BRIGHTNESS", 42), ("BRIGHTNESS", 43))}, ValueError),
        ({"ddc_changes": (("brightness", 42),)}, ValueError),
        ({"ddc_changes": (("RESTORE_FACTORY_DEFAULTS", 1),)}, ValueError),
        ({"ddc_changes": (("BRIGHTNESS", True),)}, TypeError),
        ({"ddc_changes": (("BRIGHTNESS", -1),)}, ValueError),
        ({"ddc_changes": (("BRIGHTNESS", 65536),)}, ValueError),
    ),
)
def test_apply_plan_rejects_malformed_or_dangerous_ddc_changes(
    changes: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        make_plan(**changes)


def test_every_allowlisted_ddc_code_accepts_boundary_values() -> None:
    for code in DDC_WRITE_CODES:
        assert make_plan(ddc_changes=((code, 0),)).ddc_changes == ((code, 0),)
        assert make_plan(ddc_changes=((code, 65535),)).ddc_changes == ((code, 65535),)


@pytest.mark.parametrize(
    ("changes", "error"),
    (
        ({"display_id": 1}, TypeError),
        ({"display_id": ""}, ValueError),
        ({"method": "sensorless"}, TypeError),
        ({"target_whitepoint": ""}, ValueError),
        ({"target_gamma": 2.2}, TypeError),
        ({"target_gamut": "   "}, ValueError),
        ({"clear_existing_lut": "false"}, TypeError),
        ({"output_files": ["report.json"]}, TypeError),
        ({"output_files": ("",)}, ValueError),
    ),
)
def test_apply_plan_rejects_actuator_critical_runtime_type_substitution(
    changes: dict[str, object], error: type[Exception]
) -> None:
    with pytest.raises(error):
        make_plan(**changes)


@pytest.mark.parametrize(
    "field",
    (
        "sensor_available",
        "ddc_available",
        "dwm_lut_available",
        "dwm_state_capture_available",
        "profile_write_available",
        "vcgt_available",
    ),
)
def test_capability_state_requires_exact_booleans(field: str) -> None:
    values = {
        "sensor_available": True,
        "ddc_available": True,
        "dwm_lut_available": True,
        "dwm_state_capture_available": True,
        "profile_write_available": True,
        "vcgt_available": True,
    }
    values[field] = "unavailable"
    with pytest.raises(TypeError, match="boolean"):
        CapabilityState(**values)  # type: ignore[arg-type]


def test_captured_state_distinguishes_absence_from_capture_failure() -> None:
    absent = CapturedState.captured(None)
    failed = CapturedState.not_captured("reader could not distinguish absence from failure")
    assert absent.status is CaptureStatus.CAPTURED
    assert absent.value is None
    assert failed.status is CaptureStatus.NOT_CAPTURED
    assert failed.detail is not None


def test_captured_state_rejects_unexplained_capture_failure() -> None:
    with pytest.raises(ValueError, match="detail"):
        CapturedState(CaptureStatus.NOT_CAPTURED, None, "")


def test_apply_requires_a_stored_preview() -> None:
    controller = ready_controller()
    with pytest.raises(ValueError, match="completed preview"):
        controller.confirm_apply()
    assert controller.stage is WorkflowStage.PREVIEW


def test_success_receipt_records_only_completed_operations() -> None:
    adapter = FakeAdapter()
    receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert adapter.calls == ["capture", "apply", "verify", "commit"]
    assert receipt == ApplyReceipt(True, True, True, True, False, False, None, None)


def test_capture_failure_returns_a_non_apply_receipt() -> None:
    adapter = FakeAdapter(capture_error="capture failed")
    receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert adapter.calls == ["capture"]
    assert receipt == ApplyReceipt(False, False, False, False, False, False, "capture failed", None)


def test_apply_failure_restores_the_snapshot() -> None:
    adapter = FakeAdapter(apply_error="apply failed")
    receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert adapter.calls == ["capture", "apply", "restore"]
    assert receipt == ApplyReceipt(False, True, False, False, True, True, "apply failed", None)


def test_apply_completion_is_published_without_a_trace_interrupt_gap(unmeasured_tracing: None) -> None:
    source, first_line = inspect.getsourcelines(_apply_confirmed_with_best_effort_recovery)
    apply_index = next(index for index, line in enumerate(source) if "adapter.apply(plan)" in line)
    assert "applied =" in source[apply_index]

    target_line = first_line + next(index for index, line in enumerate(source) if 'phase = "verify"' in line)

    def interrupt_after_apply(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is _apply_confirmed_with_best_effort_recovery.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise RuntimeError("post-apply publication interrupt")
        return interrupt_after_apply

    adapter = FakeAdapter()
    sys.settrace(interrupt_after_apply)
    try:
        receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    finally:
        sys.settrace(None)

    assert adapter.calls == ["capture", "apply", "restore"]
    assert receipt == ApplyReceipt(
        False,
        True,
        True,
        False,
        True,
        True,
        "post-apply publication interrupt",
        None,
    )


def test_verification_failure_restores_the_snapshot() -> None:
    adapter = FakeAdapter(verify_result=False)
    receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert adapter.calls == ["capture", "apply", "verify", "restore"]
    assert receipt == ApplyReceipt(False, True, True, False, True, True, "verification failed", None)


def test_verification_exception_restores_the_snapshot() -> None:
    adapter = FakeAdapter(verify_error="readback failed")
    receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert adapter.calls == ["capture", "apply", "verify", "restore"]
    assert receipt == ApplyReceipt(False, True, True, False, True, True, "readback failed", None)


def test_commit_exception_preserves_verified_receipt_semantics_without_compensation() -> None:
    class FailingCommitAdapter(FakeAdapter):
        def commit(self, plan: ApplyPlan) -> None:
            self.calls.append("commit")
            raise RuntimeError("commit failed")

    adapter = FailingCommitAdapter()
    receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert adapter.calls == ["capture", "apply", "verify", "commit"]
    assert receipt == ApplyReceipt(False, True, True, True, False, False, "commit failed", None)


@pytest.mark.parametrize("interrupt", (KeyboardInterrupt(), SystemExit(7)))
def test_base_exception_during_verification_restores_then_reraises(interrupt: BaseException) -> None:
    class InterruptingAdapter(FakeAdapter):
        def verify(self, plan: ApplyPlan) -> object:
            self.calls.append("verify")
            raise interrupt

    adapter = InterruptingAdapter()
    with pytest.raises(type(interrupt)) as caught:
        _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert caught.value is interrupt
    assert adapter.calls == ["capture", "apply", "verify", "restore"]


@pytest.mark.parametrize("interrupt", (KeyboardInterrupt(), SystemExit(7)))
def test_base_exception_at_verified_commit_handoff_restores_releases_and_reraises(
    interrupt: BaseException,
) -> None:
    class InterruptingCommitAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.transaction_active = False

        def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
            snapshot = super().capture(plan, authorization=authorization)
            self.transaction_active = True
            return snapshot

        def commit(self, plan: ApplyPlan) -> None:
            self.calls.append("commit")
            raise interrupt

        def restore(self, snapshot: DisplayStateSnapshot) -> None:
            super().restore(snapshot)
            self.transaction_active = False

    adapter = InterruptingCommitAdapter()
    with pytest.raises(type(interrupt)) as caught:
        _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert caught.value is interrupt
    assert adapter.calls == ["capture", "apply", "verify", "commit", "restore"]
    assert adapter.transaction_active is False


@pytest.mark.parametrize("interrupt", (KeyboardInterrupt("post-capture"), SystemExit(8)))
def test_base_exception_immediately_after_capture_restores_and_reraises(
    interrupt: BaseException, unmeasured_tracing: None
) -> None:
    class LeaseTrackingAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.transaction_active = False

        def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
            snapshot = super().capture(plan, authorization=authorization)
            self.transaction_active = True
            return snapshot

        def restore(self, snapshot: DisplayStateSnapshot) -> None:
            super().restore(snapshot)
            self.transaction_active = False

    source, first_line = inspect.getsourcelines(_apply_confirmed_with_best_effort_recovery)
    target_line = first_line + next(index for index, line in enumerate(source) if 'phase = "apply"' in line)

    def interrupt_after_capture(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is _apply_confirmed_with_best_effort_recovery.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interrupt
        return interrupt_after_capture

    adapter = LeaseTrackingAdapter()
    sys.settrace(interrupt_after_capture)
    try:
        with pytest.raises(type(interrupt)) as caught:
            _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    finally:
        sys.settrace(None)

    assert caught.value is interrupt
    assert adapter.calls == ["capture", "restore"]
    assert adapter.transaction_active is False


@pytest.mark.parametrize(
    ("interrupt_type", "interrupt_value"),
    ((KeyboardInterrupt, "post-capture-opcode"), (SystemExit, 9)),
    ids=("keyboard-interrupt", "system-exit"),
)
@pytest.mark.parametrize(
    "authorization",
    (pytest.param(None, id="no-authorization"), pytest.param(object(), id="supplied-authorization")),
)
def test_base_exception_at_capture_result_store_restores_and_allows_retry(
    interrupt_type: type[BaseException],
    interrupt_value: object,
    authorization: object | None,
    unmeasured_tracing: None,
) -> None:
    class LeaseTrackingAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.transaction_active = False
            self.capture_authorizations: list[object | None] = []

        def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
            self.capture_authorizations.append(authorization)
            if self.transaction_active:
                self.calls.append("capture-blocked")
                raise RuntimeError("capture transaction is already active")
            snapshot = super().capture(plan, authorization=authorization)
            self.transaction_active = True
            return snapshot

        def restore(self, snapshot: DisplayStateSnapshot) -> None:
            super().restore(snapshot)
            self.transaction_active = False

        def commit(self, plan: ApplyPlan) -> None:
            super().commit(plan)
            self.transaction_active = False

    instructions = tuple(dis.get_instructions(_apply_confirmed_with_best_effort_recovery))
    capture_result_stores = tuple(
        instruction.offset
        for previous, instruction in zip(instructions[:-1], instructions[1:], strict=True)
        if previous.opname.startswith("CALL")
        and instruction.opname == "STORE_FAST"
        and instruction.argval == "snapshot"
    )
    assert len(capture_result_stores) == 2
    target_offset = capture_result_stores[authorization is not None]
    interrupt = interrupt_type(interrupt_value)
    fired = False

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is _apply_confirmed_with_best_effort_recovery.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    sys.settrace(prime_opcode_tracing)
    try:
        assert _apply_confirmed_with_best_effort_recovery(FakeAdapter(), make_plan()).success is True
    finally:
        sys.settrace(None)

    def interrupt_at_capture_result_store(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if event == "call" and frame.f_code is _apply_confirmed_with_best_effort_recovery.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
            return interrupt_at_capture_result_store
        if (
            not fired
            and event == "opcode"
            and frame.f_code is _apply_confirmed_with_best_effort_recovery.__code__  # type: ignore[attr-defined]
            and frame.f_lasti == target_offset  # type: ignore[attr-defined]
        ):
            fired = True
            sys.settrace(None)
            raise interrupt
        return interrupt_at_capture_result_store

    adapter = LeaseTrackingAdapter()
    sys.settrace(interrupt_at_capture_result_store)
    try:
        with pytest.raises(interrupt_type) as caught:
            _apply_confirmed_with_best_effort_recovery(adapter, make_plan(), authorization=authorization)
    finally:
        sys.settrace(None)

    retry_receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan(), authorization=authorization)

    assert fired is True
    assert caught.value is interrupt
    assert retry_receipt == ApplyReceipt(True, True, True, True, False, False, None, None)
    assert adapter.calls == ["capture", "restore", "capture", "apply", "verify", "commit"]
    assert adapter.transaction_active is False
    assert len(adapter.capture_authorizations) == 2
    assert all(value is authorization for value in adapter.capture_authorizations)


@pytest.mark.parametrize("interrupt", (KeyboardInterrupt("sink-published"), SystemExit(10)))
def test_capture_sink_owns_snapshot_before_python_resumes_after_extend(
    interrupt: BaseException, unmeasured_tracing: None
) -> None:
    class LeaseTrackingAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.transaction_active = False

        def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
            if self.transaction_active:
                self.calls.append("capture-blocked")
                raise RuntimeError("capture transaction is already active")
            snapshot = super().capture(plan, authorization=authorization)
            self.transaction_active = True
            return snapshot

        def restore(self, snapshot: DisplayStateSnapshot) -> None:
            super().restore(snapshot)
            self.transaction_active = False

        def commit(self, plan: ApplyPlan) -> None:
            super().commit(plan)
            self.transaction_active = False

    instructions = tuple(dis.get_instructions(_capture_into_recovery_sink))
    post_extend_opcodes = tuple(
        instruction.offset
        for previous, instruction in zip(instructions[:-1], instructions[1:], strict=True)
        if previous.opname.startswith("CALL") and instruction.opname == "POP_TOP"
    )
    assert len(post_extend_opcodes) == 1
    target_offset = post_extend_opcodes[0]
    fired = False

    def prime_opcode_tracing(frame: object, event: str, _arg: object) -> object:
        if event == "call" and frame.f_code is _capture_into_recovery_sink.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
        return prime_opcode_tracing

    priming_sink: list[DisplayStateSnapshot] = []
    priming_adapter = FakeAdapter()
    sys.settrace(prime_opcode_tracing)
    try:
        primed = _capture_into_recovery_sink(priming_sink, priming_adapter.capture, make_plan())
    finally:
        sys.settrace(None)
    assert priming_sink == [primed]

    def interrupt_after_sink_publish(frame: object, event: str, _arg: object) -> object:
        nonlocal fired
        if event == "call" and frame.f_code is _capture_into_recovery_sink.__code__:  # type: ignore[attr-defined]
            frame.f_trace_opcodes = True  # type: ignore[attr-defined]
            return interrupt_after_sink_publish
        if (
            not fired
            and event == "opcode"
            and frame.f_code is _capture_into_recovery_sink.__code__  # type: ignore[attr-defined]
            and frame.f_lasti == target_offset  # type: ignore[attr-defined]
        ):
            fired = True
            sys.settrace(None)
            raise interrupt
        return interrupt_after_sink_publish

    adapter = LeaseTrackingAdapter()
    sys.settrace(interrupt_after_sink_publish)
    try:
        with pytest.raises(type(interrupt)) as caught:
            _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    finally:
        sys.settrace(None)

    retry_receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())

    assert fired is True
    assert caught.value is interrupt
    assert retry_receipt == ApplyReceipt(True, True, True, True, False, False, None, None)
    assert adapter.calls == ["capture", "restore", "capture", "apply", "verify", "commit"]
    assert adapter.transaction_active is False


@pytest.mark.parametrize("phase", ("capture", "apply", "verify", "restore"))
def test_empty_exception_messages_receive_a_nonempty_type_fallback(phase: str) -> None:
    class EmptyErrorAdapter(FakeAdapter):
        def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
            if phase == "capture":
                raise RuntimeError()
            return super().capture(plan, authorization=authorization)

        def apply(self, plan: ApplyPlan) -> None:
            if phase == "apply":
                self.calls.append("apply")
                raise RuntimeError()
            super().apply(plan)

        def verify(self, plan: ApplyPlan) -> object:
            if phase == "verify":
                self.calls.append("verify")
                raise RuntimeError()
            if phase == "restore":
                self.calls.append("verify")
                return False
            return super().verify(plan)

        def restore(self, snapshot: DisplayStateSnapshot) -> None:
            self.calls.append("restore")
            if phase == "restore":
                raise RuntimeError()

    receipt = _apply_confirmed_with_best_effort_recovery(EmptyErrorAdapter(), make_plan())
    assert receipt.error
    assert receipt.error == "RuntimeError" if phase != "restore" else receipt.error == "verification failed"
    if phase == "restore":
        assert receipt.restore_error == "RuntimeError"


def test_restore_failure_preserves_both_errors() -> None:
    adapter = FakeAdapter(apply_error="apply failed", restore_error="restore failed")
    receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert receipt.success is False
    assert receipt.restore_attempted is True
    assert receipt.restored is False
    assert receipt.error == "apply failed"
    assert receipt.restore_error == "restore failed"


def test_non_boolean_verify_result_is_failure_and_runs_compensation() -> None:
    adapter = FakeAdapter(verify_result=1)
    receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan())
    assert receipt.success is False
    assert receipt.restore_attempted is True
    assert adapter.calls == ["capture", "apply", "verify", "restore"]
    assert receipt.error and "boolean" in receipt.error


@pytest.mark.parametrize(
    "changes",
    (
        {"success": 1},
        {"captured": "yes"},
        {"applied": 1},
        {"verified": None},
        {"restore_attempted": 0},
        {"restored": "no"},
    ),
)
def test_apply_receipt_requires_exact_boolean_flags(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "success": False,
        "captured": False,
        "applied": False,
        "verified": False,
        "restore_attempted": False,
        "restored": False,
        "error": "failed",
        "restore_error": None,
    }
    values.update(changes)
    with pytest.raises(TypeError, match="boolean"):
        ApplyReceipt(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "values",
    (
        (False, False, True, False, False, False, "failed", None),
        (False, True, False, True, False, False, "failed", None),
        (False, True, False, False, False, True, "failed", None),
        (True, True, True, False, False, False, None, None),
    ),
)
def test_apply_receipt_rejects_impossible_phase_combinations(values: tuple[object, ...]) -> None:
    with pytest.raises(ValueError, match="phase|receipt"):
        ApplyReceipt(*values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "values",
    (
        (False, False, False, False, False, False, None, None),
        (False, True, False, False, False, False, "apply failed", "restore failed"),
        (False, True, False, False, True, True, "apply failed", "restore failed"),
        (False, True, True, True, True, True, "commit failed", None),
        (False, True, True, False, False, False, "verify failed", None),
        (False, True, False, False, False, False, "apply failed", None),
        (False, True, False, False, True, False, "apply failed", None),
    ),
)
def test_apply_receipt_rejects_contradictory_unsuccessful_evidence(values: tuple[object, ...]) -> None:
    with pytest.raises(ValueError, match="error|restor"):
        ApplyReceipt(*values)  # type: ignore[arg-type]


def test_canonical_plan_digest_uses_sorted_compact_json_and_asset_hashes() -> None:
    plan = make_plan(
        ddc_changes=(("BRIGHTNESS", 42),),
        icc_profile_path="display.icc",
        icc_profile_sha256=SHA256_A,
        output_files=("display.icc", "display.cube"),
    )
    payload = json.dumps(asdict(plan), sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert canonical_plan_sha256(plan) == hashlib.sha256(payload).hexdigest()


def test_confirmation_is_bound_to_one_plan_and_consumed_once() -> None:
    adapter = FakeAdapter()
    coordinator = ActuationCoordinator(adapter, all_capabilities_for)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    token = coordinator.preview(plan)
    with pytest.raises(PermissionError, match="confirmation"):
        coordinator.apply(plan, token, confirmed=False)
    assert adapter.calls == []
    with pytest.raises(PermissionError, match="consumed"):
        coordinator.apply(plan, token, confirmed=True)
    token = coordinator.preview(plan)
    receipt = coordinator.apply(plan, token, confirmed=True)
    assert receipt.success is True
    with pytest.raises(PermissionError, match="consumed"):
        coordinator.apply(plan, token, confirmed=True)


def test_preview_rejects_capability_callback_mutation_of_the_submitted_plan() -> None:
    adapter = FakeAdapter()
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))

    def mutating_provider(_display_id: str) -> CapabilityState:
        object.__setattr__(plan, "ddc_changes", (("BRIGHTNESS", 99),))
        return all_capabilities()

    coordinator = ActuationCoordinator(adapter, mutating_provider)
    with pytest.raises(PermissionError, match="changed|mutat"):
        coordinator.preview(plan)
    assert adapter.calls == []


def test_apply_rejects_capability_callback_mutation_before_any_writer_receives_a_plan() -> None:
    adapter = FakeAdapter()
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    provider_calls = 0

    def mutating_provider(_display_id: str) -> CapabilityState:
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 2:
            object.__setattr__(plan, "ddc_changes", (("BRIGHTNESS", 99),))
        return all_capabilities()

    coordinator = ActuationCoordinator(adapter, mutating_provider)
    token = coordinator.preview(plan)
    with pytest.raises(PermissionError, match="changed|mutat"):
        coordinator.apply(plan, token, confirmed=True)
    assert adapter.calls == []


def test_concurrent_confirmed_applies_cannot_invert_the_one_slot_authorization_handoff() -> None:
    first_apply_capabilities_entered = threading.Event()
    release_first_apply_capabilities = threading.Event()
    second_capture_entered = threading.Event()
    allow_second_capture_to_verify = threading.Event()
    provider_lock = threading.Lock()
    provider_calls = 0

    def staged_provider(_display_id: str) -> CapabilityState:
        nonlocal provider_calls
        with provider_lock:
            provider_calls += 1
            call_number = provider_calls
        if call_number == 2:
            first_apply_capabilities_entered.set()
            if not release_first_apply_capabilities.wait(5):
                raise RuntimeError("test timed out releasing the first capability check")
        return all_capabilities()

    class GateAwareAdapter(FakeAdapter):
        def __init__(self) -> None:
            super().__init__()
            self._capture_authorization_verifier = None
            self.captured_targets: list[int] = []

        def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
            target = plan.ddc_changes[0][1]
            self.calls.append(f"capture:{target}")
            self.captured_targets.append(target)
            if target == 43:
                second_capture_entered.set()
                if not allow_second_capture_to_verify.wait(5):
                    raise RuntimeError("test timed out allowing the second capture")
            verifier = self._capture_authorization_verifier
            assert verifier is not None
            verifier(plan, authorization)
            return replace(self.snapshot, display_id=plan.display_id)

    adapter = GateAwareAdapter()
    coordinator = ActuationCoordinator(adapter, staged_provider)
    first_plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    second_plan = make_plan(ddc_changes=(("BRIGHTNESS", 43),))
    first_token = coordinator.preview(first_plan)
    results: dict[str, ApplyReceipt | BaseException] = {}

    def run_apply(name: str, plan: ApplyPlan, token: str) -> None:
        try:
            results[name] = coordinator.apply(plan, token, confirmed=True)
        except BaseException as exc:
            results[name] = exc

    first_thread = threading.Thread(target=run_apply, args=("first", first_plan, first_token))
    first_thread.start()
    assert first_apply_capabilities_entered.wait(5)

    second_token = coordinator.preview(second_plan)
    second_thread = threading.Thread(target=run_apply, args=("second", second_plan, second_token))
    second_thread.start()

    second_capture_was_concurrent = second_capture_entered.wait(1)
    release_first_apply_capabilities.set()
    first_thread.join(5)
    assert not first_thread.is_alive()
    if not second_capture_was_concurrent:
        assert second_capture_entered.wait(5)
    allow_second_capture_to_verify.set()
    second_thread.join(5)
    assert not second_thread.is_alive()

    assert results["first"] == ApplyReceipt(True, True, True, True, False, False, None, None)
    assert results["second"] == ApplyReceipt(True, True, True, True, False, False, None, None)
    assert adapter.captured_targets == [42, 43]


def test_confirmation_rejects_a_different_plan_and_consumes_the_token() -> None:
    adapter = FakeAdapter()
    coordinator = ActuationCoordinator(adapter, all_capabilities_for)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    token = coordinator.preview(plan)
    with pytest.raises(PermissionError, match="plan"):
        coordinator.apply(replace(plan, ddc_changes=(("BRIGHTNESS", 43),)), token, confirmed=True)
    assert adapter.calls == []
    with pytest.raises(PermissionError, match="consumed"):
        coordinator.apply(plan, token, confirmed=True)


def test_confirmation_rejects_changed_asset_hash_and_consumes_token() -> None:
    adapter = FakeAdapter()
    coordinator = ActuationCoordinator(adapter, all_capabilities_for)
    plan = make_plan(icc_profile_path="display.icc", icc_profile_sha256=SHA256_A)
    token = coordinator.preview(plan)
    changed = replace(plan, icc_profile_sha256="b" * 64)
    with pytest.raises(PermissionError, match="plan"):
        coordinator.apply(changed, token, confirmed=True)
    with pytest.raises(PermissionError, match="consumed"):
        coordinator.apply(plan, token, confirmed=True)


def test_confirmation_is_consumed_before_a_failed_transaction() -> None:
    adapter = FakeAdapter(apply_error="apply failed")
    coordinator = ActuationCoordinator(adapter, all_capabilities_for)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    token = coordinator.preview(plan)
    receipt = coordinator.apply(plan, token, confirmed=True)
    assert receipt.success is False
    with pytest.raises(PermissionError, match="consumed"):
        coordinator.apply(plan, token, confirmed=True)


def test_new_preview_supersedes_the_previous_confirmation() -> None:
    adapter = FakeAdapter()
    coordinator = ActuationCoordinator(adapter, all_capabilities_for)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    old_token = coordinator.preview(plan)
    new_token = coordinator.preview(plan)
    with pytest.raises(PermissionError, match="unknown|consumed"):
        coordinator.apply(plan, old_token, confirmed=True)
    assert coordinator.apply(plan, new_token, confirmed=True).success is True


def test_confirmation_expiry_uses_injected_monotonic_clock() -> None:
    now = [10.0]
    adapter = FakeAdapter()
    coordinator = ActuationCoordinator(
        adapter,
        all_capabilities_for,
        confirmation_ttl_seconds=5.0,
        clock=lambda: now[0],
    )
    plan = make_plan()
    token = coordinator.preview(plan)
    now[0] = 15.0
    with pytest.raises(PermissionError, match="expired"):
        coordinator.apply(plan, token, confirmed=True)
    assert adapter.calls == []


@pytest.mark.parametrize("sample", [float("nan"), float("inf"), float("-inf"), True, "10"])
def test_confirmation_rejects_nonfinite_or_nonreal_clock_samples(sample: object) -> None:
    coordinator = ActuationCoordinator(FakeAdapter(), all_capabilities_for, clock=lambda: sample)  # type: ignore[arg-type,return-value]
    with pytest.raises((TypeError, ValueError), match="clock"):
        coordinator.preview(make_plan())


def test_confirmation_consumes_token_when_apply_clock_becomes_nonfinite() -> None:
    now = [10.0]
    adapter = FakeAdapter()
    coordinator = ActuationCoordinator(adapter, all_capabilities_for, clock=lambda: now[0])
    plan = make_plan()
    token = coordinator.preview(plan)
    now[0] = float("nan")
    with pytest.raises(ValueError, match="clock"):
        coordinator.apply(plan, token, confirmed=True)
    assert adapter.calls == []
    with pytest.raises(PermissionError, match="consumed"):
        coordinator.apply(plan, token, confirmed=True)


def test_confirmation_consumes_token_when_clock_moves_backward() -> None:
    now = [10.0]
    adapter = FakeAdapter()
    coordinator = ActuationCoordinator(adapter, all_capabilities_for, clock=lambda: now[0])
    plan = make_plan()
    token = coordinator.preview(plan)
    now[0] = 9.0
    with pytest.raises(ValueError, match="clock"):
        coordinator.apply(plan, token, confirmed=True)
    assert adapter.calls == []
    with pytest.raises(PermissionError, match="consumed"):
        coordinator.apply(plan, token, confirmed=True)


def test_confirmation_rejects_finite_values_whose_expiry_sum_overflows() -> None:
    coordinator = ActuationCoordinator(
        FakeAdapter(),
        all_capabilities_for,
        confirmation_ttl_seconds=1.0e308,
        clock=lambda: 1.0e308,
    )
    with pytest.raises(ValueError, match="clock|expiry"):
        coordinator.preview(make_plan())


def test_unknown_token_does_not_consume_the_current_confirmation() -> None:
    adapter = FakeAdapter()
    coordinator = ActuationCoordinator(adapter, all_capabilities_for)
    plan = make_plan()
    token = coordinator.preview(plan)
    with pytest.raises(PermissionError, match="unknown"):
        coordinator.apply(plan, "not-the-token", confirmed=True)
    assert coordinator.apply(plan, token, confirmed=True).success is True


def test_coordinator_revalidates_capability_before_capture_and_consumes_token() -> None:
    current = [all_capabilities()]
    adapter = FakeAdapter()
    coordinator = ActuationCoordinator(adapter, lambda _display_id: current[0])
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    token = coordinator.preview(plan)
    current[0] = CapabilityState(True, False, True, True, True, True)
    with pytest.raises(ValueError, match="DDC/CI"):
        coordinator.apply(plan, token, confirmed=True)
    assert adapter.calls == []
    with pytest.raises(PermissionError, match="consumed"):
        coordinator.apply(plan, token, confirmed=True)


def test_coordinator_cannot_bypass_measured_sensor_capability() -> None:
    adapter = FakeAdapter()
    capabilities = CapabilityState(False, True, True, True, True, True)
    coordinator = ActuationCoordinator(adapter, lambda _display_id: capabilities)
    with pytest.raises(ValueError, match="colorimeter"):
        coordinator.preview(make_plan(method=CalibrationMethod.MEASURED))
    assert adapter.calls == []


def test_receipt_declares_best_effort_in_process_recovery() -> None:
    receipt = _apply_confirmed_with_best_effort_recovery(FakeAdapter(), make_plan())
    assert receipt.recovery_guarantee is RecoveryGuarantee.IN_PROCESS_BEST_EFFORT
