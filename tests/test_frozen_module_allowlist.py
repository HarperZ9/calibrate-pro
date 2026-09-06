"""Positive frozen-command and module-allowlist release gates."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import textwrap
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

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
        "list-targets",
        "patterns",
        "profiles",
        "remove-profile",
        "restore-profiles",
        "show-pattern",
        "status",
        "switch-profile",
        "system-profiles",
        "verify",
    ],
    "developer_only_commands": [
        "hdr-status",
        "info",
        "list-panels",
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
        "calibrate_pro.commands.list_targets",
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


#: Imports each named module in an interpreter that refuses the spec's excludes.
#: Run out of process because refusing a name means letting scipy and numpy load
#: against a meta path finder, and a suite that did that in its own interpreter
#: would hand every later test a partially imported third-party graph.
_REFUSAL_PROBE = textwrap.dedent(
    """
    import importlib
    import importlib.abc
    import json
    import sys

    payload = json.loads(sys.stdin.read())
    refused_names = set(payload["refused"])
    reached = []


    class Refuse(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            parts = fullname.split(".")
            if any(".".join(parts[: depth + 1]) in refused_names for depth in range(len(parts))):
                reached.append(fullname)
                raise ImportError(f"No module named {fullname!r}")
            return None


    sys.meta_path.insert(0, Refuse())
    failures = {}
    for name in payload["modules"]:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}: {exc}"
    print(json.dumps({"failures": failures, "reached": sorted(set(reached))}))
    """
)


def _import_refusing(refused: set[str], modules: list[str]) -> dict[str, Any]:
    """Import each module where the named ones are unavailable, and report both."""
    completed = subprocess.run(
        [sys.executable, "-c", _REFUSAL_PROBE],
        input=json.dumps({"refused": sorted(refused), "modules": modules}),
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_no_module_the_frozen_build_imports_needs_a_name_the_spec_excludes() -> None:
    """The gates above walk first-party imports, which is not where this lives.

    An exclude only third-party code reaches is invisible to a source walk.
    ``numpy.f2py`` was excluded as unused on exactly that reading: no module
    here imports it, and ``scipy.special`` clones numpy with a star import,
    which makes numpy import f2py to answer the name. Excluding it left a build
    that could not import scipy, so the packaged window returned 1 before it
    drew anything, and the build gate reported the exit code without the
    reason. This runs the imports a shipped binary runs with each excluded name
    refused, which is the interpreter that can see it.
    """
    reachable, blocked = frozen_closure()

    result = _import_refusing(spec_excludes(SPEC), sorted(set(reachable) - set(blocked)))

    assert result["failures"] == {}
    assert result["reached"], "no excluded name was asked for, so nothing was measured"


def test_the_refusal_probe_fails_when_a_needed_module_is_taken_away() -> None:
    """The control for the gate above, which a dead probe would pass silently.

    A finder that matched nothing, or one that never reached the meta path,
    would report an empty failure set and read as a build that needs none of
    its excludes. scipy is a module the window does need, so refusing it has to
    come back as a failure naming it.
    """
    result = _import_refusing({"scipy"}, [f"{PACKAGE}.gui.app"])

    assert "scipy" in result["failures"][f"{PACKAGE}.gui.app"]


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


def _quoted_command_names(text: str) -> set[str]:
    """Every command name a sentence points at, read out of the sentence.

    The names are recognised against the whole product rather than against the
    frozen build's own split. Reading them off the shipped set would make this
    gate agree with whatever that set says: a command dropped from the binary
    stops being a name the gate recognises, and the sentence pointing at it
    passes. The wheel's table, the session commands and the declined names are
    every command this release has a name for.
    """
    from calibrate_pro import frozen_main, main
    from calibrate_pro.commands import session_args

    known = {*main._HANDLERS, *session_args.COMMANDS, *frozen_main._DECLINED_COMMANDS}
    return {name for name in re.findall(r"'([a-z][a-z-]+)'", text) if name in known}


def _operator_facing_help() -> str:
    """The strings a frozen build prints at an operator, gathered as printed."""
    from calibrate_pro.commands import session_args

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", parser_class=session_args.SessionCommandParser)
    session_args.add_parsers(subparsers)

    pieces = [session_args.COMPOSE_HINT, session_args._UNAIMED]
    for command in subparsers.choices.values():
        pieces.append(command.format_help())
    return "\n".join(pieces)


def test_every_command_the_binary_names_in_its_own_help_is_one_it_runs() -> None:
    """A refusal that names a refused command is a dead end, not an instruction.

    ``--target`` is required, the sentence refusing a line without one named
    ``list-targets``, and four help strings said to see it. The binary answered
    that name with a sentence about a wheel it does not carry, so the only way
    to read the vocabulary out of a shipped build was to guess a wrong value.
    The names are read out of the strings themselves here, so a sentence
    pointing somewhere the build will not go fails before it is packaged.
    """
    from calibrate_pro import frozen_main

    shipped = {*frozen_main._COMMANDS, *frozen_main._SESSION_COMMANDS}
    named = _quoted_command_names(_operator_facing_help())

    assert named, "no command name was found in the help text, so this gate measured nothing"
    assert named <= shipped


def test_the_frozen_build_prints_the_axis_values_a_composed_target_takes(capsys) -> None:
    """What the listing is for, read off the dispatcher an operator runs.

    The presets are printable from an error message already. The three axes are
    not: a composed target is 616 combinations, and before this command shipped
    the packaged build had no way to print them.
    """
    from calibrate_pro import frozen_main

    code = frozen_main.main(["list-targets"], program="CalibrateProCLI.exe")

    printed = capsys.readouterr().out
    assert code == 0
    for flag in ("--gamut", "--white-point", "--tone-response"):
        assert flag in printed
