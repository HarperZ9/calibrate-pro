# -*- mode: python ; coding: utf-8 -*-
"""Canonical positive-allowlisted Calibrate Pro Windows onedir graph."""

import json
import os
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata


PROJECT_ROOT = Path(SPECPATH).resolve()
freeze_package_value = os.environ.get("CALIBRATE_PRO_FREEZE_PACKAGE_ROOT")
if not freeze_package_value:
    raise SystemExit("CALIBRATE_PRO_FREEZE_PACKAGE_ROOT must identify the installed wheel package")
PACKAGE_ROOT = Path(freeze_package_value).resolve()
if PACKAGE_ROOT.name != "calibrate_pro" or not (PACKAGE_ROOT / "frozen_main.py").is_file():
    raise SystemExit(f"invalid installed Calibrate Pro package root: {PACKAGE_ROOT}")
FEATURE_POLICY_PATH = PROJECT_ROOT / "packaging/frozen-features.json"
MODULE_POLICY_PATH = PROJECT_ROOT / "packaging/frozen-modules.json"

feature_policy = json.loads(FEATURE_POLICY_PATH.read_text(encoding="utf-8"))
module_policy = json.loads(MODULE_POLICY_PATH.read_text(encoding="utf-8"))

if feature_policy.get("commands") != [
    "detect",
    "doctor",
    "generate-profiles",
    "gui",
    "hdr",
    "profiles",
    "status",
    "verify",
]:
    raise SystemExit("frozen feature policy is not the approved command set")
if module_policy.get("schema_version") != 1 or module_policy.get("default") != "reject":
    raise SystemExit("frozen module policy must be schema 1 and fail closed")

first_party_exact = set(module_policy["first_party_exact"])
optional_first_party_exact = set(module_policy["optional_first_party_exact"])
approved_first_party = first_party_exact | optional_first_party_exact
if any("*" in name for name in approved_first_party):
    raise SystemExit("wildcards are forbidden in the frozen first-party policy")


def source_module(path):
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


all_first_party = {
    source_module(path)
    for path in PACKAGE_ROOT.rglob("*.py")
}
unknown_policy_modules = approved_first_party - all_first_party
if unknown_policy_modules:
    raise SystemExit(
        "frozen module policy names missing source modules: "
        + ", ".join(sorted(unknown_policy_modules))
    )

third_party_hidden_imports = {
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtPrintSupport",
    "PySide6.QtWidgets",
    "build_color.adaptation",
    "build_color.difference",
    "build_color.gamut",
    "build_color.spaces",
    "build_ui.theme",
    "build_ui.widgets",
    "qtpy",
}
distribution_roots = set(module_policy["distribution_roots"])
for module_name in third_party_hidden_imports:
    if module_name.split(".", 1)[0] not in distribution_roots:
        raise SystemExit(f"hidden import is outside the distribution policy: {module_name}")

hidden_imports = sorted(approved_first_party | third_party_hidden_imports)
generated_excludes = all_first_party - approved_first_party
fixed_excludes = {
    "IPython",
    "PIL",
    "PyQt5",
    "PyQt6",
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
    "_tkinter",
    "accelerate",
    "build_color.gui",
    "charset_normalizer",
    "cv2",
    "diffusers",
    "fitz",
    "huggingface_hub",
    "jupyter",
    "matplotlib",
    "notebook",
    "numpy.f2py",
    "pandas",
    "pymupdf",
    "reportlab",
    "safetensors",
    "sklearn",
    "sympy",
    "tensorflow",
    "tkinter",
    "tokenizers",
    "torch",
    "torchaudio",
    "torchvision",
    "transformers",
    "wx",
    "qtpy.QtDataVisualization",
}
excludes = sorted(generated_excludes | fixed_excludes)

# Qt's generic GUI hook collects optional format, software-renderer, PDF, SVG,
# and virtual-keyboard plugins. Calibrate Pro's frozen widgets surface uses
# PNG/ICO assets and QPrinter PDF output; it does not import those optional
# modules or formats. The Windows target uses Schannel, so omit the OpenSSL TLS
# plugin rather than letting it discover unprovenanced DLLs from a user's PATH.
# Keep the redistribution graph equal to that approved runtime surface instead
# of silently shipping unrelated native components.
unused_qt_binaries = {
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
unused_system_binaries = {"ucrtbase.dll"}
unused_system_binary_prefixes = ("api-ms-win-",)
unused_qt_data_prefixes = ("PySide6/translations/",)
unused_distribution_metadata_files = {
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

dwm_lut_files = (
    "DwmLutGUI.exe",
    "dwm_lut.dll",
    "WindowsDisplayAPI.dll",
    "LICENSE",
    "LICENSE-THIRD-PARTY",
)
# Package data the frozen build reads through importlib.resources. PyInstaller
# carries no package data on its own, so a file absent from here is absent from
# the build, and the action manifest is read on every startup. Naming what is
# deliberately left out is the other half: the fake-acceptance display is a
# synthetic panel for the test suite, and a shipped binary that carries one can
# present modeled figures where an operator expects a real display.
PACKAGE_RESOURCE_ROOT = PACKAGE_ROOT / "resources"
shipped_package_resources = ("action-capabilities.json",)
unshipped_package_resources = (
    "calibrate_pro.ico",
    "calibrate_pro.png",
    "fake-acceptance-display.json",
)
present_package_resources = sorted(
    path.name for path in PACKAGE_RESOURCE_ROOT.iterdir() if path.is_file()
)
if present_package_resources != sorted(shipped_package_resources + unshipped_package_resources):
    raise SystemExit(
        "package resources are not the partition this build approved: "
        + ", ".join(present_package_resources)
    )

datas = [
    (str(PROJECT_ROOT / "dwm_lut" / name), "dwm_lut")
    for name in dwm_lut_files
]
datas.extend(
    [
        (str(PACKAGE_RESOURCE_ROOT / name), "calibrate_pro/resources")
        for name in shipped_package_resources
    ]
)
datas.extend(
    [
        (str(FEATURE_POLICY_PATH), "packaging"),
        (str(MODULE_POLICY_PATH), "packaging"),
    ]
)
distribution_metadata = {
    "PySide6-Essentials",
    "QtPy",
    "build-color",
    "build-ui",
    "hidapi",
    "numpy",
    "packaging",
    "scipy",
    "shiboken6",
}
for distribution_name in sorted(distribution_metadata):
    datas.extend(copy_metadata(distribution_name))

analysis = Analysis(
    [str(PACKAGE_ROOT / "frozen_main.py")],
    pathex=[str(PACKAGE_ROOT.parent)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PROJECT_ROOT / "packaging/pyi_rth_qt_api.py")],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)
analysis.binaries = [
    entry
    for entry in analysis.binaries
    if entry[0].replace("\\", "/") not in unused_qt_binaries
    and entry[0].replace("\\", "/") not in unused_system_binaries
    and not entry[0].replace("\\", "/").startswith(unused_system_binary_prefixes)
]
analysis.datas = [
    entry
    for entry in analysis.datas
    if not entry[0].replace("\\", "/").startswith(unused_qt_data_prefixes)
    and entry[0].replace("\\", "/") not in unused_distribution_metadata_files
]
pyz = PYZ(analysis.pure)

gui_executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="CalibratePro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
)

cli_executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="CalibrateProCLI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
)

collection = COLLECT(
    gui_executable,
    cli_executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="CalibratePro",
)
