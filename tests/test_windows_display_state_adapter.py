"""In-memory tests for the sole Windows display-state adapter boundary."""

from __future__ import annotations

import dis
import hashlib
import inspect
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from enum import Enum, IntEnum
from pathlib import Path
from types import SimpleNamespace

import pytest

from calibrate_pro import actuation as actuation_module
from calibrate_pro.actuation import ActuationCoordinator
from calibrate_pro.adapters import windows_display_state as windows_state
from calibrate_pro.adapters.windows_display_state import (
    DefaultWindowsDisplayPorts,
    InProcessDisplayTransactionMutex,
    ProductionDisplayTransactionMutex,
    WindowsDisplayStateAdapter,
    WindowsNamedDisplayTransactionMutex,
)
from calibrate_pro.recovery import (
    ApplyReceipt,
    CapturedState,
    CaptureStatus,
    DdcReading,
    DdcTargetIdentity,
    DisplayStateSnapshot,
    DwmLutSnapshot,
    IccActivationEffect,
    IccActivationError,
    IccInstallEffect,
    IccLifecycleSnapshot,
    IccProfileSnapshot,
    _apply_confirmed_with_best_effort_recovery,
)
from calibrate_pro.workflow import ApplyPlan, CalibrationMethod, CapabilityState, DwmLutKind

pytestmark = pytest.mark.windows
_OPCODE_MONITORING_AVAILABLE = hasattr(sys, "monitoring")
REQUIRES_OPCODE_MONITORING = pytest.mark.skipif(
    not _OPCODE_MONITORING_AVAILABLE,
    reason="opcode-level cancellation injection requires sys.monitoring (Python 3.12+)",
)

GammaRamp = tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]


@pytest.fixture(autouse=True)
def _isolate_process_mutexes_between_adapter_tests() -> object:
    """Tests assert retained ownership before teardown, then isolate global process locks."""
    yield
    for lock in InProcessDisplayTransactionMutex._locks.values():
        if lock.locked():
            lock.release()


#: How long teardown waits for one owner thread to leave its command loop.
OWNER_RETIREMENT_SECONDS = 5.0

#: The class-level evidence a retiring owner would otherwise republish.
_MUTEX_REGISTRIES = (
    WindowsNamedDisplayTransactionMutex._poisoned_display_keys,
    WindowsNamedDisplayTransactionMutex._poisoned_native_leases,
    WindowsNamedDisplayTransactionMutex._poisoned_native_claims,
    WindowsNamedDisplayTransactionMutex._pending_native_attempts,
    WindowsNamedDisplayTransactionMutex._pending_native_reservations,
    WindowsNamedDisplayTransactionMutex._pending_native_owners,
    WindowsNamedDisplayTransactionMutex._active_native_leases,
    WindowsNamedDisplayTransactionMutex._active_native_claims,
    WindowsNamedDisplayTransactionMutex._transient_native_quarantines,
)


@pytest.fixture(autouse=True)
def _retire_owner_threads_started_by_a_test(monkeypatch: pytest.MonkeyPatch) -> object:
    """Shut down the mutex owner threads a test leaves running.

    An owner whose release the OS never confirmed keeps its handle, and the
    thread holding it stays parked on a command that is never coming. The
    product is meant to do that, because closing a handle on a guess is the
    failure these tests exist to prevent. It also means a run accumulates live
    threads, and a thread started while coverage is measuring carries the
    coverage trace function for as long as it lives. A later test that installs
    a tracer of its own leaves the interpreter calling into a tracer that has
    been stopped, and the process dies with an access violation instead of
    reporting a result.

    Every assertion has run by the time this executes. Ending the command loop
    retires the thread and touches no handle, so what a test observed is what
    the product produced.
    """
    started: list[object] = []
    begin = windows_state._WindowsMutexOwner.start

    def record(owner: object) -> None:
        started.append(owner)
        begin(owner)

    monkeypatch.setattr(windows_state._WindowsMutexOwner, "start", record)
    yield
    # Reaching a terminal state is a published event, so retiring a thread here
    # would write the registries the test has already finished cleaning up.
    # What the test left behind is what the next one inherits.
    left_behind = [(shared, shared.copy()) for shared in _MUTEX_REGISTRIES]
    for owner in started:
        # Both reads happen under the condition the loop waits on. This is the
        # one exit that leaves an unconfirmed handle alone.
        with owner._condition:
            owner.terminal = True
            owner._condition.notify_all()
    for owner in started:
        owner.thread.join(OWNER_RETIREMENT_SECONDS)
        assert not owner.thread.is_alive(), f"mutex owner for {owner.display_key!r} outlived its test"
    for shared, contents in left_behind:
        shared.clear()
        shared.update(contents)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def assert_exception_note_if_supported(exception: BaseException, fragment: str) -> None:
    notes = getattr(exception, "__notes__", ())
    if callable(getattr(exception, "add_note", None)):
        assert any(fragment in note for note in notes)
    else:
        assert notes == ()


def valid_icc_payload(marker: bytes = b"") -> bytes:
    payload = bytearray(132 + len(marker))
    payload[0:4] = len(payload).to_bytes(4, "big")
    payload[36:40] = b"acsp"
    payload[128:132] = (0).to_bytes(4, "big")
    payload[132:] = marker
    return bytes(payload)


def valid_cube_payload(marker: str = "fixture") -> bytes:
    rows = "\n".join(("0 0 0", "1 0 0", "0 1 0", "1 1 0", "0 0 1", "1 0 1", "0 1 1", "1 1 1"))
    return f'TITLE "{marker}"\nLUT_3D_SIZE 2\n{rows}\n'.encode()


def write_asset(tmp_path: Path, name: str, payload: bytes) -> tuple[str, str]:
    suffix = Path(name).suffix.casefold()
    if suffix in {".icc", ".icm"} and payload[36:40] != b"acsp":
        payload = valid_icc_payload(payload)
    if suffix == ".cube" and b"LUT_3D_SIZE" not in payload:
        payload = valid_cube_payload(payload.decode("utf-8", errors="replace"))
    path = tmp_path / name
    path.write_bytes(payload)
    return str(path), sha256_bytes(payload)


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


def make_adapter(ports: object, **kwargs: object) -> WindowsDisplayStateAdapter:
    kwargs.setdefault("transaction_mutex", InProcessDisplayTransactionMutex())
    return WindowsDisplayStateAdapter(ports, **kwargs)  # type: ignore[arg-type]


def coordinator_for(adapter: WindowsDisplayStateAdapter) -> ActuationCoordinator:
    coordinator = getattr(adapter, "_test_actuation_coordinator", None)
    if coordinator is None:
        coordinator = ActuationCoordinator(
            adapter,
            lambda _display_id: CapabilityState(True, True, True, True, True, True),
        )
        adapter._test_actuation_coordinator = coordinator  # type: ignore[attr-defined]
    return coordinator


def capture_authorized(adapter: WindowsDisplayStateAdapter, plan: ApplyPlan) -> DisplayStateSnapshot:
    coordinator = coordinator_for(adapter)
    coordinator._capabilities_for(plan)
    issuer = coordinator._capture_authorization_issuer
    assert issuer is not None
    return adapter.capture(plan, authorization=issuer(plan))


def run_confirmed(adapter: WindowsDisplayStateAdapter, plan: ApplyPlan) -> ApplyReceipt:
    coordinator = coordinator_for(adapter)
    token = coordinator.preview(plan)
    return coordinator.apply(plan, token, confirmed=True)


def linear_ramp(offset: int = 0) -> GammaRamp:
    channel = tuple(range(offset, offset + 256))
    return channel, channel, channel


def icc_snapshot(path: str = "old.icc", payload: bytes = valid_icc_payload(b"old-icc")) -> IccProfileSnapshot:
    return IccProfileSnapshot(path, payload, sha256_bytes(payload))


def dwm_snapshot(
    kind: DwmLutKind = DwmLutKind.SDR,
    path: str = "old.cube",
    payload: bytes = valid_cube_payload("old-lut"),
) -> DwmLutSnapshot:
    return DwmLutSnapshot(kind, path, payload, sha256_bytes(payload))


class FakeWindowsDisplayPorts:
    """Complete authoritative in-memory implementation of WindowsDisplayPorts."""

    def __init__(
        self,
        *,
        icc_profile: CapturedState[IccProfileSnapshot] | None = None,
        gamma_ramp: CapturedState[GammaRamp] | None = None,
        dwm_luts: CapturedState[tuple[DwmLutSnapshot, ...]] | None = None,
    ) -> None:
        self.ddc_values = {"BRIGHTNESS": 50, "CONTRAST": 75}
        self.ddc_maxima = {"BRIGHTNESS": 100, "CONTRAST": 100}
        self.icc_profile = icc_profile or CapturedState.captured(icc_snapshot())
        self.gamma_ramp = gamma_ramp or CapturedState.captured(linear_ramp())
        self.dwm_luts = dwm_luts or CapturedState.captured((dwm_snapshot(),))
        self.calls: list[tuple[object, ...]] = []
        self.activate_icc_calls: list[tuple[str, IccProfileSnapshot]] = []
        self.icc_files: dict[str, bytes] = {}
        current_profile = self.icc_profile.value
        self.icc_installed_profiles: set[str] = set()
        self.icc_associations: dict[str, set[str]] = {"display-1": set()}
        if isinstance(current_profile, IccProfileSnapshot):
            current_name = Path(current_profile.original_path).name
            self.icc_installed_profiles.add(current_name)
            self.icc_associations["display-1"].add(current_name)
        self.failed_ddc_codes: set[str] = set()
        self.fail_icc = False
        self.fail_gamma = False
        self.fail_dwm = False

    def resolve_ddc_target(self, display_id: str) -> DdcTargetIdentity:
        self.calls.append(("resolve_ddc_target", display_id))
        return DdcTargetIdentity(display_id, f"fake-pnp:{display_id}")

    def read_ddc(self, target: DdcTargetIdentity, code: str) -> DdcReading:
        self.calls.append(("read_ddc", target.display_id, code))
        return DdcReading(self.ddc_values[code], self.ddc_maxima[code])

    def write_ddc(
        self,
        target: DdcTargetIdentity,
        code: str,
        value: int,
        *,
        expected_maximum: int,
    ) -> None:
        self.calls.append(("write_ddc", target.display_id, code, value))
        if code in self.failed_ddc_codes:
            raise RuntimeError(f"{code} restore failed")
        if self.ddc_maxima[code] != expected_maximum:
            raise RuntimeError(f"{code} maximum changed")
        self.ddc_values[code] = value

    def capture_icc_profile(self, display_id: str) -> CapturedState[IccProfileSnapshot]:
        self.calls.append(("capture_icc_profile", display_id))
        return self.icc_profile

    def is_icc_profile_installed(self, profile_name: str) -> bool:
        self.calls.append(("is_icc_profile_installed", profile_name))
        return profile_name in self.icc_installed_profiles

    def is_icc_profile_associated(self, display_id: str, profile_name: str) -> bool:
        self.calls.append(("is_icc_profile_associated", display_id, profile_name))
        return profile_name in self.icc_associations.setdefault(display_id, set())

    def materialize_icc_profile(self, profile: IccProfileSnapshot) -> IccInstallEffect:
        self.calls.append(("materialize_icc_profile", profile))
        if self.fail_icc:
            raise RuntimeError("ICC materialization failed")
        path = f"C:/Color/calibrate-pro-{profile.sha256}.icc"
        created = path not in self.icc_files
        if not created and self.icc_files[path] != profile.payload:
            raise RuntimeError("ICC content-address collision")
        self.icc_files[path] = profile.payload
        installed = IccProfileSnapshot(path, profile.payload, profile.sha256)
        return IccInstallEffect(installed, created)

    def register_icc_profile(self, effect: IccInstallEffect) -> None:
        self.calls.append(("register_icc_profile", effect))
        if self.fail_icc:
            raise RuntimeError("ICC registration failed")

    def activate_icc_profile(
        self,
        display_id: str,
        profile: IccProfileSnapshot,
        *,
        register: bool,
        associate: bool,
    ) -> IccActivationEffect:
        self.calls.append(("activate_icc_profile", display_id, profile))
        self.activate_icc_calls.append((display_id, profile))
        if self.fail_icc:
            raise RuntimeError("ICC activation failed")
        name = Path(profile.original_path).name
        if register:
            self.icc_installed_profiles.add(name)
        if associate:
            self.icc_associations.setdefault(display_id, set()).add(name)
        self.icc_profile = CapturedState.captured(profile)
        return IccActivationEffect(register, associate, True)

    def deactivate_icc_profile(self, display_id: str, profile_name: str) -> None:
        self.calls.append(("deactivate_icc_profile", display_id, profile_name))
        if self.fail_icc:
            raise RuntimeError("ICC deactivation failed")
        self.icc_associations.setdefault(display_id, set()).discard(profile_name)
        current = self.icc_profile.value
        if current is not None and Path(current.original_path).name == profile_name:
            self.icc_profile = CapturedState.captured(None)

    def remove_icc_profile(self, effect: IccInstallEffect, *, registration_attempted: bool) -> None:
        self.calls.append(("remove_icc_profile", effect, registration_attempted))
        if self.fail_icc:
            raise RuntimeError("ICC removal failed")
        self.icc_files.pop(effect.installed_profile.original_path, None)

    def capture_gamma_ramp(self, display_id: str) -> CapturedState[GammaRamp]:
        self.calls.append(("capture_gamma_ramp", display_id))
        return self.gamma_ramp

    def set_gamma_ramp(self, display_id: str, ramp: GammaRamp | None) -> None:
        self.calls.append(("set_gamma_ramp", display_id, ramp))
        if self.fail_gamma:
            raise RuntimeError("gamma restore failed")
        self.gamma_ramp = CapturedState.captured(ramp)

    def capture_dwm_luts(self, display_id: str) -> CapturedState[tuple[DwmLutSnapshot, ...]]:
        self.calls.append(("capture_dwm_luts", display_id))
        return self.dwm_luts

    def set_dwm_luts(self, display_id: str, luts: tuple[DwmLutSnapshot, ...]) -> None:
        self.calls.append(("set_dwm_luts", display_id, luts))
        if self.fail_dwm:
            raise RuntimeError("DWM restore failed")
        self.dwm_luts = CapturedState.captured(luts)


def test_adapter_constructor_does_not_probe_or_write() -> None:
    ports = FakeWindowsDisplayPorts()
    make_adapter(ports)
    assert ports.calls == []


def test_capture_reads_only_requested_domains_and_preserves_typed_state(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    vcgt_path, vcgt_sha = write_asset(tmp_path, "new.cal", b"new-vcgt")
    lut_path, lut_sha = write_asset(tmp_path, "new.cube", b"new-lut")
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, gamma_ramp_loader=lambda _: linear_ramp(1000))
    plan = make_plan(
        ddc_changes=(("CONTRAST", 70), ("BRIGHTNESS", 42)),
        icc_profile_path=profile_path,
        icc_profile_sha256=profile_sha,
        vcgt_path=vcgt_path,
        vcgt_sha256=vcgt_sha,
        dwm_lut_path=lut_path,
        dwm_lut_kind=DwmLutKind.SDR,
        dwm_lut_sha256=lut_sha,
    )
    snapshot = capture_authorized(adapter, plan)
    target = DdcTargetIdentity("display-1", "fake-pnp:display-1")
    assert snapshot == DisplayStateSnapshot(
        "display-1",
        (("CONTRAST", DdcReading(75, 100)), ("BRIGHTNESS", DdcReading(50, 100))),
        CapturedState.captured(icc_snapshot()),
        CapturedState.captured(linear_ramp()),
        CapturedState.captured((dwm_snapshot(),)),
        target,
        IccLifecycleSnapshot(
            f"calibrate-pro-{profile_sha}.icc",
            False,
            False,
        ),
    )
    assert ports.calls == [
        ("resolve_ddc_target", "display-1"),
        ("read_ddc", "display-1", "CONTRAST"),
        ("read_ddc", "display-1", "BRIGHTNESS"),
        ("is_icc_profile_installed", f"calibrate-pro-{profile_sha}.icc"),
        ("is_icc_profile_associated", "display-1", f"calibrate-pro-{profile_sha}.icc"),
        ("capture_icc_profile", "display-1"),
        ("capture_gamma_ramp", "display-1"),
        ("capture_dwm_luts", "display-1"),
    ]
    adapter.restore(snapshot)


def test_capture_skips_every_unrequested_domain() -> None:
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    snapshot = capture_authorized(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),)))
    assert snapshot == DisplayStateSnapshot(
        "display-1",
        (("BRIGHTNESS", DdcReading(50, 100)),),
        None,
        None,
        None,
        DdcTargetIdentity("display-1", "fake-pnp:display-1"),
    )
    assert ports.calls == [
        ("resolve_ddc_target", "display-1"),
        ("read_ddc", "display-1", "BRIGHTNESS"),
    ]
    adapter.restore(snapshot)


def test_ddc_target_above_reported_maximum_aborts_before_any_write() -> None:
    ports = FakeWindowsDisplayPorts()
    ports.ddc_maxima["BRIGHTNESS"] = 40
    adapter = make_adapter(ports)
    receipt = run_confirmed(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),)))
    assert receipt.captured is False
    assert receipt.applied is False
    assert ports.calls == [
        ("resolve_ddc_target", "display-1"),
        ("read_ddc", "display-1", "BRIGHTNESS"),
    ]


def test_ddc_target_equal_to_reported_maximum_is_allowed() -> None:
    ports = FakeWindowsDisplayPorts()
    ports.ddc_values["BRIGHTNESS"] = 40
    ports.ddc_maxima["BRIGHTNESS"] = 42
    adapter = make_adapter(ports)
    receipt = run_confirmed(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),)))
    assert receipt.success is True


def test_snapshot_retains_complete_ddc_current_and_maximum_evidence() -> None:
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    snapshot = capture_authorized(adapter, plan)
    assert snapshot.ddc_values == (("BRIGHTNESS", DdcReading(50, 100)),)
    adapter.restore(snapshot)


def test_ddc_maximum_change_after_capture_blocks_apply_and_compensation() -> None:
    class MaximumChangesPorts(FakeWindowsDisplayPorts):
        def __init__(self) -> None:
            super().__init__()
            self.read_count = 0
            self.write_values: list[int] = []

        def read_ddc(self, target: DdcTargetIdentity, code: str) -> DdcReading:
            self.calls.append(("read_ddc", target.display_id, code))
            self.read_count += 1
            if self.read_count == 1:
                return DdcReading(50, 100)
            return DdcReading(40, 40)

        def write_ddc(
            self,
            target: DdcTargetIdentity,
            code: str,
            value: int,
            *,
            expected_maximum: int,
        ) -> None:
            self.write_values.append(value)
            super().write_ddc(target, code, value, expected_maximum=expected_maximum)

    ports = MaximumChangesPorts()
    adapter = make_adapter(ports)
    receipt = run_confirmed(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),)))
    assert receipt.success is False
    assert receipt.restored is False
    assert ports.write_values == []


@pytest.mark.parametrize(
    ("current", "maximum", "error"),
    ((True, 100, TypeError), (0, False, TypeError), (-1, 100, ValueError), (101, 100, ValueError), (0, 0, ValueError)),
)
def test_invalid_ddc_reading_fails_closed(current: object, maximum: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        DdcReading(current, maximum)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("domain", "bad_value"),
    (
        ("icc", "not-an-icc-snapshot"),
        ("gamma", ((0,), (0,), (0,))),
    ),
)
def test_capture_rejects_malformed_runtime_evidence_before_any_write(
    tmp_path: Path, domain: str, bad_value: object
) -> None:
    ports = FakeWindowsDisplayPorts()
    if domain == "icc":
        ports.icc_profile = CapturedState.captured(bad_value)  # type: ignore[assignment,arg-type]
        path, digest = write_asset(tmp_path, "target.icc", b"target")
        plan = make_plan(icc_profile_path=path, icc_profile_sha256=digest)
        adapter = make_adapter(ports)
    else:
        ports.gamma_ramp = CapturedState.captured(bad_value)  # type: ignore[assignment,arg-type]
        path, digest = write_asset(tmp_path, "target.cal", b"target")
        plan = make_plan(vcgt_path=path, vcgt_sha256=digest)
        adapter = make_adapter(ports, gamma_ramp_loader=lambda _path: linear_ramp())
    with pytest.raises((TypeError, ValueError), match="ICC|gamma|captured|ramp"):
        capture_authorized(adapter, plan)
    assert not any(call[0].startswith(("write", "set", "activate", "materialize")) for call in ports.calls)


@pytest.mark.parametrize("domain", ["icc", "gamma", "dwm"])
def test_not_captured_requested_domain_aborts_before_any_write(tmp_path: Path, domain: str) -> None:
    path, digest = write_asset(tmp_path, f"target-{domain}.bin", domain.encode())
    ports = FakeWindowsDisplayPorts()
    changes: dict[str, object]
    if domain == "icc":
        ports.icc_profile = CapturedState.not_captured("ambiguous ICC read")
        changes = {"icc_profile_path": path, "icc_profile_sha256": digest}
    elif domain == "gamma":
        ports.gamma_ramp = CapturedState.not_captured("ambiguous gamma read")
        changes = {"vcgt_path": path, "vcgt_sha256": digest}
    else:
        ports.dwm_luts = CapturedState.not_captured("DWM state is not authoritative")
        changes = {
            "dwm_lut_path": path,
            "dwm_lut_kind": DwmLutKind.SDR,
            "dwm_lut_sha256": digest,
        }
    adapter = make_adapter(ports, gamma_ramp_loader=lambda _: linear_ramp(1000))
    receipt = run_confirmed(adapter, make_plan(**changes))
    assert receipt.captured is False
    assert receipt.applied is False
    assert receipt.restore_attempted is False
    assert all(not str(call[0]).startswith(("write_", "set_")) for call in ports.calls)


def test_asset_digest_failure_occurs_before_hardware_capture_or_write(tmp_path: Path) -> None:
    profile_path, _profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    receipt = run_confirmed(
        adapter,
        make_plan(icc_profile_path=profile_path, icc_profile_sha256="0" * 64),
    )
    assert receipt.captured is False
    assert "SHA-256" in (receipt.error or "")
    assert ports.calls == []


@pytest.mark.parametrize("asset_kind", ["icc", "dwm"])
def test_invalid_confirmed_asset_is_rejected_before_ddc_capture_or_write(tmp_path: Path, asset_kind: str) -> None:
    suffix = ".icc" if asset_kind == "icc" else ".cube"
    path = tmp_path / f"invalid{suffix}"
    path.write_bytes(b"invalid-but-hash-matched")
    digest = sha256_bytes(path.read_bytes())
    changes: dict[str, object]
    if asset_kind == "icc":
        changes = {"icc_profile_path": str(path), "icc_profile_sha256": digest}
    else:
        changes = {
            "dwm_lut_path": str(path),
            "dwm_lut_kind": DwmLutKind.SDR,
            "dwm_lut_sha256": digest,
        }
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    with pytest.raises(ValueError):
        capture_authorized(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),), **changes))
    assert ports.calls == []


@pytest.mark.parametrize("label", ("ICC profile", "VCGT", "DWM LUT"))
def test_confirmed_asset_read_is_bounded_before_parser_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    path = tmp_path / "oversized.bin"
    path.write_bytes(b"12345")
    monkeypatch.setitem(windows_state._MAX_CONFIRMED_ASSET_BYTES, label, 4)
    with pytest.raises(RuntimeError, match="size|large|limit|supported"):
        windows_state._read_exact_bytes(str(path), sha256_bytes(b"12345"), label)


def test_vcgt_parser_consumes_staged_confirmed_bytes_not_mutated_source(tmp_path: Path) -> None:
    vcgt_path, vcgt_sha = write_asset(tmp_path, "target.cal", b"confirmed-vcgt")
    source = Path(vcgt_path)
    confirmed = source.read_bytes()
    observed: list[bytes] = []

    def loader(staged_path: str) -> GammaRamp:
        source.write_bytes(b"changed-after-hash-check")
        observed.append(Path(staged_path).read_bytes())
        assert Path(staged_path).resolve() != source.resolve()
        return linear_ramp(1000)

    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, gamma_ramp_loader=loader)
    snapshot = capture_authorized(adapter, make_plan(vcgt_path=vcgt_path, vcgt_sha256=vcgt_sha))
    assert observed == [confirmed]
    adapter.restore(snapshot)


def test_concurrent_capture_cannot_overwrite_active_transaction() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingPorts(FakeWindowsDisplayPorts):
        def read_ddc(self, target: DdcTargetIdentity, code: str) -> DdcReading:
            entered.set()
            assert release.wait(timeout=5)
            return super().read_ddc(target, code)

    ports = BlockingPorts()
    adapter = make_adapter(ports)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(capture_authorized, adapter, plan)
        assert entered.wait(timeout=5)
        second = executor.submit(capture_authorized, adapter, plan)
        with pytest.raises(RuntimeError, match="active"):
            second.result(timeout=5)
        release.set()
        snapshot = first.result(timeout=5)
    adapter.restore(snapshot)


def test_separate_adapters_cannot_own_the_same_display_transaction() -> None:
    first_ports = FakeWindowsDisplayPorts()
    second_ports = FakeWindowsDisplayPorts()
    first = make_adapter(first_ports)
    second = make_adapter(second_ports)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    snapshot = capture_authorized(first, plan)
    with pytest.raises(RuntimeError, match="mutex"):
        capture_authorized(second, plan)
    assert second_ports.calls == []
    first.restore(snapshot)


def test_windows_named_mutex_constructor_is_lazy() -> None:
    calls: list[str] = []
    WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: calls.append("load"))
    assert calls == []


def test_windows_named_mutex_rejects_abandoned_state_and_uses_global_namespace() -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    names: list[str] = []
    releases: list[object] = []
    closes: list[object] = []
    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda _security, _owned, name: names.append(name) or 123),
        WaitForSingleObject=Function(lambda _handle, _timeout: 0x80),
        ReleaseMutex=Function(lambda handle: releases.append(handle) or True),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    with pytest.raises(RuntimeError, match="abandoned|manual recovery"):
        mutex.acquire("display-1")
    assert names and names[0].startswith("Global\\")
    assert releases == [123]
    assert closes == [123]
    with pytest.raises(RuntimeError, match="poison|manual recovery|abandoned"):
        mutex.acquire("display-1")
    second_instance = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    with pytest.raises(RuntimeError, match="poison|manual recovery|abandoned"):
        second_instance.acquire("display-1")
    assert len(names) == 1


def test_every_windows_adapter_requires_authorization_for_any_conforming_ports() -> None:
    class NoopMutex:
        def acquire(self, display_id: str) -> object:
            return display_id

        def release(self, handle: object) -> None:
            return None

    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=NoopMutex())
    receipt = _apply_confirmed_with_best_effort_recovery(
        adapter,
        make_plan(ddc_changes=(("BRIGHTNESS", 42),)),
    )
    assert receipt.captured is False
    assert receipt.error and "authorization" in receipt.error
    assert ports.calls == []


def test_windows_adapter_exposes_no_confirmation_authority_binding_or_minting_hooks() -> None:
    adapter = make_adapter(FakeWindowsDisplayPorts())
    assert not hasattr(adapter, "_bind_confirmation_authority")
    assert not hasattr(adapter, "_issue_capture_authorization")


def test_default_windows_adapter_mutex_is_always_cross_process() -> None:
    adapter = WindowsDisplayStateAdapter(FakeWindowsDisplayPorts())
    assert isinstance(adapter._transaction_mutex, ProductionDisplayTransactionMutex)


def test_release_failure_never_allows_unlocked_compensation_write() -> None:
    class DropsThenRaisesMutex:
        def __init__(self) -> None:
            self.owned = False

        def acquire(self, display_id: str) -> object:
            assert not self.owned
            self.owned = True
            return display_id

        def release(self, handle: object) -> None:
            assert self.owned
            self.owned = False
            raise RuntimeError("release failed after ownership was lost")

    mutex = DropsThenRaisesMutex()

    class LeaseCheckingPorts(FakeWindowsDisplayPorts):
        def __init__(self) -> None:
            super().__init__()
            self.writes_with_lease: list[tuple[int, bool]] = []

        def write_ddc(
            self,
            target: DdcTargetIdentity,
            code: str,
            value: int,
            *,
            expected_maximum: int,
        ) -> None:
            self.writes_with_lease.append((value, mutex.owned))
            super().write_ddc(target, code, value, expected_maximum=expected_maximum)

    ports = LeaseCheckingPorts()
    adapter = make_adapter(ports, transaction_mutex=mutex)
    receipt = run_confirmed(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),)))
    assert receipt.success is False
    assert receipt.restored is False
    assert receipt.restore_attempted is False
    assert receipt.error and "release failed" in receipt.error
    assert ports.writes_with_lease == [(42, True)]


def test_cancellation_during_restore_is_deferred_until_all_domains_and_release_finish(tmp_path: Path) -> None:
    vcgt_path, vcgt_sha = write_asset(tmp_path, "target.cal", b"target-vcgt")
    dwm_path, dwm_sha = write_asset(tmp_path, "target.cube", b"target-dwm")
    verification_interrupt = KeyboardInterrupt("verification cancelled")
    restoration_interrupt = KeyboardInterrupt("DDC restoration cancelled")
    original_gamma = linear_ramp()
    original_dwm = (dwm_snapshot(),)

    class CancellationPorts(FakeWindowsDisplayPorts):
        def __init__(self) -> None:
            super().__init__(
                gamma_ramp=CapturedState.captured(original_gamma),
                dwm_luts=CapturedState.captured(original_dwm),
            )
            self.read_count = 0
            self.restore_cancelled = False

        def read_ddc(self, target: DdcTargetIdentity, code: str) -> DdcReading:
            self.calls.append(("read_ddc", target.display_id, code))
            self.read_count += 1
            if self.read_count == 3:
                raise verification_interrupt
            return DdcReading(self.ddc_values[code], self.ddc_maxima[code])

        def write_ddc(
            self,
            target: DdcTargetIdentity,
            code: str,
            value: int,
            *,
            expected_maximum: int,
        ) -> None:
            self.calls.append(("write_ddc", target.display_id, code, value))
            if value == 50 and not self.restore_cancelled:
                self.restore_cancelled = True
                raise restoration_interrupt
            self.ddc_values[code] = value

    ports = CancellationPorts()
    adapter = make_adapter(ports, gamma_ramp_loader=lambda _path: linear_ramp(1000))
    plan = make_plan(
        ddc_changes=(("BRIGHTNESS", 42),),
        vcgt_path=vcgt_path,
        vcgt_sha256=vcgt_sha,
        dwm_lut_path=dwm_path,
        dwm_lut_kind=DwmLutKind.SDR,
        dwm_lut_sha256=dwm_sha,
    )
    with pytest.raises(KeyboardInterrupt) as caught:
        run_confirmed(adapter, plan)
    assert caught.value is verification_interrupt
    assert_exception_note_if_supported(caught.value, "DDC restoration cancelled")
    assert ports.gamma_ramp == CapturedState.captured(original_gamma)
    assert ports.dwm_luts == CapturedState.captured(original_dwm)
    assert adapter._active is None
    assert adapter._phase is None


def test_forged_standalone_snapshot_is_rejected_before_any_writer_call() -> None:
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    forged = DisplayStateSnapshot(
        "display-1",
        (("RESTORE_FACTORY_DEFAULTS", DdcReading(1, 100)),),  # type: ignore[arg-type]
        None,
        None,
        None,
        DdcTargetIdentity("display-1", "fake-pnp:display-1"),
    )
    with pytest.raises(RuntimeError, match="active|issued|snapshot"):
        adapter.restore(forged)
    assert ports.calls == []


def test_substituted_equal_snapshot_is_rejected_by_object_identity() -> None:
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    issued = capture_authorized(adapter, plan)
    substituted = replace(issued)
    ports.calls.clear()
    with pytest.raises(RuntimeError, match="exact|snapshot|transaction"):
        adapter.restore(substituted)
    assert ports.calls == []
    adapter.restore(issued)


def test_mutating_the_exact_issued_snapshot_never_changes_a_compensation_write() -> None:
    class MutatingSnapshotAdapter(WindowsDisplayStateAdapter):
        def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
            snapshot = super().capture(plan, authorization=authorization)
            object.__setattr__(snapshot, "ddc_values", (("BRIGHTNESS", DdcReading(99, 100)),))
            return snapshot

    ports = FakeWindowsDisplayPorts()
    adapter = MutatingSnapshotAdapter(ports, transaction_mutex=InProcessDisplayTransactionMutex())
    receipt = run_confirmed(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),)))
    writes = [call for call in ports.calls if call[0] == "write_ddc"]
    assert receipt.success is False
    assert receipt.restored is False
    assert all(call[3] != 99 for call in writes)


def test_mutating_the_confirmed_plan_after_capture_never_changes_a_writer_target() -> None:
    class MutatingPlanAdapter(WindowsDisplayStateAdapter):
        def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
            snapshot = super().capture(plan, authorization=authorization)
            object.__setattr__(plan, "ddc_changes", (("BRIGHTNESS", 99),))
            return snapshot

    ports = FakeWindowsDisplayPorts()
    adapter = MutatingPlanAdapter(ports, transaction_mutex=InProcessDisplayTransactionMutex())
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    receipt = run_confirmed(adapter, plan)
    writes = [call for call in ports.calls if call[0] == "write_ddc"]
    assert receipt.success is False
    assert all(call[3] != 99 for call in writes)


def test_failed_capture_mutex_cleanup_permanently_poisons_the_adapter(tmp_path: Path) -> None:
    class DropsThenRaisesMutex:
        def __init__(self) -> None:
            self.acquisitions = 0

        def acquire(self, display_id: str) -> object:
            self.acquisitions += 1
            return (display_id, self.acquisitions)

        def release(self, handle: object) -> None:
            raise RuntimeError("release ownership is uncertain")

    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    mutex = DropsThenRaisesMutex()
    adapter = make_adapter(
        FakeWindowsDisplayPorts(),
        transaction_mutex=mutex,
        icc_profile_validator=lambda _path: (_ for _ in ()).throw(ValueError("invalid profile")),
    )
    plan = make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha)
    with pytest.raises(RuntimeError, match="mutex|release|uncertain"):
        capture_authorized(adapter, plan)
    prior_acquisitions = mutex.acquisitions
    with pytest.raises(RuntimeError, match="poison|manual recovery|active"):
        capture_authorized(adapter, plan)
    assert mutex.acquisitions == prior_acquisitions


def test_direct_recovery_helper_cannot_actuate_default_windows_adapter() -> None:
    class NoopMutex:
        def acquire(self, display_id: str) -> object:
            return display_id

        def release(self, handle: object) -> None:
            return None

    class FakeProductionPorts(DefaultWindowsDisplayPorts):
        def __init__(self) -> None:
            super().__init__(module_loader=lambda _name: None)
            self.calls: list[tuple[object, ...]] = []

        def resolve_ddc_target(self, display_id: str) -> DdcTargetIdentity:
            self.calls.append(("resolve_ddc_target", display_id))
            return DdcTargetIdentity(display_id, f"fake-pnp:{display_id}")

        def read_ddc(self, target: DdcTargetIdentity, code: str) -> DdcReading:
            self.calls.append(("read_ddc", target.display_id, code))
            return DdcReading(50, 100)

        def write_ddc(
            self,
            target: DdcTargetIdentity,
            code: str,
            value: int,
            *,
            expected_maximum: int,
        ) -> None:
            self.calls.append(("write_ddc", target.display_id, code, value))

    ports = FakeProductionPorts()
    adapter = make_adapter(ports, transaction_mutex=NoopMutex())
    receipt = _apply_confirmed_with_best_effort_recovery(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),)))
    assert receipt.captured is False
    assert receipt.error and "authorization" in receipt.error
    assert ports.calls == []


def test_restore_readback_prevents_false_restored_receipt() -> None:
    class FaultyPorts(FakeWindowsDisplayPorts):
        def write_ddc(
            self,
            target: DdcTargetIdentity,
            code: str,
            value: int,
            *,
            expected_maximum: int,
        ) -> None:
            self.calls.append(("write_ddc", target.display_id, code, value))
            if value == 42:
                self.ddc_values[code] = 41
            # The restoration write to 50 is a silent no-op.

    ports = FaultyPorts()
    adapter = make_adapter(ports)
    receipt = run_confirmed(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),)))
    assert receipt.success is False
    assert receipt.restore_attempted is True
    assert receipt.restored is False
    assert receipt.restore_error and "conflict" in receipt.restore_error
    assert ports.ddc_values["BRIGHTNESS"] == 41


