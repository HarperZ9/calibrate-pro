"""Candidate capability-gated Windows transaction boundary for display-state I/O.

This does not become the repository's sole production actuator until Task 8 removes the
legacy GUI, tray, service, and elevation bypasses and its isolation tests pass.
"""

from __future__ import annotations

import atexit
import copy
import ctypes
import hashlib
import importlib
import json
import os
import tempfile
import threading
from collections.abc import Callable, Iterable
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from itertools import count
from numbers import Integral
from pathlib import Path
from typing import Any, NoReturn, Protocol, TypeVar, cast

from calibrate_pro.recovery import (
    CapturedState,
    CaptureStatus,
    DdcReading,
    DdcTargetIdentity,
    DisplayStateSnapshot,
    DwmLutSnapshot,
    GammaRamp,
    IccActivationEffect,
    IccActivationError,
    IccInstallEffect,
    IccLifecycleSnapshot,
    IccProfileSnapshot,
)
from calibrate_pro.workflow import DDC_WRITE_CODES, ApplyPlan, DwmLutKind

ModuleLoader = Callable[[str], Any]
MonitorNameResolver = Callable[[object], str | None]
DdcIdentityResolver = Callable[[str], str]
PhysicalMonitorIdentityResolver = Callable[[dict[str, Any]], DdcTargetIdentity]
GammaRampLoader = Callable[[str], GammaRamp]
AssetValidator = Callable[[str], None]
CaptureAuthorizationVerifier = Callable[[ApplyPlan, object | None], str]
T = TypeVar("T")

_MAX_CONFIRMED_ASSET_BYTES = {
    "ICC profile": 64 * 1024 * 1024,
    "VCGT": 16 * 1024 * 1024,
    "DWM LUT": 64 * 1024 * 1024,
}

_MAX_COMPENSATION_SCHEDULE_ATTEMPTS = 3
_MAX_UNCLAIMED_MUTEX_LEASES = 64
_MAX_RETAINED_ICC_LEASES = 64
_MAX_MANAGED_NATIVE_RESOURCES = 64
_MAX_POISONED_NATIVE_LEASES = 64
_REGISTRY_DRAIN_LIMIT = 8
_NATIVE_CALL_SETTLE_TIMEOUT_SECONDS = 5.0
_WINDOWS_MUTEX_OWNER_WAIT_SECONDS = 5.0

_MUTEX_ACQUISITION_LOCAL = threading.local()


@dataclass
class _UnclaimedMutexLease:
    mutex: object
    lease: object | None = None
    active: bool = True
    drain_token: int | None = None


_MUTEX_ACQUISITION_TOKENS = count(1)
_LEASE_DRAIN_TOKENS = count(1)
_UNCLAIMED_MUTEX_LEASES: dict[int, _UnclaimedMutexLease] = {}
_UNCLAIMED_MUTEX_LEASES_GUARD = threading.Lock()


def _mutex_reports_released(mutex: object, lease: object) -> bool:
    reader = getattr(mutex, "is_released", None)
    if callable(reader):
        result = reader(lease)
        if type(result) is not bool:
            raise TypeError("mutex terminal-state reader must return an exact boolean")
        return result
    released = getattr(lease, "released", None)
    if type(released) is bool:
        return released
    native_handle = getattr(lease, "native_handle", object())
    if native_handle is None:
        return True
    process_handle = getattr(lease, "process_handle", object())
    windows_handle = getattr(lease, "windows_handle", object())
    if process_handle is None and windows_handle is None:
        return True
    locked = getattr(lease, "locked", None)
    if callable(locked):
        result = locked()
        if type(result) is bool:
            return not result
    return False


def _forget_unclaimed_mutex_lease(
    token: int,
    record: _UnclaimedMutexLease,
    *,
    drain_token: int | None = None,
) -> bool:
    with _UNCLAIMED_MUTEX_LEASES_GUARD:
        if _UNCLAIMED_MUTEX_LEASES.get(token) is not record:
            return False
        if record.drain_token is not None and record.drain_token != drain_token:
            return False
        _UNCLAIMED_MUTEX_LEASES.pop(token, None)
        return True


def _finish_unclaimed_mutex_drain(
    token: int,
    record: _UnclaimedMutexLease,
    lease: object | None,
    drain_token: int,
    *,
    released: bool,
) -> bool:
    with _UNCLAIMED_MUTEX_LEASES_GUARD:
        if (
            _UNCLAIMED_MUTEX_LEASES.get(token) is not record
            or record.drain_token != drain_token
            or record.lease is not lease
            or record.active
        ):
            return False
        if released:
            _UNCLAIMED_MUTEX_LEASES.pop(token, None)
            return True
        record.drain_token = None
        return False


def _drain_unclaimed_mutex_leases(*, limit: int = _REGISTRY_DRAIN_LIMIT) -> int:
    """Retry a bounded number of inactive ownership records without losing evidence."""
    if type(limit) is not int or limit < 0:
        raise ValueError("unclaimed mutex drain limit must be a non-negative integer")
    candidates: list[tuple[int, _UnclaimedMutexLease, object | None, int]] = []
    installed_claims: list[tuple[int, _UnclaimedMutexLease, int]] = []
    handoff_complete = False
    try:
        with _UNCLAIMED_MUTEX_LEASES_GUARD:
            for token, record in _UNCLAIMED_MUTEX_LEASES.items():
                if len(candidates) >= limit:
                    break
                if record.active or record.drain_token is not None:
                    continue
                lease = record.lease
                drain_token = next(_LEASE_DRAIN_TOKENS)
                installed_claims.append((token, record, drain_token))
                record.drain_token = drain_token
                if record.active or record.lease is not lease or record.drain_token != drain_token:
                    record.drain_token = None
                    continue
                candidates.append((token, record, lease, drain_token))
            handoff_complete = True
    finally:
        if not handoff_complete:
            with _UNCLAIMED_MUTEX_LEASES_GUARD:
                for token, record, drain_token in installed_claims:
                    if _UNCLAIMED_MUTEX_LEASES.get(token) is record and record.drain_token == drain_token:
                        record.drain_token = None
    drained = 0
    for token, record, lease, drain_token in candidates:
        claim_resolved = False
        try:
            if lease is None:
                drained += int(
                    _finish_unclaimed_mutex_drain(
                        token,
                        record,
                        lease,
                        drain_token,
                        released=True,
                    )
                )
                claim_resolved = True
                continue
            try:
                released = _mutex_reports_released(record.mutex, lease)
            except BaseException:
                released = False
            if not released:
                try:
                    record.mutex.release(lease)  # type: ignore[attr-defined]
                except BaseException:
                    try:
                        released = _mutex_reports_released(record.mutex, lease)
                    except BaseException:
                        released = False
                else:
                    released = True
            if released:
                drained += int(
                    _finish_unclaimed_mutex_drain(
                        token,
                        record,
                        lease,
                        drain_token,
                        released=True,
                    )
                )
            else:
                _finish_unclaimed_mutex_drain(
                    token,
                    record,
                    lease,
                    drain_token,
                    released=False,
                )
            claim_resolved = True
        finally:
            if not claim_resolved:
                _finish_unclaimed_mutex_drain(
                    token,
                    record,
                    lease,
                    drain_token,
                    released=False,
                )
    return drained


class _MutexAcquisitionSink:
    """Acquirer-owned lease sink kept live until the caller acknowledges ownership."""

    def __init__(self, mutex: object) -> None:
        self._token = next(_MUTEX_ACQUISITION_TOKENS)
        self._mutex = mutex
        self._lease: object | None = None
        self._acknowledged = False
        self._entered = False
        self._exited = False
        self._record = _UnclaimedMutexLease(mutex)

    def __enter__(self) -> _MutexAcquisitionSink:
        if self._entered or self._exited:
            raise RuntimeError("mutex acquisition ownership sink cannot be re-entered")
        _drain_unclaimed_mutex_leases()
        stack = getattr(_MUTEX_ACQUISITION_LOCAL, "stack", None)
        if stack is None:
            stack = []
            _MUTEX_ACQUISITION_LOCAL.stack = stack
        try:
            with _UNCLAIMED_MUTEX_LEASES_GUARD:
                if len(_UNCLAIMED_MUTEX_LEASES) >= _MAX_UNCLAIMED_MUTEX_LEASES:
                    raise RuntimeError("unclaimed mutex lease capacity is exhausted by retained ownership evidence")
                _UNCLAIMED_MUTEX_LEASES[self._token] = self._record
            stack.append(self)
            self._entered = True
        except BaseException:
            if stack and stack[-1] is self:
                stack.pop()
            self._record.active = False
            _forget_unclaimed_mutex_lease(self._token, self._record)
            raise
        return self

    def publish(self, lease: object) -> None:
        if self._lease is not None and self._lease is not lease:
            raise RuntimeError("mutex acquisition published more than one lease to one ownership sink")
        self._lease = lease
        with _UNCLAIMED_MUTEX_LEASES_GUARD:
            record = _UNCLAIMED_MUTEX_LEASES.get(self._token)
            if record is None:
                if len(_UNCLAIMED_MUTEX_LEASES) >= _MAX_UNCLAIMED_MUTEX_LEASES:
                    raise RuntimeError("unclaimed mutex lease capacity is exhausted by retained ownership evidence")
                record = self._record
                _UNCLAIMED_MUTEX_LEASES[self._token] = record
            if record is not self._record:
                raise RuntimeError("mutex acquisition ownership token was replaced")
            if record.drain_token is not None:
                raise RuntimeError("mutex acquisition ownership record is already claimed for cleanup")
            record.lease = lease

    def acquire(self, display_id: str) -> object:
        lease = self._mutex.acquire(display_id)  # type: ignore[attr-defined]
        if self._lease is None:
            self.publish(lease)
        elif self._lease is not lease:
            raise RuntimeError("mutex acquisition returned a lease different from its published ownership")
        return lease

    def acknowledge(self, lease: object) -> None:
        if self._lease is None:
            self._lease = lease
        elif self._lease is not lease:
            raise RuntimeError("mutex acquisition acknowledgment does not match the published lease")
        previously_acknowledged = self._acknowledged
        retirement_complete = False
        try:
            self._acknowledged = True
            retirement_complete = _forget_unclaimed_mutex_lease(self._token, self._record)
        finally:
            if not retirement_complete:
                with _UNCLAIMED_MUTEX_LEASES_GUARD:
                    retirement_complete = self._token not in _UNCLAIMED_MUTEX_LEASES
                if not retirement_complete:
                    self._acknowledged = previously_acknowledged

    def __exit__(self, exc_type: object, exc: BaseException | None, _traceback: object) -> None:
        if self._exited:
            return
        stack = getattr(_MUTEX_ACQUISITION_LOCAL, "stack", None)
        stack_failure: RuntimeError | None = None
        if not stack or stack[-1] is not self:
            stack_failure = RuntimeError("mutex acquisition ownership sink stack is corrupt")
            if stack and self in stack:
                stack.remove(self)
        else:
            stack.pop()
        self._entered = False
        self._exited = True
        lease = self._lease
        cleanup_claim: int | None = None
        cleanup_claim_resolved = False
        release_dispatched = False
        try:
            with _UNCLAIMED_MUTEX_LEASES_GUARD:
                record = _UNCLAIMED_MUTEX_LEASES.get(self._token)
                if record is self._record:
                    record.active = False
                    if self._acknowledged or lease is None:
                        if record.drain_token is None:
                            _UNCLAIMED_MUTEX_LEASES.pop(self._token, None)
                    elif record.drain_token is None and record.lease is lease:
                        cleanup_claim = next(_LEASE_DRAIN_TOKENS)
                        record.drain_token = cleanup_claim
            if not self._acknowledged and lease is not None:
                cleanup_failure: RuntimeError | None = None
                cleanup_cause: BaseException | None = None
                if cleanup_claim is None:
                    cleanup_failure = RuntimeError("unacknowledged mutex acquisition cleanup ownership was unavailable")
                else:
                    try:
                        release_dispatched = True
                        self._mutex.release(lease)  # type: ignore[attr-defined]
                    except BaseException as cleanup_exc:
                        try:
                            released = _mutex_reports_released(self._mutex, lease)
                        except BaseException:
                            released = False
                        _finish_unclaimed_mutex_drain(
                            self._token,
                            self._record,
                            lease,
                            cleanup_claim,
                            released=released,
                        )
                        cleanup_claim_resolved = True
                        detail = str(cleanup_exc).strip() or type(cleanup_exc).__name__
                        if exc is None:
                            cleanup_failure = RuntimeError(f"unacknowledged mutex acquisition cleanup failed: {detail}")
                            cleanup_cause = cleanup_exc
                        else:
                            _add_exception_note(exc, f"unacknowledged mutex acquisition cleanup also failed: {detail}")
                    else:
                        _finish_unclaimed_mutex_drain(
                            self._token,
                            self._record,
                            lease,
                            cleanup_claim,
                            released=True,
                        )
                        cleanup_claim_resolved = True
                if stack_failure is not None and cleanup_failure is not None:
                    _add_exception_note(cleanup_failure, str(stack_failure))
                if cleanup_failure is not None:
                    raise cleanup_failure from cleanup_cause
        finally:
            if cleanup_claim is not None and not cleanup_claim_resolved:
                released = False
                if release_dispatched and lease is not None:
                    try:
                        released = _mutex_reports_released(self._mutex, lease)
                    except BaseException:
                        released = False
                _finish_unclaimed_mutex_drain(
                    self._token,
                    self._record,
                    lease,
                    cleanup_claim,
                    released=released,
                )
        if stack_failure is not None:
            if exc is None:
                raise stack_failure
            _add_exception_note(exc, str(stack_failure))


def _publish_mutex_lease(lease: object) -> object:
    """Single guarded ownership handoff point for acquired mutex leases."""
    stack = getattr(_MUTEX_ACQUISITION_LOCAL, "stack", None)
    if stack:
        stack[-1].publish(lease)
    return lease


class IccFileLease(Protocol):
    def validate_private_cache_identity(self, expected_path: str) -> None: ...

    def read_bytes(self) -> bytes: ...

    def close(self) -> None: ...


IccFileLeaseFactory = Callable[[str], IccFileLease]


@dataclass
class _DdcTargetOwnership:
    """Caller-held evidence for one open DDC controller and its resolved target."""

    module: Any | None = None
    controller: Any | None = None
    monitor: dict[str, Any] | None = None


@dataclass
class _IccLeaseReservation:
    token: int | None = None
    lease: IccFileLease | None = None
    retained: bool = False


@dataclass
class _IccLeaseOwnership:
    """Caller-created carrier spanning a helper return-value bytecode handoff."""

    lease: IccFileLease | None = None
    acknowledged: bool = False

    def publish(self, lease: IccFileLease) -> None:
        if self.lease is not None and self.lease is not lease:
            raise RuntimeError("ICC lease ownership carrier already holds a different lease")
        self.lease = lease

    def acknowledge(self, lease: IccFileLease) -> None:
        if self.lease is not lease:
            raise RuntimeError("ICC lease ownership acknowledgement did not match published evidence")
        self.acknowledged = True

    def recover(self, local_lease: IccFileLease | None) -> IccFileLease | None:
        if local_lease is not None:
            return local_lease
        return self.lease

    def clear(self, lease: IccFileLease | None) -> None:
        if lease is not None and self.lease is lease:
            self.lease = None


_RETAINED_ICC_LEASES: dict[int, IccFileLease] = {}
_RETAINED_ICC_LEASES_GUARD = threading.Lock()
_RETAINED_ICC_LEASE_CLAIMS: dict[int, int] = {}
_ICC_LEASE_RESERVATION_TOKENS = count(1)
_ICC_LEASE_RESERVATIONS: dict[int, _IccLeaseReservation] = {}
_ICC_LEASE_RESERVATION_BY_ID: dict[int, int] = {}


def _retire_icc_reservation_locked(lease: IccFileLease) -> None:
    lease_id = id(lease)
    reservation_token = _ICC_LEASE_RESERVATION_BY_ID.get(lease_id)
    if reservation_token is None:
        return
    reservation = _ICC_LEASE_RESERVATIONS.get(reservation_token)
    if reservation is None or reservation.lease is not lease:
        return
    retirement_complete = False
    try:
        _ICC_LEASE_RESERVATION_BY_ID.pop(lease_id, None)
        _ICC_LEASE_RESERVATIONS.pop(reservation_token, None)
        retirement_complete = True
    finally:
        if not retirement_complete:
            _ICC_LEASE_RESERVATIONS[reservation_token] = reservation
            _ICC_LEASE_RESERVATION_BY_ID[lease_id] = reservation_token


def _reserve_icc_lease_capacity(reservation: _IccLeaseReservation | None = None) -> int:
    _drain_retained_icc_leases()
    reservation_record = reservation or _IccLeaseReservation()
    with _RETAINED_ICC_LEASES_GUARD:
        reserved_ids = set(_ICC_LEASE_RESERVATION_BY_ID)
        legacy_retained = sum(token not in reserved_ids for token in _RETAINED_ICC_LEASES)
        if len(_ICC_LEASE_RESERVATIONS) + legacy_retained >= _MAX_RETAINED_ICC_LEASES:
            raise RuntimeError("ICC lease capacity is exhausted by active, pending, or retained handle evidence")
        reservation_token = next(_ICC_LEASE_RESERVATION_TOKENS)
        reservation_record.token = reservation_token
        _ICC_LEASE_RESERVATIONS[reservation_token] = reservation_record
    try:
        return reservation_token
    except BaseException:
        with _RETAINED_ICC_LEASES_GUARD:
            reservation = _ICC_LEASE_RESERVATIONS.get(reservation_token)
            if reservation is not None and reservation.lease is None:
                _ICC_LEASE_RESERVATIONS.pop(reservation_token, None)
        raise


def _activate_icc_lease_reservation(reservation_token: int, lease: IccFileLease) -> None:
    with _RETAINED_ICC_LEASES_GUARD:
        reservation = _ICC_LEASE_RESERVATIONS.get(reservation_token)
        if reservation is None or reservation.lease is not None:
            raise RuntimeError("ICC lease reservation was not pending at activation")
        lease_id = id(lease)
        if lease_id in _ICC_LEASE_RESERVATION_BY_ID:
            raise RuntimeError("ICC lease identity is already reserved")
        activated = False
        try:
            reservation.lease = lease
            _ICC_LEASE_RESERVATION_BY_ID[lease_id] = reservation_token
            activated = True
        finally:
            if not activated:
                if _ICC_LEASE_RESERVATION_BY_ID.get(lease_id) == reservation_token:
                    _ICC_LEASE_RESERVATION_BY_ID.pop(lease_id, None)
                if _ICC_LEASE_RESERVATIONS.get(reservation_token) is reservation:
                    reservation.lease = None


def _retain_late_icc_lease(reservation_token: int, lease: IccFileLease) -> None:
    """Atomically turn one pending producer reservation into retained exact evidence."""
    with _RETAINED_ICC_LEASES_GUARD:
        reservation = _ICC_LEASE_RESERVATIONS.get(reservation_token)
        if reservation is None:
            raise RuntimeError("late ICC lease has no live capacity reservation")
        lease_id = id(lease)
        existing_token = _ICC_LEASE_RESERVATION_BY_ID.get(lease_id)
        if existing_token not in (None, reservation_token):
            raise RuntimeError("late ICC lease identity is reserved by a different owner")
        existing_lease = _RETAINED_ICC_LEASES.get(lease_id)
        if existing_lease not in (None, lease):
            raise RuntimeError("late ICC lease identity collides with different retained evidence")
        previous_lease = reservation.lease
        previous_retained = reservation.retained
        publication_complete = False
        try:
            reservation.lease = lease
            _ICC_LEASE_RESERVATION_BY_ID[lease_id] = reservation_token
            _RETAINED_ICC_LEASES[lease_id] = lease
            reservation.retained = True
            publication_complete = True
        finally:
            if not publication_complete:
                reservation.lease = previous_lease
                reservation.retained = previous_retained
                if existing_token is None:
                    _ICC_LEASE_RESERVATION_BY_ID.pop(lease_id, None)
                else:
                    _ICC_LEASE_RESERVATION_BY_ID[lease_id] = existing_token
                if existing_lease is None:
                    _RETAINED_ICC_LEASES.pop(lease_id, None)
                else:
                    _RETAINED_ICC_LEASES[lease_id] = existing_lease


def _retire_pending_icc_lease_reservation(reservation_token: int) -> None:
    with _RETAINED_ICC_LEASES_GUARD:
        reservation = _ICC_LEASE_RESERVATIONS.get(reservation_token)
        if reservation is not None and reservation.lease is None:
            _ICC_LEASE_RESERVATIONS.pop(reservation_token, None)


def _retain_icc_lease(lease: IccFileLease) -> None:
    with _RETAINED_ICC_LEASES_GUARD:
        _RETAINED_ICC_LEASES[id(lease)] = lease
        reservation_token = _ICC_LEASE_RESERVATION_BY_ID.get(id(lease))
        if reservation_token is not None:
            reservation = _ICC_LEASE_RESERVATIONS.get(reservation_token)
            if reservation is not None and reservation.lease is lease:
                reservation.retained = True


def _forget_icc_lease(lease: IccFileLease) -> None:
    with _RETAINED_ICC_LEASES_GUARD:
        lease_id = id(lease)
        if lease_id in _RETAINED_ICC_LEASE_CLAIMS:
            return
        retained = _RETAINED_ICC_LEASES.get(lease_id) is lease
        retirement_complete = False
        try:
            if retained:
                _RETAINED_ICC_LEASES.pop(lease_id, None)
            _retire_icc_reservation_locked(lease)
            retirement_complete = True
        finally:
            if retained and not retirement_complete:
                _RETAINED_ICC_LEASES[lease_id] = lease


