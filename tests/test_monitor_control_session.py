"""What a session holds while it changes a display's own controls.

The transaction layer is judged elsewhere by what a panel reads at. What is
judged here is the session around it: which display a reading belongs to, what
staging is allowed to be checked against, and what a write to the panel makes
untrue everywhere else.

That last one is the reason this lane invalidates rather than only reports.
Brightness and the channel gains sit upstream of every table this build can
load, so a plan sealed before a write describes a drive state the display no
longer holds. A session that kept the seal would offer an operator a plan built
for a panel that has moved underneath it, and the plan would still verify.
"""

from __future__ import annotations

from pathlib import Path

from calibrate_pro.application.monitor_controls import BRIGHTNESS, CONTRAST, RED_GAIN
from calibrate_pro.application.outcomes import ActionError, ActionOutcome, ActionSuccess
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.workflow import CalibrationMethod
from tests.monitor_control_support import DISPLAY_ID, INSTRUMENT, FakePanel, build_monitor_service

PRESET_ID = "calibration.preset.srgb_web"

BRIGHTNESS_ACTION = "ddc.stage.brightness"
CONTRAST_ACTION = "ddc.stage.contrast"
RED_GAIN_ACTION = "ddc.stage.red_gain"


def succeeded(outcome: ActionOutcome[object]) -> object:
    assert isinstance(outcome, ActionSuccess), f"expected a success, got {outcome}"
    return outcome.value


def refused(outcome: ActionOutcome[object]) -> ActionError:
    assert isinstance(outcome, ActionError), f"expected a refusal, got {outcome}"
    return outcome


def read_display(service: FunctionalRecoveryService) -> object:
    """Detect the display and read its controls, which is where the lane starts."""
    succeeded(service.detect())
    return succeeded(service.read_monitor_controls())


def seal_a_plan(service: FunctionalRecoveryService) -> str:
    """Drive the session to a previewed plan and hand back its digest."""
    succeeded(service.select_method(CalibrationMethod.SENSORLESS))
    succeeded(service.set_target(PRESET_ID))
    succeeded(service.generate())
    preview = succeeded(service.preview())
    return str(preview.plan_sha256)


# -- the reading -----------------------------------------------------------------


def test_the_reading_is_taken_from_the_display_and_held_for_the_rest_of_the_lane(tmp_path: Path) -> None:
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)

    reading = read_display(service)

    assert reading.display_id == DISPLAY_ID
    assert reading.instrument == INSTRUMENT
    assert reading.control(BRIGHTNESS).current == 75
    assert succeeded(service.stage_monitor_control(BRIGHTNESS_ACTION, 40)).current == 75


def test_a_display_with_ddc_switched_off_in_its_own_menu_is_offered_no_reading(tmp_path: Path) -> None:
    """The route is wired and the capability is closed, which is a real machine.

    Nothing about this panel is broken. DDC/CI is a setting a display carries in
    its own menu, and a session that offered a reading it could not take would
    be refused one call later with the port already open.
    """
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel, ddc=False)
    succeeded(service.detect())

    refused(service.read_monitor_controls())

    assert panel.opens == 0
    assert panel.calls == []


def test_a_session_with_no_control_port_wired_reads_nothing(tmp_path: Path) -> None:
    service = build_monitor_service(tmp_path, None)
    succeeded(service.detect())

    refused(service.read_monitor_controls())


def test_a_display_that_stops_answering_midway_is_a_refusal_and_not_a_crash(tmp_path: Path) -> None:
    """A control that answered the reading and not the write is retryable.

    A DDC bus that has gone quiet is a state of the machine rather than a defect
    in the program, so it arrives as a refusal an operator can act on and try
    again, and the set stops before anything is written.
    """
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)
    read_display(service)
    succeeded(service.stage_monitor_control(BRIGHTNESS_ACTION, 40))
    panel.refuse_read(BRIGHTNESS, "the monitor is not responding", after=1)

    error = refused(service.apply_monitor_controls())

    assert error.retryable
    assert "not responding" in error.summary
    assert panel.writes() == []


# -- staging ---------------------------------------------------------------------


def test_a_session_that_has_not_read_the_display_stages_nothing(tmp_path: Path) -> None:
    """Every staged value is checked against a range the display reported."""
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)
    succeeded(service.detect())

    refused(service.stage_monitor_control(BRIGHTNESS_ACTION, 40))

    assert panel.calls == []


def test_staging_a_control_the_display_did_not_answer_is_refused(tmp_path: Path) -> None:
    panel = FakePanel()
    panel.refuse_read(RED_GAIN, "unsupported VCP code")
    service = build_monitor_service(tmp_path, panel)
    read_display(service)

    refused(service.stage_monitor_control(RED_GAIN_ACTION, 200))

    assert succeeded(service.stage_monitor_control(BRIGHTNESS_ACTION, 40)).requested == 40


def test_staging_a_value_past_the_range_the_display_reported_is_refused(tmp_path: Path) -> None:
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)
    read_display(service)

    error = refused(service.stage_monitor_control(BRIGHTNESS_ACTION, 150))

    assert "0 through 100" in error.summary
    assert panel.writes() == []