def test_apply_uses_preflighted_bytes_even_if_source_changes_after_capture(tmp_path: Path) -> None:
    lut_path, lut_sha = write_asset(tmp_path, "new.cube", b"confirmed-bytes")
    ports = FakeWindowsDisplayPorts(dwm_luts=CapturedState.captured(()))
    adapter = make_adapter(ports)
    plan = make_plan(
        dwm_lut_path=lut_path,
        dwm_lut_kind=DwmLutKind.HDR,
        dwm_lut_sha256=lut_sha,
    )
    capture_authorized(adapter, plan)
    confirmed_payload = Path(lut_path).read_bytes()
    Path(lut_path).write_bytes(b"changed-after-capture")
    adapter.apply(plan)
    applied = ports.dwm_luts.value
    assert applied is not None
    assert applied[0].kind is DwmLutKind.HDR
    assert applied[0].payload == confirmed_payload
    assert applied[0].sha256 == lut_sha
    assert adapter.verify(plan) is True
    adapter.commit(plan)


def test_apply_writes_only_requested_fields(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    vcgt_path, vcgt_sha = write_asset(tmp_path, "new.cal", b"new-vcgt")
    lut_path, lut_sha = write_asset(tmp_path, "new.cube", b"new-lut")
    target_ramp = linear_ramp(1000)
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, gamma_ramp_loader=lambda _: target_ramp)
    plan = make_plan(
        ddc_changes=(("BRIGHTNESS", 42),),
        icc_profile_path=profile_path,
        icc_profile_sha256=profile_sha,
        vcgt_path=vcgt_path,
        vcgt_sha256=vcgt_sha,
        dwm_lut_path=lut_path,
        dwm_lut_kind=DwmLutKind.SDR,
        dwm_lut_sha256=lut_sha,
    )
    capture_authorized(adapter, plan)
    ports.calls.clear()
    adapter.apply(plan)
    assert ports.ddc_values["BRIGHTNESS"] == 42
    expected_profile = icc_snapshot(
        f"C:/Color/calibrate-pro-{profile_sha}.icc",
        Path(profile_path).read_bytes(),
    )
    assert ports.icc_profile.value == expected_profile
    assert ports.gamma_ramp.value == target_ramp
    assert ports.dwm_luts.value == (dwm_snapshot(DwmLutKind.SDR, lut_path, Path(lut_path).read_bytes()),)
    assert [call[0] for call in ports.calls] == [
        "materialize_icc_profile",
        "read_ddc",
        "write_ddc",
        "is_icc_profile_installed",
        "is_icc_profile_associated",
        "capture_icc_profile",
        "activate_icc_profile",
        "capture_gamma_ramp",
        "set_gamma_ramp",
        "capture_dwm_luts",
        "set_dwm_luts",
    ]
    assert adapter.verify(plan) is True
    adapter.commit(plan)


def test_apply_requires_a_successful_matching_capture() -> None:
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    with pytest.raises(RuntimeError, match="capture"):
        adapter.apply(make_plan(ddc_changes=(("BRIGHTNESS", 42),)))
    assert ports.calls == []


def test_commit_consumes_verified_active_transaction(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    ports = FakeWindowsDisplayPorts(icc_profile=CapturedState.captured(None))
    adapter = make_adapter(ports)
    plan = make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha)
    capture_authorized(adapter, plan)
    adapter.apply(plan)
    ports.calls.clear()
    assert adapter.verify(plan) is True
    target_name = f"calibrate-pro-{profile_sha}.icc"
    assert ports.calls == [
        ("capture_icc_profile", "display-1"),
        ("is_icc_profile_installed", target_name),
        ("is_icc_profile_associated", "display-1", target_name),
    ]
    adapter.commit(plan)
    with pytest.raises(RuntimeError, match="active"):
        adapter.verify(plan)


def test_clear_existing_luts_applies_and_verifies_empty_authoritative_state() -> None:
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    plan = make_plan(clear_existing_lut=True)
    capture_authorized(adapter, plan)
    adapter.apply(plan)
    assert ports.dwm_luts.value == ()
    assert adapter.verify(plan) is True
    adapter.commit(plan)


def test_applying_one_dwm_kind_preserves_the_other_captured_kind(tmp_path: Path) -> None:
    target_path, target_sha = write_asset(tmp_path, "target.cube", b"new-sdr")
    old_sdr = dwm_snapshot(DwmLutKind.SDR, "old-sdr.cube", valid_cube_payload("old-sdr"))
    old_hdr = dwm_snapshot(DwmLutKind.HDR, "old-hdr.cube", valid_cube_payload("old-hdr"))
    ports = FakeWindowsDisplayPorts(dwm_luts=CapturedState.captured((old_sdr, old_hdr)))
    adapter = make_adapter(ports)
    plan = make_plan(
        dwm_lut_path=target_path,
        dwm_lut_kind=DwmLutKind.SDR,
        dwm_lut_sha256=target_sha,
    )
    capture_authorized(adapter, plan)
    adapter.apply(plan)
    expected_sdr = dwm_snapshot(DwmLutKind.SDR, target_path, Path(target_path).read_bytes())
    assert ports.dwm_luts.value == (expected_sdr, old_hdr)
    assert adapter.verify(plan) is True
    adapter.commit(plan)


def test_restore_disassociates_profile_when_capture_proved_no_association(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    ports = FakeWindowsDisplayPorts(icc_profile=CapturedState.captured(None))
    adapter = make_adapter(ports)
    plan = make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha)
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    assert ports.icc_profile.value is not None
    adapter.restore(snapshot)
    assert ports.icc_profile.status is CaptureStatus.CAPTURED
    assert ports.icc_profile.value is None
    assert len(ports.activate_icc_calls) == 1
    assert ports.activate_icc_calls[0][0] == "display-1"
    assert Path(ports.activate_icc_calls[0][1].original_path).name == f"calibrate-pro-{profile_sha}.icc"
    assert [call[0] for call in ports.calls if call[0] == "deactivate_icc_profile"] == ["deactivate_icc_profile"]
    assert f"C:/Color/calibrate-pro-{profile_sha}.icc" in ports.icc_files


def test_same_icc_digest_on_different_displays_is_serialized_before_display_capture(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "shared.icc", b"shared-icc")

    class SharedIccPorts(FakeWindowsDisplayPorts):
        def __init__(self) -> None:
            super().__init__(icc_profile=CapturedState.captured(None))
            self.profiles = {
                "display-1": CapturedState.captured(None),
                "display-2": CapturedState.captured(None),
            }

        def capture_icc_profile(self, display_id: str) -> CapturedState[IccProfileSnapshot]:
            self.calls.append(("capture_icc_profile", display_id))
            return self.profiles[display_id]

        def activate_icc_profile(
            self,
            display_id: str,
            profile: IccProfileSnapshot,
            *,
            register: bool,
            associate: bool,
        ) -> IccActivationEffect:
            self.calls.append(("activate_icc_profile", display_id, profile))
            name = Path(profile.original_path).name
            if register:
                self.icc_installed_profiles.add(name)
            if associate:
                self.icc_associations.setdefault(display_id, set()).add(name)
            self.profiles[display_id] = CapturedState.captured(profile)
            return IccActivationEffect(register, associate, True)

        def deactivate_icc_profile(self, display_id: str, profile_name: str) -> None:
            self.calls.append(("deactivate_icc_profile", display_id, profile_name))
            self.icc_associations.setdefault(display_id, set()).discard(profile_name)
            current = self.profiles[display_id].value
            if current is not None and Path(current.original_path).name == profile_name:
                self.profiles[display_id] = CapturedState.captured(None)

    ports = SharedIccPorts()
    first = make_adapter(ports)
    second = make_adapter(ports)
    first_plan = make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha)
    second_plan = replace(first_plan, display_id="display-2")
    first_snapshot = capture_authorized(first, first_plan)
    first.apply(first_plan)

    blocked = run_confirmed(second, second_plan)
    try:
        assert blocked.captured is False
        assert blocked.error and "mutex" in blocked.error
        assert ports.profiles["display-2"].value is None
    finally:
        first.restore(first_snapshot)
    target_path = f"C:/Color/calibrate-pro-{profile_sha}.icc"
    assert target_path in ports.icc_files
    retried = run_confirmed(second, second_plan)
    assert retried.success is True
    assert ports.icc_files[target_path] == Path(profile_path).read_bytes()


def test_same_target_icc_restore_readback_mismatch_marks_receipt_not_restored(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "same.icc", b"same-icc")
    vcgt_path, vcgt_sha = write_asset(tmp_path, "later.cal", b"later-vcgt")
    installed_path = f"C:/Color/calibrate-pro-{profile_sha}.icc"
    prior = icc_snapshot(installed_path, Path(profile_path).read_bytes())
    wrong = icc_snapshot("C:/Color/wrong.icc", valid_icc_payload(b"wrong"))

    class SilentWrongThenTransientFailurePorts(FakeWindowsDisplayPorts):
        def __init__(self) -> None:
            super().__init__(icc_profile=CapturedState.captured(prior))
            self.icc_files[installed_path] = prior.payload
            self.gamma_calls = 0

        def activate_icc_profile(
            self,
            display_id: str,
            profile: IccProfileSnapshot,
            *,
            register: bool,
            associate: bool,
        ) -> IccActivationEffect:
            self.calls.append(("activate_icc_profile", display_id, profile))
            self.icc_profile = CapturedState.captured(wrong)
            return IccActivationEffect(register, associate, True)

        def set_gamma_ramp(self, display_id: str, ramp: GammaRamp | None) -> None:
            self.calls.append(("set_gamma_ramp", display_id, ramp))
            self.gamma_calls += 1
            if self.gamma_calls == 1:
                raise RuntimeError("transient gamma apply failure")
            self.gamma_ramp = CapturedState.captured(ramp)

    ports = SilentWrongThenTransientFailurePorts()
    adapter = make_adapter(ports, gamma_ramp_loader=lambda _: linear_ramp(1000))
    receipt = run_confirmed(
        adapter,
        make_plan(
            icc_profile_path=profile_path,
            icc_profile_sha256=profile_sha,
            vcgt_path=vcgt_path,
            vcgt_sha256=vcgt_sha,
        ),
    )
    assert receipt.success is False
    assert receipt.restored is False
    assert receipt.restore_error and "conflict" in receipt.restore_error
    assert ports.icc_profile.value == wrong
    assert [call[0] for call in ports.calls].count("capture_icc_profile") >= 2


def test_compensation_never_unregisters_or_deletes_product_icc_cache(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "cache.icc", b"cached-icc")
    vcgt_path, vcgt_sha = write_asset(tmp_path, "failure.cal", b"failure-vcgt")
    ports = FakeWindowsDisplayPorts(icc_profile=CapturedState.captured(None))
    ports.fail_gamma = True
    adapter = make_adapter(ports, gamma_ramp_loader=lambda _: linear_ramp(1000))
    receipt = run_confirmed(
        adapter,
        make_plan(
            icc_profile_path=profile_path,
            icc_profile_sha256=profile_sha,
            vcgt_path=vcgt_path,
            vcgt_sha256=vcgt_sha,
        ),
    )
    assert receipt.success is False
    target_path = f"C:/Color/calibrate-pro-{profile_sha}.icc"
    assert ports.icc_files[target_path] == Path(profile_path).read_bytes()
    assert all(call[0] != "remove_icc_profile" for call in ports.calls)


def test_later_domain_failure_restores_prior_and_retains_icc_cache_in_order(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    vcgt_path, vcgt_sha = write_asset(tmp_path, "new.cal", b"new-vcgt")
    prior = icc_snapshot("C:/Color/prior.icc", valid_icc_payload(b"prior"))
    ports = FakeWindowsDisplayPorts(icc_profile=CapturedState.captured(prior))
    ports.fail_gamma = True
    adapter = make_adapter(ports, gamma_ramp_loader=lambda _: linear_ramp(1000))
    receipt = run_confirmed(
        adapter,
        make_plan(
            icc_profile_path=profile_path,
            icc_profile_sha256=profile_sha,
            vcgt_path=vcgt_path,
            vcgt_sha256=vcgt_sha,
        ),
    )
    assert receipt.success is False
    assert ports.icc_profile.value == prior
    target_path = f"C:/Color/calibrate-pro-{profile_sha}.icc"
    assert ports.icc_files[target_path] == Path(profile_path).read_bytes()
    icc_calls = [call[0] for call in ports.calls if "icc_profile" in str(call[0])]
    assert icc_calls == [
        "is_icc_profile_installed",
        "is_icc_profile_associated",
        "capture_icc_profile",
        "materialize_icc_profile",
        "is_icc_profile_installed",
        "is_icc_profile_associated",
        "capture_icc_profile",
        "activate_icc_profile",
        "capture_icc_profile",
        "is_icc_profile_associated",
        "activate_icc_profile",
        "deactivate_icc_profile",
        "capture_icc_profile",
        "is_icc_profile_associated",
    ]


def test_preexisting_identical_content_address_is_reused_and_never_removed(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    vcgt_path, vcgt_sha = write_asset(tmp_path, "new.cal", b"new-vcgt")
    prior = icc_snapshot("C:/Color/prior.icc", valid_icc_payload(b"prior"))
    target_path = f"C:/Color/calibrate-pro-{profile_sha}.icc"
    ports = FakeWindowsDisplayPorts(icc_profile=CapturedState.captured(prior))
    ports.icc_files[target_path] = Path(profile_path).read_bytes()
    ports.fail_gamma = True
    adapter = make_adapter(ports, gamma_ramp_loader=lambda _: linear_ramp(1000))
    run_confirmed(
        adapter,
        make_plan(
            icc_profile_path=profile_path,
            icc_profile_sha256=profile_sha,
            vcgt_path=vcgt_path,
            vcgt_sha256=vcgt_sha,
        ),
    )
    assert ports.icc_files[target_path] == Path(profile_path).read_bytes()
    assert all(call[0] != "remove_icc_profile" for call in ports.calls)


def test_reused_content_address_is_registered_when_prior_installation_is_absent(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    target_name = f"calibrate-pro-{profile_sha}.icc"
    target_path = f"C:/Color/{target_name}"

    class LifecyclePorts(FakeWindowsDisplayPorts):
        def __init__(self) -> None:
            super().__init__(icc_profile=CapturedState.captured(icc_snapshot("C:/Color/prior.icc")))
            self.icc_files[target_path] = Path(profile_path).read_bytes()
            self.register_flags: list[bool] = []

        def is_icc_profile_installed(self, profile_name: str) -> bool:
            assert profile_name == target_name
            return profile_name in self.icc_installed_profiles

        def is_icc_profile_associated(self, display_id: str, profile_name: str) -> bool:
            return profile_name in self.icc_associations.setdefault(display_id, set())

        def activate_icc_profile(
            self,
            display_id: str,
            profile: IccProfileSnapshot,
            *,
            register: bool,
            associate: bool,
        ) -> IccActivationEffect:
            self.register_flags.append(register)
            return super().activate_icc_profile(
                display_id,
                profile,
                register=register,
                associate=associate,
            )

    ports = LifecyclePorts()
    receipt = run_confirmed(
        make_adapter(ports),
        make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha),
    )
    assert receipt.success is True
    assert ports.register_flags == [True]


def test_icc_lifecycle_drift_after_capture_blocks_activation_before_writer(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    target_name = f"calibrate-pro-{profile_sha}.icc"
    ports = FakeWindowsDisplayPorts(icc_profile=CapturedState.captured(None))
    adapter = make_adapter(ports)
    plan = make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha)
    snapshot = capture_authorized(adapter, plan)
    ports.icc_installed_profiles.add(target_name)
    ports.calls.clear()
    try:
        with pytest.raises(RuntimeError, match="installation|association|changed"):
            adapter.apply(plan)
        assert all(call[0] != "activate_icc_profile" for call in ports.calls)
    finally:
        adapter.restore(snapshot)


def test_compensation_never_disassociates_a_target_that_was_previously_associated(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    vcgt_path, vcgt_sha = write_asset(tmp_path, "failure.cal", b"failure-vcgt")
    target_name = f"calibrate-pro-{profile_sha}.icc"
    target_path = f"C:/Color/{target_name}"
    prior = icc_snapshot("C:/Color/prior.icc", valid_icc_payload(b"prior"))

    class PriorAssociationPorts(FakeWindowsDisplayPorts):
        def __init__(self) -> None:
            super().__init__(icc_profile=CapturedState.captured(prior))
            self.icc_files[target_path] = Path(profile_path).read_bytes()

        def is_icc_profile_installed(self, profile_name: str) -> bool:
            return True

        def is_icc_profile_associated(self, display_id: str, profile_name: str) -> bool:
            return profile_name == target_name

        def activate_icc_profile(
            self,
            display_id: str,
            profile: IccProfileSnapshot,
            *,
            register: bool,
            associate: bool,
        ) -> IccActivationEffect:
            self.calls.append(("activate_icc_profile", display_id, profile))
            if Path(profile.original_path).name == target_name:
                raise RuntimeError("activation failed before association changed")
            self.icc_profile = CapturedState.captured(profile)
            return IccActivationEffect(register, associate, True)

    ports = PriorAssociationPorts()
    receipt = run_confirmed(
        make_adapter(ports, gamma_ramp_loader=lambda _path: linear_ramp(1000)),
        make_plan(
            icc_profile_path=profile_path,
            icc_profile_sha256=profile_sha,
            vcgt_path=vcgt_path,
            vcgt_sha256=vcgt_sha,
        ),
    )
    assert receipt.success is False
    assert all(call[0] != "deactivate_icc_profile" for call in ports.calls)


def test_partial_icc_activation_compensates_only_the_proven_new_association(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    target_name = f"calibrate-pro-{profile_sha}.icc"

    class PartialActivationPorts(FakeWindowsDisplayPorts):
        def __init__(self) -> None:
            super().__init__(icc_profile=CapturedState.captured(None))

        def activate_icc_profile(
            self,
            display_id: str,
            profile: IccProfileSnapshot,
            *,
            register: bool,
            associate: bool,
        ) -> IccActivationEffect:
            self.icc_installed_profiles.add(target_name)
            self.icc_associations.setdefault(display_id, set()).add(target_name)
            raise IccActivationError(
                "default selection failed after association",
                IccActivationEffect(registered=register, associated=True, default_selected=False),
            )

    ports = PartialActivationPorts()
    receipt = run_confirmed(
        make_adapter(ports),
        make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha),
    )
    assert receipt.success is False
    assert receipt.restored is True
    assert target_name not in ports.icc_associations["display-1"]
    assert [call[0] for call in ports.calls].count("deactivate_icc_profile") == 1


def test_icc_deactivation_failure_withholds_owned_file_deletion(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "new.icc", b"new-icc")
    vcgt_path, vcgt_sha = write_asset(tmp_path, "new.cal", b"new-vcgt")

    class DeactivationFailurePorts(FakeWindowsDisplayPorts):
        def deactivate_icc_profile(self, display_id: str, profile_name: str) -> None:
            self.calls.append(("deactivate_icc_profile", display_id, profile_name))
            raise RuntimeError("deactivation failed")

    ports = DeactivationFailurePorts(icc_profile=CapturedState.captured(None))
    ports.fail_gamma = True
    adapter = make_adapter(ports, gamma_ramp_loader=lambda _: linear_ramp(1000))
    receipt = run_confirmed(
        adapter,
        make_plan(
            icc_profile_path=profile_path,
            icc_profile_sha256=profile_sha,
            vcgt_path=vcgt_path,
            vcgt_sha256=vcgt_sha,
        ),
    )
    assert receipt.restored is False
    assert receipt.restore_error and "deactivation failed" in receipt.restore_error
    assert f"C:/Color/calibrate-pro-{profile_sha}.icc" in ports.icc_files
    assert all(call[0] != "remove_icc_profile" for call in ports.calls)


def test_dwm_sdr_and_hdr_payloads_round_trip_exactly(tmp_path: Path) -> None:
    target_path, target_sha = write_asset(tmp_path, "target.cube", b"target")
    original = (
        dwm_snapshot(DwmLutKind.SDR, "old-sdr.cube", b"sdr-bytes"),
        dwm_snapshot(DwmLutKind.HDR, "old-hdr.cube", b"hdr-bytes"),
    )
    ports = FakeWindowsDisplayPorts(dwm_luts=CapturedState.captured(original))
    adapter = make_adapter(ports)
    plan = make_plan(
        dwm_lut_path=target_path,
        dwm_lut_kind=DwmLutKind.HDR,
        dwm_lut_sha256=target_sha,
    )
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    adapter.restore(snapshot)
    assert ports.dwm_luts.value == original


def test_restore_attempts_every_captured_field_and_combines_all_errors(tmp_path: Path) -> None:
    icc_path, icc_sha = write_asset(tmp_path, "target.icc", b"target")
    vcgt_path, vcgt_sha = write_asset(tmp_path, "target.cal", b"target-vcgt")
    dwm_path, dwm_sha = write_asset(tmp_path, "target.cube", b"target")
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, gamma_ramp_loader=lambda _: linear_ramp(1000))
    plan = make_plan(
        ddc_changes=(("BRIGHTNESS", 42), ("CONTRAST", 70)),
        icc_profile_path=icc_path,
        icc_profile_sha256=icc_sha,
        vcgt_path=vcgt_path,
        vcgt_sha256=vcgt_sha,
        dwm_lut_path=dwm_path,
        dwm_lut_kind=DwmLutKind.SDR,
        dwm_lut_sha256=dwm_sha,
    )
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    ports.calls.clear()
    ports.failed_ddc_codes = {"BRIGHTNESS", "CONTRAST"}
    ports.fail_icc = True
    ports.fail_gamma = True
    ports.fail_dwm = True
    with pytest.raises(RuntimeError) as error:
        adapter.restore(snapshot)
    message = str(error.value)
    assert "BRIGHTNESS restore failed" in message
    assert "CONTRAST restore failed" in message
    assert "gamma restore failed" in message
    assert "DWM restore failed" in message
    assert [call[0] for call in ports.calls] == [
        "read_ddc",
        "write_ddc",
        "read_ddc",
        "write_ddc",
        "capture_icc_profile",
        "is_icc_profile_associated",
        "activate_icc_profile",
        "capture_gamma_ramp",
        "set_gamma_ramp",
        "capture_dwm_luts",
        "set_dwm_luts",
    ]


def test_restore_skips_unrequested_domains() -> None:
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    snapshot = capture_authorized(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),)))
    ports.calls.clear()
    adapter.restore(snapshot)
    assert ports.calls == [("read_ddc", "display-1", "BRIGHTNESS")]


def test_default_ports_constructor_is_lazy() -> None:
    loaded: list[str] = []

    def load_module(name: str) -> object:
        loaded.append(name)
        raise AssertionError("constructor must not import a Windows module")

    DefaultWindowsDisplayPorts(module_loader=load_module)
    assert loaded == []


def test_default_ports_convert_ambiguous_none_reads_to_not_captured() -> None:
    installer = SimpleNamespace(
        get_default_profile_for_display=lambda display_id: None,
        get_profile_directory=lambda: Path("unused"),
    )
    detection = SimpleNamespace(
        get_gamma_ramp=lambda display_id: None,
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": installer,
            "calibrate_pro.panels.detection": detection,
        }.__getitem__,
    )
    icc = ports.capture_icc_profile("display-1")
    gamma = ports.capture_gamma_ramp("display-1")
    assert icc.status is CaptureStatus.NOT_CAPTURED
    assert gamma.status is CaptureStatus.NOT_CAPTURED
    assert icc.detail and "persistent default" in icc.detail
    assert gamma.detail and "ambiguous" in gamma.detail


def test_default_ports_capture_profile_bytes_and_gamma_values(tmp_path: Path) -> None:
    profile = tmp_path / "old.icc"
    profile.write_bytes(valid_icc_payload(b"old-icc"))
    ramp = linear_ramp()
    installer = SimpleNamespace(
        get_default_profile_for_display=lambda display_id: profile.name,
        get_profile_directory=lambda: tmp_path,
    )
    detection = SimpleNamespace(get_gamma_ramp=lambda display_id: ramp)
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": installer,
            "calibrate_pro.panels.detection": detection,
        }.__getitem__,
    )
    assert ports.capture_icc_profile("display-1") == CapturedState.captured(icc_snapshot(str(profile)))
    assert ports.capture_gamma_ramp("display-1") == CapturedState.captured(ramp)


def test_icc_capture_rejects_persistent_default_change_across_the_byte_lease(tmp_path: Path) -> None:
    old_profile = tmp_path / "old.icc"
    new_profile = tmp_path / "new.icc"
    old_profile.write_bytes(valid_icc_payload(b"old"))
    new_profile.write_bytes(valid_icc_payload(b"new"))
    defaults = iter((old_profile.name, new_profile.name))
    installer = SimpleNamespace(
        get_default_profile_for_display=lambda _display_id: next(defaults),
        get_profile_directory=lambda: tmp_path,
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.profiles.profile_installer": installer}.__getitem__,
    )
    result = ports.capture_icc_profile("display-1")
    assert result.status is CaptureStatus.NOT_CAPTURED
    assert result.detail and "persistent default" in result.detail


def test_icc_activation_rejects_persistent_default_that_changes_after_first_readback(tmp_path: Path) -> None:
    profile = icc_snapshot(str(tmp_path / "target.icc"), valid_icc_payload(b"target"))
    Path(profile.original_path).write_bytes(profile.payload)
    wrong = "wrong.icc"
    readbacks = iter((Path(profile.original_path).name, wrong, wrong))
    installer = SimpleNamespace(
        register_profile=lambda _path: (True, ""),
        associate_profile_with_display=lambda *_args, **_kwargs: (True, ""),
        set_default_profile_for_display=lambda _name, _display: (True, ""),
        get_default_profile_for_display=lambda _display: next(readbacks),
        is_profile_installed=lambda _name: True,
        is_profile_associated_with_display=lambda _name, _display: True,
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.profiles.profile_installer": installer}.__getitem__,
    )
    with pytest.raises(IccActivationError, match="default|readback|stable"):
        ports.activate_icc_profile("display-1", profile, register=True, associate=True)


def test_icc_activation_holds_exact_read_lease_through_registration_association_and_readback(tmp_path: Path) -> None:
    color_dir = tmp_path / "system-color"
    color_dir.mkdir()
    profile = icc_snapshot(str(color_dir / "target.icc"), valid_icc_payload(b"lease"))
    Path(profile.original_path).write_bytes(profile.payload)
    events: list[str] = []

    class Lease:
        open = True

        def read_bytes(self) -> bytes:
            assert self.open
            events.append("lease-read")
            return profile.payload

        def close(self) -> None:
            assert self.open
            events.append("lease-close")
            self.open = False

    lease = Lease()

    def register(path: str) -> tuple[bool, str]:
        assert lease.open
        events.append("register")
        return True, ""

    def associate(name: str, display_id: str, *, make_default: bool) -> tuple[bool, str]:
        assert lease.open
        events.append("associate")
        return True, ""

    def set_default(name: str, display_id: str) -> tuple[bool, str]:
        assert lease.open
        events.append("default")
        return True, ""

    installer = SimpleNamespace(
        register_profile=register,
        associate_profile_with_display=associate,
        set_default_profile_for_display=set_default,
        get_default_profile_for_display=lambda _display: Path(profile.original_path).name,
        is_profile_installed=lambda _name: True,
        is_profile_associated_with_display=lambda _name, _display: True,
    )
    modules = {"calibrate_pro.profiles.profile_installer": installer}
    ports = DefaultWindowsDisplayPorts(
        module_loader=modules.__getitem__,
        icc_file_lease_factory=lambda path: events.append("lease-open") or lease,
    )
    ports.activate_icc_profile("display-1", profile, register=True, associate=True)
    assert events == [
        "lease-open",
        "lease-read",
        "register",
        "associate",
        "default",
        "lease-read",
        "lease-close",
    ]


def test_default_ports_dwm_capture_fails_closed_without_loading_controller() -> None:
    loaded: list[str] = []

    def load_module(name: str) -> object:
        loaded.append(name)
        raise AssertionError("non-authoritative capture must not construct DWM controller")

    ports = DefaultWindowsDisplayPorts(module_loader=load_module)
    result = ports.capture_dwm_luts(r"\\.\DISPLAY1")
    assert result.status is CaptureStatus.NOT_CAPTURED
    assert result.detail and "authoritative" in result.detail
    assert loaded == []


def test_default_ports_materialize_content_addressed_profile_without_overwrite(tmp_path: Path) -> None:
    color_dir = tmp_path / "system-color"
    color_dir.mkdir()
    profile = icc_snapshot(str(tmp_path / "user-name.icc"), valid_icc_payload(b"new-icc"))
    installer = SimpleNamespace(get_profile_directory=lambda: color_dir)
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.profiles.profile_installer": installer}.__getitem__,
    )
    effect = ports.materialize_icc_profile(profile)
    expected_name = f"calibrate-pro-{profile.sha256}.icc"
    assert Path(effect.installed_profile.original_path).name == expected_name
    assert Path(effect.installed_profile.original_path).read_bytes() == profile.payload
    assert effect.created_file is True
    assert ports.materialize_icc_profile(profile).created_file is False
    assert not (color_dir / "user-name.icc").exists()


def test_default_ports_refuse_content_address_collision_without_overwrite(tmp_path: Path) -> None:
    color_dir = tmp_path / "system-color"
    color_dir.mkdir()
    profile = icc_snapshot(str(tmp_path / "new.icc"), valid_icc_payload(b"new-icc"))
    destination = color_dir / f"calibrate-pro-{profile.sha256}.icc"
    destination.write_bytes(b"different")
    installer = SimpleNamespace(get_profile_directory=lambda: color_dir)
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.profiles.profile_installer": installer}.__getitem__,
    )
    with pytest.raises(RuntimeError, match="content address"):
        ports.materialize_icc_profile(profile)
    assert destination.read_bytes() == b"different"


def test_default_ports_exposes_no_transactional_icc_cache_delete_path(tmp_path: Path) -> None:
    color_dir = tmp_path / "system-color"
    color_dir.mkdir()
    profile = icc_snapshot(str(tmp_path / "new.icc"), valid_icc_payload(b"new-icc"))
    installer = SimpleNamespace(get_profile_directory=lambda: color_dir)
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.profiles.profile_installer": installer}.__getitem__,
    )
    effect = ports.materialize_icc_profile(profile)
    path = Path(effect.installed_profile.original_path)
    path.write_bytes(b"changed-after-materialization")
    assert not hasattr(ports, "remove_icc_profile")
    assert path.read_bytes() == b"changed-after-materialization"


def test_uninstall_profile_disables_path_api_deletion_and_deletes_exact_handle_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from calibrate_pro.profiles import profile_installer

    color_dir = tmp_path / "system-color"
    color_dir.mkdir()
    profile = color_dir / "owned.icc"
    profile.write_bytes(valid_icc_payload(b"owned"))
    calls: list[tuple[object, ...]] = []

    class Lease:
        def mark_delete(self) -> None:
            calls.append(("mark-delete", profile))
            profile.unlink()

    lease = Lease()

    class LeaseContext:
        def __enter__(self) -> Lease:
            calls.append(("lease-enter", profile))
            return lease

        def __exit__(self, *_args: object) -> None:
            calls.append(("lease-close", profile))

    def acquire_exact_lease(path: Path) -> LeaseContext:
        calls.append(("lease-acquire", path))
        return LeaseContext()

    class Mscms:
        @staticmethod
        def UninstallColorProfileW(machine: object, path: str, delete: bool) -> bool:
            calls.append(("unregister", machine, path, delete))
            assert delete is False
            return True

    monkeypatch.setattr(profile_installer, "MSCMS_AVAILABLE", True)
    monkeypatch.setattr(profile_installer, "mscms", Mscms())
    monkeypatch.setattr(profile_installer, "get_profile_directory", lambda: color_dir)
    monkeypatch.setattr(profile_installer, "_verified_profile_delete_lease", acquire_exact_lease)
    success, message = profile_installer.uninstall_profile(profile.name)
    assert success is True, message
    assert calls == [
        ("lease-acquire", profile),
        ("lease-enter", profile),
        ("unregister", None, str(profile), False),
        ("mark-delete", profile),
        ("lease-close", profile),
    ]
    assert not profile.exists()


@pytest.mark.parametrize("failing_step", ["register", "associate", "default", "readback", "deactivate"])
def test_default_ports_icc_phase_converts_false_result_to_exception(tmp_path: Path, failing_step: str) -> None:
    color_dir = tmp_path / "system-color"
    color_dir.mkdir()
    profile = icc_snapshot(str(tmp_path / "new.icc"), valid_icc_payload(b"new-icc"))
    calls: list[tuple[object, ...]] = []

    def register(path: str) -> tuple[bool, str]:
        calls.append(("register", path))
        return failing_step != "register", "register failed"

    def associate(name: str, display_id: str, *, make_default: bool) -> tuple[bool, str]:
        calls.append(("associate", name, display_id, make_default))
        return failing_step != "associate", "associate failed"

    def disassociate(name: str, display_id: str) -> tuple[bool, str]:
        calls.append(("deactivate", name, display_id))
        return failing_step != "deactivate", "deactivate failed"

    installer = SimpleNamespace(
        get_profile_directory=lambda: color_dir,
        register_profile=register,
        associate_profile_with_display=associate,
        disassociate_profile_from_display=disassociate,
        is_profile_installed=lambda _name: True,
        is_profile_associated_with_display=lambda _name, _display: True,
    )
    detection = SimpleNamespace(
        set_display_profile=lambda *args: failing_step != "default",
        get_display_profile=lambda _display_id: (
            str(color_dir / "wrong.icc")
            if failing_step == "readback"
            else str(color_dir / f"calibrate-pro-{profile.sha256}.icc")
        ),
    )
    modules = {
        "calibrate_pro.profiles.profile_installer": installer,
        "calibrate_pro.panels.detection": detection,
    }

    class Lease:
        def __init__(self, path: str) -> None:
            self.path = path

        def validate_private_cache_identity(self, expected_path: str) -> None:
            assert Path(expected_path) == Path(self.path)

        def read_bytes(self) -> bytes:
            return Path(self.path).read_bytes()

        def close(self) -> None:
            return None

    ports = DefaultWindowsDisplayPorts(
        module_loader=modules.__getitem__,
        icc_file_lease_factory=Lease,
    )
    effect = ports.materialize_icc_profile(profile)
    with pytest.raises(RuntimeError, match="failed|readback"):
        if failing_step == "deactivate":
            ports.deactivate_icc_profile("display-1", Path(effect.installed_profile.original_path).name)
        else:
            ports.activate_icc_profile("display-1", effect.installed_profile, register=True, associate=True)
    assert Path(effect.installed_profile.original_path).exists()


@pytest.mark.parametrize("reset", [False, True])
def test_default_ports_gamma_writer_converts_false_result_to_exception(reset: bool) -> None:
    detection = SimpleNamespace(
        set_gamma_ramp=lambda *args: False,
        reset_gamma_ramp=lambda display_id: False,
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.panels.detection": detection}.__getitem__,
    )
    with pytest.raises(RuntimeError, match="gamma ramp"):
        ports.set_gamma_ramp("display-1", None if reset else linear_ramp())


def test_default_ports_maps_ddc_by_exact_display_identity_and_fails_closed() -> None:
    class VCPCode(IntEnum):
        BRIGHTNESS = 0x10

    class Controller:
        def __init__(self) -> None:
            self.monitors = [
                {"hmonitor": "logical-1", "handle": "physical-1"},
                {"hmonitor": "logical-2", "handle": "physical-2"},
            ]

        def enumerate_monitors(self) -> list[dict[str, str]]:
            return self.monitors

        def get_vcp(self, monitor: object, code: VCPCode, *, allow_wmi_fallback: bool) -> tuple[int, int]:
            assert allow_wmi_fallback is False
            return 50, 100

        def set_vcp(self, monitor: object, code: VCPCode, value: int, *, allow_wmi_fallback: bool) -> bool:
            assert allow_wmi_fallback is False
            return False

        def close(self) -> None:
            return None

    module = SimpleNamespace(DDCCIController=Controller, VCPCode=VCPCode)
    names = {"logical-1": r"\\.\DISPLAY1", "logical-2": r"\\.\DISPLAY2"}
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.hardware.ddc_ci": module}.__getitem__,
        monitor_name_resolver=names.get,
        ddc_identity_resolver=lambda display_id: f"pnp:{display_id}",
    )
    target = ports.resolve_ddc_target(r"\\.\DISPLAY1")
    assert ports.read_ddc(target, "BRIGHTNESS") == DdcReading(50, 100)
    with pytest.raises(RuntimeError, match="DDC/CI write"):
        ports.write_ddc(target, "BRIGHTNESS", 42, expected_maximum=100)
    with pytest.raises(RuntimeError, match="matched 0"):
        ports.resolve_ddc_target(r"\\.\DISPLAY3")


