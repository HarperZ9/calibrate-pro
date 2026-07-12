"""Compatibility and import-isolation gates for the public GUI facade."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_API = json.loads((ROOT / "tests/data/gui-public-api-1.0.json").read_text(encoding="utf-8"))


def _pyside_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["QT_API"] = "pyside6"
    environment["QT_QPA_PLATFORM"] = "offscreen"
    return environment


def test_gui_import_is_lazy_and_preserves_the_approved_public_api() -> None:
    probe = """
import json
import sys

import calibrate_pro.gui as gui

forbidden = [
    "calibrate_pro.gui.main_window",
    "calibrate_pro.gui.calibration_wizard",
    "calibrate_pro.gui.professional_calibration",
]
print(json.dumps({
    "all": gui.__all__,
    "loaded": [name for name in forbidden if name in sys.modules],
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=_pyside_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    assert payload["loaded"] == []
    assert set(payload["all"]) == {*PUBLIC_API, "CalibrateProWindow"}


def test_every_approved_gui_export_resolves_under_offscreen_pyside() -> None:
    probe = """
import json

import calibrate_pro.gui as gui

resolved = []
for name in gui.__all__:
    getattr(gui, name)
    resolved.append(name)
print(json.dumps(resolved))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        env=_pyside_environment(),
        check=True,
        capture_output=True,
        text=True,
    )
    assert set(json.loads(completed.stdout)) == {*PUBLIC_API, "CalibrateProWindow"}


def test_unknown_gui_export_raises_normal_attribute_error() -> None:
    import calibrate_pro.gui as gui

    try:
        _ = gui.DefinitelyNotAnExport
    except AttributeError as exc:
        assert exc.name == "DefinitelyNotAnExport"
    else:  # pragma: no cover - assertion branch
        raise AssertionError("unknown GUI export unexpectedly resolved")
