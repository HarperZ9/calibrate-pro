"""Positive frozen-command and module-allowlist release gates."""

from __future__ import annotations

import ast
import json
import sys
from functools import cache
from pathlib import Path
from types import SimpleNamespace

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
    "schema_version": 1,
    "commands": ["doctor", "gui", "hdr"],
    "developer_only_commands": [
        "auto",
        "calibrate",
        "ddc-calibrate",
        "ddc-info",
        "detect",
        "disable-startup",
        "enable-startup",
        "export-panel",
        "hdr-status",
        "import-panel",
        "info",
        "list-panels",
        "list-targets",
        "match",
        "native-calibrate",
        "patterns",
        "plugins",
        "profiles-generate",
        "refine",
        "restore",
        "status",
        "tray",
        "uniformity",
        "verify",
    ],
}


def test_frozen_features_are_exact_and_developer_only_commands_are_explicit() -> None:
    data = json.loads((ROOT / "packaging/frozen-features.json").read_text(encoding="utf-8"))
    assert data == EXPECTED_FEATURES


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
    """What the frozen entry points reach, and which of it the build refuses.

    Read once. Every module in the closure is parsed to answer this, and three
    gates ask about the same two sets.
    """
    features = json.loads((ROOT / "packaging/frozen-features.json").read_text(encoding="utf-8"))
    entry_points = [f"{PACKAGE}.frozen_main", *(f"{PACKAGE}.commands.{name}" for name in features["commands"])]
    reachable = reachable_modules(ROOT, entry_points)
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


def test_frozen_dispatcher_rejects_developer_commands_without_importing_them(monkeypatch, capsys) -> None:
    from calibrate_pro import frozen_main

    monkeypatch.setattr(
        frozen_main,
        "import_module",
        lambda _name: (_ for _ in ()).throw(AssertionError("developer-only command imported a module")),
    )
    sys.modules.pop("calibrate_pro.gui.app", None)
    assert frozen_main.main(["calibrate"], program="CalibrateProCLI.exe") == 2
    assert "This command is available only in the developer wheel" in capsys.readouterr().err
    assert "calibrate_pro.gui.app" not in sys.modules


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