def test_default_ports_binds_captured_path_to_the_enumerated_physical_handle() -> None:
    class VCPCode(IntEnum):
        BRIGHTNESS = 0x10

    reads: list[str] = []

    class Controller:
        def enumerate_monitors(self) -> list[dict[str, str]]:
            return [{"hmonitor": "logical-a", "handle": "physical-b", "name": "Panel B"}]

        def get_vcp(self, monitor: dict[str, str], code: VCPCode, *, allow_wmi_fallback: bool) -> tuple[int, int]:
            reads.append(monitor["handle"])
            return 50, 100

        def close(self) -> None:
            return None

    module = SimpleNamespace(DDCCIController=Controller, VCPCode=VCPCode)
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.hardware.ddc_ci": module}.__getitem__,
        monitor_name_resolver=lambda _handle: r"\\.\DISPLAY1",
        ddc_identity_resolver=lambda _display_id: "pnp:physical-a",
        physical_monitor_identity_resolver=lambda _monitor: DdcTargetIdentity(r"\\.\DISPLAY1", "pnp:physical-b"),
    )
    with pytest.raises(RuntimeError, match="identity|physical|path|matched 0"):
        ports.resolve_ddc_target(r"\\.\DISPLAY1")
    assert reads == []


def test_default_ports_reenumerate_and_close_handles_before_each_ddc_operation() -> None:
    class VCPCode(IntEnum):
        BRIGHTNESS = 0x10

    topologies = [
        [{"hmonitor": "logical-a", "handle": "physical-a", "name": "Panel A"}],
        [
            {"hmonitor": "logical-a", "handle": "physical-a", "name": "Panel A"},
            {"hmonitor": "logical-b", "handle": "physical-b", "name": "Panel B"},
        ],
    ]
    controllers: list[Controller] = []
    set_calls: list[object] = []

    class Controller:
        def __init__(self) -> None:
            self.index = len(controllers)
            self.closed = False
            controllers.append(self)

        def enumerate_monitors(self) -> list[dict[str, str]]:
            return topologies[self.index]

        def get_vcp(self, monitor: object, code: VCPCode, *, allow_wmi_fallback: bool) -> tuple[int, int]:
            return 50, 100

        def set_vcp(self, monitor: object, code: VCPCode, value: int, *, allow_wmi_fallback: bool) -> bool:
            set_calls.append(monitor)
            return True

        def close(self) -> None:
            self.closed = True

    module = SimpleNamespace(DDCCIController=Controller, VCPCode=VCPCode)
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.hardware.ddc_ci": module}.__getitem__,
        monitor_name_resolver=lambda _handle: r"\\.\DISPLAY1",
        ddc_identity_resolver=lambda display_id: f"pnp:{display_id}",
    )
    target = ports.resolve_ddc_target(r"\\.\DISPLAY1")
    with pytest.raises(RuntimeError, match="matched 2|topology"):
        ports.write_ddc(target, "BRIGHTNESS", 42, expected_maximum=100)
    assert len(controllers) == 2
    assert all(controller.closed for controller in controllers)
    assert set_calls == []


def test_default_ports_rejects_physical_identity_drift_with_same_display_name() -> None:
    class VCPCode(IntEnum):
        BRIGHTNESS = 0x10

    identities = iter(("pnp:panel-a", "pnp:panel-a", "pnp:panel-b"))
    writes: list[int] = []

    class Controller:
        def enumerate_monitors(self) -> list[dict[str, str]]:
            return [{"hmonitor": "logical-a", "handle": "physical-a", "name": "Panel"}]

        def get_vcp(self, monitor: object, code: VCPCode, *, allow_wmi_fallback: bool) -> tuple[int, int]:
            return 50, 100

        def set_vcp(self, monitor: object, code: VCPCode, value: int, *, allow_wmi_fallback: bool) -> bool:
            writes.append(value)
            return True

        def close(self) -> None:
            return None

    module = SimpleNamespace(DDCCIController=Controller, VCPCode=VCPCode)
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.hardware.ddc_ci": module}.__getitem__,
        monitor_name_resolver=lambda _handle: r"\\.\DISPLAY1",
        ddc_identity_resolver=lambda _display_id: next(identities),
    )
    target = ports.resolve_ddc_target(r"\\.\DISPLAY1")
    with pytest.raises(RuntimeError, match="identity|topology"):
        ports.write_ddc(target, "BRIGHTNESS", 42, expected_maximum=100)
    assert writes == []


def test_default_ports_refuses_ambiguous_ddc_identity() -> None:
    class VCPCode(IntEnum):
        BRIGHTNESS = 0x10

    class Controller:
        def enumerate_monitors(self) -> list[dict[str, str]]:
            return [{"hmonitor": "a"}, {"hmonitor": "b"}]

        def close(self) -> None:
            return None

    module = SimpleNamespace(DDCCIController=Controller, VCPCode=VCPCode)
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.hardware.ddc_ci": module}.__getitem__,
        monitor_name_resolver=lambda handle: r"\\.\DISPLAY1",
        ddc_identity_resolver=lambda display_id: f"pnp:{display_id}",
    )
    with pytest.raises(RuntimeError, match="matched 2"):
        ports.resolve_ddc_target(r"\\.\DISPLAY1")


@pytest.mark.parametrize("failing_step", ["unload", "load", "start"])
def test_default_ports_dwm_writer_converts_every_false_result_to_exception(failing_step: str) -> None:
    class LUTType(Enum):
        SDR = "sdr"
        HDR = "hdr"

    class Controller:
        def __init__(self) -> None:
            self.monitor = SimpleNamespace(device_name=r"\\.\DISPLAY1", device_id="panel-1")

        def get_monitors(self) -> list[object]:
            return [self.monitor]

        def unload_lut(self, monitor: object, lut_type: LUTType) -> bool:
            return failing_step != "unload"

        def load_lut_file(self, monitor: object, path: str, lut_type: LUTType) -> bool:
            return failing_step != "load"

        def start_dwm_lut_gui(self) -> bool:
            return failing_step != "start"

    controller = Controller()
    module = SimpleNamespace(DwmLutController=lambda: controller, LUTType=LUTType)
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.lut_system.dwm_lut": module}.__getitem__,
    )
    with pytest.raises(RuntimeError, match="failed"):
        ports.set_dwm_luts(r"\\.\DISPLAY1", (dwm_snapshot(),))


def test_default_ports_capture_icc_uses_stable_wcs_default_and_exact_color_path(tmp_path: Path) -> None:
    color_dir = tmp_path / "color"
    color_dir.mkdir()
    payload = valid_icc_payload(b"active")
    active = color_dir / "active.icc"
    active.write_bytes(payload)
    default_read_lease_states: list[bool | None] = []

    class Lease:
        def __init__(self, path: str) -> None:
            self.path = path
            self.closed = False
            leases.append(self)

        def read_bytes(self) -> bytes:
            assert not self.closed
            return Path(self.path).read_bytes()

        def close(self) -> None:
            assert not self.closed
            self.closed = True

    leases: list[Lease] = []

    def get_default(_display_id: str) -> str:
        default_read_lease_states.append(None if not leases else leases[0].closed)
        return active.name

    installer = SimpleNamespace(
        get_profile_directory=lambda: color_dir,
        get_default_profile_for_display=get_default,
    )
    detection = SimpleNamespace(
        get_display_profile=lambda _display_id: (_ for _ in ()).throw(
            AssertionError("legacy DC-scoped ICC reader must not be used")
        )
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": installer,
            "calibrate_pro.panels.detection": detection,
        }.__getitem__,
        icc_file_lease_factory=Lease,
    )

    captured = ports.capture_icc_profile("display-1")

    assert captured == CapturedState.captured(IccProfileSnapshot(str(active), payload, sha256_bytes(payload)))
    assert default_read_lease_states == [None, False, True]
    assert len(leases) == 1 and leases[0].closed is True


def test_default_ports_activation_uses_persistent_wcs_default_setter(tmp_path: Path) -> None:
    payload = valid_icc_payload(b"target")
    target = tmp_path / "target.icc"
    target.write_bytes(payload)
    state = {"default": "prior.icc"}
    setter_calls: list[tuple[str, str]] = []

    class Lease:
        def __init__(self, path: str) -> None:
            self.path = path

        def read_bytes(self) -> bytes:
            return Path(self.path).read_bytes()

        def close(self) -> None:
            return None

    def set_default(profile_name: str, display_id: str) -> tuple[bool, str]:
        setter_calls.append((profile_name, display_id))
        state["default"] = profile_name
        return True, "selected"

    installer = SimpleNamespace(
        is_profile_installed=lambda _name: True,
        is_profile_associated_with_display=lambda _name, _display: True,
        get_default_profile_for_display=lambda _display: state["default"],
        set_default_profile_for_display=set_default,
    )
    detection = SimpleNamespace(
        set_display_profile=lambda *_args: (_ for _ in ()).throw(
            AssertionError("temporary-DC ICC setter must not be used")
        ),
        get_display_profile=lambda _display: str(tmp_path / state["default"]),
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": installer,
            "calibrate_pro.panels.detection": detection,
        }.__getitem__,
        icc_file_lease_factory=Lease,
    )
    profile = IccProfileSnapshot(str(target), payload, sha256_bytes(payload))

    effect = ports.activate_icc_profile("display-1", profile, register=False, associate=False)

    assert effect == IccActivationEffect(False, False, True)
    assert setter_calls == [(target.name, "display-1")]
    assert state["default"] == target.name


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("cancelled"), SystemExit(17)])
@pytest.mark.parametrize("failing_step", ["register", "associate", "default"])
def test_default_ports_reconcile_completed_icc_effect_after_cancellation(
    tmp_path: Path,
    interruption: BaseException,
    failing_step: str,
) -> None:
    payload = valid_icc_payload(failing_step.encode())
    target = tmp_path / "target.icc"
    target.write_bytes(payload)
    state = {
        "installed": False,
        "associated": False,
        "default": "prior.icc",
    }
    lease_closed = False

    class Lease:
        def __init__(self, path: str) -> None:
            self.path = path

        def read_bytes(self) -> bytes:
            return Path(self.path).read_bytes()

        def close(self) -> None:
            nonlocal lease_closed
            lease_closed = True

    def register(_path: str) -> tuple[bool, str]:
        state["installed"] = True
        if failing_step == "register":
            raise interruption
        return True, "registered"

    def associate(_name: str, _display: str, *, make_default: bool) -> tuple[bool, str]:
        assert make_default is False
        state["associated"] = True
        if failing_step == "associate":
            raise interruption
        return True, "associated"

    def set_default(profile_name: str, _display: str) -> tuple[bool, str]:
        state["default"] = profile_name
        if failing_step == "default":
            raise interruption
        return True, "selected"

    def legacy_set(_display: str, path: str) -> bool:
        state["default"] = Path(path).name
        if failing_step == "default":
            raise interruption
        return True

    installer = SimpleNamespace(
        register_profile=register,
        associate_profile_with_display=associate,
        is_profile_installed=lambda _name: state["installed"],
        is_profile_associated_with_display=lambda _name, _display: state["associated"],
        get_default_profile_for_display=lambda _display: state["default"],
        set_default_profile_for_display=set_default,
    )
    detection = SimpleNamespace(
        set_display_profile=legacy_set,
        get_display_profile=lambda _display: str(tmp_path / state["default"]),
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": installer,
            "calibrate_pro.panels.detection": detection,
        }.__getitem__,
        icc_file_lease_factory=Lease,
    )
    profile = IccProfileSnapshot(str(target), payload, sha256_bytes(payload))

    with pytest.raises(type(interruption)) as caught:
        ports.activate_icc_profile(
            "display-1",
            profile,
            register=True,
            associate=True,
        )

    assert caught.value is interruption
    effect = getattr(caught.value, "icc_activation_effect", None)
    assert isinstance(effect, IccActivationEffect)
    assert effect.registered is True
    assert effect.associated is (failing_step != "register")
    assert effect.default_selected is (failing_step == "default")
    assert lease_closed is True


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("capture cancelled"), SystemExit(18)])
def test_default_ports_capture_icc_closes_lease_on_cancellation(
    tmp_path: Path,
    interruption: BaseException,
) -> None:
    color_dir = tmp_path / "color"
    color_dir.mkdir()
    active = color_dir / "active.icc"
    active.write_bytes(valid_icc_payload())
    close_calls = 0

    class Lease:
        def __init__(self, _path: str) -> None:
            return None

        def read_bytes(self) -> bytes:
            raise interruption

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    installer = SimpleNamespace(
        get_profile_directory=lambda: color_dir,
        get_default_profile_for_display=lambda _display: active.name,
    )
    detection = SimpleNamespace(get_display_profile=lambda _display: str(active))
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": installer,
            "calibrate_pro.panels.detection": detection,
        }.__getitem__,
        icc_file_lease_factory=Lease,
    )

    with pytest.raises(type(interruption)) as caught:
        ports.capture_icc_profile("display-1")

    assert caught.value is interruption
    assert close_calls == 1


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("seal cancelled"), SystemExit(31)])
@pytest.mark.parametrize("sealing_step", ["deepcopy", "digest"])
def test_capture_sealing_cancellation_releases_transaction_mutex_and_state(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    sealing_step: str,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.acquired: list[object] = []
            self.released: list[object] = []

        def acquire(self, display_id: str) -> object:
            handle = (display_id, len(self.acquired))
            self.acquired.append(handle)
            return handle

        def release(self, handle: object) -> None:
            self.released.append(handle)

    mutex = TrackingMutex()
    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=mutex)
    plan = make_plan()
    original_deepcopy = windows_state.copy.deepcopy
    original_digest = windows_state._snapshot_sha256

    if sealing_step == "deepcopy":

        def interrupt_snapshot_deepcopy(value: object) -> object:
            if isinstance(value, DisplayStateSnapshot):
                raise interruption
            return original_deepcopy(value)

        monkeypatch.setattr(windows_state.copy, "deepcopy", interrupt_snapshot_deepcopy)
    else:

        def interrupt_snapshot_digest(value: DisplayStateSnapshot) -> str:
            raise interruption

        monkeypatch.setattr(windows_state, "_snapshot_sha256", interrupt_snapshot_digest)

    with pytest.raises(type(interruption)) as caught:
        capture_authorized(adapter, plan)

    assert caught.value is interruption
    assert mutex.released == list(reversed(mutex.acquired))
    assert adapter._active is None
    assert adapter._phase is None
    monkeypatch.setattr(windows_state.copy, "deepcopy", original_deepcopy)
    monkeypatch.setattr(windows_state, "_snapshot_sha256", original_digest)
    snapshot = capture_authorized(adapter, plan)
    adapter.restore(snapshot)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("publish cancelled"), SystemExit(32)])
@pytest.mark.parametrize("publication", ["applied", "verified"])
def test_phase_publication_cancellation_leaves_transaction_compensatable(
    interruption: BaseException,
    publication: str,
) -> None:
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    snapshot = capture_authorized(adapter, plan)
    original_finish = adapter._finish_phase
    target = (
        windows_state._TransactionPhase.APPLIED
        if publication == "applied"
        else windows_state._TransactionPhase.VERIFIED
    )

    def interrupt_target_phase(phase: windows_state._TransactionPhase) -> None:
        if phase is target:
            raise interruption
        original_finish(phase)

    adapter._finish_phase = interrupt_target_phase  # type: ignore[method-assign]
    if publication == "applied":
        with pytest.raises(type(interruption)) as caught:
            adapter.apply(plan)
    else:
        adapter.apply(plan)
        with pytest.raises(type(interruption)) as caught:
            adapter.verify(plan)

    assert caught.value is interruption
    assert adapter._phase is windows_state._TransactionPhase.UNCERTAIN
    adapter.restore(snapshot)
    assert ports.ddc_values["BRIGHTNESS"] == 50
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("commit finalization cancelled"), SystemExit(33)])
def test_commit_cancellation_after_mutex_release_clears_finished_transaction(
    interruption: BaseException,
) -> None:
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    plan = make_plan()
    capture_authorized(adapter, plan)
    adapter.apply(plan)
    assert adapter.verify(plan) is True
    original_release = adapter._release_transaction_mutex

    def release_then_interrupt(active: object) -> None:
        original_release(active)  # type: ignore[arg-type]
        raise interruption

    adapter._release_transaction_mutex = release_then_interrupt  # type: ignore[method-assign]
    with pytest.raises(type(interruption)) as caught:
        adapter.commit(plan)

    assert caught.value is interruption
    assert adapter._active is None
    assert adapter._phase is None


def test_icc_default_drift_aborts_before_target_activation_and_preserves_new_default(tmp_path: Path) -> None:
    prior = icc_snapshot("A.icc", valid_icc_payload(b"A"))
    concurrent = icc_snapshot("B.icc", valid_icc_payload(b"B"))

    class DriftAfterCaptureAdapter(WindowsDisplayStateAdapter):
        def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
            snapshot = super().capture(plan, authorization=authorization)
            ports.icc_profile = CapturedState.captured(concurrent)
            return snapshot

    ports = FakeWindowsDisplayPorts(icc_profile=CapturedState.captured(prior))
    adapter = DriftAfterCaptureAdapter(ports, transaction_mutex=InProcessDisplayTransactionMutex())
    profile_path, profile_sha = write_asset(tmp_path, "target.icc", b"target")
    receipt = run_confirmed(
        adapter,
        make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha),
    )

    assert receipt.success is False
    assert receipt.error and "changed after capture" in receipt.error
    assert ports.icc_profile == CapturedState.captured(concurrent)
    assert not any(call[0] == "activate_icc_profile" for call in ports.calls)
    assert adapter._active is not None
    assert adapter._active.mutex_handles
    assert adapter._phase is windows_state._TransactionPhase.UNCERTAIN


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("loader failed"), KeyboardInterrupt("loader cancelled"), SystemExit(34)],
)
def test_icc_activation_closes_lease_when_module_loading_fails(
    tmp_path: Path,
    failure: BaseException,
) -> None:
    payload = valid_icc_payload(b"target")
    target = tmp_path / "target.icc"
    target.write_bytes(payload)
    close_calls = 0

    class Lease:
        def __init__(self, _path: str) -> None:
            return None

        def read_bytes(self) -> bytes:
            return payload

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    ports = DefaultWindowsDisplayPorts(
        module_loader=lambda _name: (_ for _ in ()).throw(failure),
        icc_file_lease_factory=Lease,
    )
    profile = IccProfileSnapshot(str(target), payload, sha256_bytes(payload))

    with pytest.raises(type(failure)):
        ports.activate_icc_profile("display-1", profile, register=False, associate=False)

    assert close_calls == 1


def test_materialize_rejects_preexisting_hardlinked_cache_entry(tmp_path: Path) -> None:
    color_dir = tmp_path / "system-color"
    color_dir.mkdir()
    payload = valid_icc_payload(b"hardlink")
    profile = IccProfileSnapshot("source.icc", payload, sha256_bytes(payload))
    external = tmp_path / "external-user-file.icc"
    external.write_bytes(payload)
    destination = color_dir / f"calibrate-pro-{profile.sha256}.icc"
    try:
        destination.hardlink_to(external)
    except OSError as exc:
        pytest.skip(f"hardlinks unavailable: {exc}")
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": SimpleNamespace(get_profile_directory=lambda: color_dir)
        }.__getitem__,
    )

    with pytest.raises(RuntimeError, match="private|link|identity|cache"):
        ports.materialize_icc_profile(profile)

    assert external.read_bytes() == payload
    external.write_bytes(valid_icc_payload(b"external-mutated"))
    assert destination.read_bytes() == external.read_bytes()


def test_materialize_rejects_preexisting_symlink_cache_entry(tmp_path: Path) -> None:
    color_dir = tmp_path / "system-color"
    color_dir.mkdir()
    payload = valid_icc_payload(b"symlink")
    profile = IccProfileSnapshot("source.icc", payload, sha256_bytes(payload))
    external = tmp_path / "external-user-file.icc"
    external.write_bytes(payload)
    destination = color_dir / f"calibrate-pro-{profile.sha256}.icc"
    try:
        destination.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": SimpleNamespace(get_profile_directory=lambda: color_dir)
        }.__getitem__,
    )

    with pytest.raises(RuntimeError, match="reparse|private|identity|cache"):
        ports.materialize_icc_profile(profile)

    assert external.read_bytes() == payload


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("write cancelled"), SystemExit(19)])
def test_default_ports_materialize_removes_partial_file_after_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    color_dir = tmp_path / "color"
    color_dir.mkdir()
    payload = valid_icc_payload(b"target")
    profile = IccProfileSnapshot("source.icc", payload, sha256_bytes(payload))
    destination = color_dir / f"calibrate-pro-{profile.sha256}.icc"
    installer = SimpleNamespace(get_profile_directory=lambda: color_dir)
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.profiles.profile_installer": installer}.__getitem__
    )
    original_temporary_file = windows_state.tempfile.NamedTemporaryFile

    class InterruptingWriter:
        def __init__(self, stream: object) -> None:
            self.stream = stream

        def __enter__(self) -> InterruptingWriter:
            return self

        def __exit__(self, *_args: object) -> None:
            self.stream.close()  # type: ignore[attr-defined]

        @property
        def name(self) -> str:
            return str(self.stream.name)  # type: ignore[attr-defined]

        def write(self, value: bytes) -> int:
            self.stream.write(value[:3])  # type: ignore[attr-defined]
            self.stream.flush()  # type: ignore[attr-defined]
            raise interruption

        def flush(self) -> None:
            self.stream.flush()  # type: ignore[attr-defined]

        def fileno(self) -> int:
            return self.stream.fileno()  # type: ignore[no-any-return, attr-defined]

    def interrupting_temporary_file(*args: object, **kwargs: object) -> object:
        return InterruptingWriter(original_temporary_file(*args, **kwargs))

    with monkeypatch.context() as context:
        context.setattr(windows_state.tempfile, "NamedTemporaryFile", interrupting_temporary_file)
        with pytest.raises(type(interruption)) as caught:
            ports.materialize_icc_profile(profile)
        assert caught.value is interruption

    assert not destination.exists()
    effect = ports.materialize_icc_profile(profile)
    assert effect.created_file is True
    assert destination.read_bytes() == payload


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("wait cancelled"), SystemExit(20)])
def test_windows_named_mutex_cleans_and_poisons_uncertain_acquire(interruption: BaseException) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    releases: list[object] = []
    closes: list[object] = []
    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: (_ for _ in ()).throw(interruption)),
        ReleaseMutex=Function(lambda handle: releases.append(handle) or True),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = f"uncertain-acquire-{type(interruption).__name__}"
    key = display_id.casefold()
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire(display_id)
        assert caught.value is interruption
        assert releases == [123]
        assert closes == [123]
        with pytest.raises(RuntimeError, match="poison|manual recovery"):
            mutex.acquire(display_id)
    finally:
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(key)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("acquire cancelled"), SystemExit(22)])
def test_production_mutex_releases_process_lock_after_cancelled_windows_acquire(
    interruption: BaseException,
) -> None:
    class CancellingWindowsMutex:
        def acquire(self, _display_id: str) -> object:
            raise interruption

        def release(self, _handle: object) -> None:
            raise AssertionError("no Windows handle was returned")

    display_id = f"production-acquire-{type(interruption).__name__}"
    key = display_id.casefold()
    mutex = ProductionDisplayTransactionMutex()
    mutex._windows = CancellingWindowsMutex()  # type: ignore[assignment]
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire(display_id)
        assert caught.value is interruption
        process_lock = InProcessDisplayTransactionMutex._locks[key]
        assert process_lock.locked() is False
    finally:
        process_lock = InProcessDisplayTransactionMutex._locks.get(key)
        if process_lock is not None and process_lock.locked():
            process_lock.release()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("release cancelled"), SystemExit(23)])
def test_production_mutex_attempts_process_release_after_windows_cancellation(
    interruption: BaseException,
) -> None:
    calls: list[str] = []

    class WindowsMutex:
        def release(self, _handle: object) -> None:
            calls.append("windows")
            raise interruption

    class ProcessMutex:
        def release(self, _handle: object) -> None:
            calls.append("process")

    mutex = ProductionDisplayTransactionMutex()
    mutex._windows = WindowsMutex()  # type: ignore[assignment]
    mutex._process = ProcessMutex()  # type: ignore[assignment]
    lease = windows_state._ProductionMutexLease("process-handle", "windows-handle")

    with pytest.raises(type(interruption)) as caught:
        mutex.release(lease)

    assert caught.value is interruption
    assert calls == ["windows", "process"]
    assert lease.poisoned is True


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("display release cancelled"), SystemExit(24)])
def test_adapter_release_attempts_every_mutex_lease_after_cancellation(interruption: BaseException) -> None:
    calls: list[object] = []

    class Mutex:
        def acquire(self, display_id: str) -> object:
            return display_id

        def release(self, handle: object) -> None:
            calls.append(handle)
            if handle == "display":
                raise interruption

    adapter = WindowsDisplayStateAdapter(object(), transaction_mutex=Mutex())  # type: ignore[arg-type]
    active = SimpleNamespace(mutex_handles=["icc", "display"], lease_poisoned=False)

    with pytest.raises(type(interruption)) as caught:
        adapter._release_transaction_mutex(active)  # type: ignore[arg-type]

    assert caught.value is interruption
    assert calls == ["display", "icc"]
    assert active.mutex_handles == ["display"]
    assert active.lease_poisoned is True


@pytest.mark.parametrize("domain", ["icc", "dwm"])
def test_snapshot_digest_hashes_actual_file_payload_bytes(domain: str) -> None:
    if domain == "icc":
        payload = valid_icc_payload(b"A")
        value: object = IccProfileSnapshot("prior.icc", payload, sha256_bytes(payload))
        snapshot = DisplayStateSnapshot("display-1", (), CapturedState.captured(value), None, None)  # type: ignore[arg-type]
    else:
        payload = valid_cube_payload("A")
        value = DwmLutSnapshot(DwmLutKind.SDR, "prior.cube", payload, sha256_bytes(payload))
        snapshot = DisplayStateSnapshot("display-1", (), None, None, CapturedState.captured((value,)))  # type: ignore[arg-type]
    before = windows_state._snapshot_sha256(snapshot)
    replacement = bytes([payload[0] ^ 1]) + payload[1:]
    assert len(replacement) == len(payload)
    object.__setattr__(value, "payload", replacement)

    assert windows_state._snapshot_sha256(snapshot) != before


def test_restore_uses_authoritative_state_when_icc_effect_reconciliation_is_uncertain(tmp_path: Path) -> None:
    prior = icc_snapshot("prior.icc", valid_icc_payload(b"prior"))

    class UncertainEffectPorts(FakeWindowsDisplayPorts):
        def __init__(self) -> None:
            super().__init__(icc_profile=CapturedState.captured(prior))
            self.failed_target_activation = False

        def activate_icc_profile(
            self,
            display_id: str,
            profile: IccProfileSnapshot,
            *,
            register: bool,
            associate: bool,
        ) -> IccActivationEffect:
            name = Path(profile.original_path).name
            if name.startswith("calibrate-pro-") and not self.failed_target_activation:
                self.failed_target_activation = True
                self.calls.append(("activate_icc_profile", display_id, profile))
                self.icc_installed_profiles.add(name)
                self.icc_associations.setdefault(display_id, set()).add(name)
                self.icc_profile = CapturedState.captured(profile)
                raise IccActivationError("effect reconciliation unavailable", IccActivationEffect())
            return super().activate_icc_profile(
                display_id,
                profile,
                register=register,
                associate=associate,
            )

    ports = UncertainEffectPorts()
    profile_path, profile_sha = write_asset(tmp_path, "target.icc", b"target")
    plan = make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha)

    receipt = run_confirmed(make_adapter(ports), plan)

    target_name = f"calibrate-pro-{profile_sha}.icc"
    assert receipt.success is False
    assert receipt.restore_attempted is True
    assert receipt.restored is True
    assert ports.icc_profile.value == prior
    assert target_name not in ports.icc_associations["display-1"]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("handoff cancelled"), SystemExit(25)])
def test_capture_authorization_is_not_stranded_when_handoff_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    adapter = make_adapter(FakeWindowsDisplayPorts())
    coordinator = coordinator_for(adapter)
    plan = make_plan()
    first_token = coordinator.preview(plan)

    def interrupt_handoff(*_args: object, **_kwargs: object) -> ApplyReceipt:
        raise interruption

    with monkeypatch.context() as context:
        context.setattr(actuation_module, "_apply_confirmed_with_best_effort_recovery", interrupt_handoff)
        with pytest.raises(type(interruption)) as caught:
            coordinator.apply(plan, first_token, confirmed=True)
        assert caught.value is interruption

    second_token = coordinator.preview(plan)
    receipt = coordinator.apply(plan, second_token, confirmed=True)
    assert receipt.success is True


def test_stale_capture_authorization_cannot_consume_its_safe_supersession() -> None:
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports)
    coordinator = coordinator_for(adapter)
    plan = make_plan()
    issuer = coordinator._capture_authorization_issuer
    assert issuer is not None
    stale = issuer(plan)
    current = issuer(plan)

    with pytest.raises(PermissionError, match="one-use|authorization"):
        adapter.capture(plan, authorization=stale)
    snapshot = adapter.capture(plan, authorization=current)
    adapter.restore(snapshot)
    assert ports.calls == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("release cancelled"), SystemExit(21)])
def test_windows_named_mutex_retains_handle_and_poisons_after_uncertain_release(interruption: BaseException) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []
    release_failure = {"enabled": False}

    def release(_handle: object) -> bool:
        if release_failure["enabled"]:
            raise interruption
        return True

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(release),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = f"uncertain-release-{type(interruption).__name__}"
    key = display_id.casefold()
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    handle = mutex.acquire(display_id)
    release_failure["enabled"] = True
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.release(handle)
        assert caught.value is interruption
        assert closes == []
        assert handle.native_handle == 123  # type: ignore[attr-defined]
        assert handle.poisoned is True  # type: ignore[attr-defined]
        with pytest.raises(RuntimeError, match="poison|manual recovery"):
            mutex.acquire(display_id)
    finally:
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(key)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("close cancelled"), SystemExit(26)])
def test_windows_named_mutex_poisons_when_busy_handle_close_is_cancelled(interruption: BaseException) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0x102),
        ReleaseMutex=Function(lambda _handle: (_ for _ in ()).throw(AssertionError("busy mutex is not owned"))),
        CloseHandle=Function(lambda _handle: (_ for _ in ()).throw(interruption)),
    )
    display_id = f"busy-close-{type(interruption).__name__}"
    key = display_id.casefold()
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire(display_id)
        assert caught.value is interruption
        with pytest.raises(RuntimeError, match="poison|manual recovery"):
            mutex.acquire(display_id)
    finally:
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(key)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("plan seal cancelled"), SystemExit(41)])
def test_capture_plan_digest_cancellation_clears_phase_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    adapter = make_adapter(FakeWindowsDisplayPorts())
    plan = make_plan()
    original = windows_state._canonical_plan_sha256

    with monkeypatch.context() as context:
        context.setattr(windows_state, "_canonical_plan_sha256", lambda _plan: (_ for _ in ()).throw(interruption))
        with pytest.raises(type(interruption)) as caught:
            capture_authorized(adapter, plan)
        assert caught.value is interruption

    assert adapter._active is None
    assert adapter._phase is None
    monkeypatch.setattr(windows_state, "_canonical_plan_sha256", original)
    snapshot = capture_authorized(adapter, plan)
    adapter.restore(snapshot)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("claim cancelled"), SystemExit(42)])
@pytest.mark.parametrize("operation", ["apply", "verify", "commit"])
def test_post_claim_cancellation_is_uncertain_and_recoverable(
    interruption: BaseException,
    operation: str,
) -> None:
    class Mutex:
        def acquire(self, display_id: str) -> object:
            return display_id

        def release(self, _handle: object) -> None:
            return None

    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=Mutex())
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 42),))
    snapshot = capture_authorized(adapter, plan)
    if operation in {"verify", "commit"}:
        adapter.apply(plan)
    if operation == "commit":
        assert adapter.verify(plan) is True
    original_claim = adapter._claim_phase

    def claim_then_interrupt(*args: object, **kwargs: object) -> object:
        original_claim(*args, **kwargs)
        raise interruption

    adapter._claim_phase = claim_then_interrupt  # type: ignore[method-assign]
    with pytest.raises(type(interruption)) as caught:
        getattr(adapter, operation)(plan)

    assert caught.value is interruption
    assert adapter._phase is windows_state._TransactionPhase.UNCERTAIN
    adapter.restore(snapshot)
    assert ports.ddc_values["BRIGHTNESS"] == 50
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("restore publication cancelled"), SystemExit(43)])
def test_restore_publication_cancellation_releases_once_and_preserves_control_flow(
    interruption: BaseException,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.releases: list[object] = []

        def acquire(self, display_id: str) -> object:
            return display_id

        def release(self, handle: object) -> None:
            self.releases.append(handle)

    class InterruptingLock:
        def __init__(self, adapter: WindowsDisplayStateAdapter) -> None:
            self._lock = threading.Lock()
            self._adapter = adapter
            self.armed = True

        def __enter__(self) -> InterruptingLock:
            self._lock.acquire()
            return self

        def __exit__(self, *_args: object) -> None:
            self._lock.release()
            if self.armed and self._adapter._phase is windows_state._TransactionPhase.RESTORING:
                self.armed = False
                raise interruption

    mutex = TrackingMutex()
    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=mutex)
    snapshot = capture_authorized(adapter, make_plan())
    adapter._state_lock = InterruptingLock(adapter)  # type: ignore[assignment]

    with pytest.raises(type(interruption)) as caught:
        adapter.restore(snapshot)

    assert caught.value is interruption
    assert len(mutex.releases) == 1
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("tamper cleanup cancelled"), SystemExit(44)])
def test_tampered_restore_cleanup_preserves_control_flow_and_does_not_double_release(
    interruption: BaseException,
) -> None:
    class InterruptAfterReleaseMutex:
        def __init__(self) -> None:
            self.releases = 0

        def acquire(self, _display_id: str) -> object:
            return object()

        def release(self, _handle: object) -> None:
            self.releases += 1
            raise interruption

    mutex = InterruptAfterReleaseMutex()
    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=mutex)
    snapshot = capture_authorized(adapter, make_plan())
    object.__setattr__(snapshot, "display_id", "tampered")

    with pytest.raises(type(interruption)) as caught:
        adapter.restore(snapshot)

    assert caught.value is interruption
    assert mutex.releases == 1
    assert adapter._phase is windows_state._TransactionPhase.POISONED


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("identity drift"), SystemExit(45)])
def test_private_cache_entry_closes_once_when_post_read_identity_check_fails(
    tmp_path: Path,
    interruption: BaseException,
) -> None:
    destination = tmp_path / "cache.icc"
    payload = valid_icc_payload(b"cache")
    destination.write_bytes(payload)
    validations = 0
    closes = 0

    class Lease:
        def __init__(self, _path: str) -> None:
            return None

        def validate_private_cache_identity(self, _path: str) -> None:
            nonlocal validations
            validations += 1
            if validations == 2:
                raise interruption

        def read_bytes(self) -> bytes:
            return payload

        def close(self) -> None:
            nonlocal closes
            closes += 1

    ports = DefaultWindowsDisplayPorts(icc_file_lease_factory=Lease)
    with pytest.raises(type(interruption)) as caught:
        ports._read_private_cache_entry(destination)

    assert caught.value is interruption
    assert validations == 2
    assert closes == 1


@pytest.mark.parametrize("failure_check", [2, 4])
def test_product_cache_activation_checks_identity_around_read_and_activation(
    tmp_path: Path,
    failure_check: int,
) -> None:
    payload = valid_icc_payload(b"activation-race")
    digest = sha256_bytes(payload)
    target = tmp_path / f"calibrate-pro-{digest}.icc"
    target.write_bytes(payload)
    validations = 0
    closes = 0
    writers: list[str] = []

    class Lease:
        def __init__(self, _path: str) -> None:
            return None

        def validate_private_cache_identity(self, _path: str) -> None:
            nonlocal validations
            validations += 1
            if validations == failure_check:
                raise RuntimeError("cache identity drifted")

        def read_bytes(self) -> bytes:
            return payload

        def close(self) -> None:
            nonlocal closes
            closes += 1

    installer = SimpleNamespace(
        register_profile=lambda _path: writers.append("register") or (True, ""),
        is_profile_installed=lambda _name: True,
        associate_profile_with_display=lambda *_args, **_kwargs: writers.append("associate") or (True, ""),
        is_profile_associated_with_display=lambda *_args: True,
        set_default_profile_for_display=lambda *_args: writers.append("default") or (True, ""),
        get_default_profile_for_display=lambda _display: target.name,
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.profiles.profile_installer": installer}.__getitem__,
        icc_file_lease_factory=Lease,
    )
    profile = IccProfileSnapshot(str(target), payload, digest)

    with pytest.raises(IccActivationError, match="identity drifted"):
        ports.activate_icc_profile("display-1", profile, register=True, associate=True)

    assert validations == failure_check
    assert closes == 1
    if failure_check == 2:
        assert writers == []
    else:
        assert writers == ["register", "associate", "default"]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("create publication"), SystemExit(46)])
