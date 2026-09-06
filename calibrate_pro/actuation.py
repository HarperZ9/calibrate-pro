"""Expiring one-use confirmation bound to a capability-validated apply plan."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Protocol, cast

from calibrate_pro.recovery import (
    ApplyReceipt,
    DisplayStateAdapter,
    _apply_confirmed_with_best_effort_recovery,
)
from calibrate_pro.workflow import ApplyPlan, CapabilityState

CapabilityProvider = Callable[[str], CapabilityState]
MonotonicClock = Callable[[], float]
CaptureAuthorizationIssuer = Callable[[ApplyPlan], object]
CaptureAuthorizationVerifier = Callable[[ApplyPlan, object | None], str]


class _AuthorizableAdapter(Protocol):
    _capture_authorization_verifier: CaptureAuthorizationVerifier | None


def canonical_plan_sha256(plan: ApplyPlan) -> str:
    """Return the canonical SHA-256 digest for an immutable apply plan."""
    payload = json.dumps(asdict(plan), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _private_plan_copy(plan: ApplyPlan) -> ApplyPlan:
    """Revalidate an exact, recursively independent plan for a trust-boundary handoff."""
    if not isinstance(plan, ApplyPlan):
        raise TypeError("plan must be an ApplyPlan")
    return ApplyPlan(**asdict(copy.deepcopy(plan)))


@dataclass(frozen=True)
class _PendingConfirmation:
    token: str
    plan_digest: str
    display_id: str
    issued_at: float
    expires_at: float


def _install_capture_authorization_gate(adapter: DisplayStateAdapter) -> CaptureAuthorizationIssuer | None:
    """Bind an all-or-nothing one-use gate without exposing minting hooks on the adapter.

    This is an in-process misuse boundary. Code with arbitrary Python reflection is
    part of the trusted process and can mutate private state; it is not a security
    principal separated from the coordinator.
    """
    marker = object()
    current = getattr(adapter, "_capture_authorization_verifier", marker)
    if current is marker:
        return None
    if current is not None:
        raise RuntimeError("display adapter is already bound to an actuation coordinator")

    gate_lock = threading.Lock()
    pending: tuple[object, str] | None = None

    def issue(plan: ApplyPlan) -> object:
        nonlocal pending
        token = object()
        plan_digest = canonical_plan_sha256(plan)
        with gate_lock:
            pending = (token, plan_digest)
        return token

    def verify(plan: ApplyPlan, authorization: object | None) -> str:
        nonlocal pending
        with gate_lock:
            expected = pending
            if expected is None or authorization is not expected[0]:
                recognized = False
            else:
                pending = None
                recognized = True
        if not recognized:
            raise PermissionError("Windows display capture requires one-use coordinator authorization")
        if expected is None:
            raise AssertionError("recognized capture authorization had no pending state")
        actual_digest = canonical_plan_sha256(plan)
        if not secrets.compare_digest(expected[1], actual_digest):
            raise PermissionError("capture authorization belongs to a different plan")
        return expected[1]

    cast(_AuthorizableAdapter, adapter)._capture_authorization_verifier = verify
    return issue


class ActuationCoordinator:
    """Issue one expiring confirmation and revalidate capabilities before capture."""

    def __init__(
        self,
        adapter: DisplayStateAdapter,
        capability_provider: CapabilityProvider,
        *,
        confirmation_ttl_seconds: float = 120.0,
        clock: MonotonicClock = time.monotonic,
    ) -> None:
        if not callable(capability_provider):
            raise TypeError("capability_provider must be callable")
        if isinstance(confirmation_ttl_seconds, bool) or not isinstance(confirmation_ttl_seconds, (int, float)):
            raise TypeError("confirmation_ttl_seconds must be a finite positive number")
        ttl = float(confirmation_ttl_seconds)
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("confirmation_ttl_seconds must be a finite positive number")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._adapter = adapter
        self._capability_provider = capability_provider
        self._confirmation_ttl_seconds = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._apply_lock = threading.Lock()
        self._pending: _PendingConfirmation | None = None
        self._capture_authorization_issuer = _install_capture_authorization_gate(adapter)

    def _read_clock(self, *, not_before: float | None = None) -> float:
        sample = self._clock()
        if isinstance(sample, bool) or not isinstance(sample, (int, float)):
            raise TypeError("clock must return a finite real number")
        value = float(sample)
        if not math.isfinite(value):
            raise ValueError("clock must return a finite real number")
        if not_before is not None and value < not_before:
            raise ValueError("clock moved backward during confirmation")
        return value

    def _capabilities_for(self, plan: ApplyPlan) -> CapabilityState:
        capabilities = self._capability_provider(plan.display_id)
        if not isinstance(capabilities, CapabilityState):
            raise TypeError("capability_provider must return CapabilityState")
        capabilities.validate(plan)
        return capabilities

    def _validate_capabilities_without_plan_mutation(self, plan: ApplyPlan, expected_digest: str) -> None:
        probe = _private_plan_copy(plan)
        self._capabilities_for(probe)
        if not secrets.compare_digest(canonical_plan_sha256(probe), expected_digest):
            raise PermissionError("capability validation mutated the apply plan")

    @staticmethod
    def _require_unchanged_submission(plan: ApplyPlan, expected_digest: str) -> None:
        current = _private_plan_copy(plan)
        if not secrets.compare_digest(canonical_plan_sha256(current), expected_digest):
            raise PermissionError("submitted apply plan changed during capability validation")

    def preview(self, plan: ApplyPlan) -> str:
        with self._lock:
            self._pending = None
            sealed_plan = _private_plan_copy(plan)
            plan_digest = canonical_plan_sha256(sealed_plan)
            self._validate_capabilities_without_plan_mutation(sealed_plan, plan_digest)
            self._require_unchanged_submission(plan, plan_digest)
            issued_at = self._read_clock()
            expires_at = issued_at + self._confirmation_ttl_seconds
            if not math.isfinite(expires_at):
                raise ValueError("confirmation expiry overflows the finite clock domain")
            token = secrets.token_urlsafe(32)
            self._pending = _PendingConfirmation(
                token=token,
                plan_digest=plan_digest,
                display_id=sealed_plan.display_id,
                issued_at=issued_at,
                expires_at=expires_at,
            )
            return token

    def invalidate_confirmation(self) -> None:
        """Discard any outstanding confirmation without consuming a token.

        Called when the plan behind a confirmation changed or the operator
        stepped back. Dropping the pending record here means a token issued for
        the old plan can never be redeemed, so a stale confirmation cannot
        authorize an apply the operator did not see.
        """
        with self._lock:
            self._pending = None

    def apply(self, plan: ApplyPlan, token: str, *, confirmed: bool) -> ApplyReceipt:
        with self._apply_lock:
            confirmed_plan = _private_plan_copy(plan)
            confirmed_digest = canonical_plan_sha256(confirmed_plan)
            with self._lock:
                pending = self._pending
                if pending is None or not secrets.compare_digest(pending.token, token):
                    raise PermissionError("confirmation token is unknown or consumed")
                self._pending = None
                if self._read_clock(not_before=pending.issued_at) >= pending.expires_at:
                    raise PermissionError("confirmation token is expired and consumed")
                if confirmed is not True:
                    raise PermissionError("explicit confirmation was declined and the token is consumed")
                if pending.display_id != confirmed_plan.display_id or not secrets.compare_digest(
                    pending.plan_digest, confirmed_digest
                ):
                    raise PermissionError("confirmation token is bound to a different plan and is consumed")

            self._validate_capabilities_without_plan_mutation(confirmed_plan, confirmed_digest)
            self._require_unchanged_submission(plan, confirmed_digest)
            authorized_plan = _private_plan_copy(confirmed_plan)
            if not secrets.compare_digest(canonical_plan_sha256(authorized_plan), confirmed_digest):
                raise PermissionError("authorized apply plan changed before capture")
            authorization = (
                self._capture_authorization_issuer(authorized_plan) if self._capture_authorization_issuer else None
            )
            return _apply_confirmed_with_best_effort_recovery(
                self._adapter,
                authorized_plan,
                authorization=authorization,
            )