def test_staging_touches_no_display(tmp_path: Path) -> None:
    """The point of staging is that a set of controls is written as one."""
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)
    read_display(service)
    opened = panel.opens

    succeeded(service.stage_monitor_control(BRIGHTNESS_ACTION, 40))
    succeeded(service.stage_monitor_control(CONTRAST_ACTION, 60))

    assert panel.writes() == []
    assert panel.opens == opened


# -- writing ---------------------------------------------------------------------


def test_an_apply_with_nothing_staged_is_refused(tmp_path: Path) -> None:
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)
    read_display(service)

    refused(service.apply_monitor_controls())

    assert panel.writes() == []


def test_a_staged_set_reaches_the_display_as_one_transaction(tmp_path: Path) -> None:
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)
    read_display(service)
    succeeded(service.stage_monitor_control(BRIGHTNESS_ACTION, 40))
    succeeded(service.stage_monitor_control(CONTRAST_ACTION, 60))

    transaction = succeeded(service.apply_monitor_controls())

    assert transaction.accepted
    assert panel.written_codes() == [BRIGHTNESS, CONTRAST]
    assert (panel.values[BRIGHTNESS], panel.values[CONTRAST]) == (40, 60)


def test_a_write_leaves_the_session_with_nothing_staged_and_nothing_read(tmp_path: Path) -> None:
    """Every value in the reading was read before the write that moved them."""
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)
    read_display(service)
    succeeded(service.stage_monitor_control(BRIGHTNESS_ACTION, 40))
    succeeded(service.apply_monitor_controls())

    refused(service.apply_monitor_controls())
    refused(service.stage_monitor_control(BRIGHTNESS_ACTION, 50))


def test_the_port_is_closed_however_the_transaction_ends(tmp_path: Path) -> None:
    """Windows hands out a physical monitor handle and expects it back.

    A leaked handle is not visible in the run that leaked it. It shows up as a
    display that cannot be opened at all next time, so the count is checked on
    the path that raised as well as the one that worked.
    """
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)
    read_display(service)
    assert panel.opens == panel.closes == 1

    succeeded(service.stage_monitor_control(BRIGHTNESS_ACTION, 40))
    panel.refuse_read(BRIGHTNESS, "the monitor is not responding", after=1)
    refused(service.apply_monitor_controls())

    assert panel.opens == panel.closes == 2


def test_a_write_the_display_refused_is_reported_rather_than_raised(tmp_path: Path) -> None:
    """A set that failed partway is the case with the most to tell the operator.

    Refusing here would carry a sentence and lose the transaction, and the
    transaction is what says which codes were written and that they went back.
    So the failure travels inside the result, and only a display that would not
    be read at all is a refusal.
    """
    panel = FakePanel()
    panel.refuse_write(CONTRAST, "the display is busy")
    service = build_monitor_service(tmp_path, panel)
    read_display(service)
    succeeded(service.stage_monitor_control(BRIGHTNESS_ACTION, 40))
    succeeded(service.stage_monitor_control(CONTRAST_ACTION, 60))

    transaction = succeeded(service.apply_monitor_controls())

    assert not transaction.accepted
    assert transaction.restored == (BRIGHTNESS,)
    assert panel.values[BRIGHTNESS] == 75


def test_a_write_to_the_panel_expires_a_plan_sealed_before_it(tmp_path: Path) -> None:
    """The seal covers a drive state the write has just moved.

    A plan is built from the panel's characterization at the brightness and
    gains it was holding. Writing those controls does not make the plan wrong in
    a way the plan can detect: it verifies against itself either way. So the
    seal is dropped, and an operator is asked to build the plan again against
    the display as it now stands.
    """
    panel = FakePanel()
    service = build_monitor_service(tmp_path, panel)
    read_display(service)
    assert seal_a_plan(service)
    succeeded(service.stage_monitor_control(BRIGHTNESS_ACTION, 40))

    succeeded(service.apply_monitor_controls())

    refused(service.confirm_plan())
    refused(service.verify())


def test_a_restore_expires_the_plan_the_same_way_a_write_does(tmp_path: Path) -> None:
    """A display asked to choose its own values has moved as surely as one written to."""
    panel = FakePanel()
    panel.restores_to(brightness=50)
    service = build_monitor_service(tmp_path, panel)
    read_display(service)
    assert seal_a_plan(service)

    restore = succeeded(service.restore_monitor_defaults())

    assert restore.moved == ("Brightness 75 to 50",)
    refused(service.confirm_plan())


def test_a_restore_leaves_the_session_holding_the_reading_taken_after_it(tmp_path: Path) -> None:
    """The second reading is the display's own account of where it landed."""
    panel = FakePanel()
    panel.restores_to(brightness=50)
    service = build_monitor_service(tmp_path, panel)
    read_display(service)

    succeeded(service.restore_monitor_defaults())

    assert succeeded(service.stage_monitor_control(BRIGHTNESS_ACTION, 40)).current == 50
