"""Positive frozen-command and module-allowlist release gates."""

from __future__ import annotations

import ast
import json
import sys
from functools import cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.frozen_closure import (
    PACKAGE,
    blocked_modules,
    reachable_modules,
    spec_excludes,
    unguarded_importers,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "calibrate-pro.spec"

EXCLUDED_QT_IMPORTS = {
    "PySide6.QtDataVisualization",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "qtpy.QtDataVisualization",
}

EXPECTED_FEATURES = {
    "schema_version": 2,
    "commands": [
        "ddc-calibrate",
        "ddc-info",
        "detect",
        "diagnostics",
        "doctor",
        "generate-profiles",
        "gui",
        "hdr",
        "install-profile",
        "profiles",
        "remove-profile",
        "restore-profiles",
        "status",
        "switch-profile",
        "system-profiles",
        "verify",
    ],
    "developer_only_commands": [
        "hdr-status",
        "info",
        "list-panels",
        "list-targets",
        "mcp",
        "plugins",
        "tray",
    ],
    "declined_commands": [
        "auto",
        "calibrate",
        "disable-startup",
        "enable-startup",
        "export-panel",
        "import-panel",
        "match",
        "native-calibrate",
        "patterns",
        "refine",
        "restore",
        "uniformity",
    ],
}


def test_frozen_features_are_exact_and_developer_only_commands_are_explicit() -> None:
    data = json.loads((ROOT / "packaging/frozen-features.json").read_text(encoding="utf-8"))
    assert data == EXPECTED_FEATURES


def test_the_shipped_command_policy_is_the_dispatcher_the_binary_runs() -> None:
    """The file the build is gated on has to describe the dispatcher it ships.

    Both halves are read back. A command listed as shipped that the dispatcher
    does not route reaches an operator as an unknown command, and a name listed
    as developer-only that the dispatcher never refuses reaches them the same
    way, with a sentence about a wheel replaced by one about a typo.
    """
    from calibrate_pro import frozen_main

    features = json.loads((ROOT / "packaging/frozen-features.json").read_text(encoding="utf-8"))

    assert sorted({*frozen_main._COMMANDS, *frozen_main._SESSION_COMMANDS}) == features["commands"]
    assert sorted(frozen_main._DEVELOPER_ONLY_COMMANDS) == features["developer_only_commands"]
    assert sorted(frozen_main._DECLINED_COMMANDS) == features["declined_commands"]


def test_frozen_module_policy_is_literal_and_fail_closed() -> None:
    data = json.loads((ROOT / "packaging/frozen-modules.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["default"] == "reject"
    assert data["distribution_roots"] == [
        "PyInstaller",
        "PySide6",
        "build_color",
        "build_ui",
        "hid",
        "numpy",
        "packaging",
        "qtpy",
        "scipy",
        "shiboken6",
    ]
    assert data["first_party_exact"] == sorted(set(data["first_party_exact"]))
    assert data["optional_first_party_exact"] == sorted(set(data["optional_first_party_exact"]))
    assert all("*" not in name for name in data["first_party_exact"])
    assert all("*" not in name for name in data["optional_first_party_exact"])
    assert {
        "calibrate_pro.frozen_main",
        "calibrate_pro.commands.doctor",
        "calibrate_pro.commands.gui",
        "calibrate_pro.commands.hdr",
        "calibrate_pro.commands.session",
        "calibrate_pro.commands.session_args",
        "calibrate_pro.gui.pages.ddc_control",
        "calibrate_pro.gui.pages.profiles",
        "calibrate_pro.gui.pages.settings",
    } <= set(data["first_party_exact"])


def test_approved_first_party_modules_do_not_import_excluded_qt_surfaces() -> None:
    data = json.loads((ROOT / "packaging/frozen-modules.json").read_text(encoding="utf-8"))
    approved = [*data["first_party_exact"], *data["optional_first_party_exact"]]
    offenders: list[str] = []

    for module_name in approved:
        relative = Path(*module_name.split("."))
        source_path = ROOT / relative.with_suffix(".py")
        if not source_path.is_file():
            source_path = ROOT / relative / "__init__.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        for imported_name in imported:
            if any(
                imported_name == excluded or imported_name.startswith(excluded + ".")
                for excluded in EXCLUDED_QT_IMPORTS
            ):
                offenders.append(f"{module_name}: {imported_name}")

    assert offenders == []


@cache
def frozen_closure() -> tuple[frozenset[str], frozenset[str]]:
    """What the frozen entry point reaches, and which of it the build refuses.

    Read once. Every module in the closure is parsed to answer this, and three
    gates ask about the same two sets.

    The walk starts at the one module the spec hands PyInstaller, which is the
    whole of what a shipped binary can begin from. Naming the command modules
    alongside it would read as thorough and measure less: a name that is not a
    module is not a module the walker can open, so a command whose module the
    dispatcher no longer reaches would drop out of the closure quietly.
    """
    reachable = reachable_modules(ROOT, [f"{PACKAGE}.frozen_main"])
    return frozenset(reachable), frozenset(blocked_modules(ROOT, reachable, spec_excludes(SPEC)))


def test_the_closure_follows_the_imports_a_running_build_performs() -> None:
    """The check on the checks: a walk that found less would pass the gate below.

    Each of these is reached a different way. The GUI window is imported inside
    a handler that reports a missing PySide6, the service beneath it only from
    that window, and the doctor command is never written as an import statement
    at all, only as a string in the dispatcher's table. A walker that stopped at
    any of the three would report a smaller closure, and a smaller closure is
    one the allowlist satisfies without covering what the build imports.
    """
    reachable, _ = frozen_closure()

    assert {
        f"{PACKAGE}.commands.doctor",
        f"{PACKAGE}.gui.app",
        f"{PACKAGE}.application.service",
    } <= reachable
    assert len(reachable) > 100


def test_the_allowlist_names_every_module_the_frozen_entry_points_can_reach() -> None:
    """An unlisted module is not left out of the build, it is refused by it.

    The spec turns every first-party module absent from this policy into a
    PyInstaller exclude, so a reachable module missing here fails at the import
    that pulls it in, at runtime, in a shipped binary. Nothing is frozen to find
    that out: the closure is read from the source tree the build is made of.
    """
    policy = json.loads((ROOT / "packaging/frozen-modules.json").read_text(encoding="utf-8"))
    approved = {*policy["first_party_exact"], *policy["optional_first_party_exact"]}
    reachable, blocked = frozen_closure()

    assert sorted(reachable - blocked - approved) == []


def test_the_one_module_this_build_cannot_import_is_the_tkinter_pattern_viewer() -> None:
    """Blockedness belongs to the module, not to the guard around its call site.

    ``patterns.display`` imports tkinter when it is imported, and the spec
    excludes tkinter, so the frozen build cannot supply it however carefully it
    is called. Naming it here is what lets the gate above demand everything else
    while this one stays outside the allowlist.
    """
    _, blocked = frozen_closure()

    assert set(blocked) == {f"{PACKAGE}.patterns", f"{PACKAGE}.patterns.display"}


def test_a_module_the_build_cannot_supply_is_only_imported_behind_a_handler() -> None:
    """The refusal has to be catchable, or it arrives as a traceback on launch."""
    reachable, blocked = frozen_closure()

    assert unguarded_importers(ROOT, set(reachable), set(blocked)) == {}


def test_frozen_dispatcher_imports_only_the_selected_shared_command(monkeypatch) -> None:
    from calibrate_pro import frozen_main

    calls: list[tuple[str, object]] = []

    def fake_import(name: str) -> object:
        calls.append(("import", name))
        return SimpleNamespace(run=lambda args: calls.append(("run", args)) or 17)

    monkeypatch.setattr(frozen_main, "import_module", fake_import)
    assert frozen_main.main(["doctor", "--json"], program="CalibrateProCLI.exe") == 17
    assert calls == [
        ("import", "calibrate_pro.commands.doctor"),
        ("run", ["--json"]),
    ]


def test_frozen_dispatcher_hands_a_session_command_the_arguments_it_parsed(monkeypatch) -> None:
    """The shipped binary reads a session command's flags, not just its name.

    A dispatcher that routed the name and dropped the rest of the line would
    run the command against defaults, which for a calibration target is a
    silently different calibration rather than an error.
    """
    from calibrate_pro import frozen_main
    from calibrate_pro.commands import session

    seen: list[tuple[str, object]] = []
    monkeypatch.setattr(session, "run", lambda command, args, service=None: seen.append((command, args)) or 0)

    code = frozen_main.main(["verify", "--target", "srgb_web"], program="CalibrateProCLI.exe")

    assert code == 0
    command, arguments = seen[0]
    assert command == "verify"
    assert (arguments.target, arguments.display) == ("srgb_web", None)


def test_frozen_dispatcher_refuses_a_session_command_that_is_missing_an_argument(monkeypatch) -> None:
    """The refusal happens at the parser, so nothing is driven on a guess."""
    from calibrate_pro import frozen_main
    from calibrate_pro.commands import session

    monkeypatch.setattr(
        session,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("an unparsed command reached the driver")),
    )

    with pytest.raises(SystemExit) as raised:
        frozen_main.main(["verify"], program="CalibrateProCLI.exe")

    assert raised.value.code == 2


def test_frozen_dispatcher_rejects_developer_commands_without_importing_them(monkeypatch, capsys) -> None:
    from calibrate_pro import frozen_main

    monkeypatch.setattr(
        frozen_main,
        "import_module",
        lambda _name: (_ for _ in ()).throw(AssertionError("developer-only command imported a module")),
    )
    sys.modules.pop("calibrate_pro.gui.app", None)
    assert frozen_main.main(["tray"], program="CalibrateProCLI.exe") == 2
    assert "This command is available only in the developer wheel" in capsys.readouterr().err
    assert "calibrate_pro.gui.app" not in sys.modules


def test_the_binary_does_not_send_a_declined_name_to_the_wheel(monkeypatch, capsys) -> None:
    """A name no build performs says so here rather than recommending an install.

    Every name in this list is refused by the developer wheel as well, so the
    developer-wheel sentence sent an operator to install Python for a command
    that would refuse there too. The check reads both halves off the dispatcher:
    a declined name must not carry that sentence, and it must say what the wheel
    would do with it.
    """
    from calibrate_pro import frozen_main

    monkeypatch.setattr(
        frozen_main,
        "import_module",
        lambda _name: (_ for _ in ()).throw(AssertionError("a declined command imported a module")),
    )

    for command in sorted(frozen_main._DECLINED_COMMANDS):
        assert frozen_main.main([command], program="CalibrateProCLI.exe") == 2
        printed = capsys.readouterr().err
        assert command in printed, f"{command} does not name itself"
        assert frozen_main._DEVELOPER_ONLY_MESSAGE not in printed, f"{command} still points at the wheel"
        assert "declines it as well" in printed, f"{command} does not say what the wheel does"
        assert frozen_main._UNTOUCHED in printed, f"{command} does not say nothing was touched"


def test_the_two_dispatchers_say_the_same_thing_about_touching_nothing() -> None:
    """The sentence is written out twice, so it is compared rather than shared.

    Importing it from calibrate_pro.main would pull the action layer into the
    dispatcher that exists to avoid loading it, which the module allowlist above
    is built to prevent.
    """
    from calibrate_pro import frozen_main, main

    assert frozen_main._UNTOUCHED == main._UNTOUCHED


def test_frozen_dispatcher_defaults_gui_and_cli_safely(monkeypatch, capsys) -> None:
    from calibrate_pro import frozen_main

    imported: list[str] = []

    def fake_import(name: str) -> object:
        imported.append(name)
        return SimpleNamespace(run=lambda _args: 0)

    monkeypatch.setattr(frozen_main, "import_module", fake_import)
    assert frozen_main.main([], program="CalibratePro.exe") == 0
    assert imported == ["calibrate_pro.commands.gui"]

    imported.clear()
    assert frozen_main.main([], program="CalibrateProCLI.exe") == 0
    assert imported == []
    assert "doctor" in capsys.readouterr().out
