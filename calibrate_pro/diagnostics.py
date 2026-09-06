"""Deterministic, read-only runtime diagnostics for Calibrate Pro."""

from __future__ import annotations

import ctypes
import importlib.util
import json
import math
import os
import sys
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import Any

from calibrate_pro import __version__
from calibrate_pro.runtime import application_root

#: Each runtime dependency, the distribution that provides it, and the extra a
#: reader installs to get it. ``None`` means the base install already carries it,
#: so its absence is a damaged installation rather than an option nobody chose.
DEPENDENCIES: tuple[tuple[str, str, str | None], ...] = (
    ("build-color", "build-color", None),
    ("build-ui", "build-ui", "gui"),
    ("QtPy", "QtPy", "gui"),
    ("PySide6-Essentials", "PySide6-Essentials", "gui"),
    ("shiboken6", "shiboken6", "gui"),
    ("numpy", "numpy", None),
    ("scipy", "scipy", None),
)

_DWM_LUT_RESOURCES = (
    "dwm_lut/DwmLutGUI.exe",
    "dwm_lut/dwm_lut.dll",
    "dwm_lut/WindowsDisplayAPI.dll",
    "dwm_lut/LICENSE",
    "dwm_lut/LICENSE-THIRD-PARTY",
)
#: Package data the frozen build reads at startup. The action manifest decides
#: what every control on every surface is permitted to do, so a build missing it
#: has no surface at all, and doctor is where that shows up as a named absence
#: rather than as a traceback on launch.
_PACKAGE_RESOURCES = ("calibrate_pro/resources/action-capabilities.json",)
_COMPONENT_POLICY = "packaging/components-win64.json"
_STATIC_NOTICE_RESOURCES = (
    "THIRD_PARTY_LICENSES/LGPL-3.0-only.txt",
    "THIRD_PARTY_LICENSES/QT_SOURCE_OFFER.txt",
    "THIRD_PARTY_LICENSES/LGPL_RELINKING.md",
    "THIRD_PARTY_LICENSES/source-provenance.json",
    "THIRD_PARTY_LICENSES/binary-provenance.json",
)

_PQ_100_NITS = 100.0
_PQ_100_SIGNAL = 0.508078421517399
_PQ_ENCODE_TOLERANCE = 1e-12
_PQ_DECODE_TOLERANCE_NITS = 1e-8

_ST2084_M1 = 2610.0 / 16384.0
_ST2084_M2 = 2523.0 / 4096.0 * 128.0
_ST2084_C1 = 3424.0 / 4096.0
_ST2084_C2 = 2413.0 / 4096.0 * 32.0
_ST2084_C3 = 2392.0 / 4096.0 * 32.0
_ST2084_PEAK_NITS = 10000.0


def _pq_oetf(luminance: float) -> float:
    normalized = max(0.0, min(luminance / _ST2084_PEAK_NITS, 1.0))
    power = normalized**_ST2084_M1
    return ((_ST2084_C1 + _ST2084_C2 * power) / (1.0 + _ST2084_C3 * power)) ** _ST2084_M2


def _pq_eotf(signal: float) -> float:
    value = max(0.0, min(signal, 1.0)) ** (1.0 / _ST2084_M2)
    numerator = max(value - _ST2084_C1, 0.0)
    denominator = max(_ST2084_C2 - _ST2084_C3 * value, 1e-30)
    return (numerator / denominator) ** (1.0 / _ST2084_M1) * _ST2084_PEAK_NITS


def _capability(software_supported: bool, probe: str, detail: str | None = None) -> dict[str, object]:
    return {
        "software_supported": software_supported,
        "device_presence": "not_probed",
        "probe": probe,
        "detail": detail,
    }


def _is_windows() -> bool:
    return os.name == "nt"


def _windows_symbol(dll_name: str, symbol: str) -> bool:
    """Check a system-library export without calling it or probing a device."""
    if not _is_windows():
        return False
    try:
        library = ctypes.WinDLL(dll_name, use_last_error=True)
        getattr(library, symbol)
    except (OSError, AttributeError):
        return False
    return True


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _dependency_report() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for name, distribution, extra in DEPENDENCIES:
        try:
            version = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            version = None
        result[name] = {
            "distribution": distribution,
            "extra": extra,
            "installed": version is not None,
            "version": version,
        }
    return result


def _remediation(dependencies: dict[str, dict[str, object]], *, frozen_mode: bool) -> dict[str, object]:
    """The command that repairs a missing dependency, or nothing to run.

    A report that says NOT OK and stops there leaves a reader with no next
    action, which is the state the first public build shipped in. What repairs
    it depends on how the installation was made: pip can add an extra to a
    source install and can do nothing at all to a packaged one.
    """
    missing = sorted(name for name, entry in dependencies.items() if not entry["installed"])
    if not missing:
        return {"missing": [], "extras": [], "command": None, "note": None}
    extras = sorted({str(dependencies[name]["extra"]) for name in missing if dependencies[name]["extra"]})
    base = [name for name in missing if not dependencies[name]["extra"]]
    if frozen_mode:
        return {
            "missing": missing,
            "extras": extras,
            "command": None,
            "note": "This is a packaged build. Reinstall from the release that produced it; pip cannot repair it.",
        }
    if base and not extras:
        return {
            "missing": missing,
            "extras": extras,
            "command": "pip install --force-reinstall calibrate-pro",
            "note": "Every name above ships with the base install, so this installation is incomplete.",
        }
    note = None
    if base:
        note = (
            "Also missing from the base install: " + ", ".join(base) + ". Reinstall rather than adding the extra alone."
        )
    return {
        "missing": missing,
        "extras": extras,
        "command": 'pip install "calibrate-pro[' + ",".join(extras) + ']"',
        "note": note,
    }


