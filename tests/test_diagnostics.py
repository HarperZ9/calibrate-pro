"""Read-only runtime diagnostics and real-entrypoint safety tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

DWM_LUT_FILES = (
    "DwmLutGUI.exe",
    "dwm_lut.dll",
    "WindowsDisplayAPI.dll",
    "LICENSE",
    "LICENSE-THIRD-PARTY",
)
STATIC_NOTICE_FILES = (
    "LGPL-3.0-only.txt",
    "QT_SOURCE_OFFER.txt",
    "LGPL_RELINKING.md",
    "source-provenance.json",
    "binary-provenance.json",
)
DEPENDENCY_VERSIONS = {
    "build-color": "1.0.2",
    "build-ui": "2.0.0",
    "QtPy": "2.4.3",
    "PySide6-Essentials": "6.11.1",
    "shiboken6": "6.11.1",
    "numpy": "2.5.1",
    "scipy": "1.18.0",
}


def _complete_resource_root(root: Path) -> Path:
    (root / "LICENSE").write_text("Calibrate Pro license\n", encoding="utf-8")
    dwm_lut = root / "dwm_lut"
    dwm_lut.mkdir()
    for name in DWM_LUT_FILES:
        (dwm_lut / name).write_bytes((name + "\n").encode("utf-8"))

    notices = root / "THIRD_PARTY_LICENSES"
    notices.mkdir()
    dynamic_notices = (
        "Build-Color-1.0.2.txt",
        "Build-UI-2.0.0.txt",
        "Qt-for-Python-NOTICE.txt",
    )
    for name in (*STATIC_NOTICE_FILES, *dynamic_notices):
        (notices / name).write_text(name + "\n", encoding="utf-8")

    packaging = root / "packaging"
    packaging.mkdir()
    component_policy = {
        "schema_version": 2,
        "default": "reject",
        "path_mode": "literal-posix",
        "components": [{"notice_paths": [f"THIRD_PARTY_LICENSES/{name}"]} for name in dynamic_notices],
    }
    (packaging / "components-win64.json").write_text(
        json.dumps(component_policy),
        encoding="utf-8",
    )
    return root


def _fake_dependency_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_version(distribution: str) -> str:
        try:
            return DEPENDENCY_VERSIONS[distribution]
        except KeyError as exc:  # pragma: no cover - makes tuple drift explicit
            raise metadata.PackageNotFoundError(distribution) from exc

    monkeypatch.setattr(metadata, "version", fake_version)


def test_application_root_resolves_source_tree() -> None:
    from calibrate_pro.runtime import application_root

    assert application_root() == ROOT


def test_application_root_and_resource_path_use_meipass_when_frozen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from calibrate_pro.runtime import application_root, resource_path

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)

    assert application_root() == bundle.resolve()
    assert resource_path("dwm_lut", "DwmLutGUI.exe") == bundle.resolve() / "dwm_lut" / "DwmLutGUI.exe"


def test_doctor_report_is_complete_byte_stable_and_does_not_probe_devices(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import calibrate_pro.diagnostics as diagnostics
    from calibrate_pro import __version__

    root = _complete_resource_root(tmp_path)
    _fake_dependency_versions(monkeypatch)
    symbol_calls: list[tuple[str, str]] = []

    def fake_symbol(dll_name: str, symbol: str) -> bool:
        symbol_calls.append((dll_name, symbol))
        return True

    monkeypatch.setattr(diagnostics, "_windows_symbol", fake_symbol)
    monkeypatch.setattr(diagnostics, "_is_windows", lambda: True)
    monkeypatch.setattr(diagnostics.importlib.util, "find_spec", lambda name: object() if name == "hid" else None)

    before = set(sys.modules)
    report = diagnostics.build_doctor_report(root=root, frozen=True)
    rendered_once = diagnostics.render_doctor_json(report=report)
    rendered_twice = diagnostics.render_doctor_json(report=report)
    imported = set(sys.modules) - before

    assert report["schema_version"] == 1
    assert report["version"] == __version__
    assert report["ok"] is True
    assert report["qt"] == {"api_name": "PySide6", "ok": True}
    assert tuple(report["dependencies"]) == tuple(DEPENDENCY_VERSIONS)
    assert all(item["installed"] for item in report["dependencies"].values())
    assert report["resources"]["ok"] is True
    assert all(item["present"] for item in report["resources"]["required"])
    assert report["pq"]["ok"] is True
    assert report["pq"]["encode_100_nits"] == pytest.approx(0.508078421517399, abs=1e-12)
    assert report["pq"]["decode_100_nits"] == pytest.approx(100.0, abs=1e-8)
    assert rendered_once == rendered_twice
    assert rendered_once == json.dumps(report, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    assert json.loads(rendered_once) == report
    assert symbol_calls == [
        ("Dxva2.dll", "GetVCPFeatureAndVCPFeatureReply"),
        ("Mscms.dll", "WcsGetDefaultColorProfile"),
        ("Gdi32.dll", "GetDeviceGammaRamp"),
    ]

    for name in ("display_enumeration", "ddc_ci", "icc_profile", "gamma_ramp", "colorimeter"):
        capability = report["capabilities"][name]
        assert isinstance(capability["software_supported"], bool)
        assert capability["device_presence"] == "not_probed"
        assert capability["probe"] in {"platform", "library_symbol", "module_spec"}

    blocked = (
        "calibrate_pro.hardware",
        "calibrate_pro.services",
        "calibrate_pro.startup",
        "calibrate_pro.gui",
        "calibrate_pro.adapters.windows_display_state",
        "hid",
    )
    assert not any(any(name == prefix or name.startswith(prefix + ".") for prefix in blocked) for name in imported)


def test_missing_resource_is_reported_truthfully_and_exits_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import calibrate_pro.diagnostics as diagnostics

    root = _complete_resource_root(tmp_path)
    (root / "dwm_lut" / "WindowsDisplayAPI.dll").unlink()
    _fake_dependency_versions(monkeypatch)
    monkeypatch.setattr(diagnostics, "_windows_symbol", lambda dll_name, symbol: True)
    monkeypatch.setattr(diagnostics, "_is_windows", lambda: True)
    monkeypatch.setattr(diagnostics.importlib.util, "find_spec", lambda name: object())

    report = diagnostics.build_doctor_report(root=root, frozen=True)
    missing = [item["path"] for item in report["resources"]["required"] if not item["present"]]

    assert missing == ["dwm_lut/WindowsDisplayAPI.dll"]
    assert report["resources"]["ok"] is False
    assert report["ok"] is False
    assert diagnostics.doctor_exit_code(report) == 1


def test_invalid_component_notice_path_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import calibrate_pro.diagnostics as diagnostics

    root = _complete_resource_root(tmp_path)
    policy_path = root / "packaging" / "components-win64.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["components"].append({"notice_paths": ["../outside.txt"]})
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    _fake_dependency_versions(monkeypatch)
    monkeypatch.setattr(diagnostics, "_windows_symbol", lambda dll_name, symbol: True)
    monkeypatch.setattr(diagnostics, "_is_windows", lambda: True)
    monkeypatch.setattr(diagnostics.importlib.util, "find_spec", lambda name: object())

    report = diagnostics.build_doctor_report(root=root, frozen=True)

    assert report["resources"]["ok"] is False
    assert report["resources"]["policy_error"] == "component 3 has invalid notice_paths"
    assert report["ok"] is False
    assert diagnostics.doctor_exit_code(report) == 1


def test_python_distribution_does_not_require_frozen_desktop_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import calibrate_pro.diagnostics as diagnostics

    _fake_dependency_versions(monkeypatch)
    monkeypatch.setattr(diagnostics, "_windows_symbol", lambda dll_name, symbol: True)
    monkeypatch.setattr(diagnostics, "_is_windows", lambda: True)
    monkeypatch.setattr(diagnostics.importlib.util, "find_spec", lambda name: object())

    report = diagnostics.build_doctor_report(root=tmp_path, frozen=False)

    assert report["distribution_mode"] == "python"
    assert report["resources"] == {
        "applicable": False,
        "ok": True,
        "policy_error": None,
        "required": [],
    }
    assert report["ok"] is True
    assert diagnostics.doctor_exit_code(report) == 0


def test_real_doctor_entrypoint_is_read_only_and_cannot_import_mutation_layers() -> None:
    code = r"""