def test_windows_icc_lease_closes_created_handle_when_publication_is_interrupted(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    class Handle:
        def __bool__(self) -> bool:
            raise interruption

    handle = Handle()
    closes: list[object] = []
    inert = Function(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=Function(lambda *_args: handle),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=Function(lambda *_args: 1),
        GetFinalPathNameByHandleW=Function(lambda *_args: 1),
        CloseHandle=Function(lambda value: closes.append(value) or True),
    )

    with pytest.raises(type(interruption)) as caught:
        windows_state._WindowsIccFileLease("cache.icc", kernel32_loader=lambda: kernel32)

    assert caught.value is interruption
    assert closes == [handle]


@REQUIRES_OPCODE_MONITORING
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("CreateFileW result handoff"), SystemExit(100)])
def test_windows_icc_lease_closes_handle_when_createfile_result_handoff_is_interrupted(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []
    inert = Function(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=Function(lambda *_args: 123),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=Function(lambda *_args: 1),
        GetFinalPathNameByHandleW=Function(lambda *_args: 1),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    function = windows_state._WindowsIccFileLease.__init__
    source, first_line = inspect.getsourcelines(function)
    call_line = first_line + next(
        index for index, line in enumerate(source) if "handle =" in line and "CreateFileW" in line
    )
    instructions = list(dis.get_instructions(function))
    call_index = next(
        index
        for index, instruction in enumerate(instructions)
        if instruction.positions.lineno == call_line and instruction.opname == "CALL"
    )
    post_call_target = instructions[call_index + 1].offset

    _interrupt_at_opcode(function, post_call_target, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            windows_state._WindowsIccFileLease("cache.icc", kernel32_loader=lambda: kernel32)
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert closes == [123]


@REQUIRES_OPCODE_MONITORING
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("ICC factory result handoff"), SystemExit(101)])
def test_icc_factory_result_handoff_cancellation_closes_exact_lease_and_reuses_capacity(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    close_calls = 0

    class Lease:
        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    lease = Lease()
    retained: dict[int, object] = {}
    claims: dict[int, int] = {}
    reservations: dict[int, object] = {}
    reverse: dict[int, int] = {}
    monkeypatch.setattr(windows_state, "_RETAINED_ICC_LEASES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_ICC_LEASE_CLAIMS", claims)
    monkeypatch.setattr(windows_state, "_ICC_LEASE_RESERVATIONS", reservations)
    monkeypatch.setattr(windows_state, "_ICC_LEASE_RESERVATION_BY_ID", reverse)
    monkeypatch.setattr(windows_state, "_MAX_RETAINED_ICC_LEASES", 1)
    ports = DefaultWindowsDisplayPorts(icc_file_lease_factory=lambda _path: lease)  # type: ignore[arg-type]
    function = DefaultWindowsDisplayPorts._open_icc_file_lease
    source, first_line = inspect.getsourcelines(function)
    call_line = first_line + next(
        index for index, line in enumerate(source) if "lease =" in line and "icc_file_lease_factory" in line
    )
    instructions = list(dis.get_instructions(function))
    call_index = next(
        index
        for index, instruction in enumerate(instructions)
        if instruction.positions.lineno == call_line and instruction.opname == "CALL"
    )
    post_call_target = instructions[call_index + 1].offset

    _interrupt_at_opcode(function, post_call_target, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            ports._open_icc_file_lease("cache.icc")
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert close_calls == 1
    assert retained == {}
    assert claims == {}
    assert reservations == {}
    assert reverse == {}
    assert windows_state._drain_retained_icc_leases(limit=1) == 0
    reusable_token = windows_state._reserve_icc_lease_capacity()
    windows_state._retire_pending_icc_lease_reservation(reusable_token)
    assert reservations == {}


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("close completed"), SystemExit(47)])
def test_windows_icc_lease_never_double_closes_after_uncertain_success_boundary(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []

    def close_after_native_success(handle: object) -> bool:
        closes.append(handle)
        raise interruption

    inert = Function(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=Function(lambda *_args: 123),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=Function(lambda *_args: 1),
        GetFinalPathNameByHandleW=Function(lambda *_args: 1),
        CloseHandle=Function(close_after_native_success),
    )
    lease = windows_state._WindowsIccFileLease("cache.icc", kernel32_loader=lambda: kernel32)

    with pytest.raises(type(interruption)) as caught:
        lease.close()
    second_failure: BaseException | None = None
    try:
        lease.close()
    except BaseException as exc:
        second_failure = exc

    assert caught.value is interruption
    assert isinstance(second_failure, RuntimeError)
    assert "poison" in str(second_failure)
    assert closes == [123]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("enter cancelled"), SystemExit(48)])
def test_materialize_removes_exclusive_zero_byte_file_when_context_entry_is_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    color_dir = tmp_path / "color"
    color_dir.mkdir()
    payload = valid_icc_payload(b"target")
    profile = IccProfileSnapshot("source.icc", payload, sha256_bytes(payload))
    destination = color_dir / f"calibrate-pro-{profile.sha256}.icc"
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": SimpleNamespace(get_profile_directory=lambda: color_dir)
        }.__getitem__
    )
    original_temporary_file = windows_state.tempfile.NamedTemporaryFile

    class EntryInterrupt:
        def __init__(self, stream: object) -> None:
            self.stream = stream

        def __enter__(self) -> object:
            self.stream.close()  # type: ignore[attr-defined]
            raise interruption

        def __exit__(self, *_args: object) -> None:
            self.stream.close()  # type: ignore[attr-defined]

        @property
        def name(self) -> str:
            return str(self.stream.name)  # type: ignore[attr-defined]

    def open_then_interrupt(*args: object, **kwargs: object) -> object:
        return EntryInterrupt(original_temporary_file(*args, **kwargs))

    with monkeypatch.context() as context:
        context.setattr(windows_state.tempfile, "NamedTemporaryFile", open_then_interrupt)
        with pytest.raises(type(interruption)) as caught:
            ports.materialize_icc_profile(profile)
        assert caught.value is interruption

    assert not destination.exists()
    assert list(color_dir.glob(".calibrate-pro-icc-stage-*.tmp")) == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("link published"), SystemExit(51)])
def test_materialize_never_leaves_zero_byte_poison_at_exclusive_publish_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    color_dir = tmp_path / "color"
    color_dir.mkdir()
    payload = valid_icc_payload(b"complete-before-publish")
    profile = IccProfileSnapshot("source.icc", payload, sha256_bytes(payload))
    destination = color_dir / f"calibrate-pro-{profile.sha256}.icc"
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": SimpleNamespace(get_profile_directory=lambda: color_dir)
        }.__getitem__
    )
    original_link = os.link

    def publish_then_interrupt(source: object, target: object, *args: object, **kwargs: object) -> None:
        original_link(source, target, *args, **kwargs)
        raise interruption

    with monkeypatch.context() as context:
        context.setattr(os, "link", publish_then_interrupt)
        with pytest.raises(type(interruption)) as caught:
            ports.materialize_icc_profile(profile)
        assert caught.value is interruption

    if destination.exists():
        assert destination.read_bytes() == payload
    effect = ports.materialize_icc_profile(profile)
    assert effect.installed_profile.payload == payload
    assert destination.read_bytes() == payload


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("stage path handoff"), SystemExit(60)])
def test_materialize_cleans_stage_when_path_publication_is_interrupted(
    tmp_path: Path,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    color_dir = tmp_path / "color"
    color_dir.mkdir()
    payload = valid_icc_payload(b"stage-path-handoff")
    profile = IccProfileSnapshot("source.icc", payload, sha256_bytes(payload))
    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": SimpleNamespace(get_profile_directory=lambda: color_dir)
        }.__getitem__
    )
    source, first_line = inspect.getsourcelines(DefaultWindowsDisplayPorts.materialize_icc_profile)
    target_line = first_line + next(
        index for index, line in enumerate(source) if "stage_path = Path(stage_stream.name)" in line
    )

    def interrupt_path_publication(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is DefaultWindowsDisplayPorts.materialize_icc_profile.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_path_publication

    sys.settrace(interrupt_path_publication)
    try:
        with pytest.raises(type(interruption)) as caught:
            ports.materialize_icc_profile(profile)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert list(color_dir.glob(".calibrate-pro-icc-stage-*.tmp")) == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("DDC cancelled"), SystemExit(49)])
@pytest.mark.parametrize("operation", ["enumerate", "read", "write"])
def test_default_ports_ddc_preserves_primary_control_flow_when_close_fails(
    interruption: BaseException,
    operation: str,
) -> None:
    close_calls = 0

    class Controller:
        def enumerate_monitors(self) -> list[dict[str, object]]:
            if operation == "enumerate":
                raise interruption
            return [{"hmonitor": 1}]

        def get_vcp(self, *_args: object, **_kwargs: object) -> tuple[int, int]:
            raise interruption

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1
            raise RuntimeError("close failed")

    module = SimpleNamespace(DDCCIController=Controller, VCPCode={"BRIGHTNESS": 0x10})
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.hardware.ddc_ci": module}.__getitem__,
        ddc_identity_resolver=lambda _display: "pnp-1",
        physical_monitor_identity_resolver=lambda _monitor: DdcTargetIdentity("display-1", "pnp-1"),
    )
    target = DdcTargetIdentity("display-1", "pnp-1")

    with pytest.raises(type(interruption)) as caught:
        if operation == "enumerate":
            ports.resolve_ddc_target("display-1")
        elif operation == "read":
            ports.read_ddc(target, "BRIGHTNESS")
        else:
            ports.write_ddc(target, "BRIGHTNESS", 42, expected_maximum=100)

    assert caught.value is interruption
    assert close_calls == 1
    assert_exception_note_if_supported(caught.value, "close failed")


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("return cancelled"), SystemExit(50)])
@pytest.mark.parametrize("mutex_kind", ["in_process", "windows", "production"])
def test_mutex_acquire_return_boundary_releases_every_owned_resource(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    mutex_kind: str,
) -> None:
    display_id = f"return-boundary-{mutex_kind}-{type(interruption).__name__}"
    releases: list[object] = []
    closes: list[object] = []
    if mutex_kind == "in_process":
        mutex: object = InProcessDisplayTransactionMutex()
    elif mutex_kind == "windows":

        class Function:
            def __init__(self, callback: object) -> None:
                self.callback = callback

            def __call__(self, *args: object) -> object:
                return self.callback(*args)  # type: ignore[operator]

        kernel32 = SimpleNamespace(
            CreateMutexW=Function(lambda *_args: 123),
            WaitForSingleObject=Function(lambda *_args: 0),
            ReleaseMutex=Function(lambda handle: releases.append(handle) or True),
            CloseHandle=Function(lambda handle: closes.append(handle) or True),
        )
        mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    else:

        class ChildMutex:
            def __init__(self, name: str) -> None:
                self.name = name

            def acquire(self, _display_id: str) -> object:
                return self.name

            def release(self, handle: object) -> None:
                releases.append(handle)

        production = ProductionDisplayTransactionMutex()
        production._process = ChildMutex("process")  # type: ignore[assignment]
        production._windows = ChildMutex("windows")  # type: ignore[assignment]
        mutex = production

    with monkeypatch.context() as context:
        context.setattr(windows_state, "_publish_mutex_lease", lambda _lease: (_ for _ in ()).throw(interruption))
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire(display_id)  # type: ignore[attr-defined]

    assert caught.value is interruption
    if mutex_kind == "in_process":
        assert InProcessDisplayTransactionMutex._locks[display_id.casefold()].locked() is False
    elif mutex_kind == "windows":
        assert releases == [123]
        assert closes == [123]
    else:
        assert releases == ["windows", "process"]


@pytest.mark.parametrize("current_state", ["prior", "target", "third"])
@pytest.mark.parametrize("domain", ["ddc", "gamma", "dwm"])
def test_restore_compares_current_state_before_compensating_non_icc_domains(
    tmp_path: Path,
    domain: str,
    current_state: str,
) -> None:
    ports = FakeWindowsDisplayPorts()
    changes: dict[str, object]
    if domain == "ddc":
        changes = {"ddc_changes": (("BRIGHTNESS", 42),)}
        adapter = make_adapter(ports)
    elif domain == "gamma":
        path, digest = write_asset(tmp_path, "target.cal", b"gamma")
        changes = {"vcgt_path": path, "vcgt_sha256": digest}
        adapter = make_adapter(ports, gamma_ramp_loader=lambda _path: linear_ramp(1000))
    else:
        path, digest = write_asset(tmp_path, "target.cube", valid_cube_payload("target"))
        changes = {"dwm_lut_path": path, "dwm_lut_kind": DwmLutKind.SDR, "dwm_lut_sha256": digest}
        adapter = make_adapter(ports)
    plan = make_plan(**changes)
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    if domain == "ddc":
        if current_state == "prior":
            ports.ddc_values["BRIGHTNESS"] = 50
        elif current_state == "third":
            ports.ddc_values["BRIGHTNESS"] = 88
    elif domain == "gamma":
        if current_state == "prior":
            ports.gamma_ramp = CapturedState.captured(linear_ramp())
        elif current_state == "third":
            ports.gamma_ramp = CapturedState.captured(linear_ramp(2000))
    else:
        if current_state == "prior":
            ports.dwm_luts = CapturedState.captured((dwm_snapshot(),))
        elif current_state == "third":
            ports.dwm_luts = CapturedState.captured((dwm_snapshot(payload=valid_cube_payload("third")),))
    ports.calls.clear()

    if current_state == "third":
        with pytest.raises(RuntimeError, match="conflict|changed|concurrent"):
            adapter.restore(snapshot)
    else:
        adapter.restore(snapshot)

    writer_name = {"ddc": "write_ddc", "gamma": "set_gamma_ramp", "dwm": "set_dwm_luts"}[domain]
    writes = [call for call in ports.calls if call[0] == writer_name]
    reader_name = {"ddc": "read_ddc", "gamma": "capture_gamma_ramp", "dwm": "capture_dwm_luts"}[domain]
    reads = [call for call in ports.calls if call[0] == reader_name]
    if current_state == "prior":
        assert writes == []
        assert len(reads) == 1
    elif current_state == "target":
        assert len(writes) == 1
        assert len(reads) == 2
    else:
        assert writes == []
        assert len(reads) == 1


@pytest.mark.parametrize("current_state", ["prior", "target", "third"])
def test_restore_compares_complete_icc_state_before_compensating(
    tmp_path: Path,
    current_state: str,
) -> None:
    prior = icc_snapshot("prior.icc", valid_icc_payload(b"prior"))
    concurrent = icc_snapshot("concurrent.icc", valid_icc_payload(b"concurrent"))
    ports = FakeWindowsDisplayPorts(icc_profile=CapturedState.captured(prior))
    profile_path, profile_sha = write_asset(tmp_path, "target.icc", b"target")
    plan = make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha)
    adapter = make_adapter(ports)
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    target_name = f"calibrate-pro-{profile_sha}.icc"
    if current_state == "prior":
        ports.icc_profile = CapturedState.captured(prior)
        ports.icc_associations["display-1"].discard(target_name)
    elif current_state == "third":
        ports.icc_profile = CapturedState.captured(concurrent)
    ports.calls.clear()

    if current_state == "third":
        with pytest.raises(RuntimeError, match="conflict|changed|concurrent"):
            adapter.restore(snapshot)
    else:
        adapter.restore(snapshot)

    writers = [call for call in ports.calls if call[0] in {"activate_icc_profile", "deactivate_icc_profile"}]
    captures = [call for call in ports.calls if call[0] == "capture_icc_profile"]
    if current_state == "prior":
        assert writers == []
        assert len(captures) == 1
    elif current_state == "target":
        assert len(writers) == 2
        assert len(captures) == 2
    else:
        assert writers == []
        assert len(captures) == 1


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("before native close"), SystemExit(52)])
def test_windows_icc_lease_retains_handle_if_interrupted_before_native_close(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []
    inert = Function(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=Function(lambda *_args: 123),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=Function(lambda *_args: 1),
        GetFinalPathNameByHandleW=Function(lambda *_args: 1),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    lease = windows_state._WindowsIccFileLease("cache.icc", kernel32_loader=lambda: kernel32)
    source, first_line = inspect.getsourcelines(windows_state._WindowsIccFileLease.close)
    target_line = first_line + next(index for index, line in enumerate(source) if "CloseHandle(handle)" in line)

    def interrupt_before_close(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is windows_state._WindowsIccFileLease.close.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_before_close

    sys.settrace(interrupt_before_close)
    try:
        with pytest.raises(type(interruption)) as caught:
            lease.close()
    finally:
        sys.settrace(None)
    lease.close()

    assert caught.value is interruption
    assert closes == [123]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("final publication"), SystemExit(53)])
def test_restore_retries_final_state_publication_after_mutex_release(
    interruption: BaseException,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.releases: list[object] = []

        def acquire(self, display_id: str) -> object:
            return display_id

        def release(self, handle: object) -> None:
            self.releases.append(handle)

    class InterruptOnFinalEnter:
        def __init__(self, adapter: WindowsDisplayStateAdapter, mutex: TrackingMutex) -> None:
            self._lock = threading.Lock()
            self._adapter = adapter
            self._mutex = mutex
            self._armed = True

        def __enter__(self) -> InterruptOnFinalEnter:
            if (
                self._armed
                and self._mutex.releases
                and self._adapter._phase is windows_state._TransactionPhase.RESTORING
            ):
                self._armed = False
                raise interruption
            self._lock.acquire()
            return self

        def __exit__(self, *_args: object) -> None:
            self._lock.release()

    mutex = TrackingMutex()
    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=mutex)
    snapshot = capture_authorized(adapter, make_plan())
    adapter._state_lock = InterruptOnFinalEnter(adapter, mutex)  # type: ignore[assignment]

    with pytest.raises(type(interruption)) as caught:
        adapter.restore(snapshot)

    assert caught.value is interruption
    assert len(mutex.releases) == 1
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("capture cleanup publication"), SystemExit(54)])
def test_capture_retries_final_state_publication_after_mutex_cleanup(
    interruption: BaseException,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.releases: list[object] = []

        def acquire(self, display_id: str) -> object:
            return display_id

        def release(self, handle: object) -> None:
            self.releases.append(handle)

    class FailingPorts(FakeWindowsDisplayPorts):
        def resolve_ddc_target(self, display_id: str) -> DdcTargetIdentity:
            raise RuntimeError(f"capture failed for {display_id}")

    class InterruptOnCleanupEnter:
        def __init__(self, adapter: WindowsDisplayStateAdapter, mutex: TrackingMutex) -> None:
            self._lock = threading.Lock()
            self._adapter = adapter
            self._mutex = mutex
            self._armed = True

        def __enter__(self) -> InterruptOnCleanupEnter:
            if (
                self._armed
                and self._mutex.releases
                and self._adapter._phase is windows_state._TransactionPhase.CAPTURING
            ):
                self._armed = False
                raise interruption
            self._lock.acquire()
            return self

        def __exit__(self, *_args: object) -> None:
            self._lock.release()

    mutex = TrackingMutex()
    adapter = make_adapter(FailingPorts(), transaction_mutex=mutex)
    adapter._state_lock = InterruptOnCleanupEnter(adapter, mutex)  # type: ignore[assignment]

    with pytest.raises(type(interruption)) as caught:
        capture_authorized(adapter, make_plan(ddc_changes=(("BRIGHTNESS", 42),)))

    assert caught.value is interruption
    assert len(mutex.releases) == 1
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("named handoff"), SystemExit(55)])
@pytest.mark.parametrize("handoff", ["create", "wait"])
def test_windows_named_mutex_cleans_native_handle_after_owner_callback_failure(
    interruption: BaseException,
    handoff: str,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    releases: list[object] = []
    closes: list[object] = []

    def create(*_args: object) -> int:
        if handoff == "create":
            raise interruption
        return 123

    def wait(*_args: object) -> int:
        if handoff == "wait":
            raise interruption
        return 0

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(create),
        WaitForSingleObject=Function(wait),
        ReleaseMutex=Function(lambda handle: releases.append(handle) or True),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)

    with pytest.raises(type(interruption)) as caught:
        mutex.acquire(f"named-{handoff}-{type(interruption).__name__}")

    assert caught.value is interruption
    assert closes == ([] if handoff == "create" else [123])
    assert releases == ([] if handoff == "create" else [123])


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("process handoff"), SystemExit(56)])
def test_production_mutex_cleans_process_lock_at_first_post_acquire_line(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    releases: list[str] = []

    class ChildMutex:
        def __init__(self, name: str) -> None:
            self.name = name

        def acquire(self, _display_id: str) -> object:
            return self.name

        def release(self, handle: object) -> None:
            releases.append(str(handle))

    mutex = ProductionDisplayTransactionMutex()
    mutex._process = ChildMutex("process")  # type: ignore[assignment]
    mutex._windows = ChildMutex("windows")  # type: ignore[assignment]
    source, first_line = inspect.getsourcelines(ProductionDisplayTransactionMutex.acquire)
    acquire_index = next(index for index, line in enumerate(source) if "process_sink.acquire" in line)
    target_index = next(
        index
        for index in range(acquire_index + 1, len(source))
        if source[index].strip() and source[index].strip() != "try:"
    )
    target_line = first_line + target_index

    def interrupt_handoff(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is ProductionDisplayTransactionMutex.acquire.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_handoff

    sys.settrace(interrupt_handoff)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire("production-handoff")
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert releases == ["process"]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("pre-native close"), SystemExit(57)])
def test_windows_icc_lease_keeps_handle_retryable_when_lookup_is_interrupted_before_native_close(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []
    inert = Function(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=Function(lambda *_args: 123),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=Function(lambda *_args: 1),
        GetFinalPathNameByHandleW=Function(lambda *_args: 1),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )

    class InterruptingLookupLease(windows_state._WindowsIccFileLease):
        armed = True

        def __getattribute__(self, name: str) -> object:
            if name == "_kernel32" and object.__getattribute__(self, "armed"):
                object.__setattr__(self, "armed", False)
                raise interruption
            return object.__getattribute__(self, name)

    lease = InterruptingLookupLease("cache.icc", kernel32_loader=lambda: kernel32)
    with pytest.raises(type(interruption)) as caught:
        lease.close()
    lease.close()

    assert caught.value is interruption
    assert closes == [123]


def test_windows_icc_lease_false_close_remains_explicitly_retryable() -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []
    results = iter((False, True))
    inert = Function(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=Function(lambda *_args: 123),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=Function(lambda *_args: 1),
        GetFinalPathNameByHandleW=Function(lambda *_args: 1),
        CloseHandle=Function(lambda handle: closes.append(handle) or next(results)),
    )
    lease = windows_state._WindowsIccFileLease("cache.icc", kernel32_loader=lambda: kernel32)

    with pytest.raises(RuntimeError, match="retry|close"):
        lease.close()
    assert lease._handle == 123
    lease.close()

    assert lease._handle is None
    assert closes == [123, 123]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("cleanup handoff"), SystemExit(58)])
@pytest.mark.parametrize("operation", ["capture", "cache_read", "activate"])
def test_icc_lease_cleanup_handoff_still_closes_exactly_once(
    tmp_path: Path,
    interruption: BaseException,
    operation: str,
    unmeasured_tracing: None,
) -> None:
    payload = valid_icc_payload(b"cleanup-handoff")
    closes = 0

    class Lease:
        def __init__(self, _path: str) -> None:
            return None

        def validate_private_cache_identity(self, _path: str) -> None:
            if operation == "cache_read":
                raise RuntimeError("primary cache read failure")

        def read_bytes(self) -> bytes:
            if operation == "capture":
                raise RuntimeError("primary capture failure")
            return payload

        def close(self) -> None:
            nonlocal closes
            closes += 1

    lease = Lease("unused")
    installer = SimpleNamespace(
        get_profile_directory=lambda: tmp_path,
        get_default_profile_for_display=lambda _display: "prior.icc",
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader=(
            (lambda _name: (_ for _ in ()).throw(RuntimeError("primary activation failure")))
            if operation == "activate"
            else {"calibrate_pro.profiles.profile_installer": installer}.__getitem__
        ),
        icc_file_lease_factory=lambda _path: lease,
    )

    cleanup_helper = getattr(windows_state, "_close_icc_lease_once", None)
    if cleanup_helper is None:
        function = {
            "capture": DefaultWindowsDisplayPorts.capture_icc_profile,
            "cache_read": DefaultWindowsDisplayPorts._read_private_cache_entry,
            "activate": DefaultWindowsDisplayPorts.activate_icc_profile,
        }[operation]
        source, first_line = inspect.getsourcelines(function)
        marker = "reconciliation_failures = reconcile_effect()" if operation == "activate" else "if lease is not None:"
        target_line = first_line + next(index for index, line in enumerate(source) if marker in line)
    else:
        function = cleanup_helper
        source, first_line = inspect.getsourcelines(function)
        target_line = first_line + next(index for index, line in enumerate(source) if "_invoke_icc_lease_close" in line)

    def interrupt_cleanup(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is function.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_cleanup

    sys.settrace(interrupt_cleanup)
    try:
        with pytest.raises(type(interruption)) as caught:
            if operation == "capture":
                ports.capture_icc_profile("display-1")
            elif operation == "cache_read":
                ports._read_private_cache_entry(tmp_path / "cache.icc")
            else:
                profile = IccProfileSnapshot(str(tmp_path / "target.icc"), payload, sha256_bytes(payload))
                ports.activate_icc_profile("display-1", profile, register=False, associate=False)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert closes == 1


def test_activation_treats_windows_case_variants_as_product_cache_targets(tmp_path: Path) -> None:
    payload = valid_icc_payload(b"casefold-cache")
    digest = sha256_bytes(payload)
    target_name = f"CALIBRATE-PRO-{digest}.ICC"
    writers: list[str] = []
    validations = 0

    class Lease:
        def __init__(self, _path: str) -> None:
            return None

        def validate_private_cache_identity(self, _path: str) -> None:
            nonlocal validations
            validations += 1
            raise RuntimeError("case-variant cache identity rejected")

        def read_bytes(self) -> bytes:
            return payload

        def close(self) -> None:
            return None

    installer = SimpleNamespace(
        register_profile=lambda _path: writers.append("register") or (True, ""),
        is_profile_installed=lambda _name: True,
        associate_profile_with_display=lambda *_args, **_kwargs: writers.append("associate") or (True, ""),
        is_profile_associated_with_display=lambda *_args: True,
        set_default_profile_for_display=lambda *_args: writers.append("default") or (True, ""),
        get_default_profile_for_display=lambda _display: target_name,
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.profiles.profile_installer": installer}.__getitem__,
        icc_file_lease_factory=Lease,
    )
    profile = IccProfileSnapshot(str(tmp_path / target_name), payload, digest)

    with pytest.raises(IccActivationError, match="case-variant cache identity rejected"):
        ports.activate_icc_profile("display-1", profile, register=True, associate=True)

    assert validations == 1
    assert writers == []


def test_apply_fails_before_selection_when_prior_default_was_absent_but_target_association_preexisted(
    tmp_path: Path,
) -> None:
    payload = valid_icc_payload(b"preassociated-target")
    profile_path = tmp_path / "target.icc"
    profile_path.write_bytes(payload)
    digest = sha256_bytes(payload)
    target_name = f"calibrate-pro-{digest}.icc"
    ports = FakeWindowsDisplayPorts(icc_profile=CapturedState.captured(None))
    ports.icc_installed_profiles.add(target_name)
    ports.icc_associations["display-1"].add(target_name)
    adapter = make_adapter(ports)
    plan = make_plan(icc_profile_path=str(profile_path), icc_profile_sha256=digest)
    snapshot = capture_authorized(adapter, plan)

    with pytest.raises(RuntimeError, match="absent|cannot|conflict|uncompensat"):
        adapter.apply(plan)
    adapter.restore(snapshot)

    assert not any(call[0] == "activate_icc_profile" for call in ports.calls)
    assert target_name in ports.icc_associations["display-1"]
    assert ports.icc_profile.value is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("post-acquire"), SystemExit(59)])
def test_in_process_mutex_releases_lock_when_first_post_acquire_handoff_is_interrupted(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    display_id = f"post-acquire-{type(interruption).__name__}"
    key = display_id.casefold()
    mutex = InProcessDisplayTransactionMutex()
    source, first_line = inspect.getsourcelines(InProcessDisplayTransactionMutex.acquire)
    acquire_index = next(index for index, line in enumerate(source) if "lock.acquire" in line)
    if "acquired =" in source[acquire_index]:
        target_index = next(index for index in range(acquire_index + 1, len(source)) if source[index].strip())
    else:
        target_index = next(index for index in range(acquire_index + 1, len(source)) if source[index].strip() == "try:")
    target_line = first_line + target_index

    def interrupt_handoff(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is InProcessDisplayTransactionMutex.acquire.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_handoff

    sys.settrace(interrupt_handoff)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire(display_id)
    finally:
        sys.settrace(None)
    lock = InProcessDisplayTransactionMutex._locks[key]
    try:
        assert caught.value is interruption
        assert lock.locked() is False
    finally:
        if lock.locked():
            lock.release()


def test_in_process_mutex_never_releases_a_busy_lock_owned_by_another_lease() -> None:
    display_id = "busy-owned-elsewhere"
    mutex = InProcessDisplayTransactionMutex()
    first = mutex.acquire(display_id)
    try:
        with pytest.raises(RuntimeError, match="already held"):
            mutex.acquire(display_id)
        assert first.locked() is True  # type: ignore[attr-defined]
    finally:
        mutex.release(first)


class _RoundSevenTestMutex:
    def __init__(self) -> None:
        self.releases = 0

    def acquire(self, _display_id: str) -> object:
        return object()

    def release(self, _handle: object) -> None:
        self.releases += 1


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("capture gap"), SystemExit(60)])
def test_capture_phase_publication_is_inside_cleanup_guard(
    interruption: BaseException, unmeasured_tracing: None
) -> None:
    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=_RoundSevenTestMutex())
    plan = make_plan()
    coordinator = coordinator_for(adapter)
    issuer = coordinator._capture_authorization_issuer
    assert issuer is not None
    source, first_line = inspect.getsourcelines(WindowsDisplayStateAdapter.capture)
    phase_index = next(index for index, line in enumerate(source) if "_TransactionPhase.CAPTURING" in line)
    target_line = first_line + next(index for index in range(phase_index + 1, len(source)) if source[index].strip())

    def interrupt_after_phase(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is WindowsDisplayStateAdapter.capture.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_after_phase

    sys.settrace(interrupt_after_phase)
    try:
        with pytest.raises(type(interruption)) as caught:
            adapter.capture(plan, authorization=issuer(plan))
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("schedule gap"), SystemExit(61)])
def test_restore_retries_after_boundary_cancellation_and_attempts_remaining_domains(
    tmp_path: Path,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    vcgt_path, vcgt_sha = write_asset(tmp_path, "target.cal", b"target")
    lut_path, lut_sha = write_asset(tmp_path, "target.cube", b"target")
    prior_gamma = linear_ramp()
    prior_luts = (dwm_snapshot(),)
    ports = FakeWindowsDisplayPorts(
        gamma_ramp=CapturedState.captured(prior_gamma),
        dwm_luts=CapturedState.captured(prior_luts),
    )
    adapter = make_adapter(
        ports,
        gamma_ramp_loader=lambda _path: linear_ramp(1000),
        transaction_mutex=_RoundSevenTestMutex(),
    )
    plan = make_plan(
        ddc_changes=(("BRIGHTNESS", 60),),
        vcgt_path=vcgt_path,
        vcgt_sha256=vcgt_sha,
        dwm_lut_path=lut_path,
        dwm_lut_kind=DwmLutKind.HDR,
        dwm_lut_sha256=lut_sha,
    )
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    schedule = WindowsDisplayStateAdapter._run_restore_compensation_schedule
    source, first_line = inspect.getsourcelines(schedule)
    target_line = first_line + next(
        index for index, line in enumerate(source) if "if sealed.gamma_ramp is not None" in line
    )

    def interrupt_between_domains(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_lineno", None) == target_line
            and getattr(frame, "f_code", None) is schedule.__code__
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_between_domains

    sys.settrace(interrupt_between_domains)
    try:
        with pytest.raises(type(interruption)) as caught:
            adapter.restore(snapshot)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert ports.ddc_values["BRIGHTNESS"] == 50
    assert ports.gamma_ramp == CapturedState.captured(prior_gamma)
    assert ports.dwm_luts == CapturedState.captured(prior_luts)
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("ownership gap"), SystemExit(62)])
def test_restore_retries_cleanup_ownership_publication_before_compensation(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.releases = 0

        def acquire(self, _display_id: str) -> object:
            return object()

        def release(self, _handle: object) -> None:
            self.releases += 1

    mutex = TrackingMutex()
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=mutex)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 60),))
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    source, first_line = inspect.getsourcelines(WindowsDisplayStateAdapter.restore)
    publication_index = next(index for index, line in enumerate(source) if "cleanup_owned = True" in line)
    handle_check_index = next(index for index, line in enumerate(source) if "not active.mutex_handles" in line)
    assert all(line.strip() != "try:" for line in source[handle_check_index + 1 : publication_index + 1])
    target_line = first_line + publication_index

    def interrupt_publication(frame: object, event: str, _arg: object) -> object:
        if event == "line" and getattr(frame, "f_lineno", None) == target_line:
            sys.settrace(None)
            raise interruption
        return interrupt_publication

    sys.settrace(interrupt_publication)
    try:
        with pytest.raises(type(interruption)) as caught:
            adapter.restore(snapshot)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert ports.ddc_values["BRIGHTNESS"] == 50
    assert mutex.releases == 1
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("lease dispatch"), SystemExit(63)])
def test_icc_close_dispatch_retries_before_close_is_entered(
    interruption: BaseException, unmeasured_tracing: None
) -> None:
    closes = 0

    class Lease:
        def close(self) -> None:
            nonlocal closes
            closes += 1

    source, first_line = inspect.getsourcelines(windows_state._invoke_icc_lease_close)
    target_line = first_line + next(index for index, line in enumerate(source) if "lease.close()" in line)

    def interrupt_dispatch(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is windows_state._invoke_icc_lease_close.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_dispatch

    sys.settrace(interrupt_dispatch)
    try:
        failure = windows_state._close_icc_lease_once(Lease())  # type: ignore[arg-type]
    finally:
        sys.settrace(None)

    assert failure is interruption
    assert closes == 1


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("native dispatch"), SystemExit(64)])
def test_windows_icc_close_remains_retryable_before_native_entry(
    interruption: BaseException, unmeasured_tracing: None
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []
    inert = Function(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=Function(lambda *_args: 123),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=Function(lambda *_args: 1),
        GetFinalPathNameByHandleW=Function(lambda *_args: 1),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    lease = windows_state._WindowsIccFileLease("cache.icc", kernel32_loader=lambda: kernel32)
    source, first_line = inspect.getsourcelines(windows_state._invoke_windows_handle_close)
    target_line = first_line + next(index for index, line in enumerate(source) if "close_handle(handle)" in line)

    def interrupt_dispatch(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is windows_state._invoke_windows_handle_close.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_dispatch

    sys.settrace(interrupt_dispatch)
    try:
        with pytest.raises(type(interruption)) as caught:
            lease.close()
    finally:
        sys.settrace(None)
    lease.close()

    assert caught.value is interruption
    assert closes == [123]


@pytest.mark.parametrize("membership", ["installed", "associated"])
def test_verify_requires_target_icc_installation_and_association_membership(
    tmp_path: Path,
    membership: str,
) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "target.icc", b"target")
    target_name = f"calibrate-pro-{profile_sha}.icc"
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=_RoundSevenTestMutex())
    plan = make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha)
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    if membership == "installed":
        ports.icc_installed_profiles.discard(target_name)
    else:
        ports.icc_associations["display-1"].discard(target_name)

    matches = adapter.verify(plan)
    try:
        assert matches is False
    finally:
        adapter.restore(snapshot)


def test_apply_refuses_absent_prior_default_with_preexisting_target_association(tmp_path: Path) -> None:
    profile_path, profile_sha = write_asset(tmp_path, "target.icc", b"target")
    target_name = f"calibrate-pro-{profile_sha}.icc"
    ports = FakeWindowsDisplayPorts(icc_profile=CapturedState.captured(None))
    ports.icc_installed_profiles.add(target_name)
    ports.icc_associations["display-1"].add(target_name)
    adapter = make_adapter(ports, transaction_mutex=_RoundSevenTestMutex())
    receipt = run_confirmed(
        adapter,
        make_plan(icc_profile_path=profile_path, icc_profile_sha256=profile_sha),
    )

    assert receipt.success is False
    assert receipt.error and "absent" in receipt.error
    assert receipt.restored is True
    assert ports.icc_profile == CapturedState.captured(None)
    assert not any(call[0] == "activate_icc_profile" for call in ports.calls)


