"""Focused, offscreen tests for deterministic report PDF export."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from calibrate_pro.verification import pdf_export

ROOT = Path(__file__).resolve().parents[1]

SAMPLE_HTML = """\
<!doctype html>
<html>
  <head><meta charset="utf-8"><title>Calibration receipt</title></head>
  <body><h1>Calibration receipt</h1><p>Display: Reference Panel</p></body>
</html>
"""


def test_pdf_export_source_uses_printsupport_without_browser_or_webengine() -> None:
    source = (ROOT / "calibrate_pro/verification/pdf_export.py").read_text(encoding="utf-8")

    assert "QTextDocument" in source
    assert "QPrinter" in source
    assert "QPrinterInfo" in source
    assert "QtWebEngine" not in source
    assert "webbrowser" not in source


@pytest.mark.skipif(os.name != "nt", reason="Windows release PDF path")
def test_offscreen_export_fails_closed_when_qt_has_no_fonts(tmp_path: Path, qapp: object) -> None:
    from PySide6.QtGui import QFontDatabase

    assert QFontDatabase.families() == []
    output = tmp_path / "calibration-receipt.pdf"

    assert pdf_export._try_qt_printsupport_pdf(SAMPLE_HTML, str(output)) is False
    assert not output.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows release PDF path")
def test_printsupport_export_writes_a_complete_pdf(tmp_path: Path) -> None:
    output = tmp_path / "calibration-receipt.pdf"
    code = f"""
from PySide6.QtWidgets import QApplication
from calibrate_pro.verification.pdf_export import _try_qt_printsupport_pdf

app = QApplication.instance() or QApplication([])
raise SystemExit(0 if _try_qt_printsupport_pdf({SAMPLE_HTML!r}, {str(output)!r}) else 1)
"""
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "QT_API": "pyside6",
        "QT_QPA_PLATFORM": "windows",
    }

    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    payload = output.read_bytes()
    assert payload.startswith(b"%PDF-")
    assert payload.rstrip().endswith(b"%%EOF")
    assert not output.with_suffix(".html").exists()


def test_failed_pdf_conversion_saves_html_without_opening_a_browser(
    tmp_path: Path,
    monkeypatch,
) -> None:
    output = tmp_path / "fallback.pdf"
    opened: list[str] = []
    monkeypatch.setattr(pdf_export, "_try_qt_printsupport_pdf", lambda *_args: False, raising=False)
    monkeypatch.setattr(pdf_export, "_try_qt_webengine_pdf", lambda *_args: False, raising=False)
    if hasattr(pdf_export, "webbrowser"):
        monkeypatch.setattr(pdf_export.webbrowser, "open", lambda uri: opened.append(uri) or True)

    assert pdf_export.export_report_pdf(SAMPLE_HTML, str(output)) is True
    assert output.with_suffix(".html").read_text(encoding="utf-8") == SAMPLE_HTML
    assert not output.exists()
    assert opened == []
