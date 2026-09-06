"""Every action the manifest gives a surface reaches the operator, or is recorded here.

The per-page tests read one direction: every control on a page stands for a
declared action. Nothing read the other direction, and that is the direction a
gap hides in. An action can be declared, resolved, journalled, covered by its
own resolver tests, and still have no control anywhere, which is what happened
to ``display.characterization.use_generic``: a display outside the bundled
panel database was adopted uncharacterized, and the one action that could
characterize it was never drawn, so that display reached the Calibrate page and
was refused by every control on it.

A static scan cannot answer this. Eight of the ``bind`` calls in the package
pass an action id that is computed rather than written, so the set of bound
actions exists only at runtime. The window and both dialogs are built here and
asked what they bound.

What is left over is not a failure on its own. Three kinds of surface legitimately
have no bound control, and each one is written down below with the reason and
checked against the manifest or the source, so an entry cannot quietly become a
stale excuse for a control somebody deleted.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from importlib import resources
from pathlib import Path

import pytest

from tests.conftest import active_window
from tests.fake_acceptance_support import PRESET_ID, journal_records

#: Actions the session hides, so a window that drew a control for one would be
#: offering work the manifest declares unspecified. Each is checked below to be
#: hidden by the manifest rather than merely absent from the window.
HIDDEN_BY_THE_SESSION: dict[str, str] = {
    "measurement.live.toggle": "The live readout is hidden until its workflow is specified.",
    "settings.argyll_path": "The settings actions are hidden pending their storage contract.",
    "settings.default_target": "The settings actions are hidden pending their storage contract.",
    "settings.minimize_to_tray": "The settings actions are hidden pending their storage contract.",
    "settings.oled_automation": "The settings actions are hidden pending their storage contract.",
    "settings.panel_profiles_path": "The settings actions are hidden pending their storage contract.",
    "settings.per_app.enabled": "The settings actions are hidden pending their storage contract.",
    "settings.per_app.rules": "The settings actions are hidden pending their storage contract.",
    "settings.startup": "The settings actions are hidden pending their storage contract.",
}

#: Actions the window performs from something Qt gives it no control for: a
#: shortcut, a tray activation, a card signal, and a button on a modal dialog
#: that is built and destroyed inside one call.
PERFORMED_WITHOUT_A_CONTROL: dict[str, str] = {
    "onboarding.complete": "Performed when the welcome dialog closes.",
    "window.hide_or_minimize": "Performed by the Escape shortcut.",
    "window.toggle_visibility": "Performed when the tray icon is activated.",
    "calibration.open_for_display": "Performed when a display card asks for the Calibrate page.",
}

#: Declared, open to the session, and drawn nowhere. This is an honest null
#: rather than a policy decision, and the checks below hold it to that: an entry
#: here must not be hidden by the manifest, and must not be bound anywhere.
UNPRESENTED: dict[str, str] = {
    "calibration.target.custom_cct": "No window offers a custom correlated colour temperature.",
}

#: The modules allowed to construct a binder. Each one owns a surface with its
#: own lifetime: the window, and the two dialogs whose controls must not stay
#: registered after the dialog holding them is destroyed.
BINDER_MODULES = frozenset(
    {
        "calibrate_pro/gui/add_display.py",
        "calibrate_pro/gui/app.py",
        "calibrate_pro/gui/plan_dialog.py",
    }
)


def manifest() -> dict[str, dict[str, object]]:
    payload = resources.files("calibrate_pro").joinpath("resources", "action-capabilities.json").read_bytes()
    document = json.loads(payload.decode("utf-8"))
    return {entry["action_id"]: entry for entry in document["actions"]}


def declared_surfaces() -> set[str]:
    """Every action the manifest says an interface is supposed to present."""
    return {action_id for action_id, entry in manifest().items() if entry["surfaces"]}


def recorded() -> dict[str, str]:
    return {**HIDDEN_BY_THE_SESSION, **PERFORMED_WITHOUT_A_CONTROL, **UNPRESENTED}


def package_root() -> Path:
    import calibrate_pro

    return Path(calibrate_pro.__file__).parent


@pytest.fixture
def surfaces(qapp: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[tuple[object, set[str]]]:
    """Build every surface that binds anything, and collect what it bound.

    The tray is made available because two entries exist only on a machine that
    has one, and the offscreen platform these tests run on reports none. Both
    dialogs are opened the way the window opens them, which is also the only way
    to reach the binders they own.
    """
    from PySide6.QtWidgets import QSystemTrayIcon

    from calibrate_pro.application.outcomes import ActionSuccess
    from calibrate_pro.workflow import CalibrationMethod

    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    with active_window(monkeypatch, tmp_path) as window:
        bound = {binding.action_id for binding in window._binder.bindings}

        window.dashboard.add_display_btn.click()
        add_dialog = window._add_display_dialog
        assert add_dialog is not None, "the profile dialog did not open"
        bound |= {binding.action_id for binding in add_dialog._binder.bindings}
        add_dialog.close()

        for step in (
            lambda: window.service.select_method(CalibrationMethod.SENSORLESS),
            lambda: window.service.set_target(PRESET_ID),
            window.service.generate,
        ):
            assert isinstance(step(), ActionSuccess), "the session stopped before a plan was sealed"
        window._binder.refresh()
        window.calibrate_page._btn_preview.click()
        plan_dialog = window._plan_dialog
        assert plan_dialog is not None, "the plan dialog did not open"
        bound |= {binding.action_id for binding in plan_dialog._binder.bindings}
        plan_dialog.reject()

        yield window, bound


def test_every_declared_surface_is_presented_or_recorded(surfaces: tuple[object, set[str]]) -> None:
    """The gate. A declared surface with no control and no reason fails here."""
    _window, bound = surfaces

    assert declared_surfaces() - bound == set(recorded())


def test_no_control_stands_for_an_action_the_manifest_gives_no_surface(surfaces: tuple[object, set[str]]) -> None:
    """A control for an undeclared surface is a claim the manifest never made."""
    _window, bound = surfaces
    declared = manifest()

    for action_id in sorted(bound):
        assert action_id in declared, f"{action_id} is bound and undeclared"
        assert declared[action_id]["surfaces"], f"{action_id} is bound and declares no surface"


def test_each_action_is_recorded_under_exactly_one_reason() -> None:
    """One action, one reason. Two would let a stale entry cover a real gap."""
    tables = (HIDDEN_BY_THE_SESSION, PERFORMED_WITHOUT_A_CONTROL, UNPRESENTED)
    counted = sum(len(table) for table in tables)

    assert counted == len(recorded())


def test_the_hidden_actions_are_hidden_by_the_manifest(surfaces: tuple[object, set[str]]) -> None:
    """A window cannot record an action as hidden that the session would offer."""
    _window, _bound = surfaces
    declared = manifest()

    for action_id in sorted(HIDDEN_BY_THE_SESSION):
        assert declared[action_id]["source_policy"] == "hidden", action_id
        assert declared[action_id]["unavailable_disposition"] == "hidden", action_id


def perform_ui_arguments(path: Path) -> set[str]:
    """Collect the action ids a module names in a ``perform_ui`` call.

    Read structurally rather than by searching the text, so an id that appears
    in a comment or a docstring cannot stand in for a call that performs it.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else None
        if name not in {"perform_ui", "_perform_ui"} or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
    return found


