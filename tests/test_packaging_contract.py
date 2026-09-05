"""Static release gates for the single positive-allowlisted PyInstaller graph."""

from __future__ import annotations

import ast
import json
import os
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "calibrate-pro.spec"


def _literal_set_assignment(name: str) -> set[str]:
    tree = ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            value = ast.literal_eval(node.value)
            assert isinstance(value, set)
            return value
    raise AssertionError(f"missing literal set assignment: {name}")


def _literal_tuple_assignment(name: str) -> tuple[str, ...]:
    tree = ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            value = ast.literal_eval(node.value)
            assert isinstance(value, tuple)
            return value
    raise AssertionError(f"missing literal tuple assignment: {name}")


def test_only_the_canonical_onedir_spec_exists() -> None:
    assert SPEC.is_file()
    assert not (ROOT / "CalibratePro.spec").exists()
    text = SPEC.read_text(encoding="utf-8")
    assert 'PACKAGE_ROOT / "frozen_main.py"' in text
    assert text.count("Analysis(") == 1
    assert text.count("PYZ(") == 1
    assert text.count("EXE(") == 2
    assert text.count("COLLECT(") == 1
    assert "collect_submodules" not in text
    assert "CALIBRATE_PRO_FREEZE_PACKAGE_ROOT" in text
    assert 'PROJECT_ROOT / "calibrate_pro"' not in text


def test_both_frozen_binaries_are_unelevated_uncompressed_onedir_entries() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert text.count("exclude_binaries=True") == 2
    assert text.count("uac_admin=False") == 2
    assert text.count("strip=False") >= 2
    assert text.count("upx=False") >= 3
    assert 'name="CalibratePro"' in text
    assert 'name="CalibrateProCLI"' in text
    assert "console=False" in text
    assert "console=True" in text


def test_spec_uses_committed_policies_runtime_hook_and_literal_dwm_resources() -> None:
    text = SPEC.read_text(encoding="utf-8").replace("'", '"')
    assert "packaging/frozen-features.json" in text.replace("\\", "/")
    assert "packaging/frozen-modules.json" in text.replace("\\", "/")
    assert "packaging/pyi_rth_qt_api.py" in text.replace("\\", "/")
    for name in (
        "DwmLutGUI.exe",
        "dwm_lut.dll",
        "WindowsDisplayAPI.dll",
        "LICENSE",
        "LICENSE-THIRD-PARTY",
    ):
        assert f'"{name}"' in text
    assert '"PyQt5"' in text
    assert '"PyQt6"' in text
    assert '"build_color.gui"' in text


def test_spec_partitions_every_package_resource_into_shipped_and_withheld() -> None:
    """Both halves are literal, and together they have to be the whole directory.

    PyInstaller carries no package data on its own, so the action manifest reaches
    the frozen build only by being named here, and it is read on every startup.
    The withheld half is the same decision written down: the fake-acceptance
    display is a synthetic panel, and a shipped binary carrying one can put
    modeled figures where an operator reads a real display.
    """
    shipped = _literal_tuple_assignment("shipped_package_resources")
    withheld = _literal_tuple_assignment("unshipped_package_resources")
    present = sorted(path.name for path in (ROOT / "calibrate_pro" / "resources").iterdir() if path.is_file())

    assert sorted(shipped) == sorted(set(shipped))
    assert not set(shipped) & set(withheld)
    assert sorted([*shipped, *withheld]) == present
    assert "action-capabilities.json" in shipped
    assert "fake-acceptance-display.json" in withheld
    source = SPEC.read_text(encoding="utf-8")
    assert '(str(PACKAGE_RESOURCE_ROOT / name), "calibrate_pro/resources")' in source
    assert "if path.is_file()" in source


def test_every_explicit_hidden_import_is_policy_authorized() -> None:
    policy = json.loads((ROOT / "packaging/frozen-modules.json").read_text(encoding="utf-8"))
    allowed = {*policy["first_party_exact"], *policy["optional_first_party_exact"]}
    assert "calibrate_pro.frozen_main" in allowed
    assert policy["default"] == "reject"
    assert all("*" not in name for name in allowed)


def test_spec_copies_every_doctor_dependency_distribution_metadata() -> None:
    distribution_metadata = _literal_set_assignment("distribution_metadata")

    assert {
        "PySide6-Essentials",
        "QtPy",
        "build-color",
        "build-ui",
        "hidapi",
        "numpy",
        "packaging",
        "scipy",
        "shiboken6",
    } <= distribution_metadata