import importlib.abc
import json
import os
import sys

BLOCKED = (
    "calibrate_pro.core.calibration_engine",
    "calibrate_pro.panels",
    "calibrate_pro.targets",
    "calibrate_pro.hardware",
    "calibrate_pro.services",
    "calibrate_pro.startup",
    "calibrate_pro.gui",
    "calibrate_pro.adapters.windows_display_state",
)

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if any(fullname == item or fullname.startswith(item + ".") for item in BLOCKED):
            raise AssertionError("doctor attempted mutation/heavy import: " + fullname)
        return None

def audit(event, args):
    if event == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        if isinstance(mode, str) and any(marker in mode for marker in "wax+"):
            raise AssertionError("doctor attempted file write: " + repr(args))
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise AssertionError("doctor attempted file write: " + repr(args))
    if event in {
        "os.remove", "os.rename", "os.replace", "os.rmdir", "os.mkdir", "os.system",
        "subprocess.Popen",
    } or event.startswith("winreg."):
        raise AssertionError("doctor attempted mutation: " + event)

sys.meta_path.insert(0, Blocker())
sys.addaudithook(audit)
from calibrate_pro.main import main
result = main(["doctor", "--json"])
assert result in {0, 1}
for name in tuple(sys.modules):
    assert not any(name == item or name.startswith(item + ".") for item in BLOCKED), name
raise SystemExit(result)
"""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode in {0, 1}, result.stderr
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["schema_version"] == 1
    assert result.returncode == (0 if report["ok"] else 1)


@pytest.mark.windows
def test_dwm_lut_search_uses_packaged_resource_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import calibrate_pro.lut_system.dwm_lut as dwm_lut

    packaged = tmp_path / "packaged" / "dwm_lut"
    packaged.mkdir(parents=True)
    (packaged / "DwmLutGUI.exe").write_bytes(b"test")
    monkeypatch.setattr(dwm_lut, "resource_path", lambda *parts: tmp_path / "packaged" / Path(*parts))
    controller = object.__new__(dwm_lut.DwmLutController)
    controller._dwm_lut_path = None

    controller._find_dwm_lut()

    assert controller._dwm_lut_path == packaged