def test_materialize_retains_complete_cache_entry_after_post_publication_failure(tmp_path: Path) -> None:
    color_dir = tmp_path / "color"
    color_dir.mkdir()
    payload = valid_icc_payload(b"durable")
    profile = IccProfileSnapshot("source.icc", payload, sha256_bytes(payload))
    destination = color_dir / f"calibrate-pro-{profile.sha256}.icc"

    class FailingLease:
        def __init__(self, _path: str) -> None:
            raise RuntimeError("post-publication validation failed")

    ports = DefaultWindowsDisplayPorts(
        module_loader={
            "calibrate_pro.profiles.profile_installer": SimpleNamespace(get_profile_directory=lambda: color_dir)
        }.__getitem__,
        icc_file_lease_factory=FailingLease,  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError, match="post-publication|materialization"):
        ports.materialize_icc_profile(profile)

    assert destination.read_bytes() == payload


@pytest.mark.parametrize("domain", ["gamma", "dwm"])
def test_apply_revalidates_software_state_immediately_before_write(tmp_path: Path, domain: str) -> None:
    ports = FakeWindowsDisplayPorts()
    if domain == "gamma":
        asset_path, asset_sha = write_asset(tmp_path, "target.cal", b"target")
        adapter = make_adapter(
            ports,
            gamma_ramp_loader=lambda _path: linear_ramp(1000),
            transaction_mutex=_RoundSevenTestMutex(),
        )
        plan = make_plan(vcgt_path=asset_path, vcgt_sha256=asset_sha)
    else:
        asset_path, asset_sha = write_asset(tmp_path, "target.cube", b"target")
        adapter = make_adapter(ports, transaction_mutex=_RoundSevenTestMutex())
        plan = make_plan(
            dwm_lut_path=asset_path,
            dwm_lut_kind=DwmLutKind.HDR,
            dwm_lut_sha256=asset_sha,
        )
    snapshot = capture_authorized(adapter, plan)
    if domain == "gamma":
        concurrent = linear_ramp(2000)
        ports.gamma_ramp = CapturedState.captured(concurrent)
    else:
        concurrent_luts = (dwm_snapshot(DwmLutKind.HDR, "concurrent.cube", valid_cube_payload("concurrent")),)
        ports.dwm_luts = CapturedState.captured(concurrent_luts)

    with pytest.raises(RuntimeError, match="changed after capture"):
        adapter.apply(plan)
    with pytest.raises(RuntimeError, match="concurrent"):
        adapter.restore(snapshot)

    if domain == "gamma":
        assert ports.gamma_ramp == CapturedState.captured(concurrent)
    else:
        assert ports.dwm_luts == CapturedState.captured(concurrent_luts)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("adapter release"), SystemExit(65)])
def test_adapter_retains_mutex_lease_when_release_is_interrupted(interruption: BaseException) -> None:
    handle = object()

    class FailingMutex:
        def release(self, actual: object) -> None:
            assert actual is handle
            raise interruption

    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=FailingMutex())
    handles = [handle]

    with pytest.raises(type(interruption)) as caught:
        adapter._release_mutex_handles(handles)

    assert caught.value is interruption
    assert handles == [handle]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("named publication"), SystemExit(66)])
def test_named_mutex_terminal_callback_exception_is_honest_after_native_close(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    releases: list[object] = []
    closes: list[object] = []
    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(lambda handle: releases.append(handle) or True),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = f"named-release-publication-{type(interruption).__name__}"
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    lease = mutex.acquire(display_id)
    owner = lease.owner  # type: ignore[attr-defined]
    assert owner is not None
    owner._on_terminal = lambda _owner: (_ for _ in ()).throw(interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.release(lease)
    finally:
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_id.casefold())

    assert caught.value is interruption
    assert releases == [123]
    assert closes == [123]
    assert lease.native_handle is None  # type: ignore[attr-defined]
    assert lease.poisoned is False  # type: ignore[attr-defined]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("composite publication"), SystemExit(67)])
def test_composite_mutex_release_continues_after_child_state_publication_interruption(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    releases: list[str] = []

    class ChildMutex:
        def __init__(self, name: str) -> None:
            self.name = name

        def acquire(self, _display_id: str) -> object:
            return self.name

        def release(self, _handle: object) -> None:
            releases.append(self.name)

    mutex = ProductionDisplayTransactionMutex()
    mutex._process = ChildMutex("process")  # type: ignore[assignment]
    mutex._windows = ChildMutex("windows")  # type: ignore[assignment]
    lease = mutex.acquire("display-1")
    source, first_line = inspect.getsourcelines(ProductionDisplayTransactionMutex.release)
    target_line = first_line + next(
        index for index, line in enumerate(source) if "handle.windows_handle = None" in line
    )

    def interrupt_publication(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is ProductionDisplayTransactionMutex.release.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_publication

    sys.settrace(interrupt_publication)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.release(lease)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert releases == ["windows", "process"]
    assert lease.windows_handle is None  # type: ignore[attr-defined]
    assert lease.process_handle is None  # type: ignore[attr-defined]
    assert lease.poisoned is True  # type: ignore[attr-defined]


@REQUIRES_OPCODE_MONITORING
@pytest.mark.parametrize("operation", ["resolve", "read", "write"])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("controller handoff"), SystemExit(68)])
def test_default_ports_close_ddc_controller_when_post_acquisition_handoff_is_interrupted(
    operation: str,
    interruption: BaseException,
) -> None:
    target = DdcTargetIdentity("display-1", "path-1")
    controllers: list[object] = []

    class Controller:
        def __init__(self) -> None:
            self.closes = 0
            controllers.append(self)

        def enumerate_monitors(self) -> list[dict[str, object]]:
            return [{"handle": 123, "hmonitor": 77}]

        def close(self) -> None:
            self.closes += 1

    module = SimpleNamespace(DDCCIController=Controller, VCPCode={"BRIGHTNESS": 1})
    ports = DefaultWindowsDisplayPorts(
        module_loader=lambda _name: module,
        ddc_identity_resolver=lambda _display_id: "path-1",
        physical_monitor_identity_resolver=lambda _monitor: target,
    )
    function = {
        "resolve": DefaultWindowsDisplayPorts.resolve_ddc_target,
        "read": DefaultWindowsDisplayPorts.read_ddc,
        "write": DefaultWindowsDisplayPorts.write_ddc,
    }[operation]
    source, first_line = inspect.getsourcelines(function)
    open_index = next(index for index, line in enumerate(source) if "_open_ddc_target" in line)
    open_line = first_line + open_index
    instructions = list(dis.get_instructions(function))
    call_index = next(
        index
        for index, instruction in enumerate(instructions)
        if instruction.positions.lineno == open_line and instruction.opname == "CALL"
    )
    post_call_target = instructions[call_index + 1].offset

    _interrupt_at_opcode(function, post_call_target, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            if operation == "resolve":
                ports.resolve_ddc_target("display-1")
            elif operation == "read":
                ports.read_ddc(target, "BRIGHTNESS")
            else:
                ports.write_ddc(target, "BRIGHTNESS", 50, expected_maximum=100)
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert len(controllers) == 1
    assert controllers[0].closes == 1  # type: ignore[attr-defined]


@pytest.mark.parametrize("operation", ["capture", "cache", "activate"])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("success handoff"), SystemExit(69)])
def test_successful_icc_operations_close_lease_when_success_handoff_is_interrupted(
    tmp_path: Path,
    operation: str,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    payload = valid_icc_payload(b"success-handoff")
    closes = 0

    class Lease:
        def __init__(self, _path: str) -> None:
            return None

        def validate_private_cache_identity(self, _path: str) -> None:
            return None

        def read_bytes(self) -> bytes:
            return payload

        def close(self) -> None:
            nonlocal closes
            closes += 1

    default_name = "prior.icc" if operation == "capture" else "target.icc"
    installer = SimpleNamespace(
        get_profile_directory=lambda: tmp_path,
        get_default_profile_for_display=lambda _display: default_name,
        set_default_profile_for_display=lambda _profile, _display: (True, "selected"),
        is_profile_installed=lambda _profile: True,
        is_profile_associated_with_display=lambda _profile, _display: True,
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.profiles.profile_installer": installer}.__getitem__,
        icc_file_lease_factory=Lease,
    )
    function = {
        "capture": DefaultWindowsDisplayPorts.capture_icc_profile,
        "cache": DefaultWindowsDisplayPorts._read_private_cache_entry,
        "activate": DefaultWindowsDisplayPorts.activate_icc_profile,
    }[operation]
    source, first_line = inspect.getsourcelines(function)
    assert_indices = [index for index, line in enumerate(source) if "assert lease is not None" in line]
    target_line = first_line + assert_indices[-1]

    def interrupt_handoff(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is function.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_handoff

    profile = IccProfileSnapshot(str(tmp_path / "target.icc"), payload, sha256_bytes(payload))
    sys.settrace(interrupt_handoff)
    try:
        with pytest.raises(type(interruption)) as caught:
            if operation == "capture":
                ports.capture_icc_profile("display-1")
            elif operation == "cache":
                ports._read_private_cache_entry(tmp_path / "target.icc")
            else:
                ports.activate_icc_profile("display-1", profile, register=False, associate=False)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert closes == 1


@pytest.mark.parametrize("operation", ["capture", "cache", "activate"])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("close call handoff"), SystemExit(70)])
def test_successful_icc_operations_retry_close_dispatch_after_handoff_interruption(
    tmp_path: Path,
    operation: str,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    payload = valid_icc_payload(b"close-call-handoff")
    closes = 0

    class Lease:
        def __init__(self, _path: str) -> None:
            return None

        def validate_private_cache_identity(self, _path: str) -> None:
            return None

        def read_bytes(self) -> bytes:
            return payload

        def close(self) -> None:
            nonlocal closes
            closes += 1

    default_name = "prior.icc" if operation == "capture" else "target.icc"
    installer = SimpleNamespace(
        get_profile_directory=lambda: tmp_path,
        get_default_profile_for_display=lambda _display: default_name,
        set_default_profile_for_display=lambda _profile, _display: (True, "selected"),
        is_profile_installed=lambda _profile: True,
        is_profile_associated_with_display=lambda _profile, _display: True,
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader={"calibrate_pro.profiles.profile_installer": installer}.__getitem__,
        icc_file_lease_factory=Lease,
    )
    function = {
        "capture": DefaultWindowsDisplayPorts.capture_icc_profile,
        "cache": DefaultWindowsDisplayPorts._read_private_cache_entry,
        "activate": DefaultWindowsDisplayPorts.activate_icc_profile,
    }[operation]
    source, first_line = inspect.getsourcelines(function)
    target_line = first_line + next(
        index for index, line in enumerate(source) if "close_exc = _close_icc_lease_once(cast" in line
    )

    def interrupt_close_dispatch(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is function.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_close_dispatch

    profile = IccProfileSnapshot(str(tmp_path / "target.icc"), payload, sha256_bytes(payload))
    sys.settrace(interrupt_close_dispatch)
    try:
        with pytest.raises(type(interruption)) as caught:
            if operation == "capture":
                ports.capture_icc_profile("display-1")
            elif operation == "cache":
                ports._read_private_cache_entry(tmp_path / "target.icc")
            else:
                ports.activate_icc_profile("display-1", profile, register=False, associate=False)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert closes == 1


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("before named close"), SystemExit(71)])
def test_named_mutex_close_callback_failure_retains_exact_handle(interruption: BaseException) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    releases: list[object] = []
    closes: list[object] = []
    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(lambda handle: releases.append(handle) or True),
        CloseHandle=Function(lambda handle: closes.append(handle) or (_ for _ in ()).throw(interruption)),
    )
    display_id = f"named-close-dispatch-{type(interruption).__name__}"
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    lease = mutex.acquire(display_id)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.release(lease)
    finally:
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_id.casefold())
        WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(display_id.casefold(), None)

    assert caught.value is interruption
    assert releases == [123]
    assert closes == [123]
    assert lease.native_handle == 123  # type: ignore[attr-defined]
    assert lease.poisoned is True  # type: ignore[attr-defined]


def test_named_mutex_false_close_retains_uncertain_native_handle_truth() -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(lambda _handle: True),
        CloseHandle=Function(lambda _handle: False),
    )
    display_id = "named-false-close-truth"
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    lease = mutex.acquire(display_id)
    try:
        with pytest.raises(RuntimeError, match="close|release"):
            mutex.release(lease)

        assert lease.native_handle == 123  # type: ignore[attr-defined]
        assert lease.poisoned is True  # type: ignore[attr-defined]
    finally:
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_id.casefold())


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("release dispatch"), SystemExit(72)])
def test_adapter_mutex_release_retains_precise_ownership_at_dispatch(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    handle = object()
    releases: list[object] = []

    class TrackingMutex:
        def release(self, actual: object) -> None:
            releases.append(actual)

    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=TrackingMutex())
    handles = [handle]
    observations: list[tuple[object, ...]] = []
    source, first_line = inspect.getsourcelines(WindowsDisplayStateAdapter._release_mutex_handles)
    target_line = first_line + next(
        index for index, line in enumerate(source) if "self._transaction_mutex.release(handle)" in line
    )

    def interrupt_dispatch(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is WindowsDisplayStateAdapter._release_mutex_handles.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            observations.append(tuple(handles))
            sys.settrace(None)
            raise interruption
        return interrupt_dispatch

    sys.settrace(interrupt_dispatch)
    try:
        with pytest.raises(type(interruption)) as caught:
            adapter._release_mutex_handles(handles)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert observations == [(handle,)]
    assert releases == []
    assert handles == [handle]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("busy close dispatch"), SystemExit(73)])
def test_named_mutex_busy_close_callback_failure_is_retained(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []
    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0x00000102),
        ReleaseMutex=Function(lambda _handle: True),
        CloseHandle=Function(lambda handle: closes.append(handle) or (_ for _ in ()).throw(interruption)),
    )
    display_id = f"busy-close-dispatch-{type(interruption).__name__}"
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire(display_id)
    finally:
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_id.casefold())
        WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(display_id.casefold(), None)

    assert caught.value is interruption
    assert closes == [123]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("lease close preamble"), SystemExit(74)])
def test_icc_close_retries_cancellation_from_lease_close_preamble(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    closes = 0

    class Lease:
        def close(self) -> None:
            nonlocal closes
            closes += 1

    source, first_line = inspect.getsourcelines(Lease.close)
    target_line = first_line + next(index for index, line in enumerate(source) if "closes += 1" in line)

    def interrupt_close_preamble(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is Lease.close.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_close_preamble

    sys.settrace(interrupt_close_preamble)
    try:
        failure = windows_state._close_icc_lease_once(Lease())  # type: ignore[arg-type]
    finally:
        sys.settrace(None)

    assert failure is interruption
    assert closes == 1


@pytest.mark.parametrize("operation", ["resolve", "read", "write"])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("successful DDC close"), SystemExit(75)])
def test_successful_ddc_session_closes_when_close_dispatch_is_interrupted(
    operation: str,
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    target = DdcTargetIdentity("display-1", "path-1")
    controllers: list[object] = []

    class Controller:
        def __init__(self) -> None:
            self.closes = 0
            controllers.append(self)

        def enumerate_monitors(self) -> list[dict[str, object]]:
            return [{"handle": 123, "hmonitor": 77}]

        def get_vcp(self, *_args: object, **_kwargs: object) -> tuple[int, int]:
            return 50, 100

        def set_vcp(self, *_args: object, **_kwargs: object) -> bool:
            return True

        def close(self) -> None:
            self.closes += 1

    module = SimpleNamespace(DDCCIController=Controller, VCPCode={"BRIGHTNESS": 1})
    ports = DefaultWindowsDisplayPorts(
        module_loader=lambda _name: module,
        ddc_identity_resolver=lambda _display_id: "path-1",
        physical_monitor_identity_resolver=lambda _monitor: target,
    )
    function = {
        "resolve": DefaultWindowsDisplayPorts.resolve_ddc_target,
        "read": DefaultWindowsDisplayPorts.read_ddc,
        "write": DefaultWindowsDisplayPorts.write_ddc,
    }[operation]
    source, first_line = inspect.getsourcelines(function)
    target_line = first_line + max(
        index for index, line in enumerate(source) if "self._close_ddc_controller(controller)" in line
    )

    def interrupt_close_dispatch(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is function.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_close_dispatch

    sys.settrace(interrupt_close_dispatch)
    try:
        with pytest.raises(type(interruption)) as caught:
            if operation == "resolve":
                ports.resolve_ddc_target("display-1")
            elif operation == "read":
                ports.read_ddc(target, "BRIGHTNESS")
            else:
                ports.write_ddc(target, "BRIGHTNESS", 60, expected_maximum=100)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert len(controllers) == 1
    assert controllers[0].closes == 1  # type: ignore[attr-defined]


@pytest.mark.parametrize("primary", [KeyboardInterrupt("first restore cancellation"), SystemExit(76)])
@pytest.mark.parametrize("dispatch_interruption", [KeyboardInterrupt("retry dispatch"), SystemExit(77)])
def test_restore_keeps_cleanup_ownership_during_iterative_retry_prologue(
    primary: BaseException,
    dispatch_interruption: BaseException,
    monkeypatch: pytest.MonkeyPatch,
    unmeasured_tracing: None,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.releases = 0

        def acquire(self, _display_id: str) -> object:
            return object()

        def release(self, _handle: object) -> None:
            self.releases += 1

    mutex = TrackingMutex()
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=mutex)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 60),))
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    original_snapshot_sha256 = windows_state._snapshot_sha256
    armed = True
    schedule = WindowsDisplayStateAdapter._run_restore_compensation_schedule
    source, first_line = inspect.getsourcelines(schedule)
    target_line = first_line + next(
        index for index, line in enumerate(source) if "snapshot_tampered = _snapshot_sha256" in line
    )

    def interrupt_retry_prologue(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is schedule.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise dispatch_interruption
        return interrupt_retry_prologue

    def cancel_first_restore_entry(actual: DisplayStateSnapshot) -> str:
        nonlocal armed
        if armed:
            armed = False
            sys.settrace(interrupt_retry_prologue)
            raise primary
        return original_snapshot_sha256(actual)

    monkeypatch.setattr(windows_state, "_snapshot_sha256", cancel_first_restore_entry)
    try:
        with pytest.raises(type(primary)) as caught:
            adapter.restore(snapshot)
    finally:
        sys.settrace(None)

    assert caught.value is primary
    assert ports.ddc_values["BRIGHTNESS"] == 50
    assert mutex.releases == 1
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("primary", [KeyboardInterrupt("restore retry"), SystemExit(78)])
def test_restore_outer_retry_owner_does_not_repeat_poisoned_child_release(
    primary: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingMutex:
        def __init__(self) -> None:
            self.releases = 0

        def acquire(self, _display_id: str) -> object:
            return object()

        def release(self, _handle: object) -> None:
            self.releases += 1
            raise RuntimeError("release failed")

    mutex = FailingMutex()
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=mutex)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 60),))
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    original_snapshot_sha256 = windows_state._snapshot_sha256
    armed = True

    def cancel_first_restore_entry(actual: DisplayStateSnapshot) -> str:
        nonlocal armed
        if armed:
            armed = False
            raise primary
        return original_snapshot_sha256(actual)

    monkeypatch.setattr(windows_state, "_snapshot_sha256", cancel_first_restore_entry)

    with pytest.raises(type(primary)) as caught:
        adapter.restore(snapshot)

    assert caught.value is primary
    assert ports.ddc_values["BRIGHTNESS"] == 50
    assert mutex.releases == 1
    assert adapter._active is not None
    assert adapter._active.lease_poisoned is True
    assert adapter._phase is windows_state._TransactionPhase.POISONED


def _opcode_offset(function: object, predicate: object) -> int:
    if not _OPCODE_MONITORING_AVAILABLE:
        pytest.skip("opcode-level cancellation injection requires sys.monitoring (Python 3.12+)")
    matches = [
        instruction.offset
        for instruction in dis.get_instructions(function)  # type: ignore[arg-type]
        if predicate(instruction)  # type: ignore[operator]
    ]
    assert matches
    return matches[-1]


_OPCODE_MONITOR_TOOL_ID = getattr(getattr(sys, "monitoring", None), "OPTIMIZER_ID", None)


def _clear_opcode_interrupt() -> None:
    if _OPCODE_MONITOR_TOOL_ID is None:
        return
    try:
        sys.monitoring.set_events(_OPCODE_MONITOR_TOOL_ID, 0)
        sys.monitoring.register_callback(
            _OPCODE_MONITOR_TOOL_ID,
            sys.monitoring.events.INSTRUCTION,
            None,
        )
        sys.monitoring.free_tool_id(_OPCODE_MONITOR_TOOL_ID)
    except ValueError:
        pass


def _interrupt_at_opcode(function: object, offset: int, interruption: BaseException) -> None:
    if _OPCODE_MONITOR_TOOL_ID is None:
        pytest.skip("opcode-level cancellation injection requires sys.monitoring (Python 3.12+)")
    code = function.__code__  # type: ignore[attr-defined]
    _clear_opcode_interrupt()
    sys.monitoring.use_tool_id(_OPCODE_MONITOR_TOOL_ID, "calibrate-pro opcode ownership tests")

    def interrupt(actual_code: object, instruction_offset: int) -> None:
        if actual_code is code and instruction_offset == offset:
            _clear_opcode_interrupt()
            raise interruption

    sys.monitoring.register_callback(
        _OPCODE_MONITOR_TOOL_ID,
        sys.monitoring.events.INSTRUCTION,
        interrupt,
    )
    sys.monitoring.set_local_events(
        _OPCODE_MONITOR_TOOL_ID,
        code,
        sys.monitoring.events.INSTRUCTION,
    )


def _interrupt_at_opcode_after_event(
    function: object,
    offset: int,
    interruption: BaseException,
    entered: threading.Event,
) -> None:
    """Raise at one ownership boundary only after the native worker is in flight."""
    if _OPCODE_MONITOR_TOOL_ID is None:
        pytest.skip("opcode-level cancellation injection requires sys.monitoring (Python 3.12+)")
    code = function.__code__  # type: ignore[attr-defined]
    _clear_opcode_interrupt()
    sys.monitoring.use_tool_id(_OPCODE_MONITOR_TOOL_ID, "calibrate-pro in-flight ownership tests")

    def interrupt(actual_code: object, instruction_offset: int) -> None:
        if actual_code is code and instruction_offset == offset:
            assert entered.wait(2)
            _clear_opcode_interrupt()
            raise interruption

    sys.monitoring.register_callback(
        _OPCODE_MONITOR_TOOL_ID,
        sys.monitoring.events.INSTRUCTION,
        interrupt,
    )
    sys.monitoring.set_local_events(
        _OPCODE_MONITOR_TOOL_ID,
        code,
        sys.monitoring.events.INSTRUCTION,
    )


@pytest.mark.parametrize("primary", [KeyboardInterrupt("initial schedule"), SystemExit(79)])
@pytest.mark.parametrize("prologue", [KeyboardInterrupt("retry prologue"), SystemExit(80)])
def test_restore_single_owner_retries_cancellation_after_recursive_marker_or_iterative_prologue(
    primary: BaseException,
    prologue: BaseException,
    monkeypatch: pytest.MonkeyPatch,
    unmeasured_tracing: None,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.releases = 0

        def acquire(self, _display_id: str) -> object:
            return object()

        def release(self, _handle: object) -> None:
            self.releases += 1

    mutex = TrackingMutex()
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=mutex)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 60),))
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    original_snapshot_sha256 = windows_state._snapshot_sha256
    interruptions = [primary]
    recursive = "_invoke_restore_retry" in inspect.getsource(WindowsDisplayStateAdapter.restore)
    if not recursive:
        interruptions.append(prologue)

    def cancel_schedule_prologue(actual: DisplayStateSnapshot) -> str:
        if interruptions:
            raise interruptions.pop(0)
        return original_snapshot_sha256(actual)

    monkeypatch.setattr(windows_state, "_snapshot_sha256", cancel_schedule_prologue)
    if recursive:
        helper = windows_state._invoke_restore_retry
        call_offsets = [
            instruction.offset for instruction in dis.get_instructions(helper) if instruction.opname == "CALL"
        ]
        assert len(call_offsets) >= 2
        sys.settrace(_interrupt_at_opcode(helper, call_offsets[-1], prologue))
    try:
        with pytest.raises(type(primary)) as caught:
            adapter.restore(snapshot)
    finally:
        sys.settrace(None)

    assert caught.value is primary
    assert ports.ddc_values["BRIGHTNESS"] == 50
    assert mutex.releases == 1
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("lock store"), SystemExit(81)])
def test_in_process_acquire_reconciles_opcode_cancellation_after_lock_call(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    display_id = f"opcode-in-process-{type(interruption).__name__}"
    key = display_id.casefold()
    mutex = InProcessDisplayTransactionMutex()
    function = InProcessDisplayTransactionMutex.acquire
    target = _opcode_offset(
        function,
        lambda instruction: instruction.opname == "STORE_FAST" and instruction.argval == "acquired",
    )

    sys.settrace(_interrupt_at_opcode(function, target, interruption))
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire(display_id)
    finally:
        sys.settrace(None)
        _clear_opcode_interrupt()
    lock = InProcessDisplayTransactionMutex._locks[key]
    try:
        assert caught.value is interruption
        assert lock.locked() is False
    finally:
        if lock.locked():
            lock.release()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("child store"), SystemExit(82)])
def test_production_acquire_sink_releases_child_lost_at_store_opcode(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    releases: list[str] = []

    class ChildMutex:
        def __init__(self, name: str) -> None:
            self.name = name

        def acquire(self, _display_id: str) -> object:
            return windows_state._publish_mutex_lease(self.name)

        def release(self, handle: object) -> None:
            releases.append(str(handle))

    mutex = ProductionDisplayTransactionMutex()
    mutex._process = ChildMutex("process")  # type: ignore[assignment]
    mutex._windows = ChildMutex("windows")  # type: ignore[assignment]
    function = ProductionDisplayTransactionMutex.acquire
    target = _opcode_offset(
        function,
        lambda instruction: instruction.opname == "STORE_FAST" and instruction.argval == "process_handle",
    )

    sys.settrace(_interrupt_at_opcode(function, target, interruption))
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire("display-1")
    finally:
        sys.settrace(None)
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert releases == ["process"]


@REQUIRES_OPCODE_MONITORING
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("capture append"), SystemExit(83)])
def test_capture_acquisition_sink_releases_lease_lost_before_append_opcode(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    handle = object()
    releases: list[object] = []

    class TrackingMutex:
        def acquire(self, _display_id: str) -> object:
            return windows_state._publish_mutex_lease(handle)

        def release(self, actual: object) -> None:
            releases.append(actual)

    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=TrackingMutex())
    plan = make_plan()
    coordinator = coordinator_for(adapter)
    issuer = coordinator._capture_authorization_issuer
    assert issuer is not None
    function = WindowsDisplayStateAdapter.capture
    source, first_line = inspect.getsourcelines(function)
    append_line = first_line + next(
        index for index, line in enumerate(source) if 'mutex_handles.append(acquisition_sink.acquire(f"display:' in line
    )
    target = _opcode_offset(
        function,
        lambda instruction: instruction.opname == "CALL" and instruction.positions.lineno == append_line,
    )

    sys.settrace(_interrupt_at_opcode(function, target, interruption))
    try:
        with pytest.raises(type(interruption)) as caught:
            adapter.capture(plan, authorization=issuer(plan))
    finally:
        sys.settrace(None)
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert releases == [handle]
    assert adapter._active is None
    assert adapter._phase is None


@REQUIRES_OPCODE_MONITORING
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("release pop"), SystemExit(84)])
def test_release_reconciles_terminal_lease_after_pop_opcode_cancellation(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    class Lease:
        released = False

    lease = Lease()

    class TrackingMutex:
        def release(self, actual: object) -> None:
            assert actual is lease
            lease.released = True

        def is_released(self, actual: object) -> bool:
            assert actual is lease
            return lease.released

    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=TrackingMutex())
    handles: list[object] = [lease]
    function = WindowsDisplayStateAdapter._release_mutex_handles
    release_line = inspect.getsourcelines(function)[1] + next(
        index
        for index, line in enumerate(inspect.getsourcelines(function)[0])
        if "self._transaction_mutex.release(handle)" in line
    )
    call_offsets = [
        instruction.offset
        for instruction in dis.get_instructions(function)
        if instruction.opname == "CALL" and instruction.positions.lineno == release_line
    ]
    assert len(call_offsets) >= 2

    sys.settrace(_interrupt_at_opcode(function, call_offsets[-1], interruption))
    try:
        with pytest.raises(type(interruption)) as caught:
            adapter._release_mutex_handles(handles)
    finally:
        sys.settrace(None)
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert lease.released is True
    assert handles == []


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("release pre-entry"), SystemExit(85)])
def test_named_mutex_release_callback_failure_occurs_on_owner_thread(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    releases: list[object] = []
    release_threads: list[int] = []
    closes: list[object] = []

    def interrupt_release(handle: object) -> bool:
        releases.append(handle)
        release_threads.append(threading.get_ident())
        raise interruption

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(interrupt_release),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = f"release-pre-entry-{type(interruption).__name__}"
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    lease = mutex.acquire(display_id)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.release(lease)
    finally:
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_id.casefold())
        WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(display_id.casefold(), None)

    assert caught.value is interruption
    assert releases == [123]
    assert release_threads and release_threads != [threading.get_ident()]
    assert closes == []
    assert lease.native_handle == 123  # type: ignore[attr-defined]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("release uncertain"), SystemExit(86)])
def test_named_mutex_uncertain_entered_release_retains_handle_without_close(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    releases: list[object] = []
    closes: list[object] = []

    def interrupt_release(handle: object) -> bool:
        releases.append(handle)
        raise interruption

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(interrupt_release),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = f"release-uncertain-{type(interruption).__name__}"
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    lease = mutex.acquire(display_id)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.release(lease)
        assert caught.value is interruption
        assert releases == [123]
        assert closes == []
        assert lease.native_handle == 123  # type: ignore[attr-defined]
        assert lease.poisoned is True  # type: ignore[attr-defined]
    finally:
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_id.casefold())


def test_icc_false_close_retries_exact_lease_before_returning() -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []

    def close(handle: object) -> bool:
        closes.append(handle)
        return len(closes) == 2

    inert = Function(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=Function(lambda *_args: 123),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=Function(lambda *_args: 1),
        GetFinalPathNameByHandleW=Function(lambda *_args: 1),
        CloseHandle=Function(close),
    )
    lease = windows_state._WindowsIccFileLease("cache.icc", kernel32_loader=lambda: kernel32)

    failure = windows_state._close_icc_lease_once(lease)

    assert failure is None
    assert closes == [123, 123]
    assert lease._handle is None


def test_icc_persistent_false_close_is_retained_in_durable_registry() -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    allow_close = False

    def close(_handle: object) -> bool:
        return allow_close

    inert = Function(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=Function(lambda *_args: 123),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=Function(lambda *_args: 1),
        GetFinalPathNameByHandleW=Function(lambda *_args: 1),
        CloseHandle=Function(close),
    )
    lease = windows_state._WindowsIccFileLease("cache.icc", kernel32_loader=lambda: kernel32)

    failure = windows_state._close_icc_lease_once(lease)
    registry = getattr(windows_state, "_RETAINED_ICC_LEASES", {})
    try:
        assert failure is not None
        assert registry.get(id(lease)) is lease
        assert lease._handle == 123
    finally:
        allow_close = True
        lease.close()
        registry.pop(id(lease), None)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("acquire release pre-entry"), SystemExit(87)])
def test_named_acquire_cleanup_release_callback_failure_retains_exact_handle(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    releases: list[object] = []
    closes: list[object] = []

    def interrupt_release(handle: object) -> bool:
        releases.append(handle)
        raise interruption

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0x00000080),
        ReleaseMutex=Function(interrupt_release),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = f"acquire-release-pre-entry-{type(interruption).__name__}"
    key = display_id.casefold()
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire(display_id)
    finally:
        retained = WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(key, None)
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(key)

    assert caught.value is interruption
    assert releases == [123]
    assert closes == []
    assert retained is not None and retained.native_handle == 123


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("acquire release uncertain"), SystemExit(88)])
def test_named_acquire_uncertain_release_retains_exact_handle_without_close(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    releases: list[object] = []
    closes: list[object] = []

    def interrupt_release(handle: object) -> bool:
        releases.append(handle)
        raise interruption

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0x00000080),
        ReleaseMutex=Function(interrupt_release),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = f"acquire-release-uncertain-{type(interruption).__name__}"
    key = display_id.casefold()
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    registry = getattr(WindowsNamedDisplayTransactionMutex, "_poisoned_native_leases", {})
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire(display_id)
        assert caught.value is interruption
        assert releases == [123]
        assert closes == []
        retained = registry[key]
        assert retained.native_handle == 123
        assert retained.poisoned is True
    finally:
        registry.pop(key, None)
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(key)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("restore phase"), SystemExit(89)])
def test_restore_retries_claim_until_restoring_phase_is_published(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.releases = 0

        def acquire(self, _display_id: str) -> object:
            return object()

        def release(self, _handle: object) -> None:
            self.releases += 1

    mutex = TrackingMutex()
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=mutex)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 60),))
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    original_read = ports.read_ddc
    observed_phases: list[object] = []

    def read_with_phase(target: DdcTargetIdentity, code: str) -> DdcReading:
        observed_phases.append(adapter._phase)
        return original_read(target, code)

    ports.read_ddc = read_with_phase  # type: ignore[method-assign]
    source, first_line = inspect.getsourcelines(WindowsDisplayStateAdapter.restore)
    target_line = first_line + next(
        index for index, line in enumerate(source) if "self._phase = _TransactionPhase.RESTORING" in line
    )

    def interrupt_phase_publication(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is WindowsDisplayStateAdapter.restore.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_phase_publication

    sys.settrace(interrupt_phase_publication)
    try:
        with pytest.raises(type(interruption)) as caught:
            adapter.restore(snapshot)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    assert ports.ddc_values["BRIGHTNESS"] == 50
    assert observed_phases and set(observed_phases) == {windows_state._TransactionPhase.RESTORING}
    assert mutex.releases == 1
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("DDC once"), SystemExit(90)])
def test_restore_replays_schedule_after_one_shot_domain_cancellation(
    interruption: BaseException,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.releases = 0

        def acquire(self, _display_id: str) -> object:
            return object()

        def release(self, _handle: object) -> None:
            self.releases += 1

    mutex = TrackingMutex()
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=mutex)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 60),))
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    original_read = ports.read_ddc
    attempts = 0

    def cancel_once(target: DdcTargetIdentity, code: str) -> DdcReading:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise interruption
        return original_read(target, code)

    ports.read_ddc = cancel_once  # type: ignore[method-assign]

    with pytest.raises(type(interruption)) as caught:
        adapter.restore(snapshot)

    assert caught.value is interruption
    assert attempts >= 2
    assert ports.ddc_values["BRIGHTNESS"] == 50
    assert mutex.releases == 1
    assert adapter._active is None
    assert adapter._phase is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("DDC persistent"), SystemExit(91)])
def test_restore_persistent_domain_cancellation_retains_active_mutex_evidence(
    interruption: BaseException,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.releases = 0

        def acquire(self, _display_id: str) -> object:
            return object()

        def release(self, _handle: object) -> None:
            self.releases += 1

    mutex = TrackingMutex()
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=mutex)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 60),))
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    attempts = 0

    def cancel_persistently(_target: DdcTargetIdentity, _code: str) -> DdcReading:
        nonlocal attempts
        attempts += 1
        raise interruption

    ports.read_ddc = cancel_persistently  # type: ignore[method-assign]

    with pytest.raises(type(interruption)) as caught:
        adapter.restore(snapshot)

    assert caught.value is interruption
    assert attempts == windows_state._MAX_COMPENSATION_SCHEDULE_ATTEMPTS
    assert ports.ddc_values["BRIGHTNESS"] == 60
    assert mutex.releases == 0
    assert adapter._active is not None
    assert adapter._active.snapshot is snapshot
    assert adapter._active.mutex_handles
    assert adapter._phase is windows_state._TransactionPhase.UNCERTAIN


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("CreateMutex store"), SystemExit(92)])
def test_named_mutex_proxy_publication_cancellation_releases_on_owner_thread(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    calls: list[tuple[str, object, int]] = []
    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(lambda handle: calls.append(("release", handle, threading.get_ident())) or True),
        CloseHandle=Function(lambda handle: calls.append(("close", handle, threading.get_ident())) or True),
    )
    display_id = f"create-store-{type(interruption).__name__}"
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    with monkeypatch.context() as context:
        context.setattr(windows_state, "_publish_mutex_lease", lambda _lease: (_ for _ in ()).throw(interruption))
        with pytest.raises(type(interruption)) as caught:
            mutex.acquire(display_id)

    assert caught.value is interruption
    assert [(name, handle) for name, handle, _thread in calls] == [("release", 123), ("close", 123)]
    assert len({thread for _name, _handle, thread in calls}) == 1


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("release inner pre-call"), SystemExit(93)])
def test_release_owner_callback_cancellation_retains_native_evidence(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    releases: list[object] = []
    closes: list[object] = []

    def interrupt_release(handle: object) -> bool:
        releases.append(handle)
        raise interruption

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(interrupt_release),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = f"release-inner-pre-call-{type(interruption).__name__}"
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    lease = mutex.acquire(display_id)
    try:
        with pytest.raises(type(interruption)) as caught:
            mutex.release(lease)
    finally:
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_id.casefold())
        WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(display_id.casefold(), None)

    assert caught.value is interruption
    assert releases == [123]
    assert closes == []
    assert lease.native_handle == 123  # type: ignore[attr-defined]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("close inner pre-call"), SystemExit(94)])