def test_spec_prunes_install_specific_record_metadata_from_frozen_graph() -> None:
    unused_records = _literal_set_assignment("unused_distribution_metadata_files")

    assert unused_records == {
        "QtPy-2.4.3.dist-info/RECORD",
        "build_color-1.0.2.dist-info/RECORD",
        "build_ui-2.0.0.dist-info/RECORD",
        "hidapi-0.15.0.dist-info/RECORD",
        "numpy-2.5.1.dist-info/RECORD",
        "packaging-26.2.dist-info/RECORD",
        "pyside6_essentials-6.11.1.dist-info/RECORD",
        "scipy-1.18.0.dist-info/RECORD",
        "shiboken6-6.11.1.dist-info/RECORD",
    }
    source = SPEC.read_text(encoding="utf-8")
    assert 'entry[0].replace("\\\\", "/") not in unused_distribution_metadata_files' in source

    for policy_name in ("components-win64.json", "qt-components.json"):
        policy = json.loads((ROOT / "packaging" / policy_name).read_text(encoding="utf-8"))
        assert ".dist-info/RECORD" not in json.dumps(policy)


def test_spec_excludes_only_proven_unused_heavy_qt_surfaces_and_keeps_printsupport() -> None:
    hidden_imports = _literal_set_assignment("third_party_hidden_imports")
    fixed_excludes = _literal_set_assignment("fixed_excludes")
    unused_heavy_qt = {
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

    assert unused_heavy_qt <= fixed_excludes
    assert {"charset_normalizer", "numpy.f2py"} <= fixed_excludes
    assert "PySide6.QtPrintSupport" in hidden_imports
    assert "PySide6.QtPrintSupport" not in fixed_excludes


def test_spec_prunes_the_unused_virtual_keyboard_qml_binary_chain() -> None:
    unused_qt_binaries = _literal_set_assignment("unused_qt_binaries")

    assert unused_qt_binaries == {
        "PySide6/opengl32sw.dll",
        "PySide6/Qt6Pdf.dll",
        "PySide6/Qt6Qml.dll",
        "PySide6/Qt6QmlMeta.dll",
        "PySide6/Qt6QmlModels.dll",
        "PySide6/Qt6QmlWorkerScript.dll",
        "PySide6/Qt6Quick.dll",
        "PySide6/Qt6Svg.dll",
        "PySide6/Qt6VirtualKeyboard.dll",
        "PySide6/plugins/iconengines/qsvgicon.dll",
        "PySide6/plugins/imageformats/qicns.dll",
        "PySide6/plugins/imageformats/qpdf.dll",
        "PySide6/plugins/imageformats/qsvg.dll",
        "PySide6/plugins/imageformats/qtga.dll",
        "PySide6/plugins/imageformats/qtiff.dll",
        "PySide6/plugins/imageformats/qwbmp.dll",
        "PySide6/plugins/imageformats/qwebp.dll",
        "PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
        "PySide6/plugins/tls/qopensslbackend.dll",
    }
    assert _literal_set_assignment("unused_system_binaries") == {"ucrtbase.dll"}
    assert _literal_tuple_assignment("unused_system_binary_prefixes") == ("api-ms-win-",)
    assert _literal_tuple_assignment("unused_qt_data_prefixes") == ("PySide6/translations/",)
    source = SPEC.read_text(encoding="utf-8")
    assert "analysis.binaries = [" in source
    assert "analysis.datas = [" in source
    assert 'entry[0].replace("\\\\", "/") not in unused_qt_binaries' in source
    assert 'not entry[0].replace("\\\\", "/").startswith(unused_system_binary_prefixes)' in source
    assert 'not entry[0].replace("\\\\", "/").startswith(unused_qt_data_prefixes)' in source


def test_frozen_runtime_forces_windows_schannel_and_excludes_qt_openssl(
    monkeypatch,
) -> None:
    hook = ROOT / "packaging" / "pyi_rth_qt_api.py"
    monkeypatch.setenv("QT_API", "unexpected")
    monkeypatch.setenv("QT_TLS_BACKEND", "openssl")

    runpy.run_path(str(hook))

    assert os.environ["QT_API"] == "pyside6"
    assert os.environ["QT_TLS_BACKEND"] == "schannel"
    for policy_name in ("components-win64.json", "qt-components.json"):
        policy = json.loads((ROOT / "packaging" / policy_name).read_text(encoding="utf-8"))
        assert "qopensslbackend.dll" not in json.dumps(policy).casefold()