def _drain_retained_icc_leases(*, limit: int = _REGISTRY_DRAIN_LIMIT) -> int:
    """Retry bounded, exact retained ICC leases and forget only confirmed closes."""
    if type(limit) is not int or limit < 0:
        raise ValueError("retained ICC lease drain limit must be a non-negative integer")
    candidates: list[tuple[int, IccFileLease, int]] = []
    installed_claims: list[tuple[int, IccFileLease, int]] = []
    handoff_complete = False
    try:
        with _RETAINED_ICC_LEASES_GUARD:
            for token, lease in _RETAINED_ICC_LEASES.items():
                if len(candidates) >= limit:
                    break
                if token in _RETAINED_ICC_LEASE_CLAIMS:
                    continue
                drain_token = next(_LEASE_DRAIN_TOKENS)
                installed_claims.append((token, lease, drain_token))
                _RETAINED_ICC_LEASE_CLAIMS[token] = drain_token
                if _RETAINED_ICC_LEASES.get(token) is not lease:
                    _RETAINED_ICC_LEASE_CLAIMS.pop(token, None)
                    continue
                candidates.append((token, lease, drain_token))
            handoff_complete = True
    finally:
        if not handoff_complete:
            with _RETAINED_ICC_LEASES_GUARD:
                for token, lease, drain_token in installed_claims:
                    if (
                        _RETAINED_ICC_LEASE_CLAIMS.get(token) == drain_token
                        and _RETAINED_ICC_LEASES.get(token) is lease
                    ):
                        _RETAINED_ICC_LEASE_CLAIMS.pop(token, None)
    drained = 0
    for token, lease, drain_token in candidates:
        claim_resolved = False
        try:
            try:
                lease.close()
            except BaseException:
                with _RETAINED_ICC_LEASES_GUARD:
                    if _RETAINED_ICC_LEASE_CLAIMS.get(token) == drain_token:
                        _RETAINED_ICC_LEASE_CLAIMS.pop(token, None)
                claim_resolved = True
                continue
            with _RETAINED_ICC_LEASES_GUARD:
                if _RETAINED_ICC_LEASE_CLAIMS.get(token) == drain_token and _RETAINED_ICC_LEASES.get(token) is lease:
                    retirement_complete = False
                    try:
                        _RETAINED_ICC_LEASES.pop(token, None)
                        _retire_icc_reservation_locked(lease)
                        retirement_complete = True
                    finally:
                        if not retirement_complete:
                            _RETAINED_ICC_LEASES[token] = lease
                    _RETAINED_ICC_LEASE_CLAIMS.pop(token, None)
                    drained += 1
                elif _RETAINED_ICC_LEASE_CLAIMS.get(token) == drain_token:
                    _RETAINED_ICC_LEASE_CLAIMS.pop(token, None)
            claim_resolved = True
        finally:
            if not claim_resolved:
                with _RETAINED_ICC_LEASES_GUARD:
                    if _RETAINED_ICC_LEASE_CLAIMS.get(token) == drain_token:
                        _RETAINED_ICC_LEASE_CLAIMS.pop(token, None)
    return drained


def _require_icc_lease_capacity() -> None:
    _drain_retained_icc_leases()
    with _RETAINED_ICC_LEASES_GUARD:
        reserved_ids = set(_ICC_LEASE_RESERVATION_BY_ID)
        legacy_retained = sum(token not in reserved_ids for token in _RETAINED_ICC_LEASES)
        if len(_ICC_LEASE_RESERVATIONS) + legacy_retained >= _MAX_RETAINED_ICC_LEASES:
            raise RuntimeError("ICC lease capacity is exhausted by active, pending, or retained handle evidence")


class WindowsDisplayPorts(Protocol):
    """Narrow authoritative read/write pairs used by the transaction adapter."""

    def resolve_ddc_target(self, display_id: str) -> DdcTargetIdentity: ...

    def read_ddc(self, target: DdcTargetIdentity, code: str) -> DdcReading: ...

    def write_ddc(
        self,
        target: DdcTargetIdentity,
        code: str,
        value: int,
        *,
        expected_maximum: int,
    ) -> None: ...

    def capture_icc_profile(self, display_id: str) -> CapturedState[IccProfileSnapshot]: ...

    def is_icc_profile_installed(self, profile_name: str) -> bool: ...

    def is_icc_profile_associated(self, display_id: str, profile_name: str) -> bool: ...

    def materialize_icc_profile(self, profile: IccProfileSnapshot) -> IccInstallEffect: ...

    def activate_icc_profile(
        self,
        display_id: str,
        profile: IccProfileSnapshot,
        *,
        register: bool,
        associate: bool,
    ) -> IccActivationEffect: ...

    def deactivate_icc_profile(self, display_id: str, profile_name: str) -> None: ...

    def capture_gamma_ramp(self, display_id: str) -> CapturedState[GammaRamp]: ...

    def set_gamma_ramp(self, display_id: str, ramp: GammaRamp | None) -> None: ...

    def capture_dwm_luts(self, display_id: str) -> CapturedState[tuple[DwmLutSnapshot, ...]]: ...

    def set_dwm_luts(self, display_id: str, luts: tuple[DwmLutSnapshot, ...]) -> None: ...


def _normalize_gamma_ramp(ramp: object) -> GammaRamp:
    if not isinstance(ramp, Iterable):
        raise ValueError("gamma ramp must contain three integer channels")
    raw_channels: list[tuple[object, ...]] = []
    for channel in ramp:
        if not isinstance(channel, Iterable):
            raise ValueError("gamma ramp must contain three integer channels")
        raw_channels.append(tuple(channel))
    if len(raw_channels) != 3 or any(len(channel) != 256 for channel in raw_channels):
        raise ValueError("gamma ramp must contain exactly three channels of 256 values")
    if any(not isinstance(value, Integral) or isinstance(value, bool) for channel in raw_channels for value in channel):
        raise ValueError("gamma ramp entries must be integers")
    channels = tuple(tuple(int(cast(Any, value)) for value in channel) for channel in raw_channels)
    if any(value < 0 or value > 65535 for channel in channels for value in channel):
        raise ValueError("gamma ramp values must be between 0 and 65535")
    return channels  # type: ignore[return-value]


def _load_vcgt_gamma_ramp(path: str) -> GammaRamp:
    """Lazily load an exported VCGT file and resample it to Windows' 256 entries."""
    vcgt = importlib.import_module("calibrate_pro.core.vcgt")
    suffix = Path(path).suffix.casefold()
    if suffix == ".cal":
        table = vcgt.import_vcgt_cal(path)
    elif suffix == ".csv":
        table = vcgt.import_vcgt_csv(path)
    else:
        raise ValueError("VCGT application supports .cal and .csv files")
    if table.size < 2:
        raise ValueError("VCGT file must contain at least two entries")

    numpy = importlib.import_module("numpy")
    source_axis = numpy.linspace(0.0, 1.0, table.size)
    target_axis = numpy.linspace(0.0, 1.0, 256)
    channels = []
    for channel in (table.red, table.green, table.blue):
        values = numpy.interp(target_axis, source_axis, channel)
        channels.append(tuple(int(value) for value in numpy.rint(numpy.clip(values, 0.0, 1.0) * 65535.0)))
    return _normalize_gamma_ramp(tuple(channels))


def _read_exact_bytes(path: str, expected_sha256: str, label: str) -> bytes:
    limit = _MAX_CONFIRMED_ASSET_BYTES.get(label)
    if limit is None:
        raise ValueError(f"no confirmed-asset size ceiling is defined for {label}")
    try:
        source = Path(path)
        if source.stat().st_size > limit:
            raise RuntimeError(f"{label} exceeds the supported {limit}-byte size limit")
        with source.open("rb") as stream:
            payload = stream.read(limit + 1)
    except OSError as exc:
        raise RuntimeError(f"{label} could not be read: {exc}") from exc
    if len(payload) > limit:
        raise RuntimeError(f"{label} exceeds the supported {limit}-byte size limit")
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(f"{label} SHA-256 mismatch: expected {expected_sha256}, got {actual}")
    return payload


def _canonical_plan_sha256(plan: ApplyPlan) -> str:
    payload = json.dumps(asdict(plan), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _captured_state_evidence(state: CapturedState[Any] | None) -> object:
    if state is None:
        return None
    value = state.value
    if isinstance(value, IccProfileSnapshot):
        value_evidence: object = (
            value.original_path,
            len(value.payload),
            value.sha256,
            hashlib.sha256(value.payload).hexdigest(),
        )
    elif isinstance(value, tuple) and all(isinstance(item, DwmLutSnapshot) for item in value):
        value_evidence = tuple(
            (
                item.kind.value,
                item.original_path,
                len(item.payload),
                item.sha256,
                hashlib.sha256(item.payload).hexdigest(),
            )
            for item in value
        )
    else:
        value_evidence = value
    return state.status.value, value_evidence, state.detail


def _snapshot_sha256(snapshot: DisplayStateSnapshot) -> str:
    evidence = (
        snapshot.display_id,
        tuple((code, reading.current, reading.maximum) for code, reading in snapshot.ddc_values),
        None
        if snapshot.ddc_target is None
        else (snapshot.ddc_target.display_id, snapshot.ddc_target.monitor_device_path),
        _captured_state_evidence(snapshot.icc_profile),
        None
        if snapshot.icc_lifecycle is None
        else (
            snapshot.icc_lifecycle.target_profile_name,
            snapshot.icc_lifecycle.was_installed,
            snapshot.icc_lifecycle.was_associated,
        ),
        _captured_state_evidence(snapshot.gamma_ramp),
        _captured_state_evidence(snapshot.dwm_luts),
    )
    return hashlib.sha256(repr(evidence).encode("utf-8")).hexdigest()


def _icc_association_key(path: object) -> str | None:
    if path is None:
        return None
    return os.path.normcase(os.path.normpath(str(path)))


def _require_icc_profile_basename(value: object, label: str) -> str:
    if type(value) is not str or not value or Path(value).name != value:
        raise RuntimeError(f"{label} was not an exact ICC profile basename")
    return value


def _add_exception_note(exc: BaseException, note: str) -> None:
    add_note = getattr(exc, "add_note", None)
    if callable(add_note):
        add_note(note)


def _raise_cleanup_failures(context: str, failures: list[BaseException]) -> NoReturn:
    if not failures:
        raise RuntimeError(f"{context}: cleanup failure aggregation requires evidence")
    cancellation = next((failure for failure in failures if not isinstance(failure, Exception)), None)
    primary = cancellation if cancellation is not None else failures[0]
    for failure in failures:
        if failure is primary:
            continue
        detail = str(failure).strip() or type(failure).__name__
        _add_exception_note(primary, f"{context}: {detail}")
    raise primary


def _attach_icc_activation_effect(exc: BaseException, effect: IccActivationEffect) -> None:
    exc.__dict__["icc_activation_effect"] = effect


def _invoke_icc_lease_close(lease: IccFileLease, completed: list[bool]) -> None:
    if completed:
        raise RuntimeError("ICC lease cleanup was already completed")
    (lease.close(), completed.append(True))  # type: ignore[func-returns-value]


def _close_icc_lease_once(lease: IccFileLease) -> BaseException | None:
    """Close exactly, retrying a known retryable outcome and retaining failures durably."""
    completed: list[bool] = []
    try:
        _invoke_icc_lease_close(lease, completed)
    except BaseException as first_failure:
        if not completed:
            try:
                _invoke_icc_lease_close(lease, completed)
            except BaseException as close_failure:
                _retain_icc_lease(lease)
                first_detail = str(first_failure).strip() or type(first_failure).__name__
                close_detail = str(close_failure).strip() or type(close_failure).__name__
                if isinstance(first_failure, Exception) and not isinstance(close_failure, Exception):
                    _add_exception_note(close_failure, f"ICC lease cleanup handoff also failed: {first_detail}")
                    return close_failure
                _add_exception_note(first_failure, f"ICC lease close also failed: {close_detail}")
            else:
                _forget_icc_lease(lease)
                if isinstance(first_failure, Exception):
                    return None
        else:
            _retain_icc_lease(lease)
        return first_failure
    _forget_icc_lease(lease)
    return None


def _validate_icc_profile_file(path: str) -> None:
    payload = Path(path).read_bytes()
    if len(payload) < 132 or payload[36:40] != b"acsp":
        raise ValueError("ICC profile must contain a complete header and acsp signature")
    declared_size = int.from_bytes(payload[0:4], "big")
    if declared_size != len(payload):
        raise ValueError("ICC profile declared size must equal exact payload length")
    tag_count = int.from_bytes(payload[128:132], "big")
    table_end = 132 + tag_count * 12
    if table_end > len(payload):
        raise ValueError("ICC profile tag table exceeds the payload")
    for index in range(tag_count):
        entry = 132 + index * 12
        offset = int.from_bytes(payload[entry + 4 : entry + 8], "big")
        size = int.from_bytes(payload[entry + 8 : entry + 12], "big")
        if size == 0 or offset < table_end or offset + size > len(payload):
            raise ValueError("ICC profile tag payload is outside the declared profile")


def _validate_dwm_lut_file(path: str) -> None:
    if Path(path).suffix.casefold() != ".cube":
        raise ValueError("DWM LUT application requires a .cube file")
    try:
        text = Path(path).read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise ValueError("DWM LUT must be strict UTF-8 text") from exc
    if text.startswith("\ufeff"):
        raise ValueError("DWM LUT must not contain a UTF-8 BOM")
    size: int | None = None
    values = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("TITLE"):
            continue
        parts = line.split()
        if parts[0] == "LUT_3D_SIZE":
            if size is not None or len(parts) != 2:
                raise ValueError("DWM LUT must declare LUT_3D_SIZE exactly once")
            try:
                size = int(parts[1])
            except ValueError as exc:
                raise ValueError("DWM LUT size must be an integer") from exc
            if not 2 <= size <= 65:
                raise ValueError("DWM LUT size must be between 2 and 65")
            continue
        if parts[0] in {"DOMAIN_MIN", "DOMAIN_MAX"}:
            if len(parts) != 4:
                raise ValueError("DWM LUT domain rows require three values")
            numeric_parts = parts[1:]
        else:
            if len(parts) != 3:
                raise ValueError("DWM LUT data rows require exactly three values")
            numeric_parts = parts
            values += 1
        try:
            parsed = tuple(Decimal(value) for value in numeric_parts)
        except InvalidOperation as exc:
            raise ValueError("DWM LUT contains a non-decimal value") from exc
        if any(not value.is_finite() for value in parsed):
            raise ValueError("DWM LUT values must be finite")
    if size is None:
        raise ValueError("DWM LUT must declare LUT_3D_SIZE")
    if values != size**3:
        raise ValueError(f"DWM LUT requires exactly {size**3} data rows")


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


def _under_interruption_safe_lock(lock: Any, callback: Callable[[], T]) -> T:
    """Run one short critical section and recover a one-shot exit-boundary cancellation."""
    recursion_count_candidate = getattr(lock, "_recursion_count", None)
    recursion_count = (
        cast(Callable[[], int], recursion_count_candidate) if callable(recursion_count_candidate) else None
    )
    if recursion_count is None:
        is_owned = getattr(lock, "_is_owned", None)
        if callable(is_owned) and cast(Callable[[], bool], is_owned)():
            # CPython 3.10 RLock exposes ownership but not recursion depth.  The
            # caller already protects this reentrant critical section, so avoid
            # adding an indistinguishable acquisition that exception repair could
            # accidentally consume or leak.
            return callback()
    baseline_depth = recursion_count() if recursion_count is not None else None
    try:
        with lock:
            return callback()
    except BaseException:
        # CPython can deliver an asynchronous exception between the protected body
        # and the context manager's normal ``__exit__`` call.  Production guards are
        # owner-aware RLocks; their depth lets us repair exactly one leaked acquisition
        # without consuming recursive ownership held by our caller.
        leaked_acquisition = baseline_depth is None or (
            recursion_count is not None and recursion_count() > baseline_depth
        )
        if leaked_acquisition:
            try:
                lock.release()
            except RuntimeError:
                pass
        raise


def _normalize_final_windows_path(path: str) -> str:
    if path.startswith("\\\\?\\UNC\\"):
        path = "\\\\" + path[8:]
    elif path.startswith("\\\\?\\"):
        path = path[4:]
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


@dataclass
class _RetainedNativeResource:
    resource: object
    cleanup: Callable[[object], object]
    cleanup_uncertain: bool
    retention_key: tuple[int, int] | None = None
    publisher_acknowledged: bool = True
    cleanup_call: _NativeCallState | None = field(default=None, compare=False)
    cleanup_results: list[object] = field(default_factory=list, compare=False)
    cleaned: bool = False
    retired: bool = False
    token: int | None = None
    drain_guard: Any = field(default_factory=threading.RLock, compare=False, repr=False)


@dataclass
class _RetainedNativeTerminal:
    callback: Callable[[bool], None]
    cleaned: bool
    cause: BaseException
    results: list[object] = field(default_factory=list)
    delivery_guard: Any = field(default_factory=threading.RLock, compare=False, repr=False)


_MANAGED_NATIVE_CALL_TOKENS = count(1)
_RETAINED_NATIVE_RESOURCE_TOKENS = count(1)
_MANAGED_NATIVE_CALLS: dict[int, _NativeCallState] = {}
_RETAINED_NATIVE_RESOURCES: dict[int, _RetainedNativeResource] = {}
_RETAINED_NATIVE_RESOURCE_CLAIMS: dict[int, int] = {}
_RETAINED_NATIVE_RESOURCE_KEYS: dict[tuple[int, int], int] = {}
_RETAINED_NATIVE_TERMINALS: dict[tuple[int, int, bool], _RetainedNativeTerminal] = {}
_MANAGED_NATIVE_CALLS_GUARD = threading.RLock()


def _retain_native_resource(
    resource: object,
    cleanup: Callable[[object], object],
    cleanup_uncertain: bool,
) -> _RetainedNativeResource:
    """Move one managed producer slot to durable, exactly identified cleanup evidence."""
    retention_key = (id(resource), id(cleanup))
    candidate_token = next(_RETAINED_NATIVE_RESOURCE_TOKENS)

    def publish() -> _RetainedNativeResource:
        token = _RETAINED_NATIVE_RESOURCE_KEYS.setdefault(retention_key, candidate_token)
        record = _RETAINED_NATIVE_RESOURCES.get(token)
        if record is None:
            # A cancellation may have removed the reverse key immediately before the
            # final resource pop.  Recover that exact tombstone instead of publishing
            # a second generation for an already-cleaned value.
            recovered = next(
                (
                    (existing_token, existing)
                    for existing_token, existing in _RETAINED_NATIVE_RESOURCES.items()
                    if existing.retention_key == retention_key
                    and existing.resource is resource
                    and existing.cleanup is cleanup
                    and not existing.retired
                ),
                None,
            )
            if recovered is not None:
                token, record = recovered
                _RETAINED_NATIVE_RESOURCE_KEYS[retention_key] = token
            else:
                candidate = _RetainedNativeResource(
                    resource,
                    cleanup,
                    cleanup_uncertain,
                    retention_key,
                    publisher_acknowledged=False,
                    token=token,
                )
                record = _RETAINED_NATIVE_RESOURCES.setdefault(token, candidate)
        if record.resource is not resource or record.cleanup is not cleanup:
            raise RuntimeError("native retention identity collided with different ownership evidence")
        record.token = token
        if cleanup_uncertain:
            record.cleanup_uncertain = True
        return record

    return _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, publish)


def _retained_native_resource_occupancy_locked() -> int:
    """Count only resources whose cleanup has not completed successfully."""
    return sum(not record.cleaned and not record.retired for record in _RETAINED_NATIVE_RESOURCES.values())


def _finalize_retained_native_resource_locked(token: int, record: _RetainedNativeResource) -> None:
    """Retire both indexes before propagating a one-shot lifecycle interruption."""
    try:
        record.retired = True
        retention_key = record.retention_key
        if retention_key is not None and _RETAINED_NATIVE_RESOURCE_KEYS.get(retention_key) == token:
            _RETAINED_NATIVE_RESOURCE_KEYS.pop(retention_key, None)
        if _RETAINED_NATIVE_RESOURCES.get(token) is record:
            _RETAINED_NATIVE_RESOURCES.pop(token, None)
        _RETAINED_NATIVE_RESOURCE_CLAIMS.pop(token, None)
    except BaseException:
        # The lifecycle RLock is still held here.  Finish the idempotent transition
        # before the interruption escapes, so no concurrent publisher can observe
        # only one side of the resource/reverse-key pair.
        retention_key = record.retention_key
        if retention_key is not None and _RETAINED_NATIVE_RESOURCE_KEYS.get(retention_key) == token:
            _RETAINED_NATIVE_RESOURCE_KEYS.pop(retention_key, None)
        if _RETAINED_NATIVE_RESOURCES.get(token) is record:
            _RETAINED_NATIVE_RESOURCES.pop(token, None)
        _RETAINED_NATIVE_RESOURCE_CLAIMS.pop(token, None)
        raise


def _ack_retained_native_resource(record: _RetainedNativeResource) -> None:
    """Acknowledge that the orphan carrier durably stored this exact receipt."""

    def acknowledge() -> None:
        def mutate() -> None:
            record.publisher_acknowledged = True
            token = record.token
            if token is None:
                token = next(
                    (
                        candidate_token
                        for candidate_token, candidate in _RETAINED_NATIVE_RESOURCES.items()
                        if candidate is record
                    ),
                    None,
                )
                record.token = token
            if token is not None and record.cleaned:
                _finalize_retained_native_resource_locked(token, record)

        _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, mutate)

    _under_interruption_safe_lock(record.drain_guard, acknowledge)


def _publish_native_terminal(
    callback: Callable[[bool], None],
    cleaned: bool,
    cause: BaseException,
) -> tuple[tuple[int, int, bool], _RetainedNativeTerminal]:
    key = (id(callback), id(cause), cleaned)
    record = _RETAINED_NATIVE_TERMINALS.setdefault(key, _RetainedNativeTerminal(callback, cleaned, cause))
    if record.callback is not callback or record.cause is not cause or record.cleaned is not cleaned:
        raise RuntimeError("native terminal identity collided with different evidence")
    return key, record


def _deliver_native_terminal(record: _RetainedNativeTerminal) -> bool:
    """Give one thread the callback claim and preserve successful delivery evidence."""
    is_owned = getattr(record.delivery_guard, "_is_owned", None)
    if callable(is_owned) and cast(Callable[[], bool], is_owned)():
        return False

    def deliver() -> bool:
        if record.results:
            return True
        recursion_count = getattr(record.delivery_guard, "_recursion_count", None)
        if callable(recursion_count) and cast(Callable[[], int], recursion_count)() > 1:
            return False
        try:
            record.results.extend(map(record.callback, (record.cleaned,)))
        except BaseException as terminal_exc:
            detail = str(terminal_exc).strip() or type(terminal_exc).__name__
            _add_exception_note(record.cause, f"native terminal publication also failed: {detail}")
            return False
        return bool(record.results)

    return _under_interruption_safe_lock(record.delivery_guard, deliver)


def _drain_retained_native_terminals(*, limit: int = _REGISTRY_DRAIN_LIMIT) -> int:
    if type(limit) is not int or limit < 0:
        raise ValueError("retained native terminal drain limit must be a non-negative integer")
    drained = 0
    for key, record in list(_RETAINED_NATIVE_TERMINALS.items())[:limit]:
        delivered = _deliver_native_terminal(record)
        if delivered and _RETAINED_NATIVE_TERMINALS.get(key) is record:
            _RETAINED_NATIVE_TERMINALS.pop(key, None)
            drained += 1
    return drained