def test_close_worker_retries_inner_instruction_cancellation_before_native_entry(
    interruption: BaseException,
    unmeasured_tracing: None,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []
    inert = Function(lambda *_args: True)
    kernel32 = SimpleNamespace(
        CreateFileW=Function(lambda *_args: 123),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=Function(lambda *_args: 1),
        GetFinalPathNameByHandleW=Function(lambda *_args: 1),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    lease = windows_state._WindowsIccFileLease("cache.icc", kernel32_loader=lambda: kernel32)
    helper = windows_state._invoke_windows_handle_close
    calls = [
        instruction.offset for instruction in dis.get_instructions(helper) if instruction.opname.startswith("CALL")
    ]
    assert calls

    sys.settrace(_interrupt_at_opcode(helper, calls[-1], interruption))
    try:
        failure = windows_state._close_icc_lease_once(lease)
    finally:
        sys.settrace(None)
        _clear_opcode_interrupt()

    assert failure is interruption
    assert closes == [123]
    assert lease._handle is None


def test_unclaimed_mutex_registry_uses_monotonic_tokens_not_object_ids() -> None:
    sink_type = windows_state._MutexAcquisitionSink
    first = sink_type(SimpleNamespace(release=lambda _lease: None))
    second = sink_type(SimpleNamespace(release=lambda _lease: None))

    assert first._token != second._token
    assert first._token < second._token
    assert first._token != id(first)


def test_unclaimed_mutex_capacity_fails_closed_after_bounded_drain(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingMutex:
        def release(self, _lease: object) -> None:
            raise RuntimeError("still owned")

    monkeypatch.setattr(windows_state, "_MAX_UNCLAIMED_MUTEX_LEASES", 1)
    registry = windows_state._UNCLAIMED_MUTEX_LEASES
    registry.clear()
    first = windows_state._MutexAcquisitionSink(FailingMutex())
    with first:
        first.publish(object())
        try:
            raise KeyboardInterrupt("orphan")
        except KeyboardInterrupt as exc:
            first.__exit__(KeyboardInterrupt, exc, None)
    try:
        second = windows_state._MutexAcquisitionSink(FailingMutex())
        with pytest.raises(RuntimeError, match="capacity|retained"):
            second.__enter__()
    finally:
        registry.clear()


def test_retained_icc_registry_bounded_drain_retries_and_removes_exact_lease() -> None:
    closes = 0

    class Lease:
        def close(self) -> None:
            nonlocal closes
            closes += 1

    lease = Lease()
    registry = windows_state._RETAINED_ICC_LEASES
    registry.clear()
    windows_state._retain_icc_lease(lease)  # type: ignore[arg-type]

    drained = windows_state._drain_retained_icc_leases(limit=1)

    assert drained == 1
    assert closes == 1
    assert registry == {}


def test_poisoned_native_registry_shutdown_drain_closes_only_known_released_handle() -> None:
    closes: list[object] = []
    kernel32 = SimpleNamespace(CloseHandle=lambda handle: closes.append(handle) or True)
    lease = windows_state._WindowsNamedMutexLease(
        kernel32,
        123,
        "shutdown-drain",
        poisoned=True,
        mutex_released=True,
    )
    registry = WindowsNamedDisplayTransactionMutex._poisoned_native_leases
    registry.clear()
    registry[lease.display_key] = lease

    drained = windows_state._drain_poisoned_native_leases(limit=1)

    assert drained == 1
    assert closes == [123]
    assert registry == {}


def test_mutex_sink_stack_corruption_still_reconciles_exact_unclaimed_lease() -> None:
    releases: list[object] = []
    lease = object()
    sink = windows_state._MutexAcquisitionSink(SimpleNamespace(release=releases.append))
    sink.__enter__()
    sink.publish(lease)
    stack = windows_state._MUTEX_ACQUISITION_LOCAL.stack
    assert stack.pop() is sink
    primary = KeyboardInterrupt("corrupt stack")

    sink.__exit__(KeyboardInterrupt, primary, None)

    assert releases == [lease]
    assert sink._token not in windows_state._UNCLAIMED_MUTEX_LEASES
    assert_exception_note_if_supported(primary, "stack")


@REQUIRES_OPCODE_MONITORING
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("mutex acknowledgment handoff"), SystemExit(102)])
def test_mutex_acknowledgment_retirement_cancellation_preserves_primary_and_retries(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    @dataclass
    class Lease:
        released: bool = False

    class TrackingMutex:
        def __init__(self) -> None:
            self.acquisitions = 0
            self.releases = 0

        def acquire(self, _display_id: str) -> Lease:
            self.acquisitions += 1
            return Lease()

        def release(self, lease: Lease) -> None:
            assert lease.released is False
            lease.released = True
            self.releases += 1

        @staticmethod
        def is_released(lease: Lease) -> bool:
            return lease.released

    registry: dict[int, object] = {}
    monkeypatch.setattr(windows_state, "_UNCLAIMED_MUTEX_LEASES", registry)
    mutex = TrackingMutex()
    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=mutex)
    plan = make_plan()
    coordinator = coordinator_for(adapter)
    token = coordinator.preview(plan)
    function = windows_state._MutexAcquisitionSink.acknowledge
    source, first_line = inspect.getsourcelines(function)
    forget_line = first_line + next(
        index for index, line in enumerate(source) if "_forget_unclaimed_mutex_lease" in line
    )
    instructions = list(dis.get_instructions(function))
    call_index = next(
        index
        for index, instruction in enumerate(instructions)
        if instruction.positions.lineno == forget_line and instruction.opname == "CALL"
    )
    post_call_target = instructions[call_index + 1].offset

    _interrupt_at_opcode(function, post_call_target, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            coordinator.apply(plan, token, confirmed=True)
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert mutex.acquisitions == 1
    assert mutex.releases == 1
    assert registry == {}
    assert getattr(windows_state._MUTEX_ACQUISITION_LOCAL, "stack", []) == []
    assert adapter._active is None
    assert adapter._phase is None

    receipt = run_confirmed(adapter, plan)
    assert receipt.success is True
    assert mutex.acquisitions == 2
    assert mutex.releases == 2
    assert registry == {}


def test_icc_retained_capacity_fails_before_opening_another_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    class StuckLease:
        def close(self) -> None:
            raise RuntimeError("still open")

    registry = windows_state._RETAINED_ICC_LEASES
    registry.clear()
    retained = StuckLease()
    registry[id(retained)] = retained  # type: ignore[assignment]
    factory_calls: list[str] = []
    ports = DefaultWindowsDisplayPorts(
        icc_file_lease_factory=lambda path: factory_calls.append(path),  # type: ignore[arg-type,return-value]
    )
    monkeypatch.setattr(windows_state, "_MAX_RETAINED_ICC_LEASES", 1)
    try:
        with pytest.raises(RuntimeError, match="capacity|retained"):
            ports._open_icc_file_lease("new.icc")
    finally:
        registry.clear()

    assert factory_calls == []


def test_poisoned_native_capacity_fails_before_loading_kernel32(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = WindowsNamedDisplayTransactionMutex._poisoned_native_leases
    registry.clear()
    retained = windows_state._WindowsNamedMutexLease(
        SimpleNamespace(),
        123,
        "retained-capacity",
        poisoned=True,
        mutex_released=False,
    )
    registry[retained.display_key] = retained
    loads = 0

    def load_kernel32() -> object:
        nonlocal loads
        loads += 1
        return object()

    monkeypatch.setattr(windows_state, "_MAX_POISONED_NATIVE_LEASES", 1)
    try:
        mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=load_kernel32)
        with pytest.raises(RuntimeError, match="capacity|retained"):
            mutex.acquire("new-display")
    finally:
        registry.clear()

    assert loads == 0


def test_shutdown_registry_drain_is_bounded_and_exception_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fail(name: str) -> object:
        def drain(*, limit: int) -> int:
            assert limit == windows_state._REGISTRY_DRAIN_LIMIT
            calls.append(name)
            raise KeyboardInterrupt(name)

        return drain

    monkeypatch.setattr(windows_state, "_drain_unclaimed_mutex_leases", fail("mutex"))
    monkeypatch.setattr(windows_state, "_drain_retained_icc_leases", fail("icc"))
    monkeypatch.setattr(windows_state, "_drain_poisoned_native_leases", fail("native"))

    windows_state._drain_adapter_lease_registries_at_shutdown()

    assert calls == ["mutex", "icc", "native"]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("mixed restore"), SystemExit(95)])
def test_restore_mixed_cancellation_and_domain_error_retains_exact_active_ownership(
    interruption: BaseException,
) -> None:
    class TrackingMutex:
        def __init__(self) -> None:
            self.releases = 0

        def acquire(self, _display_id: str) -> object:
            return object()

        def release(self, _handle: object) -> None:
            self.releases += 1

    mutex = TrackingMutex()
    ports = FakeWindowsDisplayPorts()
    adapter = make_adapter(ports, transaction_mutex=mutex)
    plan = make_plan(ddc_changes=(("BRIGHTNESS", 60), ("CONTRAST", 65)))
    snapshot = capture_authorized(adapter, plan)
    adapter.apply(plan)
    ports.failed_ddc_codes.add("CONTRAST")
    original_read = ports.read_ddc
    cancel_once = True

    def mixed_read(target: DdcTargetIdentity, code: str) -> DdcReading:
        nonlocal cancel_once
        if code == "BRIGHTNESS" and cancel_once:
            cancel_once = False
            raise interruption
        return original_read(target, code)

    ports.read_ddc = mixed_read  # type: ignore[method-assign]

    with pytest.raises(type(interruption)) as caught:
        adapter.restore(snapshot)

    assert caught.value is interruption
    assert ports.ddc_values["BRIGHTNESS"] == 50
    assert ports.ddc_values["CONTRAST"] == 65
    assert mutex.releases == 0
    assert adapter._active is not None
    assert adapter._active.snapshot is snapshot
    assert adapter._active.mutex_handles
    assert adapter._phase is windows_state._TransactionPhase.UNCERTAIN


def test_unclaimed_cleanup_and_registry_drain_have_one_release_owner() -> None:
    calls: list[object] = []
    calls_guard = threading.Lock()
    first_entered = threading.Event()
    allow_first = threading.Event()
    lease = object()

    class BlockingMutex:
        def release(self, actual: object) -> None:
            with calls_guard:
                calls.append(actual)
                first = len(calls) == 1
            if first:
                first_entered.set()
                assert allow_first.wait(2)

    registry = windows_state._UNCLAIMED_MUTEX_LEASES
    registry.clear()
    sink = windows_state._MutexAcquisitionSink(BlockingMutex())
    sink.__enter__()
    sink.publish(lease)
    primary = KeyboardInterrupt("owner exits")
    worker = threading.Thread(target=lambda: sink.__exit__(KeyboardInterrupt, primary, None))
    worker.start()
    assert first_entered.wait(2)
    try:
        drained = windows_state._drain_unclaimed_mutex_leases(limit=1)
        assert drained == 0
        assert calls == [lease]
    finally:
        allow_first.set()
        worker.join(2)
        registry.clear()
        stack = getattr(windows_state._MUTEX_ACQUISITION_LOCAL, "stack", [])
        if sink in stack:
            stack.remove(sink)

    assert not worker.is_alive()
    assert calls == [lease]


def test_two_icc_registry_drainers_close_retained_lease_once() -> None:
    calls = 0
    calls_guard = threading.Lock()
    first_entered = threading.Event()
    allow_first = threading.Event()

    class Lease:
        def close(self) -> None:
            nonlocal calls
            with calls_guard:
                calls += 1
                first = calls == 1
            if first:
                first_entered.set()
                assert allow_first.wait(2)

    registry = windows_state._RETAINED_ICC_LEASES
    registry.clear()
    getattr(windows_state, "_RETAINED_ICC_LEASE_CLAIMS", {}).clear()
    lease = Lease()
    windows_state._retain_icc_lease(lease)  # type: ignore[arg-type]
    first_results: list[int] = []
    worker = threading.Thread(target=lambda: first_results.append(windows_state._drain_retained_icc_leases(limit=1)))
    worker.start()
    assert first_entered.wait(2)
    try:
        second_result = windows_state._drain_retained_icc_leases(limit=1)
        assert second_result == 0
        assert calls == 1
    finally:
        allow_first.set()
        worker.join(2)
        registry.clear()
        getattr(windows_state, "_RETAINED_ICC_LEASE_CLAIMS", {}).clear()

    assert not worker.is_alive()
    assert first_results == [1]
    assert calls == 1


def test_two_poisoned_native_drainers_close_released_handle_once() -> None:
    calls: list[object] = []
    calls_guard = threading.Lock()
    first_entered = threading.Event()
    allow_first = threading.Event()

    def close(handle: object) -> bool:
        with calls_guard:
            calls.append(handle)
            first = len(calls) == 1
        if first:
            first_entered.set()
            assert allow_first.wait(2)
        return True

    lease = windows_state._WindowsNamedMutexLease(
        SimpleNamespace(CloseHandle=close),
        123,
        "poison-drain-owner",
        poisoned=True,
        mutex_released=True,
    )
    registry = WindowsNamedDisplayTransactionMutex._poisoned_native_leases
    registry.clear()
    getattr(WindowsNamedDisplayTransactionMutex, "_poisoned_native_claims", {}).clear()
    registry[lease.display_key] = lease
    first_results: list[int] = []
    worker = threading.Thread(target=lambda: first_results.append(windows_state._drain_poisoned_native_leases(limit=1)))
    worker.start()
    assert first_entered.wait(2)
    try:
        second_result = windows_state._drain_poisoned_native_leases(limit=1)
        assert second_result == 0
        assert calls == [123]
    finally:
        allow_first.set()
        worker.join(2)
        registry.clear()
        getattr(WindowsNamedDisplayTransactionMutex, "_poisoned_native_claims", {}).clear()

    assert not worker.is_alive()
    assert first_results == [1]
    assert calls == [123]


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("result publish"), SystemExit(96)])
def test_create_mutex_callback_exception_is_terminal_and_capacity_reusable(
    interruption: BaseException,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    closes: list[object] = []
    fail_create = True

    def create(*_args: object) -> int:
        if fail_create:
            raise interruption
        return 123

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(create),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(lambda _handle: True),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = f"result-publication-{type(interruption).__name__}"
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    with pytest.raises(type(interruption)) as caught:
        mutex.acquire(display_id)

    assert caught.value is interruption
    assert closes == []
    assert display_id.casefold() not in WindowsNamedDisplayTransactionMutex._pending_native_attempts

    fail_create = False
    lease = mutex.acquire(display_id)
    mutex.release(lease)
    assert closes == [123]


def test_create_mutex_timeout_retains_carrier_until_late_exact_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    create_entered = threading.Event()
    allow_create = threading.Event()
    closed = threading.Event()
    creates = 0
    closes: list[object] = []

    def create(*_args: object) -> int:
        nonlocal creates
        creates += 1
        create_entered.set()
        assert allow_create.wait(2)
        return 123

    def close(handle: object) -> bool:
        closes.append(handle)
        closed.set()
        return True

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(create),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(lambda _handle: True),
        CloseHandle=Function(close),
    )
    display_id = "late-create-timeout"
    display_key = display_id.casefold()
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    monkeypatch.setattr(windows_state, "_WINDOWS_MUTEX_OWNER_WAIT_SECONDS", 0.01)
    pending_observed = False
    try:
        with pytest.raises(RuntimeError, match="bounded|timeout|settle"):
            mutex.acquire(display_id)
        assert create_entered.is_set()
        assert creates == 1
        pending_observed = (
            display_key in WindowsNamedDisplayTransactionMutex._pending_native_attempts
            and display_key in WindowsNamedDisplayTransactionMutex._pending_native_owners
        )
    finally:
        allow_create.set()
        closed.wait(2)
        WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_key)

    assert pending_observed is True
    assert closes == [123]
    assert display_key not in WindowsNamedDisplayTransactionMutex._pending_native_attempts
    assert display_key not in WindowsNamedDisplayTransactionMutex._pending_native_owners


def test_icc_capacity_reserves_pending_open_before_factory_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    class Lease:
        def validate_private_cache_identity(self, _path: str) -> None:
            return None

        def read_bytes(self) -> bytes:
            return b""

        def close(self) -> None:
            return None

    factory_entered = threading.Event()
    allow_factory = threading.Event()
    factory_calls: list[str] = []

    def factory(path: str) -> Lease:
        factory_calls.append(path)
        if len(factory_calls) == 1:
            factory_entered.set()
            assert allow_factory.wait(2)
        return Lease()

    registry = windows_state._RETAINED_ICC_LEASES
    registry.clear()
    monkeypatch.setattr(windows_state, "_MAX_RETAINED_ICC_LEASES", 1)
    ports = DefaultWindowsDisplayPorts(icc_file_lease_factory=factory)
    opened: list[object] = []
    worker = threading.Thread(target=lambda: opened.append(ports._open_icc_file_lease("first.icc")))
    worker.start()
    assert factory_entered.wait(2)
    try:
        with pytest.raises(RuntimeError, match="capacity|pending|retained"):
            ports._open_icc_file_lease("second.icc")
        assert factory_calls == ["first.icc"]
    finally:
        allow_factory.set()
        worker.join(2)

    assert not worker.is_alive()
    assert len(opened) == 1
    assert windows_state._close_icc_lease_once(opened[0]) is None  # type: ignore[arg-type]


def test_named_mutex_capacity_reserves_before_second_kernel_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    create_entered = threading.Event()
    allow_create = threading.Event()

    def create(*_args: object) -> int:
        create_entered.set()
        assert allow_create.wait(2)
        return 123

    first_kernel32 = SimpleNamespace(
        CreateMutexW=Function(create),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(lambda _handle: True),
        CloseHandle=Function(lambda _handle: True),
    )
    second_loads = 0

    def load_second() -> object:
        nonlocal second_loads
        second_loads += 1
        return first_kernel32

    monkeypatch.setattr(windows_state, "_MAX_POISONED_NATIVE_LEASES", 1)
    first_mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: first_kernel32)
    second_mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=load_second)
    leases: list[object] = []
    worker = threading.Thread(target=lambda: leases.append(first_mutex.acquire("first-capacity")))
    worker.start()
    assert create_entered.wait(2)
    try:
        with pytest.raises(RuntimeError, match="capacity|pending|active"):
            second_mutex.acquire("second-capacity")
        assert second_loads == 0
    finally:
        allow_create.set()
        worker.join(2)

    assert not worker.is_alive()
    assert len(leases) == 1
    first_mutex.release(leases[0])


def test_named_mutex_wait_and_release_run_on_one_owner_thread() -> None:
    caller_thread = threading.get_ident()
    calls: list[tuple[str, int]] = []

    class Function:
        def __init__(self, name: str, result: object) -> None:
            self.name = name
            self.result = result

        def __call__(self, *_args: object) -> object:
            calls.append((self.name, threading.get_ident()))
            return self.result

    kernel32 = SimpleNamespace(
        CreateMutexW=Function("create", 123),
        WaitForSingleObject=Function("wait", 0),
        ReleaseMutex=Function("release", True),
        CloseHandle=Function("close", True),
    )
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)

    lease = mutex.acquire("thread-affine-owner")
    mutex.release(lease)

    assert [name for name, _thread in calls] == ["create", "wait", "release", "close"]
    owner_threads = {thread for _name, thread in calls}
    assert len(owner_threads) == 1
    assert owner_threads != {caller_thread}


def test_named_mutex_busy_acquisition_cleanup_stays_on_owner_thread() -> None:
    caller_thread = threading.get_ident()
    calls: list[tuple[str, int]] = []

    class Function:
        def __init__(self, name: str, result: object) -> None:
            self.name = name
            self.result = result

        def __call__(self, *_args: object) -> object:
            calls.append((self.name, threading.get_ident()))
            return self.result

    kernel32 = SimpleNamespace(
        CreateMutexW=Function("create", 123),
        WaitForSingleObject=Function("wait", 0x102),
        ReleaseMutex=Function("release", True),
        CloseHandle=Function("close", True),
    )
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)

    with pytest.raises(RuntimeError, match="already held"):
        mutex.acquire("thread-affine-busy")

    assert [name for name, _thread in calls] == ["create", "wait", "close"]
    owner_threads = {thread for _name, thread in calls}
    assert len(owner_threads) == 1
    assert owner_threads != {caller_thread}


def test_named_mutex_late_acquisition_timeout_is_cleaned_by_same_owner_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, int]] = []
    create_entered = threading.Event()
    allow_create = threading.Event()
    closed = threading.Event()

    class Function:
        def __init__(self, name: str, result: object) -> None:
            self.name = name
            self.result = result

        def __call__(self, *_args: object) -> object:
            calls.append((self.name, threading.get_ident()))
            if self.name == "create":
                create_entered.set()
                assert allow_create.wait(2)
            if self.name == "close":
                closed.set()
            return self.result

    kernel32 = SimpleNamespace(
        CreateMutexW=Function("create", 123),
        WaitForSingleObject=Function("wait", 0),
        ReleaseMutex=Function("release", True),
        CloseHandle=Function("close", True),
    )
    monkeypatch.setattr(windows_state, "_WINDOWS_MUTEX_OWNER_WAIT_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(windows_state, "_NATIVE_CALL_SETTLE_TIMEOUT_SECONDS", 0.01)
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    try:
        with pytest.raises(RuntimeError, match="timeout|bounded|settle"):
            mutex.acquire("late-owner-timeout")
        assert create_entered.is_set()
    finally:
        allow_create.set()
        assert closed.wait(2)

    assert [name for name, _thread in calls] == ["create", "wait", "release", "close"]
    assert len({thread for _name, thread in calls}) == 1


def test_shutdown_releases_active_named_mutex_on_its_owner_thread() -> None:
    calls: list[tuple[str, int]] = []

    class Function:
        def __init__(self, name: str, result: object) -> None:
            self.name = name
            self.result = result

        def __call__(self, *_args: object) -> object:
            calls.append((self.name, threading.get_ident()))
            return self.result

    kernel32 = SimpleNamespace(
        CreateMutexW=Function("create", 123),
        WaitForSingleObject=Function("wait", 0),
        ReleaseMutex=Function("release", True),
        CloseHandle=Function("close", True),
    )
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    lease = mutex.acquire("shutdown-active-owner")

    windows_state._drain_adapter_lease_registries_at_shutdown()

    assert [name for name, _thread in calls] == ["create", "wait", "release", "close"]
    assert len({thread for _name, thread in calls}) == 1
    assert lease.native_handle is None  # type: ignore[attr-defined]


@REQUIRES_OPCODE_MONITORING
@pytest.mark.parametrize("domain", ["unclaimed", "icc", "native"])
def test_drain_claim_publication_cancellation_rolls_back_exact_claim(domain: str, unmeasured_tracing: None) -> None:
    if domain == "unclaimed":
        record = windows_state._UnclaimedMutexLease(SimpleNamespace(release=lambda _lease: None), object(), False)
        token = 99_001
        windows_state._UNCLAIMED_MUTEX_LEASES.clear()
        windows_state._UNCLAIMED_MUTEX_LEASES[token] = record
        function = windows_state._drain_unclaimed_mutex_leases
        marker = "record.drain_token = drain_token"
    elif domain == "icc":
        lease = SimpleNamespace(close=lambda: None)
        token = id(lease)
        windows_state._RETAINED_ICC_LEASES.clear()
        windows_state._RETAINED_ICC_LEASE_CLAIMS.clear()
        windows_state._RETAINED_ICC_LEASES[token] = lease
        function = windows_state._drain_retained_icc_leases
        marker = "_RETAINED_ICC_LEASE_CLAIMS[token] = drain_token"
    else:
        lease = windows_state._WindowsNamedMutexLease(
            SimpleNamespace(CloseHandle=lambda _handle: True),
            123,
            "claim-cancel-native",
            poisoned=True,
            mutex_released=True,
        )
        token = lease.display_key
        WindowsNamedDisplayTransactionMutex._poisoned_native_leases.clear()
        WindowsNamedDisplayTransactionMutex._poisoned_native_claims.clear()
        WindowsNamedDisplayTransactionMutex._poisoned_native_leases[token] = lease
        function = windows_state._drain_poisoned_native_leases
        marker = "_poisoned_native_claims[display_key] = drain_token"
    source, first_line = inspect.getsourcelines(function)
    claim_index = next(index for index, line in enumerate(source) if marker in line)
    claim_line = first_line + claim_index
    instructions = list(dis.get_instructions(function))
    store_index = next(
        index
        for index, instruction in enumerate(instructions)
        if instruction.positions.lineno == claim_line and instruction.opname in {"STORE_ATTR", "STORE_SUBSCR"}
    )
    target = instructions[store_index + 1].offset
    interruption = KeyboardInterrupt(f"{domain} claim publication")

    sys.settrace(_interrupt_at_opcode(function, target, interruption))
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            function(limit=1)
    finally:
        sys.settrace(None)
        _clear_opcode_interrupt()

    assert caught.value is interruption
    if domain == "unclaimed":
        assert windows_state._UNCLAIMED_MUTEX_LEASES[token] is record
        assert record.drain_token is None
        windows_state._UNCLAIMED_MUTEX_LEASES.clear()
    elif domain == "icc":
        assert windows_state._RETAINED_ICC_LEASES[token] is lease
        assert windows_state._RETAINED_ICC_LEASE_CLAIMS == {}
        windows_state._RETAINED_ICC_LEASES.clear()
    else:
        assert WindowsNamedDisplayTransactionMutex._poisoned_native_leases[token] is lease
        assert WindowsNamedDisplayTransactionMutex._poisoned_native_claims == {}
        WindowsNamedDisplayTransactionMutex._poisoned_native_leases.clear()


@REQUIRES_OPCODE_MONITORING
@pytest.mark.parametrize("domain", ["icc", "native"])
def test_capacity_reservation_return_cancellation_retires_pending_slot(domain: str, unmeasured_tracing: None) -> None:
    interruption = KeyboardInterrupt(f"{domain} reservation return")
    if domain == "icc":
        windows_state._ICC_LEASE_RESERVATIONS.clear()
        windows_state._ICC_LEASE_RESERVATION_BY_ID.clear()
        function = windows_state._reserve_icc_lease_capacity
        factory_calls: list[str] = []
        ports = DefaultWindowsDisplayPorts(
            icc_file_lease_factory=lambda path: factory_calls.append(path),  # type: ignore[arg-type,return-value]
        )
    else:
        WindowsNamedDisplayTransactionMutex._pending_native_attempts.clear()
        WindowsNamedDisplayTransactionMutex._pending_native_reservations.clear()
        WindowsNamedDisplayTransactionMutex._pending_native_owners.clear()
        function = WindowsNamedDisplayTransactionMutex._reserve_native_attempt.__func__
        loader_calls = 0

        def load_kernel32() -> object:
            nonlocal loader_calls
            loader_calls += 1
            raise AssertionError("kernel32 loader must not run after reservation-return cancellation")

        mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=load_kernel32)
    target = next(
        instruction.offset
        for instruction in dis.get_instructions(function)
        if instruction.opname.startswith("RETURN") and instruction.positions.lineno is not None
    )

    sys.settrace(_interrupt_at_opcode(function, target, interruption))
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            if domain == "icc":
                ports._open_icc_file_lease("reservation-return.icc")
            else:
                mutex.acquire("reservation-return")
    finally:
        sys.settrace(None)
        _clear_opcode_interrupt()

    assert caught.value is interruption
    if domain == "icc":
        assert windows_state._ICC_LEASE_RESERVATIONS == {}
        assert factory_calls == []
    else:
        assert "reservation-return" not in WindowsNamedDisplayTransactionMutex._pending_native_attempts
        assert "reservation-return" not in WindowsNamedDisplayTransactionMutex._pending_native_reservations
        assert loader_calls == 0


@pytest.mark.parametrize("domain", ["icc", "native"])
def test_terminal_retirement_cancellation_releases_claim_without_losing_evidence(
    domain: str, unmeasured_tracing: None
) -> None:
    interruption = KeyboardInterrupt(f"{domain} retirement")
    if domain == "icc":
        lease = SimpleNamespace(close=lambda: None)
        token = id(lease)
        windows_state._RETAINED_ICC_LEASES.clear()
        windows_state._RETAINED_ICC_LEASE_CLAIMS.clear()
        windows_state._RETAINED_ICC_LEASES[token] = lease
        function = windows_state._drain_retained_icc_leases
        marker = "_RETAINED_ICC_LEASES.pop(token, None)"
    else:
        lease = windows_state._WindowsNamedMutexLease(
            SimpleNamespace(CloseHandle=lambda _handle: True),
            123,
            "retirement-cancel-native",
            poisoned=True,
            mutex_released=True,
        )
        token = lease.display_key
        WindowsNamedDisplayTransactionMutex._poisoned_native_leases.clear()
        WindowsNamedDisplayTransactionMutex._poisoned_native_claims.clear()
        WindowsNamedDisplayTransactionMutex._poisoned_native_leases[token] = lease
        function = windows_state._drain_poisoned_native_leases
        marker = "lease.native_handle = None"
    source, first_line = inspect.getsourcelines(function)
    target_line = first_line + next(index for index, line in enumerate(source) if marker in line)

    def interrupt_retirement(frame: object, event: str, _arg: object) -> object:
        if (
            event == "line"
            and getattr(frame, "f_code", None) is function.__code__
            and getattr(frame, "f_lineno", None) == target_line
        ):
            sys.settrace(None)
            raise interruption
        return interrupt_retirement

    sys.settrace(interrupt_retirement)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            function(limit=1)
    finally:
        sys.settrace(None)

    assert caught.value is interruption
    if domain == "icc":
        assert windows_state._RETAINED_ICC_LEASE_CLAIMS == {}
        assert windows_state._RETAINED_ICC_LEASES.get(token) is lease
        windows_state._RETAINED_ICC_LEASES.clear()
    else:
        assert WindowsNamedDisplayTransactionMutex._poisoned_native_claims == {}
        retained = WindowsNamedDisplayTransactionMutex._poisoned_native_leases.get(token)
        assert retained is lease
        WindowsNamedDisplayTransactionMutex._poisoned_native_leases.clear()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("ICC post-pop retirement"), SystemExit(98)])
def test_icc_post_pop_retirement_cancellation_restores_exact_lease_and_reuses_capacity(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    close_calls = 0

    class Lease:
        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    lease = Lease()
    lease_id = id(lease)
    reservation_token = 91_338
    reservation = windows_state._IccLeaseReservation(
        token=reservation_token,
        lease=lease,
        retained=True,
    )
    retained = {lease_id: lease}
    claims: dict[int, int] = {}
    reservations = {reservation_token: reservation}
    reverse = {lease_id: reservation_token}
    monkeypatch.setattr(windows_state, "_RETAINED_ICC_LEASES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_ICC_LEASE_CLAIMS", claims)
    monkeypatch.setattr(windows_state, "_ICC_LEASE_RESERVATIONS", reservations)
    monkeypatch.setattr(windows_state, "_ICC_LEASE_RESERVATION_BY_ID", reverse)
    monkeypatch.setattr(windows_state, "_MAX_RETAINED_ICC_LEASES", 1)

    function = windows_state._drain_retained_icc_leases
    original_retire = windows_state._retire_icc_reservation_locked
    retire_calls = 0

    def interrupt_first_retirement(actual_lease: object) -> None:
        nonlocal retire_calls
        assert retained.get(lease_id) is None
        assert actual_lease is lease
        retire_calls += 1
        if retire_calls == 1:
            raise interruption
        original_retire(actual_lease)  # type: ignore[arg-type]

    monkeypatch.setattr(windows_state, "_retire_icc_reservation_locked", interrupt_first_retirement)
    with pytest.raises(type(interruption)) as caught:
        function(limit=1)

    assert caught.value is interruption
    assert close_calls == 1
    assert retire_calls == 1
    assert retained.get(lease_id) is lease
    assert claims == {}
    assert reservations.get(reservation_token) is reservation
    assert reverse.get(lease_id) == reservation_token

    assert function(limit=1) == 1
    assert close_calls == 2
    assert retained == {}
    assert claims == {}
    assert reservations == {}
    assert reverse == {}

    reusable_token = windows_state._reserve_icc_lease_capacity()
    windows_state._retire_pending_icc_lease_reservation(reusable_token)
    assert reservations == {}


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("ICC forget retirement"), SystemExit(99)])
def test_forget_icc_lease_retirement_cancellation_restores_exact_lease_and_reuses_capacity(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    close_calls = 0

    class Lease:
        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    class InterruptAfterPop(dict[int, int]):
        armed = True

        def pop(self, key: int, default: object = None) -> object:
            value = super().pop(key, default)  # type: ignore[arg-type]
            if self.armed:
                self.armed = False
                raise interruption
            return value

    lease = Lease()
    lease_id = id(lease)
    reservation_token = 91_339
    reservation = windows_state._IccLeaseReservation(
        token=reservation_token,
        lease=lease,
        retained=True,
    )
    retained = {lease_id: lease}
    claims: dict[int, int] = {}
    reservations = {reservation_token: reservation}
    reverse = InterruptAfterPop({lease_id: reservation_token})
    monkeypatch.setattr(windows_state, "_RETAINED_ICC_LEASES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_ICC_LEASE_CLAIMS", claims)
    monkeypatch.setattr(windows_state, "_ICC_LEASE_RESERVATIONS", reservations)
    monkeypatch.setattr(windows_state, "_ICC_LEASE_RESERVATION_BY_ID", reverse)
    monkeypatch.setattr(windows_state, "_MAX_RETAINED_ICC_LEASES", 1)

    with pytest.raises(type(interruption)) as caught:
        windows_state._forget_icc_lease(lease)

    assert caught.value is interruption
    assert retained.get(lease_id) is lease
    assert claims == {}
    assert reservations.get(reservation_token) is reservation
    assert reverse.get(lease_id) == reservation_token

    assert windows_state._drain_retained_icc_leases(limit=1) == 1
    assert close_calls == 1
    assert retained == {}
    assert claims == {}
    assert reservations == {}
    assert reverse == {}

    reusable_token = windows_state._reserve_icc_lease_capacity()
    windows_state._retire_pending_icc_lease_reservation(reusable_token)
    assert reservations == {}


def test_stale_terminal_owner_publication_preserves_new_pending_generation() -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(lambda _handle: True),
        CloseHandle=Function(lambda _handle: True),
    )
    display_id = "terminal-publication-generation"
    display_key = display_id.casefold()
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    lease = mutex.acquire(display_id)
    owner = lease.owner  # type: ignore[attr-defined]
    assert owner is not None

    command_completed = threading.Event()
    allow_stale_publication = threading.Event()
    release_errors: list[BaseException] = []
    original_command = owner.command

    def pause_after_owner_terminal(action: object) -> None:
        original_command(action)  # type: ignore[arg-type]
        command_completed.set()
        assert allow_stale_publication.wait(2)

    def release_worker() -> None:
        try:
            mutex.release(lease)
        except BaseException as exc:
            release_errors.append(exc)

    owner.command = pause_after_owner_terminal  # type: ignore[method-assign]
    release_thread = threading.Thread(target=release_worker)
    new_reservation = object()
    new_owner = windows_state._WindowsMutexOwner(
        kernel32,
        "new-generation",
        display_key,
        WindowsNamedDisplayTransactionMutex._owner_registry_state,
    )
    try:
        release_thread.start()
        assert command_completed.wait(2)
        WindowsNamedDisplayTransactionMutex._reserve_native_attempt(display_key, new_reservation)
        WindowsNamedDisplayTransactionMutex._publish_pending_owner(display_key, new_reservation, new_owner)
        with WindowsNamedDisplayTransactionMutex._poison_guard:
            WindowsNamedDisplayTransactionMutex._transient_native_quarantines[display_key] = new_owner
        allow_stale_publication.set()
        release_thread.join(2)

        assert not release_thread.is_alive()
        assert release_errors == []
        with WindowsNamedDisplayTransactionMutex._poison_guard:
            assert display_key in WindowsNamedDisplayTransactionMutex._pending_native_attempts
            assert WindowsNamedDisplayTransactionMutex._pending_native_reservations.get(display_key) is new_reservation
            assert WindowsNamedDisplayTransactionMutex._pending_native_owners.get(display_key) is new_owner
            assert WindowsNamedDisplayTransactionMutex._transient_native_quarantines.get(display_key) is new_owner
    finally:
        allow_stale_publication.set()
        release_thread.join(2)
        WindowsNamedDisplayTransactionMutex._retire_native_reservation(display_key, new_reservation)
        with WindowsNamedDisplayTransactionMutex._poison_guard:
            quarantines = getattr(WindowsNamedDisplayTransactionMutex, "_transient_native_quarantines", None)
            if quarantines is not None:
                quarantines.pop(display_key, None)