def test_the_actions_with_no_control_are_named_by_a_call_that_performs_them() -> None:
    """Each recorded performer is a real call site rather than an intention."""
    performed = perform_ui_arguments(package_root() / "gui" / "app.py")

    assert {
        "onboarding.complete",
        "window.hide_or_minimize",
        "window.toggle_visibility",
    } <= performed


def test_asking_a_card_for_the_calibrate_page_performs_the_declared_action(
    surfaces: tuple[object, set[str]],
) -> None:
    """The one performer that is cheap to drive is driven rather than read.

    A display card carries no bound control. It emits the index it stands for,
    and the window turns that into the action the manifest declares, so the
    journal records the operator asking for the page.
    """
    window, _bound = surfaces
    before = len(journal_records(window.session_root))

    window._navigate_to_calibrate(0)

    performed = [record["action_id"] for record in journal_records(window.session_root)]
    assert performed[before:] == ["calibration.open_for_display"]


def test_the_write_the_page_leads_to_carries_both_a_control_and_its_reason(
    surfaces: tuple[object, set[str]],
) -> None:
    """The apply is a button now, and a refused one still says what it waits for.

    This page used to draw the transaction as a sentence and no control, which
    left an operator staging values with nothing to write them. The button is
    bound, so the check is the pair: a control the binder knows about, and a
    status line still quoting the session rather than composing its own excuse
    for why the button is off.
    """
    from calibrate_pro.gui.pages.ddc_control import DDC_TRANSACTION

    window, bound = surfaces
    assert DDC_TRANSACTION in bound

    resolved = window._binder.disposition_of(DDC_TRANSACTION)
    assert window.ddc._status_label.text() == resolved.reason
    assert resolved.reason


def test_an_unpresented_action_is_a_null_rather_than_a_policy(surfaces: tuple[object, set[str]]) -> None:
    """Nothing may hide behind this table that the manifest already closes.

    An action the session hides belongs in the hidden table, where the manifest
    is checked. An entry here is a surface the session would answer for and no
    window draws, which is a gap being reported rather than explained away.
    """
    _window, bound = surfaces
    declared = manifest()

    for action_id in sorted(UNPRESENTED):
        assert declared[action_id]["source_policy"] != "hidden", action_id
        assert declared[action_id]["surfaces"], action_id
        assert action_id not in bound, action_id


def binder_construction_sites() -> set[str]:
    """Find every module in the package that builds a binder of its own."""
    root = package_root()
    sites: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "ActionBinder":
                sites.add(path.relative_to(root.parent).as_posix())
    return sites


def test_only_the_known_surfaces_own_a_binder() -> None:
    """A new binder is a new surface, and this file has not been asked about it.

    The gate reads the binders it knows how to build. A module that quietly
    stands up its own would present actions this test would then count as
    missing, or worse, would keep controls registered after the surface holding
    them was destroyed.
    """
    assert binder_construction_sites() == set(BINDER_MODULES)
