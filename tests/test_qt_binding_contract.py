from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BANNED_BINDINGS = ("PyQt5", "PyQt6")
BANNED_IDENTIFIERS = ("pyqtSignal", "pyqtSlot", "pyqtProperty")


def test_calibrate_source_contains_no_pyqt_imports_or_identifiers() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "calibrate_pro").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                names = []
            if any(
                name == binding or name.startswith(binding + ".")
                for name in names
                for binding in BANNED_BINDINGS
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}:import")
            if isinstance(node, ast.Name) and node.id in BANNED_IDENTIFIERS:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.id}")
    assert offenders == []


def test_gui_extra_selects_build_ui_2_pyside() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"build-ui[pyside6]>=2,<3"' in text
    assert '"PySide6>=6.11.1,<7"' in text
    assert "PyQt5" not in text
    assert "PyQt6" not in text


def test_qt_api_is_forced_before_build_ui_import() -> None:
    code = """
import os
os.environ['QT_API'] = 'pyqt6'
from calibrate_pro.qt_runtime import configure_qt_api
assert configure_qt_api() == 'pyside6'
from build_ui.widgets import Card
from qtpy import API_NAME
assert API_NAME == 'PySide6'
print(Card.__name__)
"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Card"


def test_qt_api_rejects_an_already_loaded_wrong_binding() -> None:
    code = """
import sys
import types
fake_qtpy = types.ModuleType('qtpy')
fake_qtpy.API_NAME = 'PyQt6'
sys.modules['qtpy'] = fake_qtpy
sys.modules['PyQt6'] = types.ModuleType('PyQt6')
from calibrate_pro.qt_runtime import configure_qt_api
try:
    configure_qt_api()
except RuntimeError as exc:
    assert 'already loaded' in str(exc)
else:
    raise AssertionError('mixed Qt binding was accepted')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_gui_package_configures_qt_before_eager_imports() -> None:
    code = """
import os
import sys
os.environ['QT_API'] = 'pyqt6'

seen = []
class BindingOrderGuard:
    def find_spec(self, fullname, path, target=None):
        if fullname == 'PySide6' or fullname.startswith('PySide6.'):
            selected = os.environ.get('QT_API')
            seen.append((fullname, selected))
            if selected != 'pyside6':
                raise RuntimeError(f'PySide6 imported before deterministic selection: {selected}')
        return None

sys.meta_path.insert(0, BindingOrderGuard())
import calibrate_pro.gui
assert seen
assert os.environ['QT_API'] == 'pyside6'
from qtpy import API_NAME
assert API_NAME == 'PySide6'
print(API_NAME)
"""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PySide6"


def test_active_window_constructs_with_pyside(qapp, monkeypatch: pytest.MonkeyPatch) -> None:
    from calibrate_pro.gui.app import CalibrateProWindow

    monkeypatch.setattr(CalibrateProWindow, "_start_services", lambda self: setattr(self, "_guard", None))
    monkeypatch.setattr(CalibrateProWindow, "_check_first_run", lambda self: None)
    window = CalibrateProWindow()
    assert type(window).__module__.startswith("calibrate_pro")
    window.close()