def test_late_success_after_release_timeout_clears_matching_transient_quarantine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    release_entered = threading.Event()
    allow_release = threading.Event()
    closes: list[object] = []

    def delayed_release(_handle: object) -> bool:
        release_entered.set()
        assert allow_release.wait(2)
        return True

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(delayed_release),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = "late-success-quarantine"
    display_key = display_id.casefold()
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    monkeypatch.setattr(windows_state, "_WINDOWS_MUTEX_OWNER_WAIT_SECONDS", 0.01)
    lease = mutex.acquire(display_id)
    owner = lease.owner  # type: ignore[attr-defined]
    assert owner is not None
    try:
        with pytest.raises(RuntimeError, match="command did not settle"):
            mutex.release(lease)
        assert release_entered.is_set()
        allow_release.set()
        owner.thread.join(2)

        assert not owner.thread.is_alive()
        assert closes == [123]
        with WindowsNamedDisplayTransactionMutex._poison_guard:
            assert display_key not in WindowsNamedDisplayTransactionMutex._poisoned_display_keys
            assert display_key not in WindowsNamedDisplayTransactionMutex._transient_native_quarantines

        replacement = mutex.acquire(display_id)
        mutex.release(replacement)
    finally:
        allow_release.set()
        owner.thread.join(2)
        with WindowsNamedDisplayTransactionMutex._poison_guard:
            WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_key)
            WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._active_native_leases.pop(display_key, None)
            quarantines = getattr(WindowsNamedDisplayTransactionMutex, "_transient_native_quarantines", None)
            if quarantines is not None:
                quarantines.pop(display_key, None)


def test_queued_release_does_not_redispatch_after_first_outcome_is_uncertain() -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    first_release_entered = threading.Event()
    allow_first_release = threading.Event()
    interruption = KeyboardInterrupt("first queued release is uncertain")
    releases: list[object] = []
    closes: list[object] = []

    def uncertain_then_successful_release(handle: object) -> bool:
        releases.append(handle)
        if len(releases) == 1:
            first_release_entered.set()
            assert allow_first_release.wait(2)
            raise interruption
        return True

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(uncertain_then_successful_release),
        CloseHandle=Function(lambda handle: closes.append(handle) or True),
    )
    display_id = "queued-release-uncertainty"
    display_key = display_id.casefold()
    mutex = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    lease = mutex.acquire(display_id)
    owner = lease.owner  # type: ignore[attr-defined]
    assert owner is not None
    errors: list[BaseException] = []

    def release_worker() -> None:
        try:
            mutex.release(lease)
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=release_worker)
    second = threading.Thread(target=release_worker)
    try:
        first.start()
        assert first_release_entered.wait(2)
        second.start()
        with owner._condition:
            assert owner._condition.wait_for(lambda: len(owner._commands) == 1, timeout=2)
        allow_first_release.set()
        first.join(2)
        second.join(2)

        assert not first.is_alive()
        assert not second.is_alive()
        assert releases == [123]
        assert closes == []
        assert errors == [interruption, interruption]
        assert lease.native_handle == 123  # type: ignore[attr-defined]
    finally:
        allow_first_release.set()
        first.join(2)
        second.join(2)
        with WindowsNamedDisplayTransactionMutex._poison_guard:
            WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_key)
            WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._active_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._transient_native_quarantines.pop(display_key, None)


def test_native_pending_reservation_rolls_back_when_publication_is_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interruption = KeyboardInterrupt("pending attempt publication")

    class InterruptAfterAdd(set[str]):
        armed = True

        def add(self, value: str) -> None:
            super().add(value)
            if self.armed:
                self.armed = False
                raise interruption

    pending = InterruptAfterAdd()
    reservations: dict[str, object] = {}
    owners: dict[str, object] = {}
    monkeypatch.setattr(WindowsNamedDisplayTransactionMutex, "_pending_native_attempts", pending)
    monkeypatch.setattr(WindowsNamedDisplayTransactionMutex, "_pending_native_reservations", reservations)
    monkeypatch.setattr(WindowsNamedDisplayTransactionMutex, "_pending_native_owners", owners)
    reservation = object()

    with pytest.raises(KeyboardInterrupt) as caught:
        WindowsNamedDisplayTransactionMutex._reserve_native_attempt("atomic-pending", reservation)

    assert caught.value is interruption
    assert pending == set()
    assert reservations == {}
    assert owners == {}


def test_pending_owner_drain_retires_incomplete_ghost_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    pending = {"ghost-pending"}
    reservations: dict[str, object] = {}
    owners: dict[str, object] = {}
    monkeypatch.setattr(WindowsNamedDisplayTransactionMutex, "_pending_native_attempts", pending)
    monkeypatch.setattr(WindowsNamedDisplayTransactionMutex, "_pending_native_reservations", reservations)
    monkeypatch.setattr(WindowsNamedDisplayTransactionMutex, "_pending_native_owners", owners)

    drained = windows_state._drain_pending_native_owners(limit=1)

    assert drained == 1
    assert pending == set()
    assert reservations == {}
    assert owners == {}


def test_mutex_sink_claim_interruption_rolls_back_for_next_exact_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interruption = KeyboardInterrupt("sink cleanup claim")
    releases: list[object] = []

    class InterruptingRecord:
        def __init__(self, mutex: object) -> None:
            object.__setattr__(self, "mutex", mutex)
            object.__setattr__(self, "lease", None)
            object.__setattr__(self, "active", True)
            object.__setattr__(self, "drain_token", None)
            object.__setattr__(self, "armed", True)

        def __setattr__(self, name: str, value: object) -> None:
            object.__setattr__(self, name, value)
            if name == "drain_token" and value is not None and self.armed:
                object.__setattr__(self, "armed", False)
                raise interruption

    monkeypatch.setattr(windows_state, "_UnclaimedMutexLease", InterruptingRecord)
    windows_state._UNCLAIMED_MUTEX_LEASES.clear()
    lease = object()
    sink = windows_state._MutexAcquisitionSink(SimpleNamespace(release=releases.append))
    sink.__enter__()
    sink.publish(lease)
    primary = KeyboardInterrupt("caller exits")
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            sink.__exit__(KeyboardInterrupt, primary, None)
        assert caught.value is interruption
        assert sink._record.drain_token is None

        assert windows_state._drain_unclaimed_mutex_leases(limit=1) == 1
        assert releases == [lease]
        assert sink._token not in windows_state._UNCLAIMED_MUTEX_LEASES
    finally:
        windows_state._UNCLAIMED_MUTEX_LEASES.clear()


def test_icc_reservation_retirement_interruption_restores_both_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    interruption = KeyboardInterrupt("ICC reverse-index retirement")

    class InterruptAfterPop(dict[int, int]):
        armed = True

        def pop(self, key: int, default: object = None) -> object:
            value = super().pop(key, default)  # type: ignore[arg-type]
            if self.armed:
                self.armed = False
                raise interruption
            return value

    lease = SimpleNamespace(close=lambda: None)
    lease_id = id(lease)
    token = 91_337
    reservation = windows_state._IccLeaseReservation(token=token, lease=lease)
    reservations = {token: reservation}
    reverse = InterruptAfterPop({lease_id: token})
    monkeypatch.setattr(windows_state, "_ICC_LEASE_RESERVATIONS", reservations)
    monkeypatch.setattr(windows_state, "_ICC_LEASE_RESERVATION_BY_ID", reverse)
    monkeypatch.setattr(windows_state, "_RETAINED_ICC_LEASES", {})
    monkeypatch.setattr(windows_state, "_RETAINED_ICC_LEASE_CLAIMS", {})

    with pytest.raises(KeyboardInterrupt) as caught:
        windows_state._forget_icc_lease(lease)  # type: ignore[arg-type]

    assert caught.value is interruption
    assert reservations.get(token) is reservation
    assert reverse.get(lease_id) == token
    windows_state._forget_icc_lease(lease)  # type: ignore[arg-type]
    assert reservations == {}
    assert reverse == {}


def test_late_composite_release_reconciles_exact_adapter_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    release_entered = threading.Event()
    allow_release = threading.Event()

    def delayed_release(_handle: object) -> bool:
        release_entered.set()
        assert allow_release.wait(2)
        return True

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(delayed_release),
        CloseHandle=Function(lambda _handle: True),
    )
    production = ProductionDisplayTransactionMutex()
    production._windows = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=production)
    plan = make_plan()
    monkeypatch.setattr(windows_state, "_WINDOWS_MUTEX_OWNER_WAIT_SECONDS", 0.01)
    capture_authorized(adapter, plan)
    adapter.apply(plan)
    assert adapter.verify(plan) is True
    first_active = adapter._active
    assert first_active is not None
    composite = first_active.mutex_handles[-1]
    windows_lease = composite.windows_handle  # type: ignore[attr-defined]
    owner = windows_lease.owner  # type: ignore[attr-defined]
    assert owner is not None
    display_key = windows_lease.display_key  # type: ignore[attr-defined]
    try:
        with pytest.raises(RuntimeError, match="command did not settle"):
            adapter.commit(plan)
        assert release_entered.is_set()
        assert composite.process_handle is None  # type: ignore[attr-defined]
        assert composite.poisoned is False  # type: ignore[attr-defined]
        assert composite.transient_windows_owner is owner  # type: ignore[attr-defined]
        assert first_active.lease_poisoned is False
        assert adapter._active is first_active
        assert adapter._phase is windows_state._TransactionPhase.UNCERTAIN
        stale_observers = list(composite._release_observers)  # type: ignore[attr-defined]

        allow_release.set()
        owner.thread.join(2)
        assert not owner.thread.is_alive()
        assert composite.windows_handle is None  # type: ignore[attr-defined]
        assert composite.transient_windows_owner is None  # type: ignore[attr-defined]
        assert composite.poisoned is False  # type: ignore[attr-defined]
        assert adapter._active is None
        assert adapter._phase is None

        second_snapshot = capture_authorized(adapter, plan)
        second_active = adapter._active
        assert second_active is not None
        for observer in stale_observers:
            observer(composite)
        assert adapter._active is second_active
        assert adapter._phase is windows_state._TransactionPhase.CAPTURED
        adapter.restore(second_snapshot)
    finally:
        allow_release.set()
        owner.thread.join(2)
        with WindowsNamedDisplayTransactionMutex._poison_guard:
            WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_key)
            WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._active_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._transient_native_quarantines.pop(display_key, None)


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("permanent release"), SystemExit(97)])
def test_permanent_composite_release_uncertainty_keeps_adapter_poisoned(interruption: BaseException) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(lambda _handle: (_ for _ in ()).throw(interruption)),
        CloseHandle=Function(lambda _handle: True),
    )
    production = ProductionDisplayTransactionMutex()
    production._windows = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=production)
    plan = make_plan()
    capture_authorized(adapter, plan)
    adapter.apply(plan)
    assert adapter.verify(plan) is True
    active = adapter._active
    assert active is not None
    composite = active.mutex_handles[-1]
    windows_lease = composite.windows_handle  # type: ignore[attr-defined]
    display_key = windows_lease.display_key  # type: ignore[attr-defined]
    try:
        with pytest.raises(type(interruption)) as caught:
            adapter.commit(plan)
        assert caught.value is interruption
        assert composite.process_handle is None  # type: ignore[attr-defined]
        assert composite.poisoned is True  # type: ignore[attr-defined]
        assert active.lease_poisoned is True
        assert adapter._active is active
        assert adapter._phase is windows_state._TransactionPhase.POISONED
    finally:
        with WindowsNamedDisplayTransactionMutex._poison_guard:
            WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_key)
            WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._active_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._transient_native_quarantines.pop(display_key, None)


def test_late_composite_failure_promotes_transient_adapter_to_permanent_poison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    release_entered = threading.Event()
    allow_release = threading.Event()
    reconciled = threading.Event()
    interruption = KeyboardInterrupt("late permanent release")

    def delayed_failure(_handle: object) -> bool:
        release_entered.set()
        assert allow_release.wait(2)
        raise interruption

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(delayed_failure),
        CloseHandle=Function(lambda _handle: True),
    )
    production = ProductionDisplayTransactionMutex()
    production._windows = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=production)
    plan = make_plan()
    monkeypatch.setattr(windows_state, "_WINDOWS_MUTEX_OWNER_WAIT_SECONDS", 0.01)
    capture_authorized(adapter, plan)
    adapter.apply(plan)
    assert adapter.verify(plan) is True
    active = adapter._active
    assert active is not None
    composite = active.mutex_handles[-1]
    windows_lease = composite.windows_handle  # type: ignore[attr-defined]
    display_key = windows_lease.display_key  # type: ignore[attr-defined]
    production.observe_release(composite, lambda _handle: reconciled.set())
    try:
        with pytest.raises(RuntimeError, match="command did not settle"):
            adapter.commit(plan)
        assert release_entered.is_set()
        assert active.lease_poisoned is False
        assert adapter._phase is windows_state._TransactionPhase.UNCERTAIN

        allow_release.set()
        assert reconciled.wait(2)
        assert composite.poisoned is True  # type: ignore[attr-defined]
        assert composite.windows_handle is windows_lease  # type: ignore[attr-defined]
        assert active.lease_poisoned is True
        assert adapter._active is active
        assert adapter._phase is windows_state._TransactionPhase.POISONED
    finally:
        allow_release.set()
        with WindowsNamedDisplayTransactionMutex._poison_guard:
            WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_key)
            WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._active_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._transient_native_quarantines.pop(display_key, None)


def test_composite_settlement_during_release_does_not_pop_adapter_evidence_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    @dataclass
    class ProcessLease:
        released: bool = False

    class BlockingProcessMutex:
        def __init__(self) -> None:
            self.release_entered = threading.Event()
            self.allow_release = threading.Event()

        def acquire(self, _display_id: str) -> ProcessLease:
            return ProcessLease()

        def release(self, lease: ProcessLease) -> None:
            self.release_entered.set()
            assert self.allow_release.wait(2)
            lease.released = True

        @staticmethod
        def is_released(lease: ProcessLease) -> bool:
            return lease.released

    windows_release_entered = threading.Event()
    allow_windows_release = threading.Event()
    windows_closed = threading.Event()

    def delayed_windows_release(_handle: object) -> bool:
        windows_release_entered.set()
        assert allow_windows_release.wait(2)
        return True

    kernel32 = SimpleNamespace(
        CreateMutexW=Function(lambda *_args: 123),
        WaitForSingleObject=Function(lambda *_args: 0),
        ReleaseMutex=Function(delayed_windows_release),
        CloseHandle=Function(lambda _handle: windows_closed.set() or True),
    )
    process = BlockingProcessMutex()
    production = ProductionDisplayTransactionMutex()
    production._process = process  # type: ignore[assignment]
    production._windows = WindowsNamedDisplayTransactionMutex(kernel32_loader=lambda: kernel32)
    adapter = make_adapter(FakeWindowsDisplayPorts(), transaction_mutex=production)
    plan = make_plan()
    monkeypatch.setattr(windows_state, "_WINDOWS_MUTEX_OWNER_WAIT_SECONDS", 0.01)
    capture_authorized(adapter, plan)
    adapter.apply(plan)
    assert adapter.verify(plan) is True
    active = adapter._active
    assert active is not None
    composite = active.mutex_handles[-1]
    windows_lease = composite.windows_handle  # type: ignore[attr-defined]
    display_key = windows_lease.display_key  # type: ignore[attr-defined]
    errors: list[BaseException] = []

    def commit_worker() -> None:
        try:
            adapter.commit(plan)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=commit_worker)
    try:
        worker.start()
        assert windows_release_entered.wait(2)
        assert process.release_entered.wait(2)
        allow_windows_release.set()
        assert windows_closed.wait(2)
        assert adapter._active is active
        assert active.mutex_handles == [composite]

        process.allow_release.set()
        worker.join(2)
        assert not worker.is_alive()
        assert errors == []
        assert active.mutex_handles == []
        assert adapter._active is None
        assert adapter._phase is None
    finally:
        allow_windows_release.set()
        process.allow_release.set()
        worker.join(2)
        with WindowsNamedDisplayTransactionMutex._poison_guard:
            WindowsNamedDisplayTransactionMutex._poisoned_display_keys.discard(display_key)
            WindowsNamedDisplayTransactionMutex._poisoned_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._active_native_leases.pop(display_key, None)
            WindowsNamedDisplayTransactionMutex._transient_native_quarantines.pop(display_key, None)


def _post_call_offset(function: object, source_fragment: str) -> int:
    if not _OPCODE_MONITORING_AVAILABLE:
        pytest.skip("opcode-level cancellation injection requires sys.monitoring (Python 3.12+)")
    source, first_line = inspect.getsourcelines(function)
    call_line = first_line + next(index for index, line in enumerate(source) if source_fragment in line)
    instructions = list(dis.get_instructions(function))  # type: ignore[arg-type]
    call_index = [
        index
        for index, instruction in enumerate(instructions)
        if instruction.positions.lineno == call_line and instruction.opname == "CALL"
    ][-1]
    return instructions[call_index + 1].offset


class _R4CtypesFunction:
    def __init__(self, callback: object) -> None:
        self.callback = callback

    def __call__(self, *args: object) -> object:
        return self.callback(*args)  # type: ignore[operator]


def _r4_kernel32(create: object, close: object) -> object:
    inert = _R4CtypesFunction(lambda *_args: True)
    return SimpleNamespace(
        CreateFileW=_R4CtypesFunction(create),
        GetFileSizeEx=inert,
        ReadFile=inert,
        SetFilePointerEx=inert,
        GetFileInformationByHandle=inert,
        GetFileType=_R4CtypesFunction(lambda *_args: 1),
        GetFinalPathNameByHandleW=_R4CtypesFunction(lambda *_args: 1),
        CloseHandle=_R4CtypesFunction(close),
    )


def _isolate_r4_native_registries(monkeypatch: pytest.MonkeyPatch) -> tuple[dict[int, object], dict[int, object]]:
    managed: dict[int, object] = {}
    retained: dict[int, object] = {}
    monkeypatch.setattr(windows_state, "_MANAGED_NATIVE_CALLS", managed)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained, raising=False)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", {}, raising=False)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_KEYS", {}, raising=False)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_TERMINALS", {}, raising=False)
    monkeypatch.setattr(windows_state, "_MAX_MANAGED_NATIVE_RESOURCES", 1, raising=False)
    return managed, retained


def _isolate_r4_icc_registries(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[int, object], dict[int, int], dict[int, object], dict[int, int]]:
    retained: dict[int, object] = {}
    claims: dict[int, int] = {}
    reservations: dict[int, object] = {}
    reverse: dict[int, int] = {}
    monkeypatch.setattr(windows_state, "_RETAINED_ICC_LEASES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_ICC_LEASE_CLAIMS", claims)
    monkeypatch.setattr(windows_state, "_ICC_LEASE_RESERVATIONS", reservations)
    monkeypatch.setattr(windows_state, "_ICC_LEASE_RESERVATION_BY_ID", reverse)
    monkeypatch.setattr(windows_state, "_MAX_RETAINED_ICC_LEASES", 1)
    return retained, claims, reservations, reverse


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("ICC caller handoff"), SystemExit(110)])
@pytest.mark.parametrize("caller", ["capture", "cache", "activate"])
def test_icc_callers_recover_post_helper_call_lease_before_store_and_reuse_capacity(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    caller: str,
) -> None:
    close_calls = 0

    class Lease:
        def validate_private_cache_identity(self, _path: str) -> None:
            return None

        def read_bytes(self) -> bytes:
            return valid_icc_payload(b"r4-caller")

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    lease = Lease()
    retained, claims, reservations, reverse = _isolate_r4_icc_registries(monkeypatch)
    installer = SimpleNamespace(
        get_default_profile_for_display=lambda _display_id: "caller.icc",
        get_profile_directory=lambda: "C:/Color",
    )
    ports = DefaultWindowsDisplayPorts(
        module_loader=lambda _name: installer,
        icc_file_lease_factory=lambda _path: lease,  # type: ignore[arg-type]
    )
    if caller == "capture":
        function = DefaultWindowsDisplayPorts.capture_icc_profile

        def invoke() -> object:
            return ports.capture_icc_profile("display-1")

    elif caller == "cache":
        function = DefaultWindowsDisplayPorts._read_private_cache_entry

        def invoke() -> object:
            return ports._read_private_cache_entry(Path("C:/Color/caller.icc"))

    else:
        function = DefaultWindowsDisplayPorts.activate_icc_profile
        payload = valid_icc_payload(b"r4-activation")
        profile = IccProfileSnapshot("C:/Color/caller.icc", payload, sha256_bytes(payload))

        def invoke() -> object:
            return ports.activate_icc_profile("display-1", profile, register=False, associate=False)

    target = _post_call_offset(function, "lease = self._open_icc_file_lease")

    _interrupt_at_opcode(function, target, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            invoke()
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert close_calls == 1
    assert retained == {}
    assert claims == {}
    assert reservations == {}
    assert reverse == {}
    assert windows_state._drain_retained_icc_leases(limit=1) == 0
    reusable = windows_state._reserve_icc_lease_capacity()
    windows_state._retire_pending_icc_lease_reservation(reusable)
    assert reservations == {}


def test_createfile_timeout_retains_uncertain_late_handle_until_exact_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    allow = threading.Event()
    cleanup_calls: list[object] = []

    def create(*_args: object) -> int:
        entered.set()
        assert allow.wait(2)
        return 401

    def close(handle: object) -> bool:
        cleanup_calls.append(handle)
        return len(cleanup_calls) > 1

    managed, retained = _isolate_r4_native_registries(monkeypatch)
    monkeypatch.setattr(windows_state, "_NATIVE_CALL_SETTLE_TIMEOUT_SECONDS", 0.01)
    kernel32 = _r4_kernel32(create, close)
    try:
        with pytest.raises(RuntimeError, match="bounded|settle"):
            windows_state._WindowsIccFileLease("blocked.icc", kernel32_loader=lambda: kernel32)
        assert entered.is_set()
        assert len(managed) == 1
        state = next(iter(managed.values()))
    finally:
        allow.set()
    assert state._event.wait(2)  # type: ignore[attr-defined]

    assert cleanup_calls == [401]
    assert managed == {}
    assert len(retained) == 1
    assert windows_state._drain_retained_native_resources(limit=1) == 1
    assert cleanup_calls == [401, 401]
    assert retained == {}
    reusable = windows_state._NativeCallState(lambda: None, orphan_cleanup=lambda _value: True)
    reusable.handoff()
    assert managed == {}


def test_native_resource_thread_start_failure_retires_unentered_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed, retained = _isolate_r4_native_registries(monkeypatch)
    state = windows_state._NativeCallState(
        lambda: object(),
        orphan_cleanup=lambda _value: True,
        orphan_retain=lambda _value, _uncertain: None,
    )
    monkeypatch.setattr(
        state._thread,  # type: ignore[attr-defined]
        "start",
        lambda: (_ for _ in ()).throw(RuntimeError("thread start rejected")),
    )

    with pytest.raises(RuntimeError, match="thread start rejected"):
        state.invoke()

    assert managed == {}
    assert retained == {}
    reusable = windows_state._NativeCallState(lambda: None, orphan_cleanup=lambda _value: True)
    reusable.handoff()
    assert managed == {}


def _native_start_dispatch_offsets() -> tuple[int, ...]:
    if not _OPCODE_MONITORING_AVAILABLE:
        return (0,)
    function = windows_state._NativeCallState._start
    source, first_line = inspect.getsourcelines(function)
    call_line = first_line + next(
        index
        for index, line in enumerate(source)
        if "self._call_thread_start()" in line or "self._thread.start()" in line
    )
    instructions = list(dis.get_instructions(function))
    call_indexes = [
        index
        for index, instruction in enumerate(instructions)
        if instruction.positions.lineno == call_line and instruction.opname == "CALL"
    ]
    assert len(call_indexes) == 1
    call_index = call_indexes[0]
    first_line_index = next(
        index for index, instruction in enumerate(instructions) if instruction.positions.lineno == call_line
    )
    return tuple(instruction.offset for instruction in instructions[first_line_index : call_index + 1])


@REQUIRES_OPCODE_MONITORING
@pytest.mark.parametrize("interruption", [KeyboardInterrupt("pre-start cancellation"), SystemExit(114)])
@pytest.mark.parametrize("start_offset", _native_start_dispatch_offsets())
def test_native_resource_pre_dispatch_cancellation_retires_all_pending_capacity(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    start_offset: int,
) -> None:
    factory_calls = 0

    def factory(_path: str) -> object:
        nonlocal factory_calls
        factory_calls += 1
        return object()

    managed, native_retained = _isolate_r4_native_registries(monkeypatch)
    retained, claims, reservations, reverse = _isolate_r4_icc_registries(monkeypatch)
    ports = DefaultWindowsDisplayPorts(icc_file_lease_factory=factory)  # type: ignore[arg-type]

    _interrupt_at_opcode(windows_state._NativeCallState._start, start_offset, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            ports._open_icc_file_lease("pre-start-cancel.icc")
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert factory_calls == 0
    assert managed == {}
    assert native_retained == {}
    assert retained == {}
    assert claims == {}
    assert reservations == {}
    assert reverse == {}

    reusable_state = windows_state._NativeCallState(lambda: None, orphan_cleanup=lambda _value: True)
    reusable_state.handoff()
    reusable_reservation = windows_state._reserve_icc_lease_capacity()
    windows_state._retire_pending_icc_lease_reservation(reusable_reservation)
    assert managed == {}
    assert reservations == {}


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("ambiguous thread start"), SystemExit(115)])
def test_native_resource_ambiguous_thread_start_retains_exact_capacity_until_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    entered = threading.Event()
    allow = threading.Event()
    resource = object()
    cleanup_calls: list[object] = []
    start_calls = 0

    def callback() -> object:
        entered.set()
        assert allow.wait(2)
        return resource

    managed, retained = _isolate_r4_native_registries(monkeypatch)
    state = windows_state._NativeCallState(
        callback,
        orphan_cleanup=lambda value: cleanup_calls.append(value) or True,
        orphan_retain=lambda _value, _uncertain: None,
    )
    runner = threading.Thread(target=state._run, daemon=True)  # type: ignore[attr-defined]

    class AmbiguousStart:
        ident = None

        def start(self) -> None:
            nonlocal start_calls
            start_calls += 1
            runner.start()
            assert entered.wait(2)
            raise interruption

    state._thread = AmbiguousStart()  # type: ignore[assignment]
    monkeypatch.setattr(windows_state, "_NATIVE_CALL_SETTLE_TIMEOUT_SECONDS", 0.01)
    try:
        with pytest.raises(type(interruption)) as caught:
            state.invoke()
        assert caught.value is interruption
        assert entered.is_set()
        with pytest.raises(RuntimeError, match="bounded|settle"):
            state.invoke()
        assert start_calls == 1
        assert list(managed.values()) == [state]
        assert retained == {}
        with pytest.raises(RuntimeError, match="capacity|active|pending|retained"):
            windows_state._NativeCallState(lambda: None, orphan_cleanup=lambda _value: True)
    finally:
        allow.set()

    assert state._event.wait(2)  # type: ignore[attr-defined]
    assert cleanup_calls == [resource]
    assert managed == {}
    assert retained == {}
    reusable = windows_state._NativeCallState(lambda: None, orphan_cleanup=lambda _value: True)
    reusable.handoff()
    assert managed == {}


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("CreateFileW in flight"), SystemExit(111)])
def test_createfile_inflight_cancellation_late_closes_exact_handle_once(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    entered = threading.Event()
    allow = threading.Event()
    cleanup_calls: list[object] = []

    def create(*_args: object) -> int:
        entered.set()
        assert allow.wait(2)
        return 402

    managed, retained = _isolate_r4_native_registries(monkeypatch)
    kernel32 = _r4_kernel32(create, lambda handle: cleanup_calls.append(handle) or True)
    target = _post_call_offset(windows_state._NativeCallState.invoke, "self._start()")
    _interrupt_at_opcode_after_event(windows_state._NativeCallState.invoke, target, interruption, entered)
    try:
        with pytest.raises(type(interruption)) as caught:
            windows_state._WindowsIccFileLease("cancel.icc", kernel32_loader=lambda: kernel32)
        assert caught.value is interruption
        assert len(managed) == 1
        state = next(iter(managed.values()))
    finally:
        _clear_opcode_interrupt()
        allow.set()
    assert state._event.wait(2)  # type: ignore[attr-defined]
    assert cleanup_calls == [402]
    assert managed == {}
    assert retained == {}


def test_icc_factory_timeout_keeps_reservation_until_uncertain_late_lease_drains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    allow = threading.Event()
    close_calls = 0

    class Lease:
        def validate_private_cache_identity(self, _path: str) -> None:
            return None

        def read_bytes(self) -> bytes:
            return b""

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1
            if close_calls <= 2:
                raise RuntimeError("late ICC close uncertain")

    lease = Lease()

    def factory(_path: str) -> Lease:
        entered.set()
        assert allow.wait(2)
        return lease

    managed, native_retained = _isolate_r4_native_registries(monkeypatch)
    retained, claims, reservations, reverse = _isolate_r4_icc_registries(monkeypatch)
    monkeypatch.setattr(windows_state, "_NATIVE_CALL_SETTLE_TIMEOUT_SECONDS", 0.01)
    ports = DefaultWindowsDisplayPorts(icc_file_lease_factory=factory)
    try:
        with pytest.raises(RuntimeError, match="bounded|settle"):
            ports._open_icc_file_lease("blocked-factory.icc")
        assert entered.is_set()
        assert len(managed) == 1
        assert len(reservations) == 1
        state = next(iter(managed.values()))
    finally:
        allow.set()
    assert state._event.wait(2)  # type: ignore[attr-defined]

    assert close_calls == 2
    assert managed == {}
    assert native_retained == {}
    assert retained == {id(lease): lease}
    assert claims == {}
    assert len(reservations) == 1
    assert reverse == {id(lease): next(iter(reservations))}
    assert windows_state._drain_retained_icc_leases(limit=1) == 1
    assert close_calls == 3
    assert retained == {}
    assert reservations == {}
    assert reverse == {}
    reopened = ports._open_icc_file_lease("reusable.icc")
    assert windows_state._close_icc_lease_once(reopened) is None


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("ICC factory in flight"), SystemExit(112)])
def test_icc_factory_inflight_cancellation_keeps_reservation_until_late_exact_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    entered = threading.Event()
    allow = threading.Event()
    close_calls = 0

    class Lease:
        def validate_private_cache_identity(self, _path: str) -> None:
            return None

        def read_bytes(self) -> bytes:
            return b""

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    lease = Lease()

    def factory(_path: str) -> Lease:
        entered.set()
        assert allow.wait(2)
        return lease

    managed, native_retained = _isolate_r4_native_registries(monkeypatch)
    retained, claims, reservations, reverse = _isolate_r4_icc_registries(monkeypatch)
    ports = DefaultWindowsDisplayPorts(icc_file_lease_factory=factory)
    target = _post_call_offset(windows_state._NativeCallState.invoke, "self._start()")
    _interrupt_at_opcode_after_event(windows_state._NativeCallState.invoke, target, interruption, entered)
    try:
        with pytest.raises(type(interruption)) as caught:
            ports._open_icc_file_lease("cancel-factory.icc")
        assert caught.value is interruption
        assert len(managed) == 1
        assert len(reservations) == 1
        state = next(iter(managed.values()))
    finally:
        _clear_opcode_interrupt()
        allow.set()
    assert state._event.wait(2)  # type: ignore[attr-defined]
    assert close_calls == 1
    assert managed == {}
    assert native_retained == {}
    assert retained == {}
    assert claims == {}
    assert reservations == {}
    assert reverse == {}


def test_ddc_controller_timeout_quarantines_uncertain_late_controller_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    allow = threading.Event()
    close_calls = 0

    class Controller:
        def __init__(self) -> None:
            entered.set()
            assert allow.wait(2)

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1
            if close_calls == 1:
                raise RuntimeError("late DDC close uncertain")

    module = SimpleNamespace(DDCCIController=Controller)
    managed, retained = _isolate_r4_native_registries(monkeypatch)
    monkeypatch.setattr(windows_state, "_NATIVE_CALL_SETTLE_TIMEOUT_SECONDS", 0.01)
    ports = DefaultWindowsDisplayPorts(module_loader=lambda _name: module)
    ownership = windows_state._DdcTargetOwnership()
    target = DdcTargetIdentity("display-1", "pnp:display-1")
    try:
        with pytest.raises(RuntimeError, match="bounded|settle"):
            ports._open_ddc_target(target, ownership)
        assert entered.is_set()
        assert ownership.controller is None
        assert len(managed) == 1
        state = next(iter(managed.values()))
    finally:
        allow.set()
    assert state._event.wait(2)  # type: ignore[attr-defined]
    assert close_calls == 1
    assert managed == {}
    assert len(retained) == 1
    quarantined = next(iter(retained.values()))
    assert quarantined.cleanup_uncertain is True  # type: ignore[attr-defined]
    assert windows_state._drain_retained_native_resources(limit=1) == 0
    assert close_calls == 1
    assert next(iter(retained.values())) is quarantined
    with pytest.raises(RuntimeError, match="capacity|active|pending|retained"):
        windows_state._NativeCallState(lambda: None, orphan_cleanup=lambda _value: True)
    assert managed == {}


