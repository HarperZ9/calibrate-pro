"""Deterministic Qt binding selection for Calibrate Pro."""

from __future__ import annotations

import os
import sys

QT_API = "pyside6"


def configure_qt_api() -> str:
    """Select PySide6 before QtPy or Build UI imports."""
    qtpy = sys.modules.get("qtpy")
    loaded_api = getattr(qtpy, "API_NAME", None) if qtpy is not None else None
    wrong_modules = sorted(
        name for name in sys.modules if name in {"PyQt5", "PyQt6"} or name.startswith(("PyQt5.", "PyQt6."))
    )
    if wrong_modules or (loaded_api is not None and loaded_api != "PySide6"):
        detail = loaded_api or wrong_modules[0]
        raise RuntimeError(f"A non-PySide Qt binding is already loaded: {detail}")
    os.environ["QT_API"] = QT_API
    return QT_API
