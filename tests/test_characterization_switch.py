"""A held session moves between the generic record and an EDID declaration.

The two controls are offered from every characterization the operator chose
themselves, so a choice can be changed without restarting the session. They are
never offered over an instrument run, since replacing a reading with a
description has to be an explicit act. Changing the characterization under a
sealed plan drops the seal, because the plan was built from the other record.

Everything runs over an injected display and detector. No instrument is opened
and no reading of a real display is involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from calibrate_pro.application.actions import ActionDisposition, ActionRegistry
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.outcomes import ActionError
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import SessionState
from calibrate_pro.commands.session import target_action
from calibrate_pro.workflow import CalibrationMethod
from tests.action_context_support import action_context
from tests.session_support import PRESET
from tests.test_edid_session import _measurement
from tests.test_edid_surfaces import (
    USE_EDID,
    USE_GENERIC,
    declared_session,
    refused,
    succeeded,
)

REGISTRY = ActionRegistry.load_default()


def _disposition(state: SessionState, action_id: str) -> ActionDisposition:
    return REGISTRY.resolve(action_id, state.to_context()).disposition


def _sealed(service: FunctionalRecoveryService, state: SessionState, *, choose_method: bool = True) -> str:
    """Take the session to a previewed plan and return the digest it sealed."""
    if choose_method:
        succeeded(service.select_method(CalibrationMethod.SENSORLESS))
    succeeded(service.set_target(target_action(PRESET)))
    succeeded(service.generate())
    succeeded(service.preview())
    assert state.sealed_plan_sha256 is not None
    return state.sealed_plan_sha256


def test_a_held_declaration_can_be_exchanged_for_the_generic_record(tmp_path: Path) -> None:
    service, state = declared_session(tmp_path)
    succeeded(service.use_edid_characterization())
    assert state.characterization_kind is CharacterizationKind.EDID_DECLARED

    assert _disposition(state, USE_GENERIC) is ActionDisposition.ENABLED
    selection = succeeded(service.use_generic_characterization())

    assert selection.characterization_kind is CharacterizationKind.EXPLICIT_GENERIC
    assert state.declared_characterization is None


def test_the_generic_record_can_be_exchanged_for_the_declaration(tmp_path: Path) -> None:
    service, state = declared_session(tmp_path)
    succeeded(service.use_generic_characterization())
    assert state.characterization_kind is CharacterizationKind.EXPLICIT_GENERIC

    assert _disposition(state, USE_EDID) is ActionDisposition.ENABLED
    selection = succeeded(service.use_edid_characterization())

    assert selection.characterization_kind is CharacterizationKind.EDID_DECLARED
    assert state.declared_characterization is not None


def test_the_choice_can_go_back_and_forth_more_than_once(tmp_path: Path) -> None:
    service, state = declared_session(tmp_path)
    for _ in range(2):
        succeeded(service.use_edid_characterization())
        succeeded(service.use_generic_characterization())
    assert state.characterization_kind is CharacterizationKind.EXPLICIT_GENERIC


@pytest.mark.parametrize("to_edid", [True, False])
def test_changing_the_characterization_drops_the_sealed_plan(tmp_path: Path, to_edid: bool) -> None:
    service, state = declared_session(tmp_path)
    succeeded(service.use_generic_characterization() if to_edid else service.use_edid_characterization())
    digest = _sealed(service, state)

    succeeded(service.use_edid_characterization() if to_edid else service.use_generic_characterization())

    assert state.sealed_plan_sha256 is None
    assert state.generated is None
    assert state.confirmation_state == "expired"
    # The held plan is gone too, so a preview cannot revive it.
    assert refused(service.preview()).code == "ACTION_NOT_AVAILABLE"
    assert service._sealed_plan is None

    # A fresh bundle seals a different digest, because it is built from the other record.
    assert _sealed(service, state, choose_method=False) != digest


@pytest.mark.parametrize("action_id", [USE_EDID, USE_GENERIC])
def test_an_instrument_run_is_never_replaced_by_either_control(tmp_path: Path, action_id: str) -> None:
    service, state = declared_session(tmp_path)
    state.record_measurement(_measurement())
    assert state.characterization_kind is CharacterizationKind.MEASURED

    assert _disposition(state, action_id) is ActionDisposition.DISABLED
    call = service.use_edid_characterization if action_id == USE_EDID else service.use_generic_characterization
    error = refused(call())

    assert isinstance(error, ActionError)
    assert error.code == "ACTION_NOT_AVAILABLE"
    assert state.characterization_kind is CharacterizationKind.MEASURED
    assert state.measured_characterization is not None


@pytest.mark.parametrize("action_id", [USE_EDID, USE_GENERIC])
def test_a_matched_record_is_still_not_overridden(action_id: str) -> None:
    resolved = REGISTRY.resolve(action_id, action_context(characterization_kind=CharacterizationKind.MATCHED))
    assert resolved.disposition is ActionDisposition.DISABLED
