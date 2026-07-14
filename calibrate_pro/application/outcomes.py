"""Typed action outcomes and the diagnostic action boundary."""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, Literal, Protocol, TypeAlias, TypeVar, cast
from uuid import uuid4

from calibrate_pro import __version__
from calibrate_pro.application.actions import ActionClassification, ActionRegistry
from calibrate_pro.application.journal import JournalRecord, JournalSink
from calibrate_pro.workflow import WorkflowStage

T = TypeVar("T")
EffectState = Literal["none", "local_write_published", "fake_apply_attempted"]


@dataclass(frozen=True)
class ActionSuccess(Generic[T]):
    action_id: str
    correlation_id: str
    stage: WorkflowStage
    value: T


@dataclass(frozen=True)
class ActionError:
    action_id: str
    code: str
    summary: str
    retryable: bool
    next_action: str | None
    stage: WorkflowStage
    category: str
    correlation_id: str
    effect_state: EffectState
    published_artifact: tuple[str, str] | None
    apply_phase_flags: tuple[tuple[str, bool], ...]
    recovery_guarantee: str | None


ActionOutcome: TypeAlias = ActionSuccess[T] | ActionError


class CorrelationIdFactory(Protocol):
    def __call__(self) -> str: ...


class ActionFailure(Exception):
    """A known application failure with a stable user-safe error contract."""

    def __init__(
        self,
        *,
        code: str,
        summary: str,
        retryable: bool,
        next_action: str | None,
        category: str,
        effect_state: EffectState = "none",
        published_artifact: tuple[str, str] | None = None,
        apply_phase_flags: tuple[tuple[str, bool], ...] = (),
        recovery_guarantee: str | None = None,
    ) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary
        self.retryable = retryable
        self.next_action = next_action
        self.category = category
        self.effect_state = effect_state
        self.published_artifact = published_artifact
        self.apply_phase_flags = apply_phase_flags
        self.recovery_guarantee = recovery_guarantee


