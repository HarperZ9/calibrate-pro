"""Positive frozen-command and module-allowlist release gates."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]

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