def _drain_retained_native_resources(*, limit: int = _REGISTRY_DRAIN_LIMIT) -> int:
    """Retry known failures while quarantining any cleanup whose outcome is uncertain.

    An uncertain native cleanup may already have released a numeric handle that Windows
    can recycle.  It therefore remains as bounded ownership evidence for manual review;
    this automatic drain never calls its cleanup function again.
    """
    if type(limit) is not int or limit < 0:
        raise ValueError("retained native resource drain limit must be a non-negative integer")

    def select_candidates() -> list[tuple[int, _RetainedNativeResource]]:
        candidates: list[tuple[int, _RetainedNativeResource]] = []
        for token, record in list(_RETAINED_NATIVE_RESOURCES.items()):
            record.token = token
            if record.retired or (record.cleaned and record.publisher_acknowledged):
                _finalize_retained_native_resource_locked(token, record)
                continue
            if len(candidates) >= limit:
                break
            if record.cleanup_uncertain or record.cleaned:
                continue
            candidates.append((token, record))
        return candidates

    candidates = _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, select_candidates)
    drained = 0
    for token, record in candidates:

        def drain_one(
            token: int = token,
            record: _RetainedNativeResource = record,
        ) -> int:
            def prepare() -> _NativeCallState | None:
                if _RETAINED_NATIVE_RESOURCES.get(token) is not record:
                    return None
                if record.retired or (record.cleaned and record.publisher_acknowledged):
                    _finalize_retained_native_resource_locked(token, record)
                    return None
                if record.cleanup_uncertain or record.cleaned:
                    return None
                if record.cleanup_call is None:
                    record.cleanup_call = _NativeCallState(record.cleanup, record.resource)
                return record.cleanup_call

            cleanup_call = _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, prepare)
            if cleanup_call is None:
                return 0

            try:
                result = cleanup_call.invoke()
            except BaseException:
                if cleanup_call.completed and cleanup_call.error is not None:

                    def quarantine() -> None:
                        if _RETAINED_NATIVE_RESOURCES.get(token) is record:
                            record.cleanup_uncertain = True

                    _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, quarantine)
                    return 0
                raise

            cleaned = bool(result)

            def publish_result() -> int:
                if _RETAINED_NATIVE_RESOURCES.get(token) is not record:
                    return 0
                if not record.cleanup_results:
                    record.cleanup_results.append(result)
                if cleaned:
                    record.cleaned = True
                    if record.publisher_acknowledged:
                        _finalize_retained_native_resource_locked(token, record)
                    return 1
                else:
                    # A confirmed failure is retryable.  The completed call state is
                    # replaced; caller cancellation never repeats a successful call.
                    record.cleanup_call = None
                    record.cleanup_results.clear()
                    return 0

            return _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, publish_result)

        drained += _under_interruption_safe_lock(record.drain_guard, drain_one)
    return drained


@dataclass
class _NativeOrphanClaim:
    owner: threading.Thread
    generation: int


_NATIVE_ORPHAN_CLAIM_TOKENS = count(1)


@dataclass
class _NativeOrphanCarrier:
    """Durable, resumable ownership evidence for one abandoned native result."""

    resource: object
    cause: BaseException
    claim: dict[int, _NativeOrphanClaim | threading.Thread] = field(default_factory=dict)
    claim_guard: Any = field(default_factory=threading.RLock, repr=False)
    cleanup_results: list[object] = field(default_factory=list)
    cleanup_uncertain: set[int] = field(default_factory=set)
    retention_results: list[object] = field(default_factory=list)
    retention_ack_results: list[object] = field(default_factory=list)
    terminal_results: list[object] = field(default_factory=list)
    terminal_key: tuple[int, int, bool] | None = None
    terminal_record: _RetainedNativeTerminal | None = None
    resolved: set[int] = field(default_factory=set)


class _NativeCallState:
    """Cancellation-isolated native-call result carrier owned by the caller."""

    def __init__(
        self,
        callback: Callable[..., object],
        *args: object,
        orphan_cleanup: Callable[[object], object] | None = None,
        orphan_retain: Callable[[object, bool], object] | None = None,
        orphan_terminal: Callable[[bool], None] | None = None,
    ) -> None:
        self._callback = callback
        self._args = args
        self._orphan_cleanup = orphan_cleanup
        self._orphan_retain = orphan_retain
        self._orphan_terminal = orphan_terminal
        self._event = threading.Event()
        self._dispatch_guard = threading.Lock()
        self._outcome_guard = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._start_succeeded = False
        self._start_uncertain = False
        self._abandoned = False
        self._timeout_error: RuntimeError | None = None
        self._orphan_carriers: dict[int, _NativeOrphanCarrier] = {}
        self.entered = False
        self.completed = False
        self.result: object | None = None
        self.error: BaseException | None = None
        self._managed_token: int | None = None
        self._no_result_terminal_key: tuple[int, int, bool] | None = None
        self._no_result_terminal_record: _RetainedNativeTerminal | None = None
        if orphan_cleanup is not None:
            _drain_retained_native_resources()
            managed_token = next(_MANAGED_NATIVE_CALL_TOKENS)
            try:

                def reserve() -> None:
                    self._managed_token = managed_token
                    if _MANAGED_NATIVE_CALLS.setdefault(managed_token, self) is not self:
                        raise RuntimeError("managed native call token collided with existing ownership")
                    occupied = len(_MANAGED_NATIVE_CALLS) + _retained_native_resource_occupancy_locked()
                    if occupied > _MAX_MANAGED_NATIVE_RESOURCES:
                        raise RuntimeError(
                            "native resource capacity is exhausted by active, pending, or retained cleanup evidence"
                        )

                _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, reserve)
            except BaseException:
                self._retire_managed()
                raise

    def _retire_managed(self) -> None:
        def retire() -> None:
            managed_token = self._managed_token
            if managed_token is None:
                return
            if _MANAGED_NATIVE_CALLS.get(managed_token) is self:
                _MANAGED_NATIVE_CALLS.pop(managed_token, None)
            self._managed_token = None

        _under_interruption_safe_lock(_MANAGED_NATIVE_CALLS_GUARD, retire)

    def handoff(self) -> None:
        """Acknowledge that exact result ownership moved to caller-held evidence."""
        self._retire_managed()

    @property
    def abandoned(self) -> bool:
        with self._outcome_guard:
            return self._abandoned

    @staticmethod
    def _orphan_claim_owner(claim: _NativeOrphanClaim | threading.Thread) -> threading.Thread:
        return claim.owner if isinstance(claim, _NativeOrphanClaim) else claim

    @staticmethod
    def _acquire_orphan_claim(
        carrier: _NativeOrphanCarrier,
        slot: int,
    ) -> _NativeOrphanClaim | None:
        owner = threading.current_thread()
        while True:

            def inspect_claim() -> tuple[_NativeOrphanClaim | None, _NativeOrphanClaim | threading.Thread | None]:
                existing = carrier.claim.get(slot)
                if existing is None:
                    claim = _NativeOrphanClaim(owner, next(_NATIVE_ORPHAN_CLAIM_TOKENS))
                    carrier.claim[slot] = claim
                    return claim, None
                if _NativeCallState._orphan_claim_owner(existing) is owner:
                    if isinstance(existing, _NativeOrphanClaim):
                        return existing, None
                    claim = _NativeOrphanClaim(owner, next(_NATIVE_ORPHAN_CLAIM_TOKENS))
                    if carrier.claim.get(slot) is existing:
                        carrier.claim[slot] = claim
                        return claim, None
                    return None, None
                return None, existing

            acquired, observed = _under_interruption_safe_lock(carrier.claim_guard, inspect_claim)
            if acquired is not None:
                return acquired
            if observed is None:
                continue
            assert observed is not None
            dead_claim: _NativeOrphanClaim | threading.Thread = observed
            observed_owner = _NativeCallState._orphan_claim_owner(dead_claim)

            if observed_owner.is_alive():
                return None

            replacement = _NativeOrphanClaim(owner, next(_NATIVE_ORPHAN_CLAIM_TOKENS))

            def replace_dead_claim(
                observed: _NativeOrphanClaim | threading.Thread = dead_claim,
                replacement: _NativeOrphanClaim = replacement,
            ) -> bool:
                if carrier.claim.get(slot) is observed:
                    carrier.claim[slot] = replacement
                    return True
                return False

            if _under_interruption_safe_lock(carrier.claim_guard, replace_dead_claim):
                return replacement

    @staticmethod
    def _orphan_claim_is_current(
        carrier: _NativeOrphanCarrier,
        slot: int,
        claim: _NativeOrphanClaim,
    ) -> bool:
        return _under_interruption_safe_lock(
            carrier.claim_guard,
            lambda: carrier.claim.get(slot) is claim,
        )

    @staticmethod
    def _release_orphan_claim(
        carrier: _NativeOrphanCarrier,
        slot: int,
        claim: _NativeOrphanClaim,
    ) -> None:
        def release() -> None:
            if carrier.claim.get(slot) is claim:
                carrier.claim.pop(slot, None)

        _under_interruption_safe_lock(carrier.claim_guard, release)

    def _finish_orphan_once(self, result: object, cause: BaseException) -> bool:
        """Advance one abandoned result through its resumable, lock-free claim.

        The carrier is published before a claim exists.  Every external stage writes its
        result into the carrier through a C-level ``list.extend(map(...))`` sink, closing
        the post-call/store gap.  A cancellation can therefore be retried without either
        repeating a known cleanup or losing the exact resource returned by the producer.
        """
        slot = 0
        candidate = _NativeOrphanCarrier(result, cause)
        carrier = self._orphan_carriers.setdefault(slot, candidate)
        if carrier.resource is not result:
            raise RuntimeError("native call produced conflicting orphan ownership evidence")
        resolved = _under_interruption_safe_lock(
            carrier.claim_guard,
            lambda: slot in carrier.resolved,
        )
        if resolved:
            self._retire_managed()
            return True

        claim = self._acquire_orphan_claim(carrier, slot)
        if claim is None:
            return False

        if not carrier.cleanup_results and slot not in carrier.cleanup_uncertain:
            carrier.cleanup_uncertain.add(slot)
            try:
                if self._orphan_cleanup is None:
                    carrier.cleanup_results.append(False)
                else:
                    carrier.cleanup_results.extend(map(self._orphan_cleanup, (carrier.resource,)))
            except BaseException as cleanup_exc:
                detail = str(cleanup_exc).strip() or type(cleanup_exc).__name__
                _add_exception_note(carrier.cause, f"native orphan cleanup outcome is uncertain: {detail}")
            else:
                carrier.cleanup_uncertain.discard(slot)

        cleaned = bool(carrier.cleanup_results[0]) if carrier.cleanup_results else False
        cleanup_uncertain = slot in carrier.cleanup_uncertain
        if not self._orphan_claim_is_current(carrier, slot, claim):
            return False
        if not cleaned and not carrier.retention_results:
            try:
                if self._orphan_retain is None:
                    raise RuntimeError("native orphan has no exact retention sink")
                carrier.retention_results.extend(map(self._orphan_retain, (carrier.resource,), (cleanup_uncertain,)))
            except BaseException as retain_exc:
                if not carrier.retention_results:
                    detail = str(retain_exc).strip() or type(retain_exc).__name__
                    _add_exception_note(carrier.cause, f"native orphan retention also failed: {detail}")
                    self._release_orphan_claim(carrier, slot, claim)
                    return False

        if not self._orphan_claim_is_current(carrier, slot, claim):
            return False

        if carrier.retention_results and not carrier.retention_ack_results:
            receipt = next(
                (value for value in carrier.retention_results if isinstance(value, _RetainedNativeResource)),
                None,
            )
            if receipt is not None:
                try:
                    carrier.retention_ack_results.extend(map(_ack_retained_native_resource, (receipt,)))
                except BaseException as ack_exc:
                    if not carrier.retention_ack_results:
                        detail = str(ack_exc).strip() or type(ack_exc).__name__
                        _add_exception_note(carrier.cause, f"native retention acknowledgement failed: {detail}")
                        self._release_orphan_claim(carrier, slot, claim)
                        return False
            else:
                carrier.retention_ack_results.append(None)

        if not self._orphan_claim_is_current(carrier, slot, claim):
            return False
        if self._orphan_terminal is None:
            if not carrier.terminal_results:
                carrier.terminal_results.append(None)
        else:
            try:
                if carrier.terminal_record is None:
                    published_key, published_record = _publish_native_terminal(
                        self._orphan_terminal,
                        cleaned,
                        carrier.cause,
                    )
                    carrier.terminal_key = published_key
                    carrier.terminal_record = published_record
            except BaseException as terminal_exc:
                detail = str(terminal_exc).strip() or type(terminal_exc).__name__
                _add_exception_note(
                    carrier.cause,
                    f"native orphan terminal publication also failed: {detail}",
                )
                self._release_orphan_claim(carrier, slot, claim)
                return False
            terminal_record = carrier.terminal_record
            stored_terminal_key = carrier.terminal_key
            assert terminal_record is not None
            assert stored_terminal_key is not None
            delivered = _deliver_native_terminal(terminal_record)
            if delivered:
                if not carrier.terminal_results:
                    carrier.terminal_results.extend(terminal_record.results)
                if _RETAINED_NATIVE_TERMINALS.get(stored_terminal_key) is terminal_record:
                    _RETAINED_NATIVE_TERMINALS.pop(stored_terminal_key, None)

        def resolve() -> bool:
            if carrier.claim.get(slot) is not claim:
                return False
            carrier.resolved.add(slot)
            carrier.claim.pop(slot, None)
            return True

        if not _under_interruption_safe_lock(carrier.claim_guard, resolve):
            return False
        self._retire_managed()
        return True

    def _finish_orphan(self, result: object, cause: BaseException) -> None:
        """Resolve an orphan and honor cancellation only after ownership is safe."""
        cancellation: BaseException | None = None
        for _attempt in range(2):
            try:
                completed = self._finish_orphan_once(result, cause)
            except (KeyboardInterrupt, SystemExit) as exc:
                if cancellation is not None:
                    raise
                cancellation = exc
                continue
            if completed:
                break
        if cancellation is not None:
            raise cancellation

    def _finish_no_result_terminal_once(self, cause: BaseException) -> None:
        callback = self._orphan_terminal
        if callback is None:
            self._retire_managed()
            return
        if self._no_result_terminal_record is None:
            key, record = _publish_native_terminal(callback, True, cause)
            self._no_result_terminal_key = key
            self._no_result_terminal_record = record
        else:
            stored_key = self._no_result_terminal_key
            record = self._no_result_terminal_record
            assert stored_key is not None
            key = stored_key
        delivered = _deliver_native_terminal(record)
        self._retire_managed()
        if delivered and _RETAINED_NATIVE_TERMINALS.get(key) is record:
            _RETAINED_NATIVE_TERMINALS.pop(key, None)

    def _finish_no_result_terminal(self, cause: BaseException) -> None:
        """Publish terminal state or retain its exact retry without consuming resource capacity."""
        cancellation: BaseException | None = None
        for _attempt in range(2):
            try:
                self._finish_no_result_terminal_once(cause)
            except (KeyboardInterrupt, SystemExit) as exc:
                if cancellation is not None:
                    _add_exception_note(cause, f"native terminal recovery was also cancelled: {type(exc).__name__}")
                    return
                cancellation = exc
                continue
            break
        if cancellation is not None:
            detail = str(cancellation).strip() or type(cancellation).__name__
            _add_exception_note(cause, f"native terminal handoff resumed after cancellation: {detail}")

    def _abandon_invoke(self, cause: BaseException) -> None:
        """Transfer an unreturned producer result back to orphan management."""
        orphan_result: object | None = None
        completed_result = False
        completed_error = False
        with self._outcome_guard:
            if self._managed_token is None:
                return
            self._abandoned = True
            if self._timeout_error is None and isinstance(cause, RuntimeError):
                self._timeout_error = cause
            if self.completed:
                if self.error is None:
                    orphan_result = self.result
                    self.result = None
                    completed_result = True
                else:
                    completed_error = True
            elif not self._start_succeeded and not self._start_uncertain and self._thread.ident is None:
                completed_error = True
        if completed_result:
            self._finish_orphan(orphan_result, cause)
        elif completed_error:
            self._finish_no_result_terminal(cause)

    def _run(self) -> None:
        try:
            self.entered = True
            try:
                result = self._callback(*self._args)
            except BaseException as exc:
                with self._outcome_guard:
                    abandoned = self._abandoned
                    terminal_error = self._timeout_error if abandoned and self._timeout_error is not None else exc
                    self.error = terminal_error
                    self.completed = True
                if abandoned:
                    self._finish_no_result_terminal(terminal_error)
                return

            publication_error: BaseException | None = None
            orphaned = False
            try:
                with self._outcome_guard:
                    orphaned = self._abandoned
                    if not orphaned:
                        self.result = result
                        self.completed = True
            except BaseException as exc:
                publication_error = exc
                orphaned = True
            if orphaned:
                cause = (
                    publication_error or self._timeout_error or RuntimeError("native result ownership was abandoned")
                )
                try:
                    self._finish_orphan(result, cause)
                except BaseException as orphan_exc:
                    detail = str(orphan_exc).strip() or type(orphan_exc).__name__
                    _add_exception_note(cause, f"native orphan handoff was resumed after cancellation: {detail}")
                    self._finish_orphan(result, cause)
                with self._outcome_guard:
                    self.error = cause
                    self.completed = True
        finally:
            self._event.set()

    def _call_thread_start(self) -> None:
        try:
            self._thread.start()
        except BaseException as exc:
            if self._thread.ident is not None:
                self._start_succeeded = True
            elif not isinstance(exc, Exception):
                self._start_uncertain = True
            raise
        self._start_succeeded = True

    def _start(self) -> None:
        with self._dispatch_guard:
            if self.completed or self._start_succeeded or self._start_uncertain or self._thread.ident is not None:
                return
            self._call_thread_start()

    def invoke(self) -> object:
        try:
            self._start()
            if not self._event.wait(_NATIVE_CALL_SETTLE_TIMEOUT_SECONDS):
                state = "entered" if self.entered else "not entered"
                timeout_error = RuntimeError(f"native call did not settle within its bounded wait ({state})")
                self._abandon_invoke(timeout_error)
                raise timeout_error
            with self._outcome_guard:
                error = self.error
                result = self.result
            if error is not None:
                raise error
            return result
        except BaseException as exc:
            self._abandon_invoke(exc)
            raise


def _invoke_windows_handle_close(
    close_handle: Callable[[object], object],
    handle: object,
    native_call: _NativeCallState,
) -> bool:
    return native_call.invoke() != 0  # close_handle(handle)


def _invoke_windows_mutex_release(
    release_mutex: Callable[[object], object],
    handle: object,
    native_call: _NativeCallState,
) -> bool:
    return native_call.invoke() != 0  # release_mutex(handle)


def _windows_mutex_release_callable(kernel32: Any) -> Callable[[object], object]:
    return cast(Callable[[object], object], kernel32.ReleaseMutex)