class ActionBoundary:
    """Convert operation and journal failures into truthful typed outcomes."""

    def __init__(
        self,
        correlation_id_factory: CorrelationIdFactory,
        journal_sink: JournalSink,
        registry: ActionRegistry | None = None,
    ) -> None:
        self._correlation_id_factory = correlation_id_factory
        self._journal_sink = journal_sink
        self._registry = registry or ActionRegistry.load_default()

    def invoke(
        self,
        action_id: str,
        stage: WorkflowStage,
        operation: Callable[[], ActionOutcome[T]],
    ) -> ActionOutcome[T]:
        try:
            correlation_id = self._correlation_id_factory()
        except Exception as exc:
            return self._correlation_failure(action_id, stage, type(exc).__name__)
        if type(correlation_id) is not str or not correlation_id:
            return self._correlation_failure(action_id, stage, "InvalidCorrelationId")

        if self._requires_preflight(action_id):
            preflight_failure = self._preflight(action_id, stage, correlation_id)
            if preflight_failure is not None:
                return preflight_failure

        exception_type: str | None = None
        try:
            outcome = operation()
        except ActionFailure as exc:
            exception_type = type(exc).__name__
            outcome = ActionError(
                action_id=action_id,
                code=exc.code,
                summary=exc.summary,
                retryable=exc.retryable,
                next_action=exc.next_action,
                stage=stage,
                category=exc.category,
                correlation_id=correlation_id,
                effect_state=exc.effect_state,
                published_artifact=exc.published_artifact,
                apply_phase_flags=exc.apply_phase_flags,
                recovery_guarantee=exc.recovery_guarantee,
            )
        except Exception as exc:
            exception_type = type(exc).__name__
            outcome = ActionError(
                action_id=action_id,
                code="UNEXPECTED_ACTION_FAILURE",
                summary="The action could not be completed.",
                retryable=False,
                next_action="Review diagnostics before retrying.",
                stage=stage,
                category="unexpected",
                correlation_id=correlation_id,
                effect_state="none",
                published_artifact=None,
                apply_phase_flags=(),
                recovery_guarantee=None,
            )

        if not isinstance(outcome, (ActionSuccess, ActionError)):
            exception_type = "InvalidActionOutcome"
            outcome = ActionError(
                action_id=action_id,
                code="UNEXPECTED_ACTION_FAILURE",
                summary="The action could not be completed.",
                retryable=False,
                next_action="Review diagnostics before retrying.",
                stage=stage,
                category="unexpected",
                correlation_id=correlation_id,
                effect_state="none",
                published_artifact=None,
                apply_phase_flags=(),
                recovery_guarantee=None,
            )
        elif outcome.action_id != action_id or outcome.stage is not stage or outcome.correlation_id != correlation_id:
            exception_type = "InvalidActionOutcomeIdentity"
            outcome = ActionError(
                action_id=action_id,
                code="INVALID_ACTION_OUTCOME",
                summary="The action returned an outcome with inconsistent invocation identity.",
                retryable=False,
                next_action="Review diagnostics before retrying.",
                stage=stage,
                category="contract",
                correlation_id=correlation_id,
                effect_state="none",
                published_artifact=None,
                apply_phase_flags=(),
                recovery_guarantee=None,
            )

        try:
            effect_state, published_artifact, phase_flags, recovery_guarantee = self._effect_evidence(
                action_id,
                outcome,
            )
        except Exception as exc:
            exception_type = type(exc).__name__
            effect_state, published_artifact, phase_flags, recovery_guarantee = self._recover_effect_evidence(
                action_id,
                outcome,
            )
            outcome = self._sync_failure(
                action_id,
                stage,
                correlation_id,
                effect_state,
                published_artifact,
                phase_flags,
                recovery_guarantee,
            )
        try:
            record = self._record(
                action_id=action_id,
                stage=stage,
                correlation_id=correlation_id,
                outcome=outcome,
                exception_type=exception_type,
                published_artifact=published_artifact,
                phase_flags=phase_flags,
                recovery_guarantee=recovery_guarantee,
            )
        except Exception:
            return self._sync_failure(
                action_id,
                stage,
                correlation_id,
                effect_state,
                published_artifact,
                phase_flags,
                recovery_guarantee,
            )
        try:
            sync_outcome = self._journal_sink.append_and_sync(record)
        except Exception:
            return self._sync_failure(
                action_id,
                stage,
                correlation_id,
                effect_state,
                published_artifact,
                phase_flags,
                recovery_guarantee,
            )
        if not isinstance(sync_outcome, ActionSuccess):
            return self._sync_failure(
                action_id,
                stage,
                correlation_id,
                effect_state,
                published_artifact,
                phase_flags,
                recovery_guarantee,
            )
        return cast(ActionOutcome[T], outcome)

    def _correlation_failure(
        self,
        action_id: str,
        stage: WorkflowStage,
        exception_type: str,
    ) -> ActionError:
        correlation_id = _emergency_correlation_id()
        outcome = ActionError(
            action_id=action_id,
            code="CORRELATION_ID_UNAVAILABLE",
            summary="The action could not start because its diagnostic correlation ID was unavailable.",
            retryable=True,
            next_action="Restore the diagnostic correlation provider and retry.",
            stage=stage,
            category="diagnostics",
            correlation_id=correlation_id,
            effect_state="none",
            published_artifact=None,
            apply_phase_flags=(),
            recovery_guarantee=None,
        )
        try:
            record = self._record(
                action_id=action_id,
                stage=stage,
                correlation_id=correlation_id,
                outcome=outcome,
                exception_type=exception_type,
                published_artifact=None,
                phase_flags=(),
                recovery_guarantee=None,
            )
            self._journal_sink.append_and_sync(record)
        except Exception:
            pass
        return outcome

    def _requires_preflight(self, action_id: str) -> bool:
        spec = self._registry._spec_for(action_id)
        if spec is None or not spec.receipt_required:
            return False
        return spec.classification is ActionClassification.LOCAL_FILE_WRITE or action_id == "fake_acceptance.apply"

    def _preflight(self, action_id: str, stage: WorkflowStage, correlation_id: str) -> ActionError | None:
        try:
            outcome = self._journal_sink.preflight(action_id, correlation_id)
        except Exception:
            outcome = None
        if isinstance(outcome, ActionSuccess):
            return None
        return ActionError(
            action_id=action_id,
            code="DIAGNOSTIC_JOURNAL_UNAVAILABLE",
            summary="The diagnostic journal is unavailable, so the action was not started.",
            retryable=True,
            next_action="Restore diagnostic journal access and retry.",
            stage=stage,
            category="diagnostics",
            correlation_id=correlation_id,
            effect_state="none",
            published_artifact=None,
            apply_phase_flags=(),
            recovery_guarantee=None,
        )

    def _effect_evidence(
        self,
        action_id: str,
        outcome: ActionOutcome[Any],
    ) -> tuple[EffectState, tuple[str, str] | None, tuple[tuple[str, bool], ...], str | None]:
        if isinstance(outcome, ActionError):
            return (
                outcome.effect_state,
                outcome.published_artifact,
                outcome.apply_phase_flags,
                outcome.recovery_guarantee,
            )
        value = outcome.value
        if action_id == "fake_acceptance.apply":
            phase_flags = _read_apply_phase_flags(value)
            recovery_guarantee = _read_recovery_guarantee(value)
            return "fake_apply_attempted", None, phase_flags, recovery_guarantee
        spec = self._registry._spec_for(action_id)
        if spec is not None and spec.classification is ActionClassification.LOCAL_FILE_WRITE:
            published_artifact = _read_published_artifact(value)
            if published_artifact is not None:
                return "local_write_published", published_artifact, (), None
        return "none", None, (), None

    def _recover_effect_evidence(
        self,
        action_id: str,
        outcome: ActionOutcome[Any],
    ) -> tuple[EffectState, tuple[str, str] | None, tuple[tuple[str, bool], ...], str | None]:
        """Recover only evidence already present on a typed outcome after extractor failure."""
        if isinstance(outcome, ActionError):
            return (
                outcome.effect_state,
                outcome.published_artifact,
                outcome.apply_phase_flags,
                outcome.recovery_guarantee,
            )
        if action_id == "fake_acceptance.apply":
            try:
                phase_flags = _read_apply_phase_flags(outcome.value)
            except Exception:
                phase_flags = ()
            try:
                recovery_guarantee = _read_recovery_guarantee(outcome.value)
            except Exception:
                recovery_guarantee = None
            return "fake_apply_attempted", None, phase_flags, recovery_guarantee
        try:
            spec = self._registry._spec_for(action_id)
        except Exception:
            return "none", None, (), None
        if spec is not None and spec.classification is ActionClassification.LOCAL_FILE_WRITE:
            try:
                published_artifact = _read_published_artifact(outcome.value)
            except Exception:
                published_artifact = None
            if published_artifact is not None:
                return "local_write_published", published_artifact, (), None
        return "none", None, (), None

    def _record(
        self,
        *,
        action_id: str,
        stage: WorkflowStage,
        correlation_id: str,
        outcome: ActionOutcome[Any],
        exception_type: str | None,
        published_artifact: tuple[str, str] | None,
        phase_flags: tuple[tuple[str, bool], ...],
        recovery_guarantee: str | None,
    ) -> JournalRecord:
        error = outcome if isinstance(outcome, ActionError) else None
        runtime_mode: Literal["source", "frozen", "fake_acceptance"]
        if action_id == "fake_acceptance.apply":
            runtime_mode = "fake_acceptance"
        elif getattr(sys, "frozen", False):
            runtime_mode = "frozen"
        else:
            runtime_mode = "source"
        return JournalRecord(
            timestamp_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            correlation_id=correlation_id,
            product_version=__version__,
            runtime_mode=runtime_mode,
            platform_version=platform.platform(),
            action_id=action_id,
            workflow_stage=stage.value,
            capability_flags=(),
            outcome="failure" if error is not None else "success",
            exception_type=exception_type,
            error_code=error.code if error is not None else None,
            technical_category=error.category if error is not None else None,
            redacted_message=error.summary if error is not None else None,
            display_pseudonym=None,
            plan_sha256=None,
            asset_sha256=(),
            apply_phase_flags=phase_flags,
            recovery_guarantee=recovery_guarantee,
            export_basename=published_artifact[0] if published_artifact is not None else None,
            export_sha256=published_artifact[1] if published_artifact is not None else None,
        )

    @staticmethod
    def _sync_failure(
        action_id: str,
        stage: WorkflowStage,
        correlation_id: str,
        effect_state: EffectState,
        published_artifact: tuple[str, str] | None,
        phase_flags: tuple[tuple[str, bool], ...],
        recovery_guarantee: str | None,
    ) -> ActionError:
        return ActionError(
            action_id=action_id,
            code="ACTION_COMPLETED_DIAGNOSTICS_FAILED",
            summary="The action completed, but its final diagnostic record could not be synchronized.",
            retryable=False,
            next_action="Preserve the reported effect evidence and restore diagnostic journal access.",
            stage=stage,
            category="diagnostics",
            correlation_id=correlation_id,
            effect_state=effect_state,
            published_artifact=published_artifact,
            apply_phase_flags=phase_flags,
            recovery_guarantee=recovery_guarantee,
        )