@pytest.mark.parametrize("interruption", [KeyboardInterrupt("DDC controller in flight"), SystemExit(113)])
def test_ddc_controller_inflight_cancellation_late_closes_exact_controller_once(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    entered = threading.Event()
    allow = threading.Event()
    close_calls = 0

    class Controller:
        def __init__(self) -> None:
            entered.set()
            assert allow.wait(2)

        def close(self) -> None:
            nonlocal close_calls
            close_calls += 1

    module = SimpleNamespace(DDCCIController=Controller)
    managed, retained = _isolate_r4_native_registries(monkeypatch)
    ports = DefaultWindowsDisplayPorts(module_loader=lambda _name: module)
    ownership = windows_state._DdcTargetOwnership()
    target = DdcTargetIdentity("display-1", "pnp:display-1")
    invoke_target = _post_call_offset(windows_state._NativeCallState.invoke, "self._start()")
    _interrupt_at_opcode_after_event(
        windows_state._NativeCallState.invoke,
        invoke_target,
        interruption,
        entered,
    )
    try:
        with pytest.raises(type(interruption)) as caught:
            ports._open_ddc_target(target, ownership)
        assert caught.value is interruption
        assert ownership.controller is None
        assert len(managed) == 1
        state = next(iter(managed.values()))
    finally:
        _clear_opcode_interrupt()
        allow.set()
    assert state._event.wait(2)  # type: ignore[attr-defined]
    assert close_calls == 1
    assert managed == {}
    assert retained == {}


def _offset_after_source_instruction(
    function: object,
    source_fragment: str,
    opnames: set[str],
) -> int:
    if not _OPCODE_MONITORING_AVAILABLE:
        pytest.skip("opcode-level cancellation injection requires sys.monitoring (Python 3.12+)")
    source, first_line = inspect.getsourcelines(function)
    source_line = first_line + next(index for index, line in enumerate(source) if source_fragment in line)
    instructions = list(dis.get_instructions(function))  # type: ignore[arg-type]
    mutation_index = next(
        index
        for index, instruction in enumerate(instructions)
        if instruction.positions.lineno == source_line and instruction.opname in opnames
    )
    return instructions[mutation_index + 1].offset


@pytest.mark.parametrize(
    "interruption",
    [KeyboardInterrupt("managed token assignment"), SystemExit(116)],
)
def test_managed_native_token_assignment_cancellation_retires_published_slot(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    managed, retained = _isolate_r4_native_registries(monkeypatch)
    function = windows_state._NativeCallState.__init__
    target = _offset_after_source_instruction(
        function,
        "_under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, reserve)",
        {"CALL"},
    )

    _interrupt_at_opcode(function, target, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            windows_state._NativeCallState(
                lambda: object(),
                orphan_cleanup=lambda _resource: True,
            )
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert managed == {}
    assert retained == {}

    reusable = windows_state._NativeCallState(lambda: object(), orphan_cleanup=lambda _resource: True)
    reusable.handoff()
    assert managed == {}


@pytest.mark.parametrize(
    "interruption",
    [KeyboardInterrupt("managed registry publication"), SystemExit(117)],
)
def test_managed_native_registry_publication_failure_rolls_back_exact_slot(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    class InterruptAfterSet(dict[int, object]):
        armed = True

        def setdefault(self, key: int, value: object) -> object:
            published = super().setdefault(key, value)
            if self.armed:
                self.armed = False
                raise interruption
            return published

    managed = InterruptAfterSet()
    retained: dict[int, object] = {}
    monkeypatch.setattr(windows_state, "_MANAGED_NATIVE_CALLS", managed)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", {})
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_KEYS", {})
    monkeypatch.setattr(windows_state, "_MAX_MANAGED_NATIVE_RESOURCES", 1)

    with pytest.raises(type(interruption)) as caught:
        windows_state._NativeCallState(
            lambda: object(),
            orphan_cleanup=lambda _resource: True,
        )

    assert caught.value is interruption
    assert managed == {}
    assert retained == {}

    reusable = windows_state._NativeCallState(lambda: object(), orphan_cleanup=lambda _resource: True)
    reusable.handoff()
    assert managed == {}


@pytest.mark.parametrize("boundary", ["claim", "candidate"])
@pytest.mark.parametrize(
    "interruption",
    [KeyboardInterrupt("retained native drain handoff"), SystemExit(118)],
)
def test_retained_native_drain_handoff_cancellation_releases_claim_and_preserves_evidence(
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    interruption: BaseException,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []
    record = windows_state._RetainedNativeResource(
        resource,
        lambda value: cleanup_calls.append(value) or True,
        False,
    )
    token = 93_001
    retained = {token: record}
    claims: dict[int, int] = {}
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", claims)
    function = windows_state._drain_retained_native_resources
    if boundary == "claim":
        target = _offset_after_source_instruction(
            function,
            "candidates = _under_interruption_safe_lock",
            {"STORE_FAST"},
        )
    else:
        target = _offset_after_source_instruction(
            function,
            "drained = 0",
            {"STORE_FAST"},
        )

    _interrupt_at_opcode(function, target, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            function(limit=1)
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert retained == {token: record}
    assert claims == {}
    assert cleanup_calls == []

    assert function(limit=1) == 1
    assert cleanup_calls == [resource]
    assert retained == {}
    assert claims == {}


def test_falsy_native_resources_receive_exact_once_orphan_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FalsyResource:
        def __bool__(self) -> bool:
            return False

    managed, retained = _isolate_r4_native_registries(monkeypatch)
    resources: tuple[object, ...] = (0, FalsyResource())
    cleanup_calls: list[object] = []

    for resource in resources:
        state = windows_state._NativeCallState(
            lambda value=resource: value,
            orphan_cleanup=lambda value: cleanup_calls.append(value) or True,
            orphan_retain=lambda _value, _uncertain: (_ for _ in ()).throw(
                AssertionError("successfully cleaned resource must not be retained")
            ),
        )
        cause = RuntimeError("caller abandoned native result")
        state._finish_orphan(resource, cause)
        state._finish_orphan(resource, cause)

    assert cleanup_calls == list(resources)
    assert managed == {}
    assert retained == {}


def test_cleanup_uncertain_native_evidence_is_quarantined_for_manual_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []
    record = windows_state._RetainedNativeResource(
        resource,
        lambda value: cleanup_calls.append(value) or True,
        True,
    )
    token = 93_002
    managed, retained = _isolate_r4_native_registries(monkeypatch)
    retained[token] = record

    assert windows_state._drain_retained_native_resources(limit=1) == 0
    assert windows_state._drain_retained_native_resources(limit=1) == 0
    assert cleanup_calls == []
    assert retained == {token: record}
    assert retained[token].cleanup_uncertain is True  # type: ignore[attr-defined]

    with pytest.raises(RuntimeError, match="capacity|active|pending|retained"):
        windows_state._NativeCallState(lambda: object(), orphan_cleanup=lambda _resource: True)

    assert managed == {}
    assert retained == {token: record}


@pytest.mark.parametrize(
    "interruption",
    [KeyboardInterrupt("cleanup outcome unknown"), SystemExit(119)],
)
def test_retained_native_cleanup_interruption_becomes_non_retryable_uncertain_evidence(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []

    def cleanup(value: object) -> bool:
        cleanup_calls.append(value)
        if len(cleanup_calls) == 1:
            raise interruption
        return True

    record = windows_state._RetainedNativeResource(resource, cleanup, False)
    token = 93_003
    retained = {token: record}
    claims: dict[int, int] = {}
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", claims)

    assert windows_state._drain_retained_native_resources(limit=1) == 0
    assert cleanup_calls == [resource]
    quarantined = retained[token]
    assert quarantined.cleanup_uncertain is True
    assert claims == {}

    assert windows_state._drain_retained_native_resources(limit=1) == 0
    assert cleanup_calls == [resource]
    assert retained[token] is quarantined
    assert claims == {}


@pytest.mark.parametrize(
    "interruption",
    [KeyboardInterrupt("orphan claim publication"), SystemExit(120)],
)
@pytest.mark.parametrize(
    ("boundary", "source_fragment", "opnames"),
    [
        ("carrier", "carrier = self._orphan_carriers.setdefault(slot, candidate)", {"STORE_DEREF"}),
        ("claim", "claim = self._acquire_orphan_claim(carrier, slot)", {"STORE_DEREF"}),
        (
            "cleanup-result",
            "cleaned = bool(carrier.cleanup_results[0]) if carrier.cleanup_results else False",
            {"STORE_FAST"},
        ),
        (
            "resolved",
            "if not _under_interruption_safe_lock(carrier.claim_guard, resolve):",
            {"CALL"},
        ),
    ],
)
def test_orphan_handoff_cancellation_keeps_exact_resource_retryable_and_releases_capacity(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
    boundary: str,
    source_fragment: str,
    opnames: set[str],
) -> None:
    resource = object()
    cleanup_calls: list[object] = []
    managed, retained = _isolate_r4_native_registries(monkeypatch)
    state = windows_state._NativeCallState(
        lambda: resource,
        orphan_cleanup=lambda value: cleanup_calls.append(value) or True,
        orphan_retain=lambda _value, _uncertain: (_ for _ in ()).throw(
            AssertionError("successfully cleaned resource must not be retained")
        ),
    )
    function = windows_state._NativeCallState._finish_orphan_once
    target = _offset_after_source_instruction(
        function,
        source_fragment,
        opnames,
    )

    _interrupt_at_opcode(function, target, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            state._finish_orphan(resource, RuntimeError("caller abandoned result"))
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert state._outcome_guard.acquire(blocking=False)  # type: ignore[attr-defined]
    state._outcome_guard.release()  # type: ignore[attr-defined]
    assert state._orphan_carriers[0].resource is resource  # type: ignore[attr-defined]
    assert cleanup_calls == [resource]
    assert managed == {}
    assert retained == {}

    state._finish_orphan(resource, RuntimeError("retry orphan cleanup"))
    assert cleanup_calls == [resource]
    assert managed == {}
    assert retained == {}

    reusable = windows_state._NativeCallState(lambda: object(), orphan_cleanup=lambda _value: True)
    reusable.handoff()
    assert managed == {}


@pytest.mark.parametrize(
    "interruption",
    [KeyboardInterrupt("orphan claim takeover"), SystemExit(121)],
)
def test_orphan_dead_claim_takeover_cancellation_is_resumable_without_duplicate_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []
    managed, retained = _isolate_r4_native_registries(monkeypatch)
    state = windows_state._NativeCallState(
        lambda: resource,
        orphan_cleanup=lambda value: cleanup_calls.append(value) or True,
    )
    dead_owner = threading.Thread(target=lambda: None)
    dead_owner.start()
    dead_owner.join(2)
    assert not dead_owner.is_alive()
    carrier = windows_state._NativeOrphanCarrier(resource, RuntimeError("abandoned"))
    carrier.claim[0] = dead_owner
    state._orphan_carriers[0] = carrier  # type: ignore[attr-defined]
    function = windows_state._NativeCallState._finish_orphan_once
    target = _offset_after_source_instruction(
        function,
        "claim = self._acquire_orphan_claim(carrier, slot)",
        {"STORE_DEREF"},
    )

    _interrupt_at_opcode(function, target, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            state._finish_orphan(resource, RuntimeError("retry abandoned result"))
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert state._outcome_guard.acquire(blocking=False)  # type: ignore[attr-defined]
    state._outcome_guard.release()  # type: ignore[attr-defined]
    assert carrier.resource is resource
    assert cleanup_calls == [resource]
    assert managed == {}
    assert retained == {}

    state._finish_orphan(resource, RuntimeError("resume takeover"))
    assert cleanup_calls == [resource]
    assert managed == {}
    assert retained == {}


@pytest.mark.parametrize(
    "interruption",
    [KeyboardInterrupt("worker orphan claim"), SystemExit(122)],
)
def test_orphan_worker_automatically_resumes_one_shot_handoff_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    interruption: BaseException,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []
    managed, retained = _isolate_r4_native_registries(monkeypatch)
    state = windows_state._NativeCallState(
        lambda: resource,
        orphan_cleanup=lambda value: cleanup_calls.append(value) or True,
    )
    state._abandoned = True  # type: ignore[attr-defined]
    function = windows_state._NativeCallState._finish_orphan_once
    target = _offset_after_source_instruction(
        function,
        "claim = self._acquire_orphan_claim(carrier, slot)",
        {"STORE_DEREF"},
    )

    _interrupt_at_opcode(function, target, interruption)
    try:
        state._run()  # type: ignore[attr-defined]
    finally:
        _clear_opcode_interrupt()

    assert state._event.is_set()  # type: ignore[attr-defined]
    assert state._outcome_guard.acquire(blocking=False)  # type: ignore[attr-defined]
    state._outcome_guard.release()  # type: ignore[attr-defined]
    assert cleanup_calls == [resource]
    assert managed == {}
    assert retained == {}


@pytest.mark.parametrize("stage", ["retain", "terminal"])
@pytest.mark.parametrize(
    "interruption",
    [KeyboardInterrupt("orphan stage retry"), SystemExit(123)],
)
def test_orphan_stage_cancellation_retries_only_the_incomplete_stage(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    interruption: BaseException,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []
    retain_calls: list[tuple[object, bool]] = []
    terminal_calls: list[bool] = []
    managed, retained = _isolate_r4_native_registries(monkeypatch)

    def retain(value: object, cleanup_uncertain: bool) -> None:
        retain_calls.append((value, cleanup_uncertain))
        if stage == "retain" and len(retain_calls) == 1:
            raise interruption

    def terminal(cleaned: bool) -> None:
        terminal_calls.append(cleaned)
        if stage == "terminal" and len(terminal_calls) == 1:
            raise interruption

    state = windows_state._NativeCallState(
        lambda: resource,
        orphan_cleanup=lambda value: cleanup_calls.append(value) or False,
        orphan_retain=retain,
        orphan_terminal=terminal,
    )

    state._finish_orphan(resource, RuntimeError("abandoned result"))

    assert cleanup_calls == [resource]
    assert retain_calls == [(resource, False)] * (2 if stage == "retain" else 1)
    assert terminal_calls == [False]
    assert managed == {}
    assert retained == {}
    if stage == "terminal":
        assert len(windows_state._RETAINED_NATIVE_TERMINALS) == 1
        assert windows_state._drain_retained_native_terminals(limit=1) == 1
        assert terminal_calls == [False, False]
        assert windows_state._RETAINED_NATIVE_TERMINALS == {}


@pytest.mark.parametrize(
    ("source_fragment", "opnames", "interruption"),
    [
        (
            "return _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, publish)",
            {"CALL"},
            KeyboardInterrupt("retained identity publication"),
        ),
        (
            "return _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, publish)",
            {"CALL"},
            SystemExit(124),
        ),
    ],
)
def test_native_retention_publication_cancellation_is_unlocked_and_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    source_fragment: str,
    opnames: set[str],
    interruption: BaseException,
) -> None:
    resource = object()

    def cleanup(_value: object) -> bool:
        return True

    retained: dict[int, object] = {}
    guard = threading.Lock()
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", {})
    monkeypatch.setattr(windows_state, "_MANAGED_NATIVE_CALLS_GUARD", guard)
    function = windows_state._retain_native_resource
    target = _offset_after_source_instruction(function, source_fragment, opnames)

    _interrupt_at_opcode(function, target, interruption)
    try:
        with pytest.raises(type(interruption)) as caught:
            function(resource, cleanup, False)
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    available = guard.acquire(blocking=False)
    if available:
        guard.release()
    else:
        guard.release()
    assert available

    function(resource, cleanup, False)
    assert len(retained) == 1
    assert next(iter(retained.values())).resource is resource  # type: ignore[attr-defined]


def test_orphan_retention_post_publication_cancellation_never_duplicates_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []

    def cleanup(value: object) -> bool:
        cleanup_calls.append(value)
        return len(cleanup_calls) > 1

    managed, retained = _isolate_r4_native_registries(monkeypatch)
    state = windows_state._NativeCallState(
        lambda: resource,
        orphan_cleanup=cleanup,
        orphan_retain=lambda value, uncertain: windows_state._retain_native_resource(
            value,
            cleanup,
            uncertain,
        ),
    )
    function = windows_state._retain_native_resource
    target = _offset_after_source_instruction(
        function,
        "return _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, publish)",
        {"CALL"},
    )
    interruption = SystemExit(126)

    _interrupt_at_opcode(function, target, interruption)
    try:
        state._finish_orphan(resource, RuntimeError("abandoned"))
    finally:
        _clear_opcode_interrupt()

    assert cleanup_calls == [resource]
    assert managed == {}
    assert len(retained) == 1
    assert windows_state._drain_retained_native_resources(limit=1) == 1
    assert windows_state._drain_retained_native_resources(limit=1) == 0
    assert cleanup_calls == [resource, resource]
    assert retained == {}


def test_managed_retirement_cancellation_never_strands_registry_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed, retained = _isolate_r4_native_registries(monkeypatch)
    guard = threading.Lock()
    monkeypatch.setattr(windows_state, "_MANAGED_NATIVE_CALLS_GUARD", guard)
    state = windows_state._NativeCallState(lambda: object(), orphan_cleanup=lambda _value: True)
    function = windows_state._NativeCallState._retire_managed
    target = _offset_after_source_instruction(
        function,
        "_under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, retire)",
        {"CALL"},
    )

    interruption = SystemExit(125)
    _interrupt_at_opcode(function, target, interruption)
    try:
        with pytest.raises(SystemExit) as caught:
            state.handoff()
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    available = guard.acquire(blocking=False)
    if available:
        guard.release()
    else:
        guard.release()
    assert available
    state.handoff()
    assert managed == {}
    assert retained == {}


def test_cleanup_exception_cancellation_preserves_uncertainty_before_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []

    def cleanup(value: object) -> bool:
        cleanup_calls.append(value)
        if len(cleanup_calls) == 1:
            raise RuntimeError("native cleanup outcome unknown")
        return True

    managed, retained = _isolate_r4_native_registries(monkeypatch)
    state = windows_state._NativeCallState(
        lambda: resource,
        orphan_cleanup=cleanup,
        orphan_retain=lambda value, uncertain: windows_state._retain_native_resource(
            value,
            cleanup,
            uncertain,
        ),
    )
    function = windows_state._NativeCallState._finish_orphan_once
    target = _offset_after_source_instruction(
        function,
        "carrier.cleanup_uncertain.add(slot)",
        {"CALL"},
    )
    interruption = KeyboardInterrupt("uncertainty publication")

    _interrupt_at_opcode(function, target, interruption)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            state._finish_orphan(resource, RuntimeError("abandoned"))
    finally:
        _clear_opcode_interrupt()

    assert caught.value is interruption
    assert cleanup_calls == []
    assert managed == {}
    assert len(retained) == 1
    assert next(iter(retained.values())).cleanup_uncertain is True  # type: ignore[attr-defined]


def test_callback_error_terminal_failure_releases_managed_capacity_with_durable_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    terminal_calls: list[bool] = []

    def callback() -> object:
        raise RuntimeError("producer failed")

    def terminal(cleaned: bool) -> None:
        terminal_calls.append(cleaned)
        raise KeyboardInterrupt("terminal publication interrupted")

    managed, retained = _isolate_r4_native_registries(monkeypatch)
    state = windows_state._NativeCallState(
        callback,
        orphan_cleanup=lambda _value: True,
        orphan_terminal=terminal,
    )
    state._abandoned = True  # type: ignore[attr-defined]

    state._run()  # type: ignore[attr-defined]

    assert terminal_calls == [True]
    assert state._event.is_set()  # type: ignore[attr-defined]
    assert managed == {}
    assert retained == {}
    assert len(windows_state._RETAINED_NATIVE_TERMINALS) == 1
    reusable = windows_state._NativeCallState(lambda: object(), orphan_cleanup=lambda _value: True)
    reusable.handoff()
    assert managed == {}


def test_dead_orphan_claim_takeover_has_one_compare_and_swap_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_barrier = threading.Barrier(2)
    cleanup_barrier = threading.Barrier(2)
    cleanup_calls: list[object] = []
    resource = object()

    class DeadOwner(threading.Thread):
        armed = False

        def is_alive(self) -> bool:
            if self.armed:
                claim_barrier.wait(2)
                return False
            return super().is_alive()

    dead_owner = DeadOwner(target=lambda: None)
    dead_owner.start()
    dead_owner.join(2)
    dead_owner.armed = True

    def cleanup(value: object) -> bool:
        cleanup_calls.append(value)
        try:
            cleanup_barrier.wait(0.25)
        except threading.BrokenBarrierError:
            pass
        return True

    managed, retained = _isolate_r4_native_registries(monkeypatch)
    state = windows_state._NativeCallState(lambda: resource, orphan_cleanup=cleanup)
    carrier = windows_state._NativeOrphanCarrier(resource, RuntimeError("abandoned"))
    carrier.claim[0] = dead_owner
    state._orphan_carriers[0] = carrier  # type: ignore[attr-defined]
    results: list[bool] = []
    errors: list[BaseException] = []

    def contend() -> None:
        try:
            results.append(state._finish_orphan_once(resource, carrier.cause))
        except BaseException as exc:
            errors.append(exc)

    contenders = [threading.Thread(target=contend) for _ in range(2)]
    for contender in contenders:
        contender.start()
    for contender in contenders:
        contender.join(3)

    assert not any(contender.is_alive() for contender in contenders)
    assert errors == []
    assert cleanup_calls == [resource]
    assert results.count(True) == 1
    assert managed == {}
    assert retained == {}


def test_r9_retention_publication_interleaved_drain_never_republishes_cleaned_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []

    def cleanup(value: object) -> bool:
        cleanup_calls.append(value)
        return len(cleanup_calls) > 1

    class InterruptAfterPublication(dict[int, object]):
        armed = True

        def setdefault(self, key: int, value: object) -> object:
            published = super().setdefault(key, value)
            if self.armed:
                self.armed = False
                raise SystemExit(209)
            return published

    managed: dict[int, object] = {}
    retained = InterruptAfterPublication()
    monkeypatch.setattr(windows_state, "_MANAGED_NATIVE_CALLS", managed)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", {})
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_KEYS", {})
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_TERMINALS", {})
    monkeypatch.setattr(windows_state, "_MAX_MANAGED_NATIVE_RESOURCES", 1)

    state = windows_state._NativeCallState(
        lambda: resource,
        orphan_cleanup=cleanup,
        orphan_retain=lambda value, uncertain: windows_state._retain_native_resource(
            value,
            cleanup,
            uncertain,
        ),
    )
    cause = RuntimeError("abandoned")

    assert state._finish_orphan_once(resource, cause) is False  # type: ignore[attr-defined]
    assert cleanup_calls == [resource]
    assert windows_state._drain_retained_native_resources(limit=1) == 1
    assert cleanup_calls == [resource, resource]

    assert state._finish_orphan_once(resource, cause) is True  # type: ignore[attr-defined]
    assert windows_state._drain_retained_native_resources(limit=1) == 0
    assert cleanup_calls == [resource, resource]
    assert managed == {}
    assert retained == {}
    assert windows_state._RETAINED_NATIVE_RESOURCE_KEYS == {}


def test_r9_retained_drain_pre_cleanup_interruption_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []

    def cleanup(value: object) -> bool:
        cleanup_calls.append(value)
        return True

    record = windows_state._RetainedNativeResource(
        resource,
        cleanup,
        False,
        (id(resource), id(cleanup)),
    )
    token = 94_001

    retained = {token: record}
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", {})
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_KEYS", {record.retention_key: token})

    function = windows_state._drain_retained_native_resources
    original_invoke = windows_state._NativeCallState.invoke
    armed = True

    def interrupt_before_dispatch(state: object) -> object:
        nonlocal armed
        if armed:
            armed = False
            raise KeyboardInterrupt("before retained cleanup dispatch")
        return original_invoke(state)  # type: ignore[arg-type]

    monkeypatch.setattr(windows_state._NativeCallState, "invoke", interrupt_before_dispatch)
    with pytest.raises(KeyboardInterrupt, match="before retained cleanup dispatch"):
        function(limit=1)

    assert cleanup_calls == []
    assert function(limit=1) == 1
    assert cleanup_calls == [resource]
    assert retained == {}
    assert windows_state._RETAINED_NATIVE_RESOURCE_KEYS == {}


def test_r9_cancelled_drain_releases_concurrent_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []

    def cleanup(value: object) -> bool:
        cleanup_calls.append(value)
        return True

    record = windows_state._RetainedNativeResource(
        resource,
        cleanup,
        False,
        (id(resource), id(cleanup)),
    )
    token = 94_002
    retained = {token: record}
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", {})
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_KEYS", {record.retention_key: token})

    original_invoke = windows_state._NativeCallState.invoke
    cancelled_entered = threading.Event()
    permit_cancellation = threading.Event()
    retry_started = threading.Event()
    interruptions: list[BaseException] = []
    retry_results: list[int] = []

    def interrupt_cancelled_drainer(state: object) -> object:
        if threading.current_thread().name == "cancelled-drainer":
            cancelled_entered.set()
            assert permit_cancellation.wait(2)
            raise KeyboardInterrupt("cancel retained cleanup before dispatch")
        return original_invoke(state)  # type: ignore[arg-type]

    def cancelled_drain() -> None:
        try:
            windows_state._drain_retained_native_resources(limit=1)
        except BaseException as exc:
            interruptions.append(exc)

    def retry_drain() -> None:
        retry_started.set()
        retry_results.append(windows_state._drain_retained_native_resources(limit=1))

    monkeypatch.setattr(
        windows_state._NativeCallState,
        "invoke",
        interrupt_cancelled_drainer,
    )
    cancelled = threading.Thread(target=cancelled_drain, name="cancelled-drainer")
    retry = threading.Thread(target=retry_drain, name="retry-drainer")

    cancelled.start()
    assert cancelled_entered.wait(2)
    retry.start()
    assert retry_started.wait(2)
    assert retry.is_alive()
    permit_cancellation.set()

    cancelled.join(2)
    retry.join(2)
    assert not cancelled.is_alive()
    assert not retry.is_alive()
    assert len(interruptions) == 1
    assert isinstance(interruptions[0], KeyboardInterrupt)
    assert retry_results == [1]
    assert cleanup_calls == [resource]
    assert retained == {}
    assert windows_state._RETAINED_NATIVE_RESOURCE_KEYS == {}


def test_r9_retained_drain_post_cleanup_interruption_reuses_durable_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []

    class InterruptOnceTruth:
        armed = True

        def __bool__(self) -> bool:
            if self.armed:
                self.armed = False
                raise KeyboardInterrupt("after retained cleanup success")
            return True

    result = InterruptOnceTruth()

    def cleanup(value: object) -> object:
        cleanup_calls.append(value)
        return result

    record = windows_state._RetainedNativeResource(
        resource,
        cleanup,  # type: ignore[arg-type]
        False,
        (id(resource), id(cleanup)),
    )
    token = 94_002
    retained = {token: record}
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", {})
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_KEYS", {record.retention_key: token})

    with pytest.raises(KeyboardInterrupt, match="after retained cleanup success"):
        windows_state._drain_retained_native_resources(limit=1)

    assert windows_state._drain_retained_native_resources(limit=1) == 1
    assert cleanup_calls == [resource]
    assert retained == {}
    assert windows_state._RETAINED_NATIVE_RESOURCE_KEYS == {}


def test_r9_dead_claim_stale_contender_cannot_retire_live_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()
    cleanup_entered = threading.Event()
    release_cleanup = threading.Event()
    start_barrier = threading.Barrier(2)
    cleanup_calls: list[object] = []
    terminal_calls: list[bool] = []
    outcomes: list[tuple[str, str]] = []

    def cleanup(value: object) -> bool:
        cleanup_calls.append(value)
        cleanup_entered.set()
        assert release_cleanup.wait(3)
        return True

    class CoordinatedDeadOwner(threading.Thread):
        def __init__(self) -> None:
            super().__init__(target=lambda: None)

        def is_alive(self) -> bool:
            if threading.current_thread().name in {"r9-a", "r9-b"}:
                start_barrier.wait(2)
                if threading.current_thread().name == "r9-b":
                    assert cleanup_entered.wait(2)
                return False
            return super().is_alive()

    dead_owner = CoordinatedDeadOwner()
    dead_owner.start()
    dead_owner.join(2)

    class InterruptStalePop(dict[int, threading.Thread]):
        armed = True

        def pop(self, key: int, default: object = None) -> object:
            removed = super().pop(key, default)  # type: ignore[arg-type]
            if self.armed and threading.current_thread().name == "r9-b" and removed is not dead_owner:
                self.armed = False
                raise SystemExit(210)
            return removed

    managed, retained = _isolate_r4_native_registries(monkeypatch)
    state = windows_state._NativeCallState(
        lambda: resource,
        orphan_cleanup=cleanup,
        orphan_retain=lambda value, uncertain: windows_state._retain_native_resource(
            value,
            cleanup,
            uncertain,
        ),
        orphan_terminal=lambda cleaned: terminal_calls.append(cleaned),
    )
    carrier = windows_state._NativeOrphanCarrier(resource, RuntimeError("abandoned"))
    carrier.claim = InterruptStalePop({0: dead_owner})  # type: ignore[assignment]
    state._orphan_carriers[0] = carrier  # type: ignore[attr-defined]

    def contend() -> None:
        try:
            state._finish_orphan(resource, carrier.cause)  # type: ignore[attr-defined]
            outcomes.append((threading.current_thread().name, "returned"))
        except BaseException as exc:
            outcomes.append((threading.current_thread().name, type(exc).__name__))

    first = threading.Thread(target=contend, name="r9-a")
    second = threading.Thread(target=contend, name="r9-b")
    first.start()
    second.start()
    second.join(3)
    release_cleanup.set()
    first.join(3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert cleanup_calls == [resource]
    assert terminal_calls == [True]
    assert carrier.resolved == {0}
    assert managed == {}
    assert retained == {}
    assert outcomes == [("r9-b", "returned"), ("r9-a", "returned")]


def test_r9_result_terminal_failure_is_durable_and_capacity_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()
    terminal_calls: list[bool] = []
    managed, retained = _isolate_r4_native_registries(monkeypatch)

    def terminal(cleaned: bool) -> None:
        terminal_calls.append(cleaned)
        if len(terminal_calls) == 1:
            raise RuntimeError("terminal temporarily unavailable")

    state = windows_state._NativeCallState(
        lambda: resource,
        orphan_cleanup=lambda _value: True,
        orphan_terminal=terminal,
    )
    state._finish_orphan(resource, RuntimeError("abandoned"))  # type: ignore[attr-defined]

    assert terminal_calls == [True]
    assert managed == {}
    assert retained == {}
    assert len(windows_state._RETAINED_NATIVE_TERMINALS) == 1

    reusable = windows_state._NativeCallState(lambda: object(), orphan_cleanup=lambda _value: True)
    reusable.handoff()
    assert managed == {}

    assert windows_state._drain_retained_native_terminals(limit=1) == 1
    assert terminal_calls == [True, True]
    assert windows_state._RETAINED_NATIVE_TERMINALS == {}

    state._finish_orphan(resource, RuntimeError("retry after delivery"))  # type: ignore[attr-defined]
    assert terminal_calls == [True, True]


def test_r9_retained_terminal_drain_has_one_callback_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback_entered = threading.Event()
    release_callback = threading.Event()
    calls: list[bool] = []

    def callback(cleaned: bool) -> None:
        calls.append(cleaned)
        callback_entered.set()
        assert release_callback.wait(3)

    terminals: dict[tuple[int, int, bool], object] = {}
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_TERMINALS", terminals)
    windows_state._publish_native_terminal(callback, True, RuntimeError("terminal"))
    results: list[int] = []

    def drain() -> None:
        results.append(windows_state._drain_retained_native_terminals(limit=1))

    first = threading.Thread(target=drain)
    second = threading.Thread(target=drain)
    first.start()
    assert callback_entered.wait(2)
    second.start()
    release_callback.set()
    first.join(3)
    second.join(3)

    assert not first.is_alive()
    assert not second.is_alive()
    assert calls == [True]
    assert sorted(results) == [0, 1]
    assert terminals == {}


def test_r9_retained_terminal_reentrant_drain_does_not_duplicate_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []
    nested_results: list[int] = []
    terminals: dict[tuple[int, int, bool], windows_state._RetainedNativeTerminal] = {}
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_TERMINALS", terminals)

    def callback(cleaned: bool) -> None:
        calls.append(cleaned)
        nested_results.append(windows_state._drain_retained_native_terminals(limit=1))

    windows_state._publish_native_terminal(callback, True, RuntimeError("terminal"))

    assert windows_state._drain_retained_native_terminals(limit=1) == 1
    assert calls == [True]
    assert nested_results == [0]
    assert terminals == {}


def test_r9_terminal_delivery_is_resumable_at_every_delivery_opcode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery_code = next(
        constant
        for constant in windows_state._deliver_native_terminal.__code__.co_consts
        if getattr(constant, "co_name", None) == "deliver"
    )
    function = SimpleNamespace(__code__=delivery_code)
    offsets = [instruction.offset for instruction in dis.get_instructions(delivery_code)]

    for offset in offsets:
        calls: list[bool] = []

        def callback(cleaned: bool, calls: list[bool] = calls) -> None:
            calls.append(cleaned)

        terminals: dict[tuple[int, int, bool], windows_state._RetainedNativeTerminal] = {}
        monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_TERMINALS", terminals)
        windows_state._publish_native_terminal(callback, True, RuntimeError(f"terminal {offset}"))

        interruption = KeyboardInterrupt(f"terminal delivery opcode {offset}")
        _interrupt_at_opcode(function, offset, interruption)
        try:
            try:
                windows_state._drain_retained_native_terminals(limit=1)
            except KeyboardInterrupt as caught:
                assert caught is interruption
        finally:
            _clear_opcode_interrupt()

        assert windows_state._drain_retained_native_terminals(limit=1) in (0, 1)
        assert windows_state._drain_retained_native_terminals(limit=1) == 0
        assert calls == [True]
        assert terminals == {}


def test_r9_resource_and_reverse_key_retirement_is_resumable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()
    cleanup_calls: list[object] = []

    def cleanup(value: object) -> bool:
        cleanup_calls.append(value)
        return True

    key = (id(resource), id(cleanup))
    token = 94_003
    record = windows_state._RetainedNativeResource(resource, cleanup, False, key)

    class InterruptAfterResourcePop(dict[int, object]):
        armed = True

        def pop(self, key: int, default: object = None) -> object:
            removed = super().pop(key, default)
            if self.armed:
                self.armed = False
                raise KeyboardInterrupt("after retained resource removal")
            return removed

    retained = InterruptAfterResourcePop({token: record})
    reverse = {key: token}
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", {})
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_KEYS", reverse)

    with pytest.raises(KeyboardInterrupt, match="after retained resource removal"):
        windows_state._drain_retained_native_resources(limit=1)

    assert windows_state._drain_retained_native_resources(limit=1) == 0
    assert cleanup_calls == [resource]
    assert retained == {}
    assert reverse == {}


def test_r9_retention_retry_repairs_missing_reverse_key_for_active_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = object()

    def cleanup(_value: object) -> bool:
        return True

    key = (id(resource), id(cleanup))
    token = 94_004
    record = windows_state._RetainedNativeResource(resource, cleanup, False, key, token=token)
    retained = {token: record}
    reverse: dict[tuple[int, int], int] = {}
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
    monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_KEYS", reverse)

    recovered = windows_state._retain_native_resource(resource, cleanup, False)

    assert recovered is record
    assert reverse == {key: token}
    assert retained == {token: record}


def test_r9_retirement_never_exposes_only_one_resource_index_at_any_opcode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    function = windows_state._finalize_retained_native_resource_locked
    offsets = [instruction.offset for instruction in dis.get_instructions(function)]

    for offset in offsets:
        resource = object()

        def cleanup(_value: object) -> bool:
            return True

        key = (id(resource), id(cleanup))
        token = 95_000 + offset
        record = windows_state._RetainedNativeResource(resource, cleanup, False, key, token=token)
        retained = {token: record}
        reverse = {key: token}
        claims = {token: 1}
        monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCES", retained)
        monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_KEYS", reverse)
        monkeypatch.setattr(windows_state, "_RETAINED_NATIVE_RESOURCE_CLAIMS", claims)

        interruption = KeyboardInterrupt(f"retirement opcode {offset}")
        _interrupt_at_opcode(function, offset, interruption)
        try:
            try:
                function(token, record)
            except KeyboardInterrupt as caught:
                assert caught is interruption
        finally:
            _clear_opcode_interrupt()

        assert bool(retained) is bool(reverse), f"split resource indexes after opcode {offset}"
        if retained:
            assert retained == {token: record}
            assert reverse == {key: token}
            function(token, record)
        assert retained == {}
        assert reverse == {}


def test_r9_interruption_safe_lock_releases_at_every_opcode_boundary() -> None:
    function = windows_state._under_interruption_safe_lock
    offsets = [instruction.offset for instruction in dis.get_instructions(function)]

    for offset in offsets:
        guard = threading.RLock()
        interruption = KeyboardInterrupt(f"lock opcode {offset}")
        _interrupt_at_opcode(function, offset, interruption)
        try:
            try:
                function(guard, lambda: None)
            except KeyboardInterrupt as caught:
                assert caught is interruption
        finally:
            _clear_opcode_interrupt()

        available_to_contender: list[bool] = []

        def contend(
            guard: threading.RLock = guard,
            available_to_contender: list[bool] = available_to_contender,
        ) -> None:
            acquired = guard.acquire(blocking=False)
            available_to_contender.append(acquired)
            if acquired:
                guard.release()

        contender = threading.Thread(target=contend)
        contender.start()
        contender.join(2)
        assert not contender.is_alive()
        assert available_to_contender == [True], f"lock remained held after opcode {offset}"


def test_r9_interruption_safe_lock_preserves_callers_recursive_ownership() -> None:
    guard = threading.RLock()
    acquired_by_contender: list[bool] = []
    guard.acquire()
    try:
        with pytest.raises(RuntimeError, match="critical section failed"):
            windows_state._under_interruption_safe_lock(
                guard,
                lambda: (_ for _ in ()).throw(RuntimeError("critical section failed")),
            )

        def contend(
            guard: threading.RLock = guard,
            acquired_by_contender: list[bool] = acquired_by_contender,
        ) -> None:
            acquired = guard.acquire(blocking=False)
            acquired_by_contender.append(acquired)
            if acquired:
                guard.release()

        contender = threading.Thread(target=contend)
        contender.start()
        contender.join(2)
        assert not contender.is_alive()
        assert acquired_by_contender == [False]
    finally:
        guard.release()


def test_r9_interruption_safe_lock_preserves_outer_owner_at_every_opcode_boundary() -> None:
    function = windows_state._under_interruption_safe_lock
    offsets = [instruction.offset for instruction in dis.get_instructions(function)]

    for offset in offsets:
        guard = threading.RLock()
        guard.acquire()
        interruption = KeyboardInterrupt(f"recursive lock opcode {offset}")
        _interrupt_at_opcode(function, offset, interruption)
        try:
            try:
                function(guard, lambda: None)
            except KeyboardInterrupt as caught:
                assert caught is interruption
        finally:
            _clear_opcode_interrupt()

        acquired_by_contender: list[bool] = []

        def contend(
            guard: threading.RLock = guard,
            acquired_by_contender: list[bool] = acquired_by_contender,
        ) -> None:
            acquired = guard.acquire(blocking=False)
            acquired_by_contender.append(acquired)
            if acquired:
                guard.release()

        contender = threading.Thread(target=contend)
        contender.start()
        contender.join(2)
        assert not contender.is_alive()
        try:
            assert acquired_by_contender == [False], f"outer lock released after opcode {offset}"
        finally:
            if acquired_by_contender == [False]:
                guard.release()

        available_after_outer_release: list[bool] = []

        def verify_released(
            guard: threading.RLock = guard,
            available_after_outer_release: list[bool] = available_after_outer_release,
        ) -> None:
            acquired = guard.acquire(blocking=False)
            available_after_outer_release.append(acquired)
            if acquired:
                guard.release()

        verifier = threading.Thread(target=verify_released)
        verifier.start()
        verifier.join(2)
        assert not verifier.is_alive()
        assert available_after_outer_release == [True], f"extra lock depth remained after opcode {offset}"
