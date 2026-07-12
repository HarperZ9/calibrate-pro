"""Shared unelevated GUI command for source and frozen entrypoints."""

from __future__ import annotations

import sys
from collections.abc import Sequence


def run(args: Sequence[str] | None = None) -> int:
    """Launch the proposal-and-confirmation desktop shell with PySide6."""
    from calibrate_pro.qt_runtime import configure_qt_api

    configure_qt_api()
    try:
        from PySide6.QtWidgets import QApplication

        from calibrate_pro.gui.app import CalibrateProWindow
    except ImportError as exc:
        print(f"Calibrate Pro GUI dependencies are unavailable: {exc}", file=sys.stderr)
        return 1

    argv = [sys.argv[0], *(args or [])]
    application = QApplication.instance() or QApplication(argv)
    window = CalibrateProWindow()
    window.show()
    return int(application.exec())
