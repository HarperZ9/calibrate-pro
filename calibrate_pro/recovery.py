"""Truthful transactional display application through an injected adapter."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path
from typing import Generic, Protocol, TypeVar

from calibrate_pro.workflow import ApplyPlan, DwmLutKind

GammaRamp = tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
T = TypeVar("T")


class CaptureStatus(str, Enum):
    """Whether a reader authoritatively captured the requested state."""

    CAPTURED = "captured"
    NOT_CAPTURED = "not_captured"


class RecoveryGuarantee(str, Enum):
    """The strongest recovery guarantee implemented by this v1 boundary."""

    IN_PROCESS_BEST_EFFORT = "in_process_best_effort"


@dataclass(frozen=True)
class CapturedState(Generic[T]):
    """A captured value, where ``None`` is distinct from a failed capture."""

    status: CaptureStatus
    value: T | None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, CaptureStatus):
            raise TypeError("status must be a CaptureStatus")
        if self.status is CaptureStatus.CAPTURED:
            if self.detail is not None:
                raise ValueError("captured state must not include a failure detail")
            return
        if self.value is not None:
            raise ValueError("NOT_CAPTURED state cannot contain a value")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise ValueError("NOT_CAPTURED state requires a non-empty failure detail")

    @classmethod
    def captured(cls, value: T | None) -> CapturedState[T]:
        return cls(CaptureStatus.CAPTURED, value)

    @classmethod
    def not_captured(cls, detail: str) -> CapturedState[T]:
        return cls(CaptureStatus.NOT_CAPTURED, None, detail)


def _validate_file_snapshot(original_path: str, payload: bytes, digest: str) -> None:
    if not isinstance(original_path, str) or not original_path.strip():
        raise ValueError("snapshot original_path must be a non-empty string")
    if type(payload) is not bytes:
        raise TypeError("snapshot payload must be exact bytes")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise ValueError("snapshot sha256 must be a canonical lowercase SHA-256 digest")
    if not hashlib.sha256(payload).hexdigest() == digest:
        raise ValueError("snapshot sha256 does not match payload bytes")


@dataclass(frozen=True)
class IccProfileSnapshot:
    """Recoverable ICC association input with exact profile bytes."""

    original_path: str
    payload: bytes
    sha256: str

    def __post_init__(self) -> None:
        _validate_file_snapshot(self.original_path, self.payload, self.sha256)


@dataclass(frozen=True)
class IccInstallEffect:
    """Product-owned content-addressed ICC file materialization evidence."""

    installed_profile: IccProfileSnapshot
    created_file: bool

    def __post_init__(self) -> None:
        if type(self.created_file) is not bool:
            raise TypeError("created_file must be a boolean")
        expected_name = f"calibrate-pro-{self.installed_profile.sha256}.icc"
        if Path(self.installed_profile.original_path).name != expected_name:
            raise ValueError("installed ICC profile must use its exact product-owned content-addressed filename")


@dataclass(frozen=True)
class IccLifecycleSnapshot:
    """Authoritative pre-mutation installation and per-display association truth."""

    target_profile_name: str
    was_installed: bool
    was_associated: bool

    def __post_init__(self) -> None:
        if type(self.target_profile_name) is not str or Path(self.target_profile_name).name != self.target_profile_name:
            raise ValueError("ICC lifecycle target must be an exact profile basename")
        if type(self.was_installed) is not bool or type(self.was_associated) is not bool:
            raise TypeError("ICC lifecycle evidence must use exact booleans")
        if self.was_associated and not self.was_installed:
            raise ValueError("an associated ICC target must also be installed")


@dataclass(frozen=True)
class IccActivationEffect:
    """Stepwise ICC effects proven complete before a later phase failed."""

    registered: bool = False
    associated: bool = False
    default_selected: bool = False

    def __post_init__(self) -> None:
        if any(type(value) is not bool for value in (self.registered, self.associated, self.default_selected)):
            raise TypeError("ICC activation effects must be exact booleans")


class IccActivationError(RuntimeError):
    """Activation failure carrying only effects that authoritatively completed."""

    def __init__(self, message: str, effect: IccActivationEffect) -> None:
        super().__init__(message or "ICC activation failed")
        if not isinstance(effect, IccActivationEffect):
            raise TypeError("ICC activation error requires IccActivationEffect")
        self.effect = effect


@dataclass(frozen=True)
class DwmLutSnapshot:
    """Recoverable DWM LUT input with explicit processing domain."""

    kind: DwmLutKind
    original_path: str
    payload: bytes
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, DwmLutKind):
            raise TypeError("DWM LUT kind must be a DwmLutKind")
        _validate_file_snapshot(self.original_path, self.payload, self.sha256)


@dataclass(frozen=True)
class DdcReading:
    """Exact selected-monitor VCP value and its reported maximum."""

    current: int
    maximum: int

    def __post_init__(self) -> None:
        if type(self.current) is not int or type(self.maximum) is not int:
            raise TypeError("DDC current and maximum must be exact integers")
        if not 0 <= self.current <= self.maximum <= 65535 or self.maximum == 0:
            raise ValueError("DDC reading must satisfy 0 <= current <= maximum <= 65535 with positive maximum")


@dataclass(frozen=True)
class DdcTargetIdentity:
    """Stable physical monitor identity bound independently of transient handles."""

    display_id: str
    monitor_device_path: str

    def __post_init__(self) -> None:
        for name, value in (
            ("display_id", self.display_id),
            ("monitor_device_path", self.monitor_device_path),
        ):
            if type(value) is not str:
                raise TypeError(f"{name} must be an exact string")
            if not value.strip():
                raise ValueError(f"{name} must be non-empty")


@dataclass(frozen=True)
class DisplayStateSnapshot:
    """Only requested domains are present; every present domain is authoritative."""

    display_id: str
    ddc_values: tuple[tuple[str, DdcReading], ...]
    icc_profile: CapturedState[IccProfileSnapshot] | None
    gamma_ramp: CapturedState[GammaRamp] | None
    dwm_luts: CapturedState[tuple[DwmLutSnapshot, ...]] | None
    ddc_target: DdcTargetIdentity | None = None
    icc_lifecycle: IccLifecycleSnapshot | None = None

    def __post_init__(self) -> None:
        if type(self.display_id) is not str or not self.display_id.strip():
            raise ValueError("snapshot display_id must be a non-empty exact string")
        if type(self.ddc_values) is not tuple:
            raise TypeError("snapshot ddc_values must be an exact tuple")
        if bool(self.ddc_values) != (self.ddc_target is not None):
            raise ValueError("snapshot DDC target and readings must be present together")
        seen: set[str] = set()
        for row in self.ddc_values:
            if type(row) is not tuple or len(row) != 2:
                raise TypeError("each snapshot DDC row must be an exact pair")
            code, reading = row
            if type(code) is not str or not code:
                raise TypeError("snapshot DDC code must be an exact non-empty string")
            if code in seen:
                raise ValueError(f"duplicate snapshot DDC code: {code}")
            seen.add(code)
            if not isinstance(reading, DdcReading):
                raise TypeError("snapshot DDC value must be DdcReading")
        if self.ddc_target is not None and self.ddc_target.display_id != self.display_id:
            raise ValueError("snapshot DDC target belongs to a different display")
        if self.icc_lifecycle is not None:
            if not isinstance(self.icc_lifecycle, IccLifecycleSnapshot):
                raise TypeError("snapshot ICC lifecycle evidence must be IccLifecycleSnapshot")
            if self.icc_profile is None:
                raise ValueError("snapshot ICC lifecycle evidence requires requested ICC state")


@dataclass(frozen=True)
class ApplyReceipt:
    """Operation evidence whose flags describe only completed phases."""

    success: bool
    captured: bool
    applied: bool
    verified: bool
    restore_attempted: bool
    restored: bool
    error: str | None
    restore_error: str | None
    recovery_guarantee: RecoveryGuarantee = RecoveryGuarantee.IN_PROCESS_BEST_EFFORT

    def __post_init__(self) -> None:
        flags = (
            self.success,
            self.captured,
            self.applied,
            self.verified,
            self.restore_attempted,
            self.restored,
        )
        if any(type(flag) is not bool for flag in flags):
            raise TypeError("every apply receipt phase flag must be an exact boolean")
        if not isinstance(self.recovery_guarantee, RecoveryGuarantee):
            raise TypeError("recovery_guarantee must be RecoveryGuarantee")
        for name, value in (("error", self.error), ("restore_error", self.restore_error)):
            if value is not None and (type(value) is not str or not value):
                raise TypeError(f"{name} must be null or a non-empty exact string")
        if self.applied and not self.captured:
            raise ValueError("receipt phase invariant: applied requires captured")
        if self.verified and not self.applied:
            raise ValueError("receipt phase invariant: verified requires applied")
        if self.restore_attempted and not self.captured:
            raise ValueError("receipt phase invariant: restoration requires captured state")
        if self.restored and not self.restore_attempted:
            raise ValueError("receipt phase invariant: restored requires an attempted restoration")
        if not self.success and self.error is None:
            raise ValueError("receipt phase invariant: an unsuccessful operation requires an error")
        if self.restore_error is not None and (not self.restore_attempted or self.restored):
            raise ValueError("receipt phase invariant: restore_error requires attempted, unsuccessful restoration")
        if self.restored and self.restore_error is not None:
            raise ValueError("receipt phase invariant: restored evidence forbids restore_error")
        if self.restore_attempted and not self.restored and self.restore_error is None:
            raise ValueError("receipt phase invariant: unsuccessful restoration requires restore_error")
        if self.verified and self.restore_attempted:
            raise ValueError("receipt phase invariant: verified commit failure cannot claim restoration")
        if not self.success and self.captured and not self.verified and not self.restore_attempted:
            raise ValueError("receipt phase invariant: an unsuccessful captured operation requires restoration")
        if self.success:
            if not (self.captured and self.applied and self.verified):
                raise ValueError("receipt phase invariant: success requires capture, apply, and verify")
            if self.restore_attempted or self.restored or self.error is not None or self.restore_error is not None:
                raise ValueError("receipt phase invariant: success cannot contain recovery or errors")


class DisplayStateAdapter(Protocol):
    def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot: ...

    def apply(self, plan: ApplyPlan) -> None: ...

    def verify(self, plan: ApplyPlan) -> bool: ...

    def commit(self, plan: ApplyPlan) -> None: ...

    def restore(self, snapshot: DisplayStateSnapshot) -> None: ...


def _exception_text(exc: BaseException) -> str:
    """Return receipt-safe error text even for exceptions with an empty message."""
    message = str(exc).strip()
    return message or type(exc).__name__


def _add_exception_note(exc: BaseException, note: str) -> None:
    add_note = getattr(exc, "add_note", None)
    if callable(add_note):
        add_note(note)


def _capture_into_recovery_sink(
    sink: list[DisplayStateSnapshot],
    capture: Callable[[ApplyPlan], DisplayStateSnapshot],
    plan: ApplyPlan,
) -> DisplayStateSnapshot:
    """Publish a returned capture before control reaches another Python opcode."""
    # ``list.extend`` drives the built-in ``map`` iterator in C. Once the
    # Python capture callable returns, its exact result is appended to the
    # recovery-owned sink before the interpreter resumes this frame. This is
    # the cancellation-isolated ownership handoff; a Python wrapper that did
    # ``snapshot = capture(plan)`` would recreate the original CALL/STORE gap.
    sink.extend(map(capture, (plan,)))
    return sink[0]


def _apply_confirmed_with_best_effort_recovery(
    adapter: DisplayStateAdapter,
    plan: ApplyPlan,
    *,
    authorization: object | None = None,
) -> ApplyReceipt:
    """Capture before writes and compensate in-process after apply/readback uncertainty."""
    snapshot: DisplayStateSnapshot | None = None
    capture_sink: list[DisplayStateSnapshot] = []
    applied = False
    phase = "capture"
    try:
        if authorization is None:
            snapshot = _capture_into_recovery_sink(capture_sink, adapter.capture, plan)
        else:
            snapshot = _capture_into_recovery_sink(
                capture_sink,
                partial(adapter.capture, authorization=authorization),
                plan,
            )
        phase = "apply"
        # Keep the call and its completion flag on one trace line so a line-level
        # cancellation cannot report a returned apply as incomplete.
        # fmt: off
        adapter.apply(plan); applied = True  # noqa: E702
        # fmt: on
        phase = "verify"
        verified = adapter.verify(plan)
        if type(verified) is not bool:
            raise TypeError("display verification result must be an exact boolean")
        if not verified:
            raise RuntimeError("verification failed")
        phase = "commit"
        adapter.commit(plan)
    except Exception as exc:
        if snapshot is None and capture_sink:
            snapshot = capture_sink[0]
        if snapshot is None:
            return ApplyReceipt(False, False, False, False, False, False, _exception_text(exc), None)
        if phase == "commit":
            return ApplyReceipt(False, True, True, True, False, False, _exception_text(exc), None)
        try:
            adapter.restore(snapshot)
        except Exception as restore_exc:
            return ApplyReceipt(
                False,
                True,
                applied,
                False,
                True,
                False,
                _exception_text(exc),
                _exception_text(restore_exc),
            )
        except BaseException as cancellation:
            _add_exception_note(cancellation, f"display operation also failed: {_exception_text(exc)}")
            raise
        return ApplyReceipt(False, True, applied, False, True, True, _exception_text(exc), None)
    except BaseException as cancellation:
        if snapshot is None and capture_sink:
            snapshot = capture_sink[0]
        if snapshot is not None:
            try:
                adapter.restore(snapshot)
            except BaseException as restore_exc:
                _add_exception_note(
                    cancellation,
                    f"display compensation also failed: {_exception_text(restore_exc)}",
                )
        raise
    return ApplyReceipt(True, True, True, True, False, False, None, None)