def _safe_notice_path(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    normalized = path.as_posix()
    if (
        normalized != "LICENSE"
        and not normalized.startswith("THIRD_PARTY_LICENSES/")
        and normalized not in {"dwm_lut/LICENSE", "dwm_lut/LICENSE-THIRD-PARTY"}
    ):
        return None
    return normalized


def _component_notice_paths(root: Path) -> tuple[tuple[str, ...], str | None]:
    policy_path = root / Path(*PurePosixPath(_COMPONENT_POLICY).parts)
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return (), f"{type(exc).__name__}: {exc}"
    components = policy.get("components") if isinstance(policy, dict) else None
    if (
        not isinstance(policy, dict)
        or policy.get("schema_version") != 2
        or policy.get("default") != "reject"
        or policy.get("path_mode") != "literal-posix"
        or not isinstance(components, list)
    ):
        return (), "component policy must be schema 2 with literal-posix paths"
    paths: set[str] = set()
    for index, component in enumerate(components):
        notice_paths = component.get("notice_paths") if isinstance(component, dict) else None
        if not isinstance(notice_paths, list) or not notice_paths:
            return (), f"component {index} has invalid notice_paths"
        for value in notice_paths:
            notice_path = _safe_notice_path(value)
            if notice_path is None:
                return (), f"component {index} has invalid notice_paths"
            paths.add(notice_path)
    return tuple(sorted(paths)), None


def _resource_report(root: Path) -> dict[str, object]:
    dynamic_notices, policy_error = _component_notice_paths(root)
    required_paths = tuple(
        dict.fromkeys(
            (
                *_PACKAGE_RESOURCES,
                *_DWM_LUT_RESOURCES,
                _COMPONENT_POLICY,
                *_STATIC_NOTICE_RESOURCES,
                *dynamic_notices,
            )
        )
    )
    required = [
        {
            "path": relative,
            "present": (root / Path(*PurePosixPath(relative).parts)).is_file(),
        }
        for relative in required_paths
    ]
    ok = policy_error is None and all(bool(item["present"]) for item in required)
    return {
        "applicable": True,
        "ok": ok,
        "policy_error": policy_error,
        "required": required,
    }


def _pq_report() -> dict[str, object]:
    encoded = _pq_oetf(_PQ_100_NITS)
    decoded = _pq_eotf(_PQ_100_SIGNAL)
    encode_ok = math.isclose(encoded, _PQ_100_SIGNAL, rel_tol=0.0, abs_tol=_PQ_ENCODE_TOLERANCE)
    decode_ok = math.isclose(decoded, _PQ_100_NITS, rel_tol=0.0, abs_tol=_PQ_DECODE_TOLERANCE_NITS)
    return {
        "ok": encode_ok and decode_ok,
        "encode_100_nits": encoded,
        "encode_abs_tolerance": _PQ_ENCODE_TOLERANCE,
        "decode_100_nits": decoded,
        "decode_abs_tolerance_nits": _PQ_DECODE_TOLERANCE_NITS,
    }


def _capabilities_report() -> dict[str, dict[str, object]]:
    return {
        "display_enumeration": _capability(_is_windows(), "platform"),
        "ddc_ci": _capability(
            _windows_symbol("Dxva2.dll", "GetVCPFeatureAndVCPFeatureReply"),
            "library_symbol",
            "Dxva2.dll/GetVCPFeatureAndVCPFeatureReply",
        ),
        "icc_profile": _capability(
            _windows_symbol("Mscms.dll", "WcsGetDefaultColorProfile"),
            "library_symbol",
            "Mscms.dll/WcsGetDefaultColorProfile",
        ),
        "gamma_ramp": _capability(
            _windows_symbol("Gdi32.dll", "GetDeviceGammaRamp"),
            "library_symbol",
            "Gdi32.dll/GetDeviceGammaRamp",
        ),
        "colorimeter": _capability(_module_available("hid"), "module_spec", "hid"),
    }


def build_doctor_report(root: Path | None = None, *, frozen: bool | None = None) -> dict[str, object]:
    """Build a schema-1 report without probing physical devices or mutating state."""
    resolved_root = (root if root is not None else application_root()).resolve()
    frozen_mode = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    dependencies = _dependency_report()
    resources = (
        _resource_report(resolved_root)
        if frozen_mode
        else {
            "applicable": False,
            "ok": True,
            "policy_error": None,
            "required": [],
        }
    )
    pq = _pq_report()
    qt_ok = all(dependencies[name]["installed"] for name in ("QtPy", "PySide6-Essentials", "shiboken6"))
    dependencies_ok = all(item["installed"] for item in dependencies.values())
    report: dict[str, object] = {
        "schema_version": 1,
        "version": __version__,
        "distribution_mode": "frozen" if frozen_mode else "python",
        "application_root": str(resolved_root),
        "dependencies": dependencies,
        "qt": {"api_name": "PySide6", "ok": qt_ok},
        "resources": resources,
        "pq": pq,
        "capabilities": _capabilities_report(),
        "remediation": _remediation(dependencies, frozen_mode=frozen_mode),
    }
    report["ok"] = bool(dependencies_ok and qt_ok and resources["ok"] and pq["ok"])
    return report


def doctor_exit_code(report: dict[str, object]) -> int:
    """Return zero only for a positively healthy report."""
    return 0 if report.get("ok") is True else 1


def render_doctor_json(*, report: dict[str, object] | None = None, root: Path | None = None) -> str:
    """Render byte-stable compact JSON for the supplied or newly built report."""
    payload = report if report is not None else build_doctor_report(root=root)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