class _WindowsIccFileLease:
    """Read handle that permits readers while denying path writes and deletion."""

    _GENERIC_READ = 0x80000000
    _FILE_SHARE_READ = 0x00000001
    _OPEN_EXISTING = 3
    _FILE_ATTRIBUTE_NORMAL = 0x00000080
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _FILE_TYPE_DISK = 0x0001
    _MAX_PROFILE_BYTES = 64 * 1024 * 1024

    def __init__(self, path: str, kernel32_loader: Callable[[], Any] | None = None) -> None:
        kernel32 = (kernel32_loader or (lambda: ctypes.WinDLL("kernel32", use_last_error=True)))()
        self._kernel32 = kernel32
        self._handle: object | None = None
        self._close_poisoned = False
        kernel32.CreateFileW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        kernel32.CreateFileW.restype = ctypes.c_void_p
        kernel32.GetFileSizeEx.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_longlong)]
        kernel32.GetFileSizeEx.restype = wintypes.BOOL
        kernel32.ReadFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_void_p,
        ]
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.SetFilePointerEx.argtypes = [
            ctypes.c_void_p,
            ctypes.c_longlong,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        kernel32.SetFilePointerEx.restype = wintypes.BOOL
        kernel32.GetFileInformationByHandle.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ByHandleFileInformation),
        ]
        kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
        kernel32.GetFileType.argtypes = [ctypes.c_void_p]
        kernel32.GetFileType.restype = wintypes.DWORD
        kernel32.GetFinalPathNameByHandleW.argtypes = [
            ctypes.c_void_p,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = wintypes.BOOL
        invalid_handle = ctypes.c_void_p(-1).value
        handle: object | None = None

        def cleanup_orphan_handle(value: object) -> bool:
            if value in (None, 0, invalid_handle):
                return True
            return kernel32.CloseHandle(value) != 0

        def retain_orphan_handle(value: object, cleanup_uncertain: bool) -> object:
            if value not in (None, 0, invalid_handle):
                return _retain_native_resource(value, cleanup_orphan_handle, cleanup_uncertain)
            return None

        create_call = _NativeCallState(
            kernel32.CreateFileW,
            path,
            self._GENERIC_READ,
            self._FILE_SHARE_READ,
            None,
            self._OPEN_EXISTING,
            self._FILE_ATTRIBUTE_NORMAL | self._FILE_FLAG_OPEN_REPARSE_POINT,
            None,
            orphan_cleanup=cleanup_orphan_handle,
            orphan_retain=retain_orphan_handle,
        )
        try:
            handle = create_call.invoke()  # CreateFileW(...) result is already carrier-owned.
            if not handle or handle == invalid_handle:
                raise RuntimeError(f"ICC profile lease could not be opened: {ctypes.WinError(ctypes.get_last_error())}")
            self._handle = handle
            create_call.handoff()
        except BaseException as exc:
            if handle is None and create_call.completed and not create_call.abandoned:
                handle = create_call.result
            if handle not in (None, 0, invalid_handle):
                self._handle = handle
                try:
                    self.close()
                except BaseException as close_exc:
                    detail = str(close_exc).strip() or type(close_exc).__name__
                    _add_exception_note(exc, f"ICC profile lease construction cleanup also failed: {detail}")
            if not create_call.abandoned:
                create_call.handoff()
            raise

    def validate_private_cache_identity(self, expected_path: str) -> None:
        """Prove the held object is the exact regular, private content-address path."""
        if self._handle is None:
            raise RuntimeError("ICC profile lease is closed")
        if self._kernel32.GetFileType(self._handle) != self._FILE_TYPE_DISK:
            raise RuntimeError("product ICC cache identity is not a disk file")
        information = _ByHandleFileInformation()
        if not self._kernel32.GetFileInformationByHandle(self._handle, ctypes.byref(information)):
            raise RuntimeError(f"product ICC cache identity read failed: {ctypes.WinError(ctypes.get_last_error())}")
        attributes = int(information.dwFileAttributes)
        if attributes & self._FILE_ATTRIBUTE_REPARSE_POINT:
            raise RuntimeError("product ICC cache identity is a reparse point")
        if attributes & self._FILE_ATTRIBUTE_DIRECTORY:
            raise RuntimeError("product ICC cache identity is not a regular file")
        if int(information.nNumberOfLinks) != 1:
            raise RuntimeError("product ICC cache identity is not a private single-link file")

        required = int(self._kernel32.GetFinalPathNameByHandleW(self._handle, None, 0, 0))
        if required <= 0:
            raise RuntimeError(f"product ICC cache final path query failed: {ctypes.WinError(ctypes.get_last_error())}")
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = int(self._kernel32.GetFinalPathNameByHandleW(self._handle, buffer, len(buffer), 0))
        if written <= 0 or written >= len(buffer):
            raise RuntimeError(f"product ICC cache final path read failed: {ctypes.WinError(ctypes.get_last_error())}")
        if _normalize_final_windows_path(buffer.value) != _normalize_final_windows_path(expected_path):
            raise RuntimeError("product ICC cache handle does not resolve to its exact content-addressed path")

    def read_bytes(self) -> bytes:
        if self._handle is None:
            raise RuntimeError("ICC profile lease is closed")
        size = ctypes.c_longlong()
        if not self._kernel32.GetFileSizeEx(self._handle, ctypes.byref(size)):
            raise RuntimeError(f"ICC profile lease size read failed: {ctypes.WinError(ctypes.get_last_error())}")
        if not 0 <= size.value <= self._MAX_PROFILE_BYTES:
            raise RuntimeError("ICC profile lease size is outside the supported range")
        if not self._kernel32.SetFilePointerEx(self._handle, 0, None, 0):
            raise RuntimeError(f"ICC profile lease seek failed: {ctypes.WinError(ctypes.get_last_error())}")
        if size.value == 0:
            return b""
        buffer = (ctypes.c_ubyte * size.value)()
        read = ctypes.c_ulong()
        if not self._kernel32.ReadFile(self._handle, buffer, size.value, ctypes.byref(read), None):
            raise RuntimeError(f"ICC profile lease read failed: {ctypes.WinError(ctypes.get_last_error())}")
        if read.value != size.value:
            raise RuntimeError("ICC profile lease produced a short read")
        return bytes(buffer)

    def close(self) -> None:
        if self._close_poisoned:
            raise RuntimeError("ICC profile lease close is poisoned because the native close outcome is uncertain")
        handle = self._handle
        if handle is None:
            return
        close_handle = self._kernel32.CloseHandle
        native_call = _NativeCallState(close_handle, handle)
        closed = False
        try:
            closed = _invoke_windows_handle_close(close_handle, handle, native_call)  # CloseHandle(handle)
        except BaseException as dispatch_exc:
            try:
                closed = _invoke_windows_handle_close(close_handle, handle, native_call)
            except BaseException:
                if native_call.entered:
                    self._close_poisoned = True
                raise dispatch_exc from None
            if closed:
                self._handle = None
            raise dispatch_exc
        if closed:
            self._handle = None
        else:
            raise RuntimeError(
                f"ICC profile lease close failed and remains retryable: {ctypes.WinError(ctypes.get_last_error())}"
            )


class DefaultWindowsDisplayPorts:
    """Lazy adapters over existing Windows modules, with ambiguous reads rejected."""

    def __init__(
        self,
        *,
        module_loader: ModuleLoader = importlib.import_module,
        monitor_name_resolver: MonitorNameResolver | None = None,
        ddc_identity_resolver: DdcIdentityResolver | None = None,
        physical_monitor_identity_resolver: PhysicalMonitorIdentityResolver | None = None,
        icc_file_lease_factory: IccFileLeaseFactory = _WindowsIccFileLease,
    ) -> None:
        self._load_module = module_loader
        self._monitor_name_resolver = monitor_name_resolver
        self._ddc_identity_resolver = ddc_identity_resolver
        self._physical_monitor_identity_resolver = physical_monitor_identity_resolver
        self._icc_file_lease_factory = icc_file_lease_factory
        self._ddc_module: Any | None = None
        self._dwm_module: Any | None = None
        self._dwm_controller: Any | None = None

    def _open_icc_file_lease(
        self,
        path: str,
        ownership: _IccLeaseOwnership | None = None,
    ) -> IccFileLease:
        ownership = ownership or _IccLeaseOwnership()
        reservation = _IccLeaseReservation()
        reservation_token: int | None = None
        lease: IccFileLease | None = None
        factory_call: _NativeCallState | None = None
        try:
            reservation_token = _reserve_icc_lease_capacity(reservation)

            def cleanup_late_lease(value: object) -> bool:
                return _close_icc_lease_once(cast(IccFileLease, value)) is None

            def retain_late_lease(value: object, _cleanup_uncertain: bool) -> None:
                assert reservation_token is not None
                _retain_late_icc_lease(reservation_token, cast(IccFileLease, value))

            def finish_late_lease(cleaned: bool) -> None:
                if cleaned:
                    assert reservation_token is not None
                    _retire_pending_icc_lease_reservation(reservation_token)

            factory_call = _NativeCallState(
                self._icc_file_lease_factory,
                path,
                orphan_cleanup=cleanup_late_lease,
                orphan_retain=retain_late_lease,
                orphan_terminal=finish_late_lease,
            )
            lease = cast(IccFileLease, factory_call.invoke())  # icc_file_lease_factory(...) carrier
            _activate_icc_lease_reservation(reservation_token, lease)
            ownership.publish(lease)
            factory_call.handoff()
        except BaseException:
            if (
                lease is None
                and factory_call is not None
                and factory_call.completed
                and not factory_call.abandoned
                and factory_call.result is not None
            ):
                lease = cast(IccFileLease, factory_call.result)
            lease = ownership.recover(lease)
            if lease is not None:
                _close_icc_lease_once(lease)
                ownership.clear(lease)
            abandoned = factory_call is not None and factory_call.abandoned
            if factory_call is not None and not abandoned:
                factory_call.handoff()
            cleanup_token = reservation_token if reservation_token is not None else reservation.token
            if cleanup_token is not None and not abandoned:
                _retire_pending_icc_lease_reservation(cleanup_token)
            raise
        return cast(IccFileLease, lease)

    def _ddc_module_value(self) -> Any:
        if self._ddc_module is None:
            self._ddc_module = self._load_module("calibrate_pro.hardware.ddc_ci")
        return self._ddc_module

    def _resolve_monitor_name(self, handle: object) -> str | None:
        if self._monitor_name_resolver is not None:
            return self._monitor_name_resolver(handle)
        detection = self._load_module("calibrate_pro.panels.detection")
        info = detection.MONITORINFOEX()
        info.cbSize = ctypes.sizeof(info)
        if not detection.user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            return None
        return str(info.szDevice)

    def _resolve_ddc_device_path(self, display_id: str) -> str:
        if self._ddc_identity_resolver is not None:
            path = self._ddc_identity_resolver(display_id)
        else:
            detection = self._load_module("calibrate_pro.panels.detection")
            matches = [
                display
                for display in detection.enumerate_displays()
                if str(display.device_name).casefold() == display_id.casefold()
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    f"DDC/CI display identity {display_id!r} resolved to {len(matches)} PnP device paths"
                )
            path = str(matches[0].device_id)
        if type(path) is not str or not path.strip():
            raise RuntimeError(f"DDC/CI display identity {display_id!r} has no stable PnP device path")
        return path

    @staticmethod
    def _close_ddc_controller(controller: Any) -> None:
        close = getattr(controller, "close", None)
        if not callable(close):
            raise RuntimeError("DDC/CI controller cannot prove physical monitor handle cleanup")
        close()

    @classmethod
    def _close_ddc_after_failure(cls, controller: Any, primary: BaseException) -> NoReturn:
        """Attempt handle cleanup without replacing a primary control-flow exception."""
        try:
            cls._close_ddc_controller(controller)
        except BaseException as close_exc:
            primary_detail = str(primary).strip() or type(primary).__name__
            close_detail = str(close_exc).strip() or type(close_exc).__name__
            if not isinstance(primary, Exception):
                _add_exception_note(primary, f"DDC/CI controller close also failed: {close_detail}")
                raise primary from close_exc
            if not isinstance(close_exc, Exception):
                _add_exception_note(close_exc, f"DDC/CI operation also failed: {primary_detail}")
                raise close_exc from primary
            raise RuntimeError(
                f"DDC/CI operation failed ({primary_detail}); controller close also failed ({close_detail})"
            ) from primary
        raise primary

    def _resolve_physical_monitor_identity(self, monitor: dict[str, Any]) -> DdcTargetIdentity:
        if self._physical_monitor_identity_resolver is not None:
            identity = self._physical_monitor_identity_resolver(monitor)
            if not isinstance(identity, DdcTargetIdentity):
                raise TypeError("physical monitor identity resolver must return DdcTargetIdentity")
            return identity
        if "hmonitor" not in monitor:
            raise RuntimeError("enumerated physical monitor has no owning HMONITOR identity")
        display_id = self._resolve_monitor_name(monitor["hmonitor"])
        if display_id is None:
            raise RuntimeError("enumerated physical monitor has no authoritative display identity")
        return DdcTargetIdentity(display_id, self._resolve_ddc_device_path(display_id))

    def _open_ddc_target(self, target: DdcTargetIdentity, ownership: _DdcTargetOwnership) -> None:
        if not isinstance(target, DdcTargetIdentity):
            raise TypeError("DDC/CI target must be DdcTargetIdentity")
        module = self._ddc_module_value()

        def cleanup_orphan_controller(value: object) -> bool:
            self._close_ddc_controller(value)
            return True

        def retain_orphan_controller(value: object, cleanup_uncertain: bool) -> object:
            return _retain_native_resource(value, cleanup_orphan_controller, cleanup_uncertain)

        controller_call = _NativeCallState(
            module.DDCCIController,
            orphan_cleanup=cleanup_orphan_controller,
            orphan_retain=retain_orphan_controller,
        )
        try:
            controller = cast(Any, controller_call.invoke())
            ownership.controller = controller
            controller_call.handoff()
            monitors = list(controller.enumerate_monitors())
            matches = []
            for monitor in monitors:
                identity = self._resolve_physical_monitor_identity(monitor)
                if (
                    identity.display_id.casefold() == target.display_id.casefold()
                    and identity.monitor_device_path.casefold() == target.monitor_device_path.casefold()
                ):
                    matches.append(monitor)
            if len(matches) != 1:
                raise RuntimeError(
                    "DDC/CI captured display/path identity "
                    f"{target.display_id!r}/{target.monitor_device_path!r} matched {len(matches)} physical monitors"
                )
            ownership.module = module
            ownership.monitor = matches[0]
        except BaseException:
            if (
                ownership.controller is None
                and controller_call.completed
                and not controller_call.abandoned
                and controller_call.result is not None
            ):
                ownership.controller = controller_call.result
            if not controller_call.abandoned:
                controller_call.handoff()
            raise

    def resolve_ddc_target(self, display_id: str) -> DdcTargetIdentity:
        target = DdcTargetIdentity(display_id, self._resolve_ddc_device_path(display_id))
        ownership = _DdcTargetOwnership()
        try:
            self._open_ddc_target(target, ownership)
            controller = ownership.controller
            if controller is None:
                raise AssertionError("DDC/CI target acquisition returned no controller")
            self._close_ddc_controller(controller)
            ownership.controller = None
        except BaseException as exc:
            controller = ownership.controller
            if controller is not None:
                self._close_ddc_after_failure(controller, exc)
            raise
        return target

    @staticmethod
    def _vcp_code(module: Any, code: str) -> Any:
        if type(code) is not str or code not in DDC_WRITE_CODES:
            raise ValueError(f"DDC/CI code is outside the calibration allowlist: {code!r}")
        try:
            return module.VCPCode[code]
        except (KeyError, AttributeError) as exc:
            raise ValueError(f"unknown DDC/CI VCP code: {code}") from exc

    def read_ddc(self, target: DdcTargetIdentity, code: str) -> DdcReading:
        ownership = _DdcTargetOwnership()
        try:
            self._open_ddc_target(target, ownership)
            module = ownership.module
            controller = ownership.controller
            monitor = ownership.monitor
            if module is None or controller is None or monitor is None:
                raise AssertionError("DDC/CI target acquisition did not publish complete ownership evidence")
            current, maximum = controller.get_vcp(
                monitor,
                self._vcp_code(module, code),
                allow_wmi_fallback=False,
            )
            reading = DdcReading(int(current), int(maximum))
            self._close_ddc_controller(controller)
            ownership.controller = None
        except BaseException as exc:
            controller = ownership.controller
            if controller is not None:
                self._close_ddc_after_failure(controller, exc)
            raise
        return reading

    def write_ddc(
        self,
        target: DdcTargetIdentity,
        code: str,
        value: int,
        *,
        expected_maximum: int,
    ) -> None:
        if type(value) is not int or type(expected_maximum) is not int:
            raise TypeError("DDC/CI write value and expected maximum must be exact integers")
        ownership = _DdcTargetOwnership()
        try:
            self._open_ddc_target(target, ownership)
            module = ownership.module
            controller = ownership.controller
            monitor = ownership.monitor
            if module is None or controller is None or monitor is None:
                raise AssertionError("DDC/CI target acquisition did not publish complete ownership evidence")
            _current, maximum = controller.get_vcp(
                monitor,
                self._vcp_code(module, code),
                allow_wmi_fallback=False,
            )
            if int(maximum) != expected_maximum:
                raise RuntimeError(f"DDC/CI {code} maximum changed from {expected_maximum} to {int(maximum)}")
            if not 0 <= value <= expected_maximum:
                raise RuntimeError(f"DDC/CI {code} target {value} exceeds maximum {expected_maximum}")
            if not controller.set_vcp(
                monitor,
                self._vcp_code(module, code),
                value,
                allow_wmi_fallback=False,
            ):
                raise RuntimeError(f"DDC/CI write failed for {code}")
            self._close_ddc_controller(controller)
            ownership.controller = None
        except BaseException as exc:
            controller = ownership.controller
            if controller is not None:
                self._close_ddc_after_failure(controller, exc)
            raise

    def is_icc_profile_installed(self, profile_name: str) -> bool:
        installer = self._load_module("calibrate_pro.profiles.profile_installer")
        result = installer.is_profile_installed(profile_name)
        if type(result) is not bool:
            raise TypeError("ICC installation reader did not return an exact boolean")
        return result

    def is_icc_profile_associated(self, display_id: str, profile_name: str) -> bool:
        installer = self._load_module("calibrate_pro.profiles.profile_installer")
        result = installer.is_profile_associated_with_display(profile_name, display_id)
        if type(result) is not bool:
            raise TypeError("ICC association reader did not return an exact boolean")
        return result

    def capture_icc_profile(self, display_id: str) -> CapturedState[IccProfileSnapshot]:
        try:
            installer = self._load_module("calibrate_pro.profiles.profile_installer")
            profile_name = _require_icc_profile_basename(
                installer.get_default_profile_for_display(display_id),
                "Windows default color profile",
            )
            directory = Path(installer.get_profile_directory())
            path = directory / profile_name
        except Exception as exc:
            return CapturedState.not_captured(f"ICC persistent default read failed: {exc}")
        lease: IccFileLease | None = None
        lease_ownership = _IccLeaseOwnership()
        try:
            lease = self._open_icc_file_lease(str(path), lease_ownership)
            lease_ownership.acknowledge(lease)
            payload = lease.read_bytes()
            held_name = _require_icc_profile_basename(
                installer.get_default_profile_for_display(display_id),
                "Windows default color profile",
            )
            if held_name.casefold() != profile_name.casefold():
                raise RuntimeError("ICC persistent default changed while its exact-byte lease was held")
        except BaseException as exc:
            lease = lease_ownership.recover(lease)
            close_exc = _close_icc_lease_once(lease) if lease is not None else None
            lease_ownership.clear(lease)
            if close_exc is not None:
                close_detail = str(close_exc).strip() or type(close_exc).__name__
                if not isinstance(exc, Exception):
                    _add_exception_note(exc, f"ICC capture lease close also failed: {close_detail}")
                    raise exc from close_exc
                if not isinstance(close_exc, Exception):
                    _add_exception_note(close_exc, f"ICC capture also failed: {str(exc).strip() or type(exc).__name__}")
                    raise close_exc from exc
                return CapturedState.not_captured(
                    f"ICC profile capture failed ({str(exc).strip() or type(exc).__name__}); "
                    f"lease close also failed ({close_detail})"
                )
            if isinstance(exc, Exception):
                return CapturedState.not_captured(
                    f"ICC profile capture failed: {str(exc).strip() or type(exc).__name__}"
                )
            raise exc
        handoff_failure: BaseException | None = None
        try:
            assert lease is not None
        except BaseException as exc:
            handoff_failure = exc
        close_dispatch_failure: BaseException | None = None
        try:
            close_exc = _close_icc_lease_once(cast(IccFileLease, lease))
            lease_ownership.clear(lease)
        except BaseException as exc:
            close_dispatch_failure = exc
            close_exc = _close_icc_lease_once(cast(IccFileLease, lease))
            lease_ownership.clear(lease)
        if close_dispatch_failure is not None:
            if handoff_failure is None:
                handoff_failure = close_dispatch_failure
            else:
                _add_exception_note(
                    handoff_failure,
                    "ICC capture close dispatch also failed: "
                    f"{str(close_dispatch_failure).strip() or type(close_dispatch_failure).__name__}",
                )
        if handoff_failure is not None:
            if close_exc is not None:
                _add_exception_note(
                    handoff_failure,
                    f"ICC capture lease close also failed: {str(close_exc).strip() or type(close_exc).__name__}",
                )
            raise handoff_failure
        if close_exc is not None:
            if not isinstance(close_exc, Exception):
                raise close_exc
            return CapturedState.not_captured(f"ICC profile capture lease could not close: {close_exc}")
        try:
            final_name = _require_icc_profile_basename(
                installer.get_default_profile_for_display(display_id),
                "Windows default color profile",
            )
        except Exception as exc:
            return CapturedState.not_captured(f"ICC final persistent-default read failed: {exc}")
        if final_name.casefold() != profile_name.casefold():
            return CapturedState.not_captured("ICC persistent default changed before capture could return")
        snapshot = IccProfileSnapshot(str(path), payload, hashlib.sha256(payload).hexdigest())
        return CapturedState.captured(snapshot)

    def _read_private_cache_entry(self, destination: Path) -> bytes:
        lease: IccFileLease | None = None
        lease_ownership = _IccLeaseOwnership()
        try:
            lease = self._open_icc_file_lease(str(destination), lease_ownership)
            lease_ownership.acknowledge(lease)
            lease.validate_private_cache_identity(str(destination))
            payload = lease.read_bytes()
            lease.validate_private_cache_identity(str(destination))
        except BaseException as exc:
            lease = lease_ownership.recover(lease)
            close_exc = _close_icc_lease_once(lease) if lease is not None else None
            lease_ownership.clear(lease)
            if close_exc is not None:
                close_detail = str(close_exc).strip() or type(close_exc).__name__
                if not isinstance(exc, Exception):
                    _add_exception_note(exc, f"ICC cache lease close also failed: {close_detail}")
                    raise exc from close_exc
                if not isinstance(close_exc, Exception):
                    _add_exception_note(
                        close_exc,
                        f"ICC cache verification also failed: {str(exc).strip() or type(exc).__name__}",
                    )
                    raise close_exc from exc
                raise RuntimeError(
                    f"ICC cache verification failed ({exc}); lease close also failed ({close_detail})"
                ) from exc
            raise
        handoff_failure = None
        try:
            assert lease is not None
        except BaseException as exc:
            handoff_failure = exc
        close_dispatch_failure = None
        try:
            close_exc = _close_icc_lease_once(cast(IccFileLease, lease))
            lease_ownership.clear(lease)
        except BaseException as exc:
            close_dispatch_failure = exc
            close_exc = _close_icc_lease_once(cast(IccFileLease, lease))
            lease_ownership.clear(lease)
        if close_dispatch_failure is not None:
            if handoff_failure is None:
                handoff_failure = close_dispatch_failure
            else:
                _add_exception_note(
                    handoff_failure,
                    "ICC cache close dispatch also failed: "
                    f"{str(close_dispatch_failure).strip() or type(close_dispatch_failure).__name__}",
                )
        if handoff_failure is not None:
            if close_exc is not None:
                _add_exception_note(
                    handoff_failure,
                    f"ICC cache lease close also failed: {str(close_exc).strip() or type(close_exc).__name__}",
                )
            raise handoff_failure
        if close_exc is not None:
            raise close_exc
        return payload

    def materialize_icc_profile(self, profile: IccProfileSnapshot) -> IccInstallEffect:
        if not isinstance(profile, IccProfileSnapshot):
            raise TypeError("ICC materialization requires IccProfileSnapshot")
        IccProfileSnapshot(profile.original_path, profile.payload, profile.sha256)
        with tempfile.TemporaryDirectory(prefix="calibrate-pro-icc-validate-") as temporary_directory:
            staged = Path(temporary_directory) / "profile.icc"
            staged.write_bytes(profile.payload)
            _validate_icc_profile_file(str(staged))
        installer = self._load_module("calibrate_pro.profiles.profile_installer")
        directory = Path(installer.get_profile_directory())
        if not directory.is_dir():
            raise RuntimeError(f"ICC profile directory is unavailable: {directory}")
        name = f"calibrate-pro-{profile.sha256}.icc"
        destination = directory / name
        created = False
        try:
            stage_path: Path | None = None
            stage_stream: Any | None = None
            stage_failure: BaseException | None = None
            try:
                stage_stream = tempfile.NamedTemporaryFile(
                    mode="wb",
                    prefix=".calibrate-pro-icc-stage-",
                    suffix=".tmp",
                    dir=directory,
                    delete=False,
                )
                stage_path = Path(stage_stream.name)
                with stage_stream as stream:
                    stream.write(profile.payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(stage_path, destination)
                    created = True
                except FileExistsError:
                    pass
            except BaseException as exc:
                stage_failure = exc
            stage_cleanup_failures: list[BaseException] = []
            if stage_path is None and stage_stream is not None:
                try:
                    stage_path = Path(stage_stream.name)
                except BaseException as exc:
                    stage_cleanup_failures.append(exc)
            if stage_stream is not None:
                try:
                    close_stage = getattr(stage_stream, "close", None)
                    if callable(close_stage):
                        close_stage()
                except BaseException as exc:
                    stage_cleanup_failures.append(exc)
            if stage_path is not None:
                try:
                    stage_path.unlink(missing_ok=True)
                except BaseException as exc:
                    stage_cleanup_failures.append(exc)
            if stage_failure is not None:
                for stage_cleanup_error in stage_cleanup_failures:
                    detail = str(stage_cleanup_error).strip() or type(stage_cleanup_error).__name__
                    _add_exception_note(stage_failure, f"ICC staging cleanup also failed: {detail}")
                raise stage_failure
            if stage_cleanup_failures:
                _raise_cleanup_failures("additional ICC staging cleanup failure", stage_cleanup_failures)
            try:
                existing = self._read_private_cache_entry(destination)
            except BaseException as exc:
                if not created and isinstance(exc, Exception):
                    raise RuntimeError(
                        f"existing product-owned ICC profile content address has no private cache identity: {exc}"
                    ) from exc
                raise
            if hashlib.sha256(existing).hexdigest() != profile.sha256:
                raise RuntimeError("product-owned ICC profile bytes do not match their content address")
            if existing != profile.payload:
                raise RuntimeError("product-owned ICC profile bytes do not match their content address")
        except BaseException as exc:
            if not isinstance(exc, Exception):
                raise exc
            raise RuntimeError(f"ICC materialization failed: {exc}") from exc
        installed = IccProfileSnapshot(str(destination), profile.payload, profile.sha256)
        return IccInstallEffect(installed, created)

    def activate_icc_profile(
        self,
        display_id: str,
        profile: IccProfileSnapshot,
        *,
        register: bool,
        associate: bool,
    ) -> IccActivationEffect:
        if type(register) is not bool or type(associate) is not bool:
            raise TypeError("ICC register/associate flags must be exact booleans")
        if not isinstance(profile, IccProfileSnapshot):
            raise TypeError("ICC activation requires IccProfileSnapshot")
        IccProfileSnapshot(profile.original_path, profile.payload, profile.sha256)
        lease: IccFileLease | None = None
        lease_ownership = _IccLeaseOwnership()
        installer: Any | None = None
        profile_name: str | None = None
        registered = False
        associated = False
        default_selected = False
        registration_attempted = False
        association_attempted = False
        default_attempted = False

        def effect() -> IccActivationEffect:
            return IccActivationEffect(registered, associated, default_selected)

        def exact_bool(value: object, label: str) -> bool:
            if type(value) is not bool:
                raise TypeError(f"{label} did not return an exact boolean")
            return value

        def reconcile_effect() -> list[BaseException]:
            nonlocal registered, associated, default_selected
            failures: list[BaseException] = []
            if installer is None or profile_name is None:
                return failures
            if registration_attempted:
                try:
                    registered = exact_bool(
                        installer.is_profile_installed(profile_name),
                        "ICC installation reconciliation",
                    )
                except BaseException as reconciliation_error:
                    failures.append(reconciliation_error)
            if association_attempted:
                try:
                    associated = exact_bool(
                        installer.is_profile_associated_with_display(profile_name, display_id),
                        "ICC association reconciliation",
                    )
                except BaseException as reconciliation_error:
                    failures.append(reconciliation_error)
            if association_attempted or default_attempted:
                try:
                    selected = _require_icc_profile_basename(
                        installer.get_default_profile_for_display(display_id),
                        "Windows default color profile",
                    )
                    default_selected = selected.casefold() == profile_name.casefold()
                except BaseException as reconciliation_error:
                    failures.append(reconciliation_error)
            return failures

        profile_name_evidence = Path(profile.original_path).name
        product_cache_target = profile_name_evidence.casefold() == f"calibrate-pro-{profile.sha256}.icc"

        def validate_cache_identity() -> None:
            if product_cache_target:
                assert lease is not None
                lease.validate_private_cache_identity(profile.original_path)

        try:
            lease = self._open_icc_file_lease(profile.original_path, lease_ownership)
            lease_ownership.acknowledge(lease)
            installer = self._load_module("calibrate_pro.profiles.profile_installer")
            profile_name = _require_icc_profile_basename(
                Path(profile.original_path).name,
                "ICC activation target",
            )
            validate_cache_identity()
            initial = lease.read_bytes()
            validate_cache_identity()
            if initial != profile.payload or hashlib.sha256(initial).hexdigest() != profile.sha256:
                raise RuntimeError("ICC activation lease bytes differ from captured evidence")
            validate_cache_identity()
            if register:
                registration_attempted = True
                success, message = installer.register_profile(profile.original_path)
                if type(success) is not bool:
                    raise TypeError("ICC profile registration did not return an exact boolean")
                if success is not True:
                    raise RuntimeError(message or "ICC profile registration failed")
                if not exact_bool(
                    installer.is_profile_installed(profile_name),
                    "ICC profile registration readback",
                ):
                    raise RuntimeError("ICC profile registration readback did not prove installation")
                registered = True
            if associate:
                association_attempted = True
                success, message = installer.associate_profile_with_display(
                    profile_name,
                    display_id,
                    make_default=False,
                )
                if type(success) is not bool:
                    raise TypeError("ICC profile association did not return an exact boolean")
                if success is not True:
                    raise RuntimeError(message or "ICC profile association failed")
                if not exact_bool(
                    installer.is_profile_associated_with_display(profile_name, display_id),
                    "ICC profile association readback",
                ):
                    raise RuntimeError("ICC profile association readback did not prove membership")
                associated = True
            default_attempted = True
            success, message = installer.set_default_profile_for_display(profile_name, display_id)
            if type(success) is not bool:
                raise TypeError("ICC persistent default selection did not return an exact boolean")
            if success is not True:
                raise RuntimeError(message or "failed to make ICC profile the persistent display default")
            selected = _require_icc_profile_basename(
                installer.get_default_profile_for_display(display_id),
                "Windows default color profile",
            )
            if selected.casefold() != profile_name.casefold():
                raise RuntimeError("ICC persistent-default readback did not select the confirmed profile")
            default_selected = True
            validate_cache_identity()
            validate_cache_identity()
            final = lease.read_bytes()
            validate_cache_identity()
            if final != profile.payload or hashlib.sha256(final).hexdigest() != profile.sha256:
                raise RuntimeError("ICC activation lease bytes changed during activation")
            stable_name = _require_icc_profile_basename(
                installer.get_default_profile_for_display(display_id),
                "Windows default color profile",
            )
            if stable_name.casefold() != profile_name.casefold():
                raise RuntimeError("ICC persistent default was not stable across activation readback")
            if register and not exact_bool(
                installer.is_profile_installed(profile_name),
                "ICC profile final installation readback",
            ):
                raise RuntimeError("ICC profile installation was not stable across activation readback")
            if associate and not exact_bool(
                installer.is_profile_associated_with_display(profile_name, display_id),
                "ICC profile final association readback",
            ):
                raise RuntimeError("ICC profile association was not stable across activation readback")
        except BaseException as exc:
            reconciliation_failures: list[BaseException] = []
            lease = lease_ownership.recover(lease)
            close_exc = _close_icc_lease_once(lease) if lease is not None else None
            lease_ownership.clear(lease)
            if close_exc is not None:
                reconciliation_failures.append(close_exc)
            reconciliation_failures.extend(reconcile_effect())
            resolved_effect = effect()
            failure_details = [str(item).strip() or type(item).__name__ for item in reconciliation_failures]
            if not isinstance(exc, Exception):
                for detail in failure_details:
                    _add_exception_note(exc, f"ICC activation cleanup/reconciliation also failed: {detail}")
                _attach_icc_activation_effect(exc, resolved_effect)
                raise exc
            cancellation = next((item for item in reconciliation_failures if not isinstance(item, Exception)), None)
            if cancellation is not None:
                _add_exception_note(
                    cancellation, f"ICC activation also failed: {str(exc).strip() or type(exc).__name__}"
                )
                for detail in failure_details:
                    if detail != (str(cancellation).strip() or type(cancellation).__name__):
                        _add_exception_note(cancellation, f"additional ICC activation cleanup failure: {detail}")
                _attach_icc_activation_effect(cancellation, resolved_effect)
                raise cancellation from exc
            message = str(exc).strip() or type(exc).__name__
            if failure_details:
                message += "; ICC activation reconciliation/cleanup failed: " + "; ".join(failure_details)
            raise IccActivationError(message, resolved_effect) from exc
        handoff_failure = None
        try:
            assert lease is not None
        except BaseException as exc:
            handoff_failure = exc
        close_dispatch_failure = None
        try:
            close_exc = _close_icc_lease_once(cast(IccFileLease, lease))
            lease_ownership.clear(lease)
        except BaseException as exc:
            close_dispatch_failure = exc
            close_exc = _close_icc_lease_once(cast(IccFileLease, lease))
            lease_ownership.clear(lease)
        if close_dispatch_failure is not None:
            if handoff_failure is None:
                handoff_failure = close_dispatch_failure
            else:
                _add_exception_note(
                    handoff_failure,
                    "ICC activation close dispatch also failed: "
                    f"{str(close_dispatch_failure).strip() or type(close_dispatch_failure).__name__}",
                )
        if handoff_failure is not None:
            if close_exc is not None:
                _add_exception_note(
                    handoff_failure,
                    f"ICC activation lease close also failed: {str(close_exc).strip() or type(close_exc).__name__}",
                )
            _attach_icc_activation_effect(handoff_failure, effect())
            raise handoff_failure
        if close_exc is not None:
            if isinstance(close_exc, Exception):
                raise IccActivationError(
                    f"ICC activation lease close failed: {str(close_exc).strip() or type(close_exc).__name__}",
                    effect(),
                ) from close_exc
            _attach_icc_activation_effect(close_exc, effect())
            raise close_exc
        return effect()

    def deactivate_icc_profile(self, display_id: str, profile_name: str) -> None:
        if Path(profile_name).name != profile_name or not profile_name.startswith("calibrate-pro-"):
            raise ValueError("only an exact product-owned ICC profile name may be deactivated")
        installer = self._load_module("calibrate_pro.profiles.profile_installer")
        success, message = installer.disassociate_profile_from_display(profile_name, display_id)
        if not success:
            raise RuntimeError(message or "ICC profile disassociation failed")

    def capture_gamma_ramp(self, display_id: str) -> CapturedState[GammaRamp]:
        detection = self._load_module("calibrate_pro.panels.detection")
        try:
            ramp = detection.get_gamma_ramp(display_id)
        except Exception as exc:
            return CapturedState.not_captured(f"gamma ramp read failed: {exc}")
        if ramp is None:
            return CapturedState.not_captured(
                "ambiguous gamma ramp result: the legacy reader cannot prove identity versus read failure"
            )
        try:
            normalized = _normalize_gamma_ramp(ramp)
        except ValueError as exc:
            return CapturedState.not_captured(f"gamma ramp capture was invalid: {exc}")
        return CapturedState.captured(normalized)

    def set_gamma_ramp(self, display_id: str, ramp: GammaRamp | None) -> None:
        detection = self._load_module("calibrate_pro.panels.detection")
        if ramp is None:
            if not detection.reset_gamma_ramp(display_id):
                raise RuntimeError("failed to reset the display gamma ramp")
            return
        red, green, blue = _normalize_gamma_ramp(ramp)
        numpy = importlib.import_module("numpy")
        if not detection.set_gamma_ramp(
            display_id,
            numpy.asarray(red, dtype=numpy.uint16),
            numpy.asarray(green, dtype=numpy.uint16),
            numpy.asarray(blue, dtype=numpy.uint16),
        ):
            raise RuntimeError("failed to set the display gamma ramp")

    def capture_dwm_luts(self, display_id: str) -> CapturedState[tuple[DwmLutSnapshot, ...]]:
        del display_id
        return CapturedState.not_captured(
            "authoritative DWM LUT capture is unavailable; process-local active-LUT memory is insufficient"
        )

    def _dwm_context(self) -> tuple[Any, Any]:
        if self._dwm_controller is None:
            self._dwm_module = self._load_module("calibrate_pro.lut_system.dwm_lut")
            self._dwm_controller = self._dwm_module.DwmLutController()
        assert self._dwm_module is not None
        return self._dwm_module, self._dwm_controller

    def _dwm_monitor(self, display_id: str) -> tuple[Any, Any, object]:
        module, controller = self._dwm_context()
        matches = [
            monitor
            for monitor in controller.get_monitors()
            if display_id.casefold() in {str(monitor.device_name).casefold(), str(monitor.device_id).casefold()}
        ]
        if len(matches) != 1:
            raise RuntimeError(f"DWM LUT display identity {display_id!r} matched {len(matches)} monitors")
        return module, controller, matches[0]

    def set_dwm_luts(self, display_id: str, luts: tuple[DwmLutSnapshot, ...]) -> None:
        if not isinstance(luts, tuple) or any(not isinstance(item, DwmLutSnapshot) for item in luts):
            raise TypeError("DWM LUT state must be a tuple of DwmLutSnapshot values")
        kinds = tuple(item.kind for item in luts)
        if len(set(kinds)) != len(kinds):
            raise ValueError("DWM LUT state may contain at most one LUT per kind")

        with tempfile.TemporaryDirectory(prefix="calibrate-pro-dwm-") as temporary_directory:
            root = Path(temporary_directory)
            staged_luts: list[tuple[DwmLutSnapshot, Path]] = []
            for lut in luts:
                kind_directory = root / lut.kind.value
                kind_directory.mkdir()
                staged = kind_directory / Path(lut.original_path).name
                staged.write_bytes(lut.payload)
                _validate_dwm_lut_file(str(staged))
                staged_luts.append((lut, staged))

            module, controller, monitor = self._dwm_monitor(display_id)
            for lut_type in (module.LUTType.SDR, module.LUTType.HDR):
                if not controller.unload_lut(monitor, lut_type):
                    raise RuntimeError(f"failed to unload {lut_type.value.upper()} DWM LUT")
            for lut, staged in staged_luts:
                lut_type = module.LUTType.HDR if lut.kind is DwmLutKind.HDR else module.LUTType.SDR
                if not controller.load_lut_file(monitor, str(staged), lut_type):
                    raise RuntimeError(f"failed to load {lut.kind.value.upper()} DWM LUT")
            if luts and not controller.start_dwm_lut_gui():
                raise RuntimeError("failed to start DWM LUT")


class DisplayTransactionMutex(Protocol):
    """Exclusive display transaction ownership across adapter instances."""

    def acquire(self, display_id: str) -> object: ...

    def release(self, handle: object) -> None: ...


class InProcessDisplayTransactionMutex:
    """Non-reentrant per-display mutex shared by every adapter in this process."""

    _guard = threading.Lock()
    _locks: dict[str, threading.Lock] = {}

    def acquire(self, display_id: str) -> object:
        key = display_id.casefold()
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
            if lock.locked():
                raise RuntimeError(f"display transaction mutex is already held for {display_id!r}")
            acquired = False
            acquisition_started = False
            try:
                acquisition_started = True
                acquired = lock.acquire(blocking=False)
                if not acquired:
                    raise RuntimeError(f"display transaction mutex is already held for {display_id!r}")
                return _publish_mutex_lease(lock)
            except BaseException as exc:
                if acquired or (acquisition_started and lock.locked()):
                    try:
                        lock.release()
                    except BaseException as cleanup_exc:
                        detail = str(cleanup_exc).strip() or type(cleanup_exc).__name__
                        _add_exception_note(exc, f"in-process mutex acquisition cleanup also failed: {detail}")
                raise

    def release(self, handle: object) -> None:
        if not isinstance(handle, type(threading.Lock())):
            raise TypeError("invalid in-process display mutex handle")
        handle.release()


class _WindowsMutexOwnerAction(Enum):
    RELEASE = "release"
    CLOSE = "close"
    SHUTDOWN = "shutdown"


class _WindowsMutexOwnerCommandTimeout(RuntimeError):
    """Caller wait expired while the exact owner retained command execution."""


@dataclass
class _WindowsMutexOwnerRequest:
    action: _WindowsMutexOwnerAction
    done: threading.Event
    error: BaseException | None = None


class _WindowsMutexOwner:
    """One durable thread that owns a Win32 mutex for its complete lifetime."""

    def __init__(
        self,
        kernel32: Any,
        name: str,
        display_key: str,
        on_terminal: Callable[[_WindowsMutexOwner], None],
    ) -> None:
        self.kernel32 = kernel32
        self.name = name
        self.display_key = display_key
        self._on_terminal = on_terminal
        self._condition = threading.Condition(threading.RLock())
        self._commands: list[_WindowsMutexOwnerRequest] = []
        self._acquisition_done = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self.proxy: _WindowsNamedMutexLease | None = None
        self.native_handle: object | None = None
        self.acquired = False
        self.mutex_released = False
        self.release_uncertain = False
        self.close_uncertain = False
        self.poisoned = False
        self.terminal = False
        self.abandoned = False
        self.acquisition_error: BaseException | None = None
        self.last_error: BaseException | None = None
        self._terminal_callback_attempted = False
        self._abandonment_request: _WindowsMutexOwnerRequest | None = None
        self._settlement_observers: list[Callable[[_WindowsMutexOwner], None]] = []

    @property
    def thread(self) -> threading.Thread:
        return self._thread

    def start(self) -> None:
        self._thread.start()

    def _publish_proxy_locked(self) -> None:
        proxy = self.proxy
        if proxy is None:
            return
        proxy.native_handle = self.native_handle
        proxy.mutex_released = self.mutex_released
        proxy.close_uncertain = self.close_uncertain
        proxy.poisoned = self.poisoned

    def attach(self, proxy: _WindowsNamedMutexLease) -> None:
        with self._condition:
            if self.proxy is not None and self.proxy is not proxy:
                raise RuntimeError("Windows mutex owner already has a different proxy")
            self.proxy = proxy
            self._publish_proxy_locked()

    def await_acquisition(self) -> None:
        if not self._acquisition_done.wait(_WINDOWS_MUTEX_OWNER_WAIT_SECONDS):
            self.abandon()
            raise RuntimeError("Windows mutex owner acquisition did not settle within its bounded wait")
        with self._condition:
            error = self.acquisition_error
            acquired = self.acquired
        if error is not None:
            raise error
        if not acquired:
            raise RuntimeError("Windows mutex owner ended acquisition without ownership evidence")

    def abandon(self, *, wait: bool = False) -> None:
        request: _WindowsMutexOwnerRequest | None = None
        with self._condition:
            self.abandoned = True
            if self.acquired and not self.terminal:
                request = self._abandonment_request
                if request is None:
                    request = _WindowsMutexOwnerRequest(_WindowsMutexOwnerAction.SHUTDOWN, threading.Event())
                    self._abandonment_request = request
                    self._commands.append(request)
            self._condition.notify_all()
        if wait and request is not None:
            if not request.done.wait(_WINDOWS_MUTEX_OWNER_WAIT_SECONDS):
                raise RuntimeError("Windows mutex owner abandonment did not settle within its bounded wait")
            if request.error is not None:
                raise request.error

    def observe_settlement(self, observer: Callable[[_WindowsMutexOwner], None]) -> None:
        """Run one observer when this exact generation is terminal or permanently uncertain."""
        invoke_now = False
        with self._condition:
            if (self.terminal and self.native_handle is None) or self.poisoned:
                invoke_now = True
            else:
                self._settlement_observers.append(observer)
        if invoke_now:
            observer(self)

    def command(self, action: _WindowsMutexOwnerAction) -> None:
        with self._condition:
            if self.terminal:
                return
            if action is _WindowsMutexOwnerAction.CLOSE and not self.mutex_released:
                raise RuntimeError("Windows mutex owner cannot close before release is confirmed")
            if self.release_uncertain and action in {
                _WindowsMutexOwnerAction.RELEASE,
                _WindowsMutexOwnerAction.SHUTDOWN,
            }:
                raise self.last_error or RuntimeError("Windows mutex release outcome is uncertain")
            if self.close_uncertain and action in {
                _WindowsMutexOwnerAction.CLOSE,
                _WindowsMutexOwnerAction.SHUTDOWN,
            }:
                raise self.last_error or RuntimeError("Windows mutex close outcome is uncertain")
            request = _WindowsMutexOwnerRequest(action, threading.Event())
            self._commands.append(request)
            self._condition.notify_all()
        if not request.done.wait(_WINDOWS_MUTEX_OWNER_WAIT_SECONDS):
            raise _WindowsMutexOwnerCommandTimeout("Windows mutex owner command did not settle within its bounded wait")
        if request.error is not None:
            raise request.error

    def _release_native(self) -> BaseException | None:
        handle = self.native_handle
        if handle is None or self.mutex_released:
            return None
        try:
            released = bool(self.kernel32.ReleaseMutex(handle))
        except BaseException as exc:
            self.release_uncertain = True
            self.poisoned = True
            self.last_error = exc
            return exc
        if not released:
            error = RuntimeError("failed to release the Windows display transaction mutex")
            self.poisoned = True
            self.last_error = error
            return error
        self.mutex_released = True
        self.last_error = None
        return None

    def _close_native(self) -> BaseException | None:
        handle = self.native_handle
        if handle is None:
            self.terminal = True
            return None
        try:
            closed = bool(self.kernel32.CloseHandle(handle))
        except BaseException as exc:
            self.close_uncertain = True
            self.poisoned = True
            self.last_error = exc
            return exc
        if not closed:
            error = RuntimeError("failed to close the Windows display transaction mutex handle")
            self.poisoned = True
            self.last_error = error
            return error
        self.native_handle = None
        self.terminal = True
        self.last_error = None
        return None

    def _release_then_close(self) -> BaseException | None:
        release_error = self._release_native()
        if release_error is not None:
            return release_error
        return self._close_native()

    def _publish_registry_state(self) -> BaseException | None:
        observers: list[Callable[[_WindowsMutexOwner], None]] = []
        with self._condition:
            terminal = self.terminal
            if not terminal and not self.poisoned:
                return None
            if terminal:
                if self._terminal_callback_attempted:
                    return None
                self._terminal_callback_attempted = True
            observers = self._settlement_observers
            self._settlement_observers = []
        publication_error: BaseException | None = None
        try:
            self._on_terminal(self)
        except BaseException as exc:
            publication_error = exc
        for observer in observers:
            try:
                observer(self)
            except BaseException as exc:
                if publication_error is None:
                    publication_error = exc
                else:
                    detail = str(exc).strip() or type(exc).__name__
                    _add_exception_note(publication_error, f"Windows mutex terminal observer also failed: {detail}")
        return publication_error

    def _process_request(self, request: _WindowsMutexOwnerRequest) -> None:
        if self.poisoned:
            request.error = self.last_error or RuntimeError("Windows mutex owner is poisoned")
        elif request.action in {_WindowsMutexOwnerAction.RELEASE, _WindowsMutexOwnerAction.SHUTDOWN}:
            request.error = self._release_then_close()
        else:
            request.error = self._close_native()
        with self._condition:
            self._publish_proxy_locked()
        callback_error = self._publish_registry_state()
        if callback_error is not None:
            if request.error is None:
                request.error = callback_error
            else:
                detail = str(callback_error).strip() or type(callback_error).__name__
                _add_exception_note(request.error, f"Windows mutex registry publication also failed: {detail}")
        request.done.set()

    def _command_loop(self) -> None:
        while True:
            with self._condition:
                while not self._commands and not self.terminal:
                    self._condition.wait()
                if self.terminal:
                    pending_requests = self._commands
                    self._commands = []
                    for pending_request in pending_requests:
                        pending_request.done.set()
                    return
                request = self._commands.pop(0)
            self._process_request(request)

    def _cleanup_failed_acquisition(self, error: BaseException, *, may_own: bool) -> None:
        self.acquisition_error = error
        if may_own:
            self.poisoned = True
            cleanup_error = self._release_then_close()
        else:
            self.mutex_released = True
            cleanup_error = self._close_native()
        if cleanup_error is not None and cleanup_error is not error:
            detail = str(cleanup_error).strip() or type(cleanup_error).__name__
            _add_exception_note(error, f"Windows mutex owner acquisition cleanup also failed: {detail}")
            if not isinstance(cleanup_error, Exception):
                primary_detail = str(error).strip() or type(error).__name__
                _add_exception_note(cleanup_error, f"Windows mutex acquisition also failed: {primary_detail}")
                self.acquisition_error = cleanup_error
        with self._condition:
            self._publish_proxy_locked()
        callback_error = self._publish_registry_state()
        if callback_error is not None:
            detail = str(callback_error).strip() or type(callback_error).__name__
            current_error = self.acquisition_error or error
            _add_exception_note(current_error, f"Windows mutex registry publication also failed: {detail}")
            if not isinstance(callback_error, Exception):
                self.acquisition_error = callback_error
        self._acquisition_done.set()
        if not self.terminal:
            self._command_loop()

    def _run(self) -> None:
        handle: object | None = None
        try:
            try:
                handle = self.kernel32.CreateMutexW(None, False, self.name)
                if not handle:
                    raise RuntimeError("failed to create the Windows display transaction mutex")
                self.native_handle = handle
                wait_result = int(self.kernel32.WaitForSingleObject(handle, 0))
            except BaseException as exc:
                if handle is None:
                    self.acquisition_error = exc
                    self.terminal = True
                else:
                    self._cleanup_failed_acquisition(exc, may_own=True)
                return

            if wait_result == WindowsNamedDisplayTransactionMutex._WAIT_OBJECT_0:
                with self._condition:
                    self.acquired = True
                    abandoned = self.abandoned
                    self._publish_proxy_locked()
                if abandoned:
                    error = RuntimeError("Windows mutex acquisition completed after caller timeout")
                    self._cleanup_failed_acquisition(error, may_own=True)
                    return
                self._acquisition_done.set()
                self._command_loop()
                return
            if wait_result == WindowsNamedDisplayTransactionMutex._WAIT_ABANDONED:
                error = RuntimeError("abandoned display transaction mutex requires manual recovery")
                self._cleanup_failed_acquisition(error, may_own=True)
                return
            error = RuntimeError(f"display transaction mutex is already held for {self.display_key!r}")
            self._cleanup_failed_acquisition(error, may_own=False)
        finally:
            callback_error = self._publish_registry_state() if self.terminal else None
            if callback_error is not None:
                if self.acquisition_error is None:
                    self.acquisition_error = callback_error
                else:
                    detail = str(callback_error).strip() or type(callback_error).__name__
                    _add_exception_note(
                        self.acquisition_error,
                        f"Windows mutex terminal registry publication also failed: {detail}",
                    )
            self._acquisition_done.set()


@dataclass
class _WindowsNamedMutexLease:
    kernel32: Any
    native_handle: object | None
    display_key: str
    poisoned: bool = False
    mutex_released: bool = False
    close_uncertain: bool = False
    owner: _WindowsMutexOwner | None = None


class WindowsNamedDisplayTransactionMutex:
    """Lazy cross-process named mutex; construction performs no Windows call."""

    _WAIT_OBJECT_0 = 0x00000000
    _WAIT_ABANDONED = 0x00000080
    _poison_guard = threading.Lock()
    _poisoned_display_keys: set[str] = set()
    _poisoned_native_leases: dict[str, _WindowsNamedMutexLease] = {}
    _poisoned_native_claims: dict[str, int] = {}
    _pending_native_attempts: set[str] = set()
    _pending_native_reservations: dict[str, object] = {}
    _pending_native_owners: dict[str, _WindowsMutexOwner] = {}
    _active_native_leases: dict[str, _WindowsNamedMutexLease] = {}
    _active_native_claims: dict[str, int] = {}
    _transient_native_quarantines: dict[str, _WindowsMutexOwner] = {}

    def __init__(self, kernel32_loader: Callable[[], Any] | None = None) -> None:
        self._kernel32_loader = kernel32_loader or (lambda: ctypes.WinDLL("kernel32", use_last_error=True))

    @classmethod
    def _poison_lease(cls, lease: _WindowsNamedMutexLease) -> None:
        lease.poisoned = True
        with cls._poison_guard:
            owner = lease.owner
            if owner is not None and cls._transient_native_quarantines.get(lease.display_key) is owner:
                cls._transient_native_quarantines.pop(lease.display_key, None)
            if owner is None or cls._pending_native_owners.get(lease.display_key) is owner:
                cls._pending_native_attempts.discard(lease.display_key)
                cls._pending_native_reservations.pop(lease.display_key, None)
                cls._pending_native_owners.pop(lease.display_key, None)
            if cls._active_native_leases.get(lease.display_key) is lease:
                cls._active_native_leases.pop(lease.display_key, None)
            cls._poisoned_display_keys.add(lease.display_key)
            if lease.native_handle is not None:
                cls._poisoned_native_leases[lease.display_key] = lease

    @classmethod
    def _quarantine_command_timeout(cls, lease: _WindowsNamedMutexLease) -> None:
        """Retain one exact live owner without making a transient wait miss permanent."""
        owner = lease.owner
        if owner is None:
            raise RuntimeError("Windows mutex timeout quarantine requires an exact native owner")
        with cls._poison_guard:
            if cls._active_native_leases.get(lease.display_key) is not lease:
                return
            cls._transient_native_quarantines[lease.display_key] = owner

    @classmethod
    def _reserve_native_attempt(cls, display_key: str, reservation: object | None = None) -> None:
        reservation_identity = reservation if reservation is not None else object()
        with cls._poison_guard:
            if display_key in cls._poisoned_display_keys:
                raise RuntimeError("display transaction mutex is poisoned and requires manual recovery")
            occupied = (
                set(cls._pending_native_attempts)
                | set(cls._active_native_leases)
                | set(cls._poisoned_native_leases)
                | set(cls._transient_native_quarantines)
            )
            if len(occupied) >= _MAX_POISONED_NATIVE_LEASES:
                raise RuntimeError(
                    "Windows mutex capacity is exhausted by active, pending, or retained native-handle evidence"
                )
            if display_key in occupied:
                raise RuntimeError("display transaction mutex already has an active or pending native attempt")
            publication_complete = False
            try:
                cls._pending_native_attempts.add(display_key)
                cls._pending_native_reservations[display_key] = reservation_identity
                publication_complete = True
            finally:
                if not publication_complete:
                    cls._pending_native_attempts.discard(display_key)
                    if cls._pending_native_reservations.get(display_key) is reservation_identity:
                        cls._pending_native_reservations.pop(display_key, None)
        try:
            return
        except BaseException:
            with cls._poison_guard:
                if cls._pending_native_reservations.get(display_key) is reservation_identity:
                    cls._pending_native_attempts.discard(display_key)
                    cls._pending_native_reservations.pop(display_key, None)
            raise

    @classmethod
    def _publish_pending_owner(
        cls,
        display_key: str,
        reservation: object,
        owner: _WindowsMutexOwner,
    ) -> None:
        with cls._poison_guard:
            if (
                display_key not in cls._pending_native_attempts
                or cls._pending_native_reservations.get(display_key) is not reservation
            ):
                raise RuntimeError("Windows mutex native-attempt reservation is not pending")
            cls._pending_native_owners[display_key] = owner

    @classmethod
    def _activate_native_attempt(
        cls,
        lease: _WindowsNamedMutexLease,
        reservation: object | None = None,
    ) -> None:
        owner = lease.owner
        with cls._poison_guard:
            if lease.display_key not in cls._pending_native_attempts:
                raise RuntimeError("Windows mutex native-attempt reservation is not pending")
            if reservation is not None and cls._pending_native_reservations.get(lease.display_key) is not reservation:
                raise RuntimeError("Windows mutex native-attempt reservation identity changed")
            if owner is not None and cls._pending_native_owners.get(lease.display_key) is not owner:
                raise RuntimeError("Windows mutex native-attempt owner identity changed")
            activated = False
            try:
                cls._active_native_leases[lease.display_key] = lease
                cls._pending_native_attempts.remove(lease.display_key)
                cls._pending_native_reservations.pop(lease.display_key, None)
                cls._pending_native_owners.pop(lease.display_key, None)
                activated = True
            finally:
                if not activated and cls._active_native_leases.get(lease.display_key) is lease:
                    cls._active_native_leases.pop(lease.display_key, None)

    @classmethod
    def _retire_native_reservation(cls, display_key: str, reservation: object) -> None:
        with cls._poison_guard:
            if cls._pending_native_reservations.get(display_key) is reservation:
                cls._pending_native_attempts.discard(display_key)
                cls._pending_native_reservations.pop(display_key, None)
                cls._pending_native_owners.pop(display_key, None)

    @classmethod
    def _owner_registry_state(cls, owner: _WindowsMutexOwner) -> None:
        """Publish owner truth and retire terminal identities under one registry lock."""
        with cls._poison_guard:
            display_key = owner.display_key
            lease = owner.proxy
            if lease is not None:
                lease.native_handle = owner.native_handle
                lease.mutex_released = owner.mutex_released
                lease.close_uncertain = owner.close_uncertain
                lease.poisoned = owner.poisoned
            if owner.poisoned:
                cls._poisoned_display_keys.add(display_key)
                if cls._transient_native_quarantines.get(display_key) is owner:
                    cls._transient_native_quarantines.pop(display_key, None)
            if owner.poisoned and lease is not None and owner.native_handle is not None:
                if cls._pending_native_owners.get(display_key) is owner:
                    cls._pending_native_attempts.discard(display_key)
                    cls._pending_native_reservations.pop(display_key, None)
                    cls._pending_native_owners.pop(display_key, None)
                if cls._active_native_leases.get(display_key) is lease:
                    cls._active_native_leases.pop(display_key, None)
                cls._poisoned_native_leases[display_key] = lease
            if not owner.terminal or owner.native_handle is not None:
                return
            if cls._pending_native_owners.get(display_key) is owner:
                cls._pending_native_attempts.discard(display_key)
                cls._pending_native_reservations.pop(display_key, None)
                cls._pending_native_owners.pop(display_key, None)
            if cls._transient_native_quarantines.get(display_key) is owner:
                cls._transient_native_quarantines.pop(display_key, None)
            if lease is not None and cls._active_native_leases.get(display_key) is lease:
                cls._active_native_leases.pop(display_key, None)
            if (
                lease is not None
                and display_key not in cls._poisoned_native_claims
                and cls._poisoned_native_leases.get(display_key) is lease
            ):
                cls._poisoned_native_leases.pop(display_key, None)

    def acquire(self, display_id: str) -> object:
        display_key = display_id.casefold()
        _drain_poisoned_native_leases()
        reservation = object()
        owner: _WindowsMutexOwner | None = None
        lease: _WindowsNamedMutexLease | None = None
        owner_started = False
        try:
            type(self)._reserve_native_attempt(display_key, reservation)
            kernel32 = self._kernel32_loader()
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel32.WaitForSingleObject.restype = ctypes.c_ulong
            kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
            kernel32.ReleaseMutex.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = wintypes.BOOL
            name_digest = hashlib.sha256(display_key.encode("utf-8")).hexdigest()
            name = f"Global\\CalibratePro.DisplayTransaction.{name_digest}"
            owner = _WindowsMutexOwner(kernel32, name, display_key, type(self)._owner_registry_state)
            lease = _WindowsNamedMutexLease(kernel32, None, display_key, owner=owner)
            owner.attach(lease)
            type(self)._publish_pending_owner(display_key, reservation, owner)
            owner.start()
            owner_started = True
            owner.await_acquisition()
            type(self)._activate_native_attempt(lease, reservation)
            return _publish_mutex_lease(lease)
        except BaseException as exc:
            if owner is not None and (owner_started or owner.thread.ident is not None):
                try:
                    owner.abandon(wait=True)
                except BaseException as cleanup_exc:
                    detail = str(cleanup_exc).strip() or type(cleanup_exc).__name__
                    _add_exception_note(exc, f"Windows mutex acquisition abandonment also failed: {detail}")
                type(self)._owner_registry_state(owner)
            else:
                type(self)._retire_native_reservation(display_key, reservation)
            raise

    def release(self, handle: object) -> None:
        if not isinstance(handle, _WindowsNamedMutexLease):
            raise TypeError("invalid Windows display mutex handle")
        owner = handle.owner
        if owner is None:
            raise TypeError("Windows display mutex lease has no native owner")
        if handle.poisoned or handle.native_handle is None:
            raise RuntimeError("Windows display mutex lease is poisoned or already released")
        try:
            owner.command(_WindowsMutexOwnerAction.RELEASE)
        except _WindowsMutexOwnerCommandTimeout:
            type(self)._owner_registry_state(owner)
            if handle.native_handle is not None:
                type(self)._quarantine_command_timeout(handle)
            raise
        except BaseException:
            type(self)._owner_registry_state(owner)
            if handle.native_handle is not None:
                type(self)._poison_lease(handle)
            raise
        type(self)._owner_registry_state(owner)
        if handle.native_handle is not None:
            type(self)._poison_lease(handle)
            raise RuntimeError("Windows display mutex owner returned without terminal close evidence")


def _drain_pending_native_owners(*, limit: int = _REGISTRY_DRAIN_LIMIT) -> int:
    """Ask bounded pending owners to retire after their native acquisition settles."""
    if type(limit) is not int or limit < 0:
        raise ValueError("pending native owner drain limit must be a non-negative integer")
    mutex_type = WindowsNamedDisplayTransactionMutex
    with mutex_type._poison_guard:
        ghost_keys = list(
            (mutex_type._pending_native_attempts - set(mutex_type._pending_native_reservations))
            | (set(mutex_type._pending_native_reservations) - mutex_type._pending_native_attempts)
        )[:limit]
        for display_key in ghost_keys:
            mutex_type._pending_native_attempts.discard(display_key)
            mutex_type._pending_native_reservations.pop(display_key, None)
            mutex_type._pending_native_owners.pop(display_key, None)
        owners = list(mutex_type._pending_native_owners.values())[: max(0, limit - len(ghost_keys))]
    for owner in owners:
        owner.abandon()
    return len(ghost_keys) + len(owners)


def _drain_active_native_owners(*, limit: int = _REGISTRY_DRAIN_LIMIT) -> int:
    """Release bounded active leases on the same threads that acquired them."""
    if type(limit) is not int or limit < 0:
        raise ValueError("active native owner drain limit must be a non-negative integer")
    mutex_type = WindowsNamedDisplayTransactionMutex
    candidates: list[tuple[str, _WindowsNamedMutexLease, _WindowsMutexOwner, int]] = []
    installed_claims: list[tuple[str, _WindowsNamedMutexLease, int]] = []
    handoff_complete = False
    try:
        with mutex_type._poison_guard:
            for display_key, lease in list(mutex_type._active_native_leases.items()):
                if len(candidates) >= limit:
                    break
                if lease.native_handle is None:
                    mutex_type._active_native_leases.pop(display_key, None)
                    continue
                owner = lease.owner
                if owner is None or display_key in mutex_type._active_native_claims:
                    continue
                drain_token = next(_LEASE_DRAIN_TOKENS)
                installed_claims.append((display_key, lease, drain_token))
                mutex_type._active_native_claims[display_key] = drain_token
                if mutex_type._active_native_leases.get(display_key) is not lease:
                    mutex_type._active_native_claims.pop(display_key, None)
                    continue
                candidates.append((display_key, lease, owner, drain_token))
            handoff_complete = True
    finally:
        if not handoff_complete:
            with mutex_type._poison_guard:
                for display_key, _lease, drain_token in installed_claims:
                    if mutex_type._active_native_claims.get(display_key) == drain_token:
                        mutex_type._active_native_claims.pop(display_key, None)
    drained = 0
    for display_key, lease, owner, drain_token in candidates:
        claim_resolved = False
        try:
            try:
                owner.command(_WindowsMutexOwnerAction.SHUTDOWN)
            except BaseException:
                mutex_type._owner_registry_state(owner)
                if lease.native_handle is not None:
                    mutex_type._poison_lease(lease)
            with mutex_type._poison_guard:
                if mutex_type._active_native_claims.get(display_key) == drain_token:
                    if owner.terminal and owner.native_handle is None:
                        if mutex_type._active_native_leases.get(display_key) is lease:
                            mutex_type._active_native_leases.pop(display_key, None)
                        drained += 1
                    mutex_type._active_native_claims.pop(display_key, None)
            claim_resolved = True
        finally:
            if not claim_resolved:
                with mutex_type._poison_guard:
                    if mutex_type._active_native_claims.get(display_key) == drain_token:
                        mutex_type._active_native_claims.pop(display_key, None)
    return drained


def _drain_poisoned_native_leases(*, limit: int = _REGISTRY_DRAIN_LIMIT) -> int:
    """Close bounded handles only when mutex release is known and close is retryable."""
    if type(limit) is not int or limit < 0:
        raise ValueError("poisoned native lease drain limit must be a non-negative integer")
    mutex_type = WindowsNamedDisplayTransactionMutex
    candidates: list[tuple[str, _WindowsNamedMutexLease, object | None, int]] = []
    installed_claims: list[tuple[str, _WindowsNamedMutexLease, int]] = []
    handoff_complete = False
    try:
        with mutex_type._poison_guard:
            for display_key, lease in mutex_type._poisoned_native_leases.items():
                if len(candidates) >= limit:
                    break
                native_handle = lease.native_handle
                if display_key in mutex_type._poisoned_native_claims or (
                    native_handle is not None and (not lease.mutex_released or lease.close_uncertain)
                ):
                    continue
                drain_token = next(_LEASE_DRAIN_TOKENS)
                installed_claims.append((display_key, lease, drain_token))
                mutex_type._poisoned_native_claims[display_key] = drain_token
                if (
                    mutex_type._poisoned_native_leases.get(display_key) is not lease
                    or lease.native_handle is not native_handle
                    or (native_handle is not None and (not lease.mutex_released or lease.close_uncertain))
                ):
                    mutex_type._poisoned_native_claims.pop(display_key, None)
                    continue
                candidates.append((display_key, lease, native_handle, drain_token))
            handoff_complete = True
    finally:
        if not handoff_complete:
            with mutex_type._poison_guard:
                for display_key, lease, drain_token in installed_claims:
                    if (
                        mutex_type._poisoned_native_claims.get(display_key) == drain_token
                        and mutex_type._poisoned_native_leases.get(display_key) is lease
                    ):
                        mutex_type._poisoned_native_claims.pop(display_key, None)
    drained = 0
    for display_key, lease, native_handle, drain_token in candidates:
        claim_resolved = False
        try:
            if native_handle is None:
                closed = True
            elif lease.owner is not None:
                try:
                    lease.owner.command(_WindowsMutexOwnerAction.CLOSE)
                except BaseException:
                    mutex_type._owner_registry_state(lease.owner)
                    closed = lease.owner.terminal and lease.owner.native_handle is None
                else:
                    mutex_type._owner_registry_state(lease.owner)
                    closed = lease.owner.terminal and lease.owner.native_handle is None
            else:
                close_call = _NativeCallState(lease.kernel32.CloseHandle, native_handle)
                try:
                    closed = _invoke_windows_handle_close(lease.kernel32.CloseHandle, native_handle, close_call)
                except BaseException:
                    try:
                        closed = _invoke_windows_handle_close(lease.kernel32.CloseHandle, native_handle, close_call)
                    except BaseException:
                        with mutex_type._poison_guard:
                            if mutex_type._poisoned_native_claims.get(display_key) == drain_token:
                                mutex_type._poisoned_native_claims.pop(display_key, None)
                            lease.close_uncertain = close_call.entered
                        claim_resolved = True
                        continue
            if not closed:
                with mutex_type._poison_guard:
                    if mutex_type._poisoned_native_claims.get(display_key) == drain_token:
                        mutex_type._poisoned_native_claims.pop(display_key, None)
                claim_resolved = True
                continue
            with mutex_type._poison_guard:
                if (
                    mutex_type._poisoned_native_claims.get(display_key) == drain_token
                    and mutex_type._poisoned_native_leases.get(display_key) is lease
                    and (lease.native_handle is native_handle or lease.native_handle is None)
                ):
                    lease.native_handle = None
                    mutex_type._poisoned_native_leases.pop(display_key, None)
                    mutex_type._poisoned_native_claims.pop(display_key, None)
                    drained += 1
                elif mutex_type._poisoned_native_claims.get(display_key) == drain_token:
                    mutex_type._poisoned_native_claims.pop(display_key, None)
            claim_resolved = True
        finally:
            if not claim_resolved:
                with mutex_type._poison_guard:
                    if mutex_type._poisoned_native_claims.get(display_key) == drain_token:
                        mutex_type._poisoned_native_claims.pop(display_key, None)
    return drained


class ProductionDisplayTransactionMutex:
    """Process and Windows-kernel mutexes acquired as one fail-closed lease."""

    def __init__(self) -> None:
        self._process = InProcessDisplayTransactionMutex()
        self._windows = WindowsNamedDisplayTransactionMutex()

    @staticmethod
    def _notify_reconciliation_observers(handle: _ProductionMutexLease) -> None:
        with handle._state_guard:
            settled = handle.poisoned or (
                handle.process_handle is None
                and handle.windows_handle is None
                and handle.transient_windows_owner is None
            )
            if not settled:
                return
            observers = handle._release_observers if handle.reconciliation_required else []
            handle._release_observers = []
            handle.reconciliation_required = False
        failures: list[BaseException] = []
        for observer in observers:
            try:
                observer(handle)
            except BaseException as exc:
                failures.append(exc)
        if failures:
            _raise_cleanup_failures("production mutex reconciliation observer failure", failures)

    def observe_release(
        self,
        handle: object,
        observer: Callable[[_ProductionMutexLease], None],
    ) -> None:
        if not isinstance(handle, _ProductionMutexLease):
            raise TypeError("invalid production display mutex handle")
        invoke_now = False
        with handle._state_guard:
            if handle.poisoned or (
                handle.process_handle is None
                and handle.windows_handle is None
                and handle.transient_windows_owner is None
            ):
                invoke_now = True
            elif all(existing is not observer for existing in handle._release_observers):
                handle._release_observers.append(observer)
        if invoke_now:
            observer(handle)

    def is_released(self, handle: object) -> bool:
        if not isinstance(handle, _ProductionMutexLease):
            raise TypeError("invalid production display mutex handle")
        with handle._state_guard:
            return (
                not handle.poisoned
                and handle.process_handle is None
                and handle.windows_handle is None
                and handle.transient_windows_owner is None
            )

    def is_transient(self, handle: object) -> bool:
        if not isinstance(handle, _ProductionMutexLease):
            raise TypeError("invalid production display mutex handle")
        with handle._state_guard:
            return not handle.poisoned and handle.transient_windows_owner is not None

    def _reconcile_windows_settlement(
        self,
        handle: _ProductionMutexLease,
        windows_handle: object,
        owner: _WindowsMutexOwner,
    ) -> None:
        with handle._state_guard:
            if (
                handle.transient_windows_owner is not owner
                or handle.windows_handle is not windows_handle
                or handle.poisoned
            ):
                return
            if owner.poisoned:
                handle.poisoned = True
                handle.transient_windows_owner = None
                handle.permanent_error = owner.last_error or RuntimeError(
                    "Windows mutex owner became permanently uncertain"
                )
            elif owner.terminal and owner.native_handle is None:
                handle.windows_handle = None
                handle.transient_windows_owner = None
                handle.transient_error = None
            else:
                return
        self._notify_reconciliation_observers(handle)

    def _retain_transient_windows_release(
        self,
        handle: _ProductionMutexLease,
        windows_handle: object,
        error: _WindowsMutexOwnerCommandTimeout,
    ) -> bool:
        owner = getattr(windows_handle, "owner", None)
        if not isinstance(owner, _WindowsMutexOwner):
            return False
        with handle._state_guard:
            if handle.windows_handle is not windows_handle or handle.poisoned:
                return False
            handle.transient_windows_owner = owner
            handle.transient_error = error
            handle.reconciliation_required = True
        owner.observe_settlement(
            lambda observed_owner: self._reconcile_windows_settlement(
                handle,
                windows_handle,
                observed_owner,
            )
        )
        return True

    def acquire(self, display_id: str) -> object:
        lease = _ProductionMutexLease(None, None)
        stack = getattr(_MUTEX_ACQUISITION_LOCAL, "stack", None)
        if stack:
            stack[-1].publish(lease)
        try:
            with _MutexAcquisitionSink(self._process) as process_sink:
                process_handle = process_sink.acquire(display_id)
                lease.process_handle = process_handle
                process_sink.acknowledge(process_handle)
            with _MutexAcquisitionSink(self._windows) as windows_sink:
                windows_handle = windows_sink.acquire(display_id)
                lease.windows_handle = windows_handle
                windows_sink.acknowledge(windows_handle)
            return _publish_mutex_lease(lease)
        except BaseException as exc:
            failures = [exc]
            if lease.windows_handle is not None and not _mutex_reports_released(self._windows, lease.windows_handle):
                try:
                    self._windows.release(lease.windows_handle)
                except BaseException as cleanup_exc:
                    failures.append(cleanup_exc)
            if lease.windows_handle is not None and _mutex_reports_released(self._windows, lease.windows_handle):
                lease.windows_handle = None
            if lease.process_handle is not None and not _mutex_reports_released(self._process, lease.process_handle):
                try:
                    self._process.release(lease.process_handle)
                except BaseException as cleanup_exc:
                    failures.append(cleanup_exc)
            if lease.process_handle is not None and _mutex_reports_released(self._process, lease.process_handle):
                lease.process_handle = None
            if lease.windows_handle is not None or lease.process_handle is not None:
                lease.poisoned = True
            _raise_cleanup_failures("process mutex cleanup after Windows acquisition failure", failures)

    def release(self, handle: object) -> None:
        if not isinstance(handle, _ProductionMutexLease):
            raise TypeError("invalid production display mutex handle")
        with handle._state_guard:
            if handle.poisoned:
                raise RuntimeError("production display mutex lease is poisoned")
            transient_owner = handle.transient_windows_owner
            transient_error = handle.transient_error
        if transient_owner is not None:
            windows_handle = handle.windows_handle
            if windows_handle is not None:
                self._reconcile_windows_settlement(handle, windows_handle, transient_owner)
            with handle._state_guard:
                if handle.poisoned:
                    raise RuntimeError("production display mutex lease is poisoned")
                if handle.transient_windows_owner is not None:
                    raise transient_error or _WindowsMutexOwnerCommandTimeout(
                        "Windows mutex owner command did not settle within its bounded wait"
                    )
        with handle._state_guard:
            if handle.windows_handle is None and handle.process_handle is None:
                return
        failures: list[BaseException] = []
        transient_failure: _WindowsMutexOwnerCommandTimeout | None = None
        if handle.windows_handle is not None:
            windows_handle = handle.windows_handle
            windows_released = _mutex_reports_released(self._windows, windows_handle)
            if not windows_released:
                try:
                    self._windows.release(windows_handle)
                    windows_released = True
                except _WindowsMutexOwnerCommandTimeout as exc:
                    windows_released = _mutex_reports_released(self._windows, windows_handle)
                    if not windows_released and self._retain_transient_windows_release(handle, windows_handle, exc):
                        transient_failure = exc
                    elif not windows_released:
                        failures.append(exc)
                except BaseException as exc:
                    failures.append(exc)
                    windows_released = _mutex_reports_released(self._windows, windows_handle)
            if windows_released:
                publication_failure: BaseException | None = None
                try:
                    with handle._state_guard:
                        if handle.windows_handle is windows_handle:
                            handle.windows_handle = None
                            handle.transient_windows_owner = None
                            handle.transient_error = None
                except BaseException as exc:
                    publication_failure = exc
                    with handle._state_guard:
                        if handle.windows_handle is windows_handle:
                            handle.windows_handle = None
                            handle.transient_windows_owner = None
                            handle.transient_error = None
                if publication_failure is not None:
                    failures.append(publication_failure)
        if handle.process_handle is not None:
            process_handle = handle.process_handle
            process_released = _mutex_reports_released(self._process, process_handle)
            if not process_released:
                try:
                    self._process.release(process_handle)
                    process_released = True
                except BaseException as exc:
                    failures.append(exc)
                    process_released = _mutex_reports_released(self._process, process_handle)
            if process_released:
                publication_failure = None
                try:
                    with handle._state_guard:
                        if handle.process_handle is process_handle:
                            handle.process_handle = None
                except BaseException as exc:
                    publication_failure = exc
                    with handle._state_guard:
                        if handle.process_handle is process_handle:
                            handle.process_handle = None
                if publication_failure is not None:
                    failures.append(publication_failure)
        if failures:
            with handle._state_guard:
                handle.poisoned = True
                handle.transient_windows_owner = None
                handle.permanent_error = failures[0]
            _raise_cleanup_failures("additional production mutex release failure", failures)
        self._notify_reconciliation_observers(handle)
        if transient_failure is not None:
            with handle._state_guard:
                still_transient = handle.transient_windows_owner is not None
                permanent_error = handle.permanent_error if handle.poisoned else None
            if permanent_error is not None:
                raise permanent_error
            if still_transient:
                raise transient_failure


@dataclass
class _ProductionMutexLease:
    process_handle: object | None
    windows_handle: object | None
    poisoned: bool = False
    transient_windows_owner: _WindowsMutexOwner | None = None
    transient_error: _WindowsMutexOwnerCommandTimeout | None = None
    permanent_error: BaseException | None = None
    reconciliation_required: bool = False
    _release_observers: list[Callable[[_ProductionMutexLease], None]] = field(default_factory=list, repr=False)
    _state_guard: threading.Lock = field(default_factory=threading.Lock, repr=False)


@dataclass(frozen=True)
class _PreparedPlan:
    plan: ApplyPlan
    icc_profile: IccProfileSnapshot | None
    gamma_ramp: GammaRamp | None
    dwm_lut: DwmLutSnapshot | None


class _TransactionPhase(str, Enum):
    CAPTURING = "capturing"
    CAPTURED = "captured"
    APPLYING = "applying"
    APPLIED = "applied"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    COMMITTING = "committing"
    UNCERTAIN = "uncertain"
    POISONED = "poisoned"
    RESTORING = "restoring"


@dataclass
class _IccMutationJournal:
    effect: IccInstallEffect | None = None
    activation_attempted: bool = False
    activation_effect: IccActivationEffect = IccActivationEffect()


@dataclass
class _ActiveTransaction:
    prepared: _PreparedPlan
    snapshot: DisplayStateSnapshot
    sealed_snapshot: DisplayStateSnapshot
    plan_sha256: str
    snapshot_sha256: str
    mutex_handles: list[object]
    icc: _IccMutationJournal
    lease_poisoned: bool = False
    release_reconciliation_bound: bool = False
    release_call_in_progress: bool = False
    release_reconciliation_pending: bool = False


class WindowsDisplayStateAdapter:
    """Preflight, capture, apply, verify, and restore through injected ports."""

    def __init__(
        self,
        ports: WindowsDisplayPorts,
        *,
        gamma_ramp_loader: GammaRampLoader = _load_vcgt_gamma_ramp,
        icc_profile_validator: AssetValidator = _validate_icc_profile_file,
        dwm_lut_validator: AssetValidator = _validate_dwm_lut_file,
        transaction_mutex: DisplayTransactionMutex | None = None,
    ) -> None:
        self._ports = ports
        self._gamma_ramp_loader = gamma_ramp_loader
        self._icc_profile_validator = icc_profile_validator
        self._dwm_lut_validator = dwm_lut_validator
        if transaction_mutex is None:
            transaction_mutex = ProductionDisplayTransactionMutex()
        self._transaction_mutex = transaction_mutex
        self._state_lock = threading.Lock()
        self._phase: _TransactionPhase | None = None
        self._active: _ActiveTransaction | None = None
        self._capture_authorization_verifier: CaptureAuthorizationVerifier | None = None

    @staticmethod
    def _require_captured(state: CapturedState[T], label: str) -> CapturedState[T]:
        if not isinstance(state, CapturedState):
            raise TypeError(f"{label} reader did not return CapturedState")
        if state.status is CaptureStatus.NOT_CAPTURED:
            raise RuntimeError(f"{label} state was not captured: {state.detail}")
        return state

    def _prepare(self, plan: ApplyPlan) -> _PreparedPlan:
        profile: IccProfileSnapshot | None = None
        if plan.icc_profile_path is not None:
            assert plan.icc_profile_sha256 is not None
            payload = _read_exact_bytes(plan.icc_profile_path, plan.icc_profile_sha256, "ICC profile")
            with tempfile.TemporaryDirectory(prefix="calibrate-pro-icc-validate-") as temporary_directory:
                staged = Path(temporary_directory) / Path(plan.icc_profile_path).name
                staged.write_bytes(payload)
                self._icc_profile_validator(str(staged))
            profile = IccProfileSnapshot(plan.icc_profile_path, payload, plan.icc_profile_sha256)

        gamma: GammaRamp | None = None
        if plan.vcgt_path is not None:
            assert plan.vcgt_sha256 is not None
            payload = _read_exact_bytes(plan.vcgt_path, plan.vcgt_sha256, "VCGT")
            with tempfile.TemporaryDirectory(prefix="calibrate-pro-vcgt-") as temporary_directory:
                staged = Path(temporary_directory) / Path(plan.vcgt_path).name
                staged.write_bytes(payload)
                gamma = _normalize_gamma_ramp(self._gamma_ramp_loader(str(staged)))

        dwm_lut: DwmLutSnapshot | None = None
        if plan.dwm_lut_path is not None:
            assert plan.dwm_lut_kind is not None
            assert plan.dwm_lut_sha256 is not None
            payload = _read_exact_bytes(plan.dwm_lut_path, plan.dwm_lut_sha256, "DWM LUT")
            with tempfile.TemporaryDirectory(prefix="calibrate-pro-dwm-validate-") as temporary_directory:
                staged = Path(temporary_directory) / Path(plan.dwm_lut_path).name
                staged.write_bytes(payload)
                self._dwm_lut_validator(str(staged))
            dwm_lut = DwmLutSnapshot(
                plan.dwm_lut_kind,
                plan.dwm_lut_path,
                payload,
                plan.dwm_lut_sha256,
            )
        return _PreparedPlan(plan, profile, gamma, dwm_lut)

    def capture(self, plan: ApplyPlan, *, authorization: object | None = None) -> DisplayStateSnapshot:
        mutex_handles: list[object] = []
        try:
            with self._state_lock:
                verifier = self._capture_authorization_verifier
                if verifier is None:
                    raise PermissionError("Windows display capture requires bound coordinator authorization")
                confirmed_plan_sha256 = verifier(plan, authorization)
                if self._phase is not None:
                    raise RuntimeError("a display transaction is already active")
                self._phase = _TransactionPhase.CAPTURING
            sealed_plan = ApplyPlan(**asdict(copy.deepcopy(plan)))
            if _canonical_plan_sha256(sealed_plan) != confirmed_plan_sha256:
                raise PermissionError("confirmed apply plan changed while capture authorization was consumed")
            if sealed_plan.icc_profile_sha256 is not None:
                with _MutexAcquisitionSink(self._transaction_mutex) as acquisition_sink:
                    mutex_handles.append(acquisition_sink.acquire(f"icc-sha256:{sealed_plan.icc_profile_sha256}"))
                    acquisition_sink.acknowledge(mutex_handles[-1])
            with _MutexAcquisitionSink(self._transaction_mutex) as acquisition_sink:
                mutex_handles.append(acquisition_sink.acquire(f"display:{sealed_plan.display_id}"))
                acquisition_sink.acknowledge(mutex_handles[-1])
            prepared = self._prepare(sealed_plan)
            display_id = sealed_plan.display_id
            ddc_target = self._ports.resolve_ddc_target(display_id) if sealed_plan.ddc_changes else None
            if ddc_target is not None:
                if not isinstance(ddc_target, DdcTargetIdentity):
                    raise TypeError("DDC target resolver did not return DdcTargetIdentity")
                DdcTargetIdentity(ddc_target.display_id, ddc_target.monitor_device_path)
            ddc_values_list: list[tuple[str, DdcReading]] = []
            for code, target in sealed_plan.ddc_changes:
                assert ddc_target is not None
                reading = self._ports.read_ddc(ddc_target, code)
                if not isinstance(reading, DdcReading):
                    raise TypeError("DDC reader did not return DdcReading")
                DdcReading(reading.current, reading.maximum)
                if target > reading.maximum:
                    raise ValueError(f"DDC target {target} exceeds {code} maximum {reading.maximum}")
                ddc_values_list.append((code, reading))
            ddc_values = tuple(ddc_values_list)
            icc_profile = None
            icc_lifecycle = None
            if sealed_plan.icc_profile_path is not None:
                assert sealed_plan.icc_profile_sha256 is not None
                target_profile_name = f"calibrate-pro-{sealed_plan.icc_profile_sha256}.icc"
                was_installed = self._ports.is_icc_profile_installed(target_profile_name)
                was_associated = self._ports.is_icc_profile_associated(display_id, target_profile_name)
                if type(was_installed) is not bool or type(was_associated) is not bool:
                    raise TypeError("ICC lifecycle readers must return exact booleans")
                icc_lifecycle = IccLifecycleSnapshot(
                    target_profile_name,
                    was_installed,
                    was_associated,
                )
                icc_profile = self._require_captured(self._ports.capture_icc_profile(display_id), "ICC profile")
                if icc_profile.value is not None and not isinstance(icc_profile.value, IccProfileSnapshot):
                    raise TypeError("captured ICC profile must be None or IccProfileSnapshot")
                if icc_profile.value is not None:
                    IccProfileSnapshot(
                        icc_profile.value.original_path,
                        icc_profile.value.payload,
                        icc_profile.value.sha256,
                    )
            gamma_ramp = None
            if sealed_plan.vcgt_path is not None:
                gamma_ramp = self._require_captured(self._ports.capture_gamma_ramp(display_id), "gamma ramp")
                if gamma_ramp.value is not None:
                    normalized_gamma = _normalize_gamma_ramp(gamma_ramp.value)
                    if type(gamma_ramp.value) is not tuple or gamma_ramp.value != normalized_gamma:
                        raise TypeError("captured gamma ramp must be an exact normalized GammaRamp tuple")
            dwm_luts = None
            if sealed_plan.dwm_lut_path is not None or sealed_plan.clear_existing_lut:
                dwm_luts = self._require_captured(self._ports.capture_dwm_luts(display_id), "DWM LUT")
                if dwm_luts.value is None:
                    raise RuntimeError("captured DWM LUT state must be a tuple, not None")
                self._validate_lut_set(dwm_luts.value)
            snapshot = DisplayStateSnapshot(
                display_id,
                ddc_values,
                icc_profile,
                gamma_ramp,
                dwm_luts,
                ddc_target,
                icc_lifecycle,
            )
            assert mutex_handles
            sealed_snapshot = copy.deepcopy(snapshot)
            snapshot_sha256 = _snapshot_sha256(sealed_snapshot)
            with self._state_lock:
                self._active = _ActiveTransaction(
                    prepared,
                    snapshot,
                    sealed_snapshot,
                    confirmed_plan_sha256,
                    snapshot_sha256,
                    mutex_handles,
                    _IccMutationJournal(),
                )
                self._phase = _TransactionPhase.CAPTURED
            return snapshot
        except BaseException as exc:
            release_failure: BaseException | None = None
            try:
                self._release_mutex_handles(mutex_handles)
            except BaseException as mutex_exc:
                release_failure = mutex_exc
            publication_failure: BaseException | None = None
            try:
                with self._state_lock:
                    self._active = None
                    self._phase = _TransactionPhase.POISONED if release_failure is not None else None
            except BaseException as state_exc:
                publication_failure = state_exc
                with self._state_lock:
                    self._active = None
                    self._phase = _TransactionPhase.POISONED if release_failure is not None else None
            if publication_failure is not None:
                _raise_cleanup_failures(
                    "capture state publication also failed",
                    [exc, publication_failure],
                )
            if release_failure is not None:
                release_detail = str(release_failure).strip() or type(release_failure).__name__
                message = f"capture failed and a transaction mutex could not be released: {release_detail}"
                if not isinstance(release_failure, Exception):
                    _add_exception_note(
                        release_failure,
                        f"capture also failed: {str(exc).strip() or type(exc).__name__}",
                    )
                    raise release_failure from exc
                if isinstance(exc, Exception):
                    raise RuntimeError(message) from exc
                _add_exception_note(exc, message)
                raise
            raise

    @staticmethod
    def _validate_lut_set(luts: tuple[DwmLutSnapshot, ...]) -> None:
        if not isinstance(luts, tuple) or any(not isinstance(item, DwmLutSnapshot) for item in luts):
            raise TypeError("captured DWM LUT state must be a tuple of DwmLutSnapshot values")
        if len({item.kind for item in luts}) != len(luts):
            raise RuntimeError("captured DWM LUT state contains duplicate LUT kinds")
        for item in luts:
            DwmLutSnapshot(item.kind, item.original_path, item.payload, item.sha256)

    def _claim_phase(
        self,
        plan: ApplyPlan,
        expected: _TransactionPhase,
        claimed: _TransactionPhase,
    ) -> _ActiveTransaction:
        with self._state_lock:
            if self._active is None or self._phase is not expected:
                raise RuntimeError(f"operation requires an active {expected.value} transaction")
            try:
                incoming_plan_sha256 = _canonical_plan_sha256(copy.deepcopy(plan))
            except BaseException:
                self._phase = _TransactionPhase.UNCERTAIN
                raise
            if incoming_plan_sha256 != self._active.plan_sha256:
                self._phase = _TransactionPhase.UNCERTAIN
                raise RuntimeError("active capture belongs to a changed or different apply plan")
            if _snapshot_sha256(self._active.snapshot) != self._active.snapshot_sha256:
                self._phase = _TransactionPhase.UNCERTAIN
                raise RuntimeError("adapter-issued snapshot evidence changed after capture")
            self._phase = claimed
            return self._active

    def _finish_phase(self, phase: _TransactionPhase) -> None:
        with self._state_lock:
            self._phase = phase

    def _mutex_release_state(self, active: _ActiveTransaction) -> str:
        transient_reader = getattr(self._transaction_mutex, "is_transient", None)
        any_transient = False
        for handle in list(active.mutex_handles):
            try:
                if _mutex_reports_released(self._transaction_mutex, handle):
                    continue
                transient = transient_reader(handle) if callable(transient_reader) else False
                if type(transient) is not bool:
                    raise TypeError("mutex transient-state reader must return an exact boolean")
            except BaseException:
                return "permanent"
            if not transient:
                return "permanent"
            any_transient = True
        if any_transient:
            return "transient"
        return "released"

    def _reconcile_transaction_mutex_release(self, active: _ActiveTransaction) -> None:
        with self._state_lock:
            if self._active is not active:
                return
            if getattr(active, "release_call_in_progress", False):
                active.release_reconciliation_pending = True
                return
            state = self._mutex_release_state(active)
            if state == "permanent":
                active.lease_poisoned = True
                self._phase = _TransactionPhase.POISONED
                return
            if state != "released":
                return
            active.mutex_handles.clear()
            self._active = None
            self._phase = None

    def _bind_transaction_mutex_reconciliation(self, active: _ActiveTransaction) -> None:
        if getattr(active, "release_reconciliation_bound", False):
            return
        observer = getattr(self._transaction_mutex, "observe_release", None)
        if not callable(observer):
            active.release_reconciliation_bound = True
            return
        for handle in list(active.mutex_handles):
            observer(
                handle,
                lambda _released_handle, expected=active: self._reconcile_transaction_mutex_release(expected),
            )
        active.release_reconciliation_bound = True

    def _release_transaction_mutex(self, active: _ActiveTransaction) -> None:
        self._bind_transaction_mutex_reconciliation(active)
        active.release_call_in_progress = True
        try:
            self._release_mutex_handles(active.mutex_handles)
        except BaseException:
            state = self._mutex_release_state(active)
            if state == "permanent":
                active.lease_poisoned = True
            elif state == "released":
                self._reconcile_transaction_mutex_release(active)
            raise
        finally:
            active.release_call_in_progress = False
            if getattr(active, "release_reconciliation_pending", False):
                active.release_reconciliation_pending = False
                self._reconcile_transaction_mutex_release(active)

    def _release_mutex_handles(self, handles: list[object]) -> None:
        failures: list[BaseException] = []
        for index in range(len(handles) - 1, -1, -1):
            handle = handles[index]
            try:
                (self._transaction_mutex.release(handle), handles.pop(index))  # type: ignore[func-returns-value]
            except BaseException as exc:
                failures.append(exc)
                try:
                    released = _mutex_reports_released(self._transaction_mutex, handle)
                except BaseException as state_exc:
                    failures.append(state_exc)
                    released = False
                if released and index < len(handles) and handles[index] is handle:
                    handles.pop(index)
        if failures:
            _raise_cleanup_failures("additional transaction mutex release failure", failures)

    def _target_luts(self, active: _ActiveTransaction) -> tuple[DwmLutSnapshot, ...]:
        plan = active.prepared.plan
        if plan.clear_existing_lut:
            return ()
        target = active.prepared.dwm_lut
        if target is None:
            return ()
        captured = active.sealed_snapshot.dwm_luts
        if captured is None or captured.value is None:
            raise RuntimeError("DWM LUT application requires captured prior state")
        preserved = tuple(lut for lut in captured.value if lut.kind is not target.kind)
        order = {DwmLutKind.SDR: 0, DwmLutKind.HDR: 1}
        return tuple(sorted((*preserved, target), key=lambda lut: order[lut.kind]))

    def apply(self, plan: ApplyPlan) -> None:
        try:
            active = self._claim_phase(plan, _TransactionPhase.CAPTURED, _TransactionPhase.APPLYING)
            prepared = active.prepared
            plan = prepared.plan
            display_id = plan.display_id
            if prepared.icc_profile is not None:
                effect = self._ports.materialize_icc_profile(prepared.icc_profile)
                if not isinstance(effect, IccInstallEffect):
                    raise TypeError("ICC materialization did not return IccInstallEffect")
                installed = effect.installed_profile
                IccProfileSnapshot(installed.original_path, installed.payload, installed.sha256)
                IccInstallEffect(installed, effect.created_file)
                active.icc.effect = effect
            captured_ddc = dict(active.sealed_snapshot.ddc_values)
            for code, value in plan.ddc_changes:
                target = active.sealed_snapshot.ddc_target
                if target is None:
                    raise RuntimeError("DDC apply requires captured stable target identity")
                expected = captured_ddc[code]
                if self._ports.read_ddc(target, code) != expected:
                    raise RuntimeError(f"DDC {code} changed after capture")
                self._ports.write_ddc(
                    target,
                    code,
                    value,
                    expected_maximum=expected.maximum,
                )
            if prepared.icc_profile is not None:
                assert active.icc.effect is not None
                effect = active.icc.effect
                lifecycle = active.sealed_snapshot.icc_lifecycle
                if lifecycle is None:
                    raise RuntimeError("ICC application requires captured installation/association evidence")
                installed_now = self._ports.is_icc_profile_installed(lifecycle.target_profile_name)
                associated_now = self._ports.is_icc_profile_associated(
                    display_id,
                    lifecycle.target_profile_name,
                )
                if type(installed_now) is not bool or type(associated_now) is not bool:
                    raise TypeError("ICC lifecycle revalidation must return exact booleans")
                if (installed_now, associated_now) != (
                    lifecycle.was_installed,
                    lifecycle.was_associated,
                ):
                    raise RuntimeError("ICC installation or association changed after capture")
                captured_prior = active.sealed_snapshot.icc_profile
                if captured_prior is None:
                    raise RuntimeError("ICC application requires captured persistent-default evidence")
                current_prior = self._require_captured(
                    self._ports.capture_icc_profile(display_id),
                    "ICC persistent default pre-activation",
                )
                if not self._same_profile(current_prior.value, captured_prior.value):
                    raise RuntimeError("ICC persistent default changed after capture")
                if captured_prior.value is None and lifecycle.was_associated:
                    raise RuntimeError(
                        "captured absent ICC default is not safely restorable when the target association pre-existed"
                    )
                active.icc.activation_attempted = True
                try:
                    activation_effect = self._ports.activate_icc_profile(
                        display_id,
                        effect.installed_profile,
                        register=not lifecycle.was_installed,
                        associate=not lifecycle.was_associated,
                    )
                except IccActivationError as exc:
                    active.icc.activation_effect = exc.effect
                    raise
                except BaseException as exc:
                    interrupted_effect = getattr(exc, "icc_activation_effect", None)
                    if isinstance(interrupted_effect, IccActivationEffect):
                        active.icc.activation_effect = interrupted_effect
                    raise
                if not isinstance(activation_effect, IccActivationEffect):
                    raise TypeError("ICC activation did not return IccActivationEffect")
                active.icc.activation_effect = activation_effect
            if prepared.gamma_ramp is not None:
                captured_gamma = active.sealed_snapshot.gamma_ramp
                if captured_gamma is None:
                    raise RuntimeError("gamma ramp application requires captured prior state")
                current_gamma = self._require_captured(
                    self._ports.capture_gamma_ramp(display_id),
                    "gamma ramp pre-application comparison",
                )
                if current_gamma.value != captured_gamma.value:
                    raise RuntimeError("gamma ramp changed after capture")
                self._ports.set_gamma_ramp(display_id, prepared.gamma_ramp)
            if prepared.dwm_lut is not None or plan.clear_existing_lut:
                captured_luts = active.sealed_snapshot.dwm_luts
                if captured_luts is None or captured_luts.value is None:
                    raise RuntimeError("DWM LUT application requires captured prior state")
                current_luts = self._require_captured(
                    self._ports.capture_dwm_luts(display_id),
                    "DWM LUT pre-application comparison",
                )
                if current_luts.value is None or not self._same_luts(current_luts.value, captured_luts.value):
                    raise RuntimeError("DWM LUT state changed after capture")
                self._ports.set_dwm_luts(display_id, self._target_luts(active))
            self._finish_phase(_TransactionPhase.APPLIED)
        except BaseException:
            with self._state_lock:
                if self._active is not None and self._phase is _TransactionPhase.APPLYING:
                    self._phase = _TransactionPhase.UNCERTAIN
            raise

    @staticmethod
    def _same_profile(actual: IccProfileSnapshot | None, expected: IccProfileSnapshot | None) -> bool:
        if expected is None:
            return actual is None
        return (
            actual is not None
            and Path(actual.original_path).name.casefold() == Path(expected.original_path).name.casefold()
            and actual.sha256 == expected.sha256
            and actual.payload == expected.payload
        )

    @staticmethod
    def _same_luts(actual: tuple[DwmLutSnapshot, ...], expected: tuple[DwmLutSnapshot, ...]) -> bool:
        def evidence(luts: tuple[DwmLutSnapshot, ...]) -> dict[DwmLutKind, tuple[str, bytes]]:
            return {lut.kind: (lut.sha256, lut.payload) for lut in luts}

        return len(actual) == len(expected) and evidence(actual) == evidence(expected)

    def verify(self, plan: ApplyPlan) -> bool:
        try:
            active = self._claim_phase(plan, _TransactionPhase.APPLIED, _TransactionPhase.VERIFYING)
            prepared = active.prepared
            plan = prepared.plan
            display_id = plan.display_id
            matches = True
            captured_ddc = dict(active.sealed_snapshot.ddc_values)
            for code, expected_current in plan.ddc_changes:
                target = active.sealed_snapshot.ddc_target
                if target is None:
                    raise RuntimeError("DDC verification requires captured stable target identity")
                actual = self._ports.read_ddc(target, code)
                if actual.current != expected_current or actual.maximum != captured_ddc[code].maximum:
                    matches = False
            if prepared.icc_profile is not None:
                if active.icc.effect is None:
                    raise RuntimeError("ICC verification requires materialization evidence")
                lifecycle = active.sealed_snapshot.icc_lifecycle
                if lifecycle is None:
                    raise RuntimeError("ICC verification requires captured lifecycle evidence")
                actual_profile = self._require_captured(
                    self._ports.capture_icc_profile(display_id), "ICC profile verification"
                )
                if not self._same_profile(actual_profile.value, active.icc.effect.installed_profile):
                    matches = False
                installed = self._ports.is_icc_profile_installed(lifecycle.target_profile_name)
                associated = self._ports.is_icc_profile_associated(display_id, lifecycle.target_profile_name)
                if type(installed) is not bool or type(associated) is not bool:
                    raise TypeError("ICC verification lifecycle readers must return exact booleans")
                if not installed or not associated:
                    matches = False
            if prepared.gamma_ramp is not None:
                actual_gamma = self._require_captured(
                    self._ports.capture_gamma_ramp(display_id), "gamma ramp verification"
                )
                if actual_gamma.value != prepared.gamma_ramp:
                    matches = False
            if prepared.dwm_lut is not None or plan.clear_existing_lut:
                actual_luts = self._require_captured(self._ports.capture_dwm_luts(display_id), "DWM LUT verification")
                if actual_luts.value is None:
                    raise RuntimeError("captured DWM LUT verification state must be a tuple, not None")
                if not self._same_luts(actual_luts.value, self._target_luts(active)):
                    matches = False
            self._finish_phase(_TransactionPhase.VERIFIED if matches else _TransactionPhase.UNCERTAIN)
        except BaseException:
            with self._state_lock:
                if self._active is not None and self._phase is _TransactionPhase.VERIFYING:
                    self._phase = _TransactionPhase.UNCERTAIN
            raise
        return matches

    def commit(self, plan: ApplyPlan) -> None:
        try:
            active = self._claim_phase(plan, _TransactionPhase.VERIFIED, _TransactionPhase.COMMITTING)
            self._release_transaction_mutex(active)
            with self._state_lock:
                self._active = None
                self._phase = None
        except BaseException:
            with self._state_lock:
                current = self._active
                if current is None:
                    self._phase = None
                elif current.lease_poisoned:
                    self._active = current
                    self._phase = _TransactionPhase.POISONED
                elif current.mutex_handles:
                    self._active = current
                    self._phase = _TransactionPhase.UNCERTAIN
                else:
                    self._active = None
                    self._phase = None
            raise

    def _run_restore_compensation_schedule(
        self,
        active: _ActiveTransaction,
        snapshot: DisplayStateSnapshot,
    ) -> tuple[list[str], BaseException | None]:
        errors: list[str] = []
        deferred_cancellation: BaseException | None = None

        def record_restore_failure(label: str, exc: BaseException) -> None:
            nonlocal deferred_cancellation
            detail = str(exc).strip() or type(exc).__name__
            errors.append(f"{label}: {detail}")
            if not isinstance(exc, Exception):
                if deferred_cancellation is None:
                    deferred_cancellation = exc
                else:
                    _add_exception_note(
                        deferred_cancellation,
                        f"additional compensation cancellation: {label}: {detail}",
                    )

        try:
            snapshot_tampered = _snapshot_sha256(snapshot) != active.snapshot_sha256
        except Exception:
            snapshot_tampered = True
        if snapshot_tampered:
            raise RuntimeError("adapter-issued snapshot evidence changed after capture; no compensation writer ran")

        sealed = active.sealed_snapshot
        ddc_targets = dict(active.prepared.plan.ddc_changes)
        for code, prior in sealed.ddc_values:
            try:
                if code not in DDC_WRITE_CODES:
                    raise RuntimeError("captured DDC code is outside the calibration allowlist")
                if sealed.ddc_target is None:
                    raise RuntimeError("captured DDC target identity is missing")
                current = self._ports.read_ddc(sealed.ddc_target, code)
                if current.maximum != prior.maximum:
                    raise RuntimeError(f"maximum changed from {prior.maximum} to {current.maximum}")
                if current == prior:
                    continue
                target = DdcReading(ddc_targets[code], prior.maximum)
                if current != target:
                    raise RuntimeError("concurrent DDC state conflict; stale compensation was withheld")
                self._ports.write_ddc(
                    sealed.ddc_target,
                    code,
                    prior.current,
                    expected_maximum=prior.maximum,
                )
                if self._ports.read_ddc(sealed.ddc_target, code) != prior:
                    raise RuntimeError(f"readback did not equal {prior}")
            except BaseException as exc:
                record_restore_failure(f"DDC {code}", exc)

        if sealed.icc_profile is not None:
            try:
                prior_state = self._require_captured(sealed.icc_profile, "ICC profile restoration")
                lifecycle = sealed.icc_lifecycle
                if lifecycle is None:
                    raise RuntimeError("captured target installation/association evidence is missing")
                effect = active.icc.effect
                icc_target = effect.installed_profile if effect is not None else None
                target_matches_prior = icc_target is not None and self._same_profile(icc_target, prior_state.value)
                current_state = self._require_captured(
                    self._ports.capture_icc_profile(sealed.display_id),
                    "ICC profile compensation comparison",
                )
                target_name = lifecycle.target_profile_name
                associated_now = self._ports.is_icc_profile_associated(sealed.display_id, target_name)
                if type(associated_now) is not bool:
                    raise TypeError("ICC target association restoration reader must return an exact boolean")

                default_is_prior = self._same_profile(current_state.value, prior_state.value)
                default_is_target = icc_target is not None and self._same_profile(current_state.value, icc_target)
                association_is_prior = associated_now == lifecycle.was_associated
                if (
                    default_is_target
                    and prior_state.value is None
                    and not (associated_now and not lifecycle.was_associated)
                ):
                    raise RuntimeError(
                        "captured absent ICC default cannot be restored without changing a preexisting association"
                    )
                if default_is_prior and association_is_prior:
                    pass
                elif not active.icc.activation_attempted or icc_target is None or target_matches_prior:
                    raise RuntimeError("concurrent ICC state conflict; stale compensation was withheld")
                elif not (default_is_prior or default_is_target):
                    raise RuntimeError("concurrent ICC default conflict; stale compensation was withheld")
                else:
                    wrote = False
                    if default_is_target and prior_state.value is not None:
                        self._ports.activate_icc_profile(
                            sealed.display_id,
                            prior_state.value,
                            register=False,
                            associate=False,
                        )
                        wrote = True
                    if associated_now and not lifecycle.was_associated:
                        self._ports.deactivate_icc_profile(sealed.display_id, target_name)
                        wrote = True
                    if wrote:
                        actual_icc = self._require_captured(
                            self._ports.capture_icc_profile(sealed.display_id),
                            "ICC profile restoration readback",
                        )
                        if not self._same_profile(actual_icc.value, prior_state.value):
                            raise RuntimeError("readback did not match captured profile bytes")
                        associated_after = self._ports.is_icc_profile_associated(sealed.display_id, target_name)
                        if associated_after != lifecycle.was_associated:
                            raise RuntimeError("ICC target association readback did not match captured state")
            except BaseException as exc:
                record_restore_failure("ICC profile", exc)

        if sealed.gamma_ramp is not None:
            try:
                prior_gamma = self._require_captured(sealed.gamma_ramp, "gamma ramp restoration")
                current_gamma = self._require_captured(
                    self._ports.capture_gamma_ramp(sealed.display_id),
                    "gamma ramp compensation comparison",
                )
                if current_gamma.value == prior_gamma.value:
                    pass
                elif current_gamma.value == active.prepared.gamma_ramp:
                    self._ports.set_gamma_ramp(sealed.display_id, prior_gamma.value)
                    actual_gamma = self._require_captured(
                        self._ports.capture_gamma_ramp(sealed.display_id),
                        "gamma ramp restoration readback",
                    )
                    if actual_gamma.value != prior_gamma.value:
                        raise RuntimeError("readback did not match captured gamma ramp")
                else:
                    raise RuntimeError("concurrent gamma ramp conflict; stale compensation was withheld")
            except BaseException as exc:
                record_restore_failure("gamma ramp", exc)

        if sealed.dwm_luts is not None:
            try:
                prior_dwm = self._require_captured(sealed.dwm_luts, "DWM LUT restoration")
                if prior_dwm.value is None:
                    raise RuntimeError("captured DWM LUT restoration state must be a tuple, not None")
                current_dwm = self._require_captured(
                    self._ports.capture_dwm_luts(sealed.display_id),
                    "DWM LUT compensation comparison",
                )
                if current_dwm.value is None:
                    raise RuntimeError("current DWM LUT state must be a tuple, not None")
                target_dwm = self._target_luts(active)
                if self._same_luts(current_dwm.value, prior_dwm.value):
                    pass
                elif self._same_luts(current_dwm.value, target_dwm):
                    self._ports.set_dwm_luts(sealed.display_id, prior_dwm.value)
                    actual_dwm = self._require_captured(
                        self._ports.capture_dwm_luts(sealed.display_id),
                        "DWM LUT restoration readback",
                    )
                    if actual_dwm.value is None or not self._same_luts(actual_dwm.value, prior_dwm.value):
                        raise RuntimeError("readback did not match captured DWM LUT bytes")
                else:
                    raise RuntimeError("concurrent DWM LUT conflict; stale compensation was withheld")
            except BaseException as exc:
                record_restore_failure("DWM LUT", exc)

        return errors, deferred_cancellation

    def restore(self, snapshot: DisplayStateSnapshot) -> None:
        active: _ActiveTransaction | None = None
        cleanup_owned = False
        primary: BaseException | None = None
        release_error: BaseException | None = None
        claim_complete = False
        claim_cancellations: list[BaseException] = []
        schedule_cancellations: list[BaseException] = []

        try:
            while not claim_complete:
                try:
                    with self._state_lock:
                        if self._phase in {
                            _TransactionPhase.CAPTURING,
                            _TransactionPhase.APPLYING,
                            _TransactionPhase.VERIFYING,
                            _TransactionPhase.COMMITTING,
                            _TransactionPhase.RESTORING,
                        }:
                            raise RuntimeError("cannot restore while another transaction phase is in progress")
                        active = self._active
                        if active is None:
                            raise RuntimeError("restore requires the adapter-issued snapshot of an active transaction")
                        if snapshot is not active.snapshot:
                            raise RuntimeError("restore requires the exact adapter-issued snapshot object")
                        if active.lease_poisoned or self._phase is _TransactionPhase.POISONED:
                            raise RuntimeError("transaction mutex ownership is poisoned; compensation is unsafe")
                        if not active.mutex_handles:
                            raise RuntimeError("transaction mutex is not held; compensation is unsafe")
                        cleanup_owned = True
                        self._phase = _TransactionPhase.RESTORING
                        claim_complete = True
                except BaseException as claim_exc:
                    if isinstance(claim_exc, Exception):
                        raise
                    claim_cancellations.append(claim_exc)
                    with self._state_lock:
                        if active is not None and self._active is active and self._phase is _TransactionPhase.RESTORING:
                            self._phase = _TransactionPhase.UNCERTAIN
                    continue
            if active is None:
                raise AssertionError("restore ownership claim completed without an active transaction")

            errors: list[str] = []
            deferred_cancellation: BaseException | None = None
            schedule_complete = False
            for _attempt in range(_MAX_COMPENSATION_SCHEDULE_ATTEMPTS):
                try:
                    errors, deferred_cancellation = self._run_restore_compensation_schedule(active, snapshot)
                except BaseException as schedule_exc:
                    if isinstance(schedule_exc, Exception):
                        raise
                    schedule_cancellations.append(schedule_exc)
                    continue
                if deferred_cancellation is not None:
                    schedule_cancellations.append(deferred_cancellation)
                    continue
                schedule_complete = True
                break
            if not schedule_complete:
                cleanup_owned = False
                with self._state_lock:
                    if self._active is active:
                        self._phase = _TransactionPhase.UNCERTAIN
                cancellation = schedule_cancellations[0]
                for additional in schedule_cancellations[1:]:
                    if additional is cancellation:
                        continue
                    _add_exception_note(
                        cancellation,
                        "additional compensation schedule cancellation: "
                        f"{str(additional).strip() or type(additional).__name__}",
                    )
                if errors:
                    _add_exception_note(cancellation, "display compensation failures: " + "; ".join(errors))
                _add_exception_note(
                    cancellation,
                    "display compensation retry budget was exhausted; active mutex ownership was retained",
                )
                raise cancellation
            cancellations = [*claim_cancellations, *schedule_cancellations]
            if errors:
                cleanup_owned = False
                with self._state_lock:
                    if self._active is active:
                        self._phase = _TransactionPhase.UNCERTAIN
                if cancellations:
                    cancellation = cancellations[0]
                    for additional in cancellations[1:]:
                        if additional is cancellation:
                            continue
                        _add_exception_note(
                            cancellation,
                            "additional compensation schedule cancellation: "
                            f"{str(additional).strip() or type(additional).__name__}",
                        )
                    _add_exception_note(cancellation, "display compensation failures: " + "; ".join(errors))
                    _add_exception_note(
                        cancellation,
                        "display restoration remained incomplete; active mutex ownership was retained",
                    )
                    raise cancellation
                raise RuntimeError(
                    "display state restoration failed with active mutex ownership retained: " + "; ".join(errors)
                )
            if cancellations:
                cancellation = cancellations[0]
                for additional in cancellations[1:]:
                    _add_exception_note(
                        cancellation,
                        "additional compensation schedule cancellation: "
                        f"{str(additional).strip() or type(additional).__name__}",
                    )
                if deferred_cancellation is not None:
                    _add_exception_note(
                        cancellation,
                        "display compensation schedule also deferred: "
                        f"{str(deferred_cancellation).strip() or type(deferred_cancellation).__name__}",
                    )
                raise cancellation
            if deferred_cancellation is not None:
                _add_exception_note(
                    deferred_cancellation,
                    "display compensation failures: " + "; ".join(errors),
                )
                raise deferred_cancellation
            return

        except BaseException as exc:
            primary = exc
            raise
        finally:
            if cleanup_owned and active is not None and not active.lease_poisoned:
                try:
                    self._release_transaction_mutex(active)
                except BaseException as exc:
                    release_error = exc
                publication_error: BaseException | None = None
                try:
                    with self._state_lock:
                        if (
                            (self._active is not active and not active.mutex_handles)
                            or release_error is None
                            or not active.mutex_handles
                        ):
                            self._active = None
                            self._phase = None
                        elif active.lease_poisoned or self._mutex_release_state(active) == "permanent":
                            active.lease_poisoned = True
                            self._active = active
                            self._phase = _TransactionPhase.POISONED
                        else:
                            self._active = active
                            self._phase = _TransactionPhase.UNCERTAIN
                except BaseException as exc:
                    publication_error = exc
                    with self._state_lock:
                        if (
                            (self._active is not active and not active.mutex_handles)
                            or release_error is None
                            or not active.mutex_handles
                        ):
                            self._active = None
                            self._phase = None
                        elif active.lease_poisoned or self._mutex_release_state(active) == "permanent":
                            active.lease_poisoned = True
                            self._active = active
                            self._phase = _TransactionPhase.POISONED
                        else:
                            self._active = active
                            self._phase = _TransactionPhase.UNCERTAIN
                if publication_error is not None:
                    cleanup_failures = [publication_error]
                    if release_error is not None:
                        cleanup_failures.append(release_error)
                    if primary is not None:
                        cleanup_failures.insert(0, primary)
                    _raise_cleanup_failures("additional restore finalization failure", cleanup_failures)
                if release_error is not None:
                    release_detail = str(release_error).strip() or type(release_error).__name__
                    if primary is None:
                        raise release_error
                    if not isinstance(primary, Exception):
                        _add_exception_note(primary, f"transaction mutex release also failed: {release_detail}")
                    elif not isinstance(release_error, Exception):
                        _add_exception_note(
                            release_error,
                            f"display compensation also failed: {str(primary).strip() or type(primary).__name__}",
                        )
                        raise release_error from primary
                    else:
                        raise RuntimeError(
                            f"{str(primary).strip() or type(primary).__name__}; "
                            f"transaction mutex release also failed: {release_detail}"
                        ) from primary


def _drain_adapter_lease_registries_at_shutdown() -> None:
    """Best-effort bounded shutdown pass; retained uncertainty is never discarded."""
    drains = (
        _drain_unclaimed_mutex_leases,
        _drain_retained_icc_leases,
        _drain_retained_native_resources,
        _drain_retained_native_terminals,
        _drain_pending_native_owners,
        _drain_active_native_owners,
        _drain_poisoned_native_leases,
    )
    for drain in drains:
        try:
            drain(limit=_REGISTRY_DRAIN_LIMIT)
        except BaseException:
            continue


atexit.register(_drain_adapter_lease_registries_at_shutdown)