def _read_published_artifact(value: object) -> tuple[str, str] | None:
    explicit = getattr(value, "published_artifact", None)
    if _is_string_pair(explicit):
        return cast(tuple[str, str], explicit)
    published_path = getattr(value, "published_path", None)
    bundle_sha256 = getattr(value, "bundle_sha256", None)
    basename = getattr(published_path, "name", None)
    if type(basename) is str and basename and type(bundle_sha256) is str and bundle_sha256:
        return basename, bundle_sha256
    return None


def _read_apply_phase_flags(value: object) -> tuple[tuple[str, bool], ...]:
    explicit = getattr(value, "apply_phase_flags", None)
    if _is_phase_flags(explicit):
        return cast(tuple[tuple[str, bool], ...], explicit)
    names = ("captured", "applied", "verified", "restore_attempted", "restored")
    if all(type(getattr(value, name, None)) is bool for name in names):
        return tuple((name, cast(bool, getattr(value, name))) for name in names)
    return ()


def _read_recovery_guarantee(value: object) -> str | None:
    guarantee = getattr(value, "recovery_guarantee", None)
    if type(guarantee) is str and guarantee:
        return guarantee
    enum_value = getattr(guarantee, "value", None)
    if type(enum_value) is str and enum_value:
        return enum_value
    return None


def _is_string_pair(value: object) -> bool:
    return (
        type(value) is tuple
        and len(cast(tuple[object, ...], value)) == 2
        and all(type(item) is str and item for item in cast(tuple[object, ...], value))
    )


def _is_phase_flags(value: object) -> bool:
    if type(value) is not tuple:
        return False
    for item in cast(tuple[object, ...], value):
        if type(item) is not tuple or len(cast(tuple[object, ...], item)) != 2:
            return False
        name, flag = cast(tuple[object, object], item)
        if type(name) is not str or not name or type(flag) is not bool:
            return False
    return True


def _emergency_correlation_id() -> str:
    try:
        return f"correlation-unavailable-{uuid4().hex}"
    except Exception:
        return "correlation-id-unavailable"


__all__ = [
    "ActionBoundary",
    "ActionError",
    "ActionFailure",
    "ActionOutcome",
    "ActionSuccess",
    "CorrelationIdFactory",
]
