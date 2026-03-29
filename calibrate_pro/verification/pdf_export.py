"""
PDF Export — Calibrate Pro

Exports HTML verification/calibration reports to PDF.

Strategy (in order of preference):
1. Use QWebEngineView's printToPdf() if PyQt6-WebEngine is available
2. Fall back to opening the HTML in the system browser for manual print-to-PDF
3. Last resort: save the HTML and inform the user

Usage:
    from calibrate_pro.verification.pdf_export import export_report_pdf
    success = export_report_pdf(html_content, "/path/to/report.pdf")
"""

import logging
import webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)


def _try_qt_webengine_pdf(html_content: str, output_path: str) -> bool:
    """
    Attempt to render HTML to PDF using Qt WebEngine.

    This blocks via a local event loop until the PDF is written.
    Returns True on success, False if WebEngine is unavailable or fails.
    """
    try:
        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        from PyQt6.QtWidgets import QApplication

        # Ensure a QApplication exists
        app = QApplication.instance()
        if app is None:
            return False

        view = QWebEngineView()
        view.setHtml(html_content)

        loop = QEventLoop()
        pdf_written = [False]

        def _on_load_finished(ok: bool):
            if not ok:
                loop.quit()
                return
            # Small delay to let rendering settle
            QTimer.singleShot(500, _do_print)

        def _do_print():
            view.page().printToPdf(output_path)

        def _on_pdf_printing_finished(file_path: str, success: bool):
            pdf_written[0] = success
            loop.quit()

        view.loadFinished.connect(_on_load_finished)
        view.page().pdfPrintingFinished.connect(_on_pdf_printing_finished)

        # Timeout after 30 seconds
        QTimer.singleShot(30_000, loop.quit)
        loop.exec()

        view.deleteLater()
        return pdf_written[0]

    except ImportError:
        logger.debug("PyQt6-WebEngine not available for PDF export")
        return False
    except Exception as e:
        logger.warning("Qt WebEngine PDF export failed: %s", e)
        return False


def _fallback_browser_print(html_content: str, output_path: str) -> bool:
    """
    Save the HTML to a temporary file and open it in the system browser.

    The user can then use the browser's built-in print-to-PDF.
    Returns True (the file was opened), but the user must complete the PDF
    save manually.
    """
    try:
        # Write HTML next to the intended PDF output for easy access
        html_path = Path(output_path).with_suffix(".html")
        html_path.write_text(html_content, encoding="utf-8")
        webbrowser.open(html_path.as_uri())
        return True
    except Exception as e:
        logger.warning("Browser fallback failed: %s", e)
        return False


def _save_html_fallback(html_content: str, output_path: str) -> bool:
    """
    Last resort: save the HTML file beside the requested PDF path.
    """
    try:
        html_path = Path(output_path).with_suffix(".html")
        html_path.write_text(html_content, encoding="utf-8")
        return True
    except Exception as e:
        logger.error("Could not save HTML fallback: %s", e)
        return False


def export_report_pdf(html_content: str, output_path: str) -> bool:
    """
    Export an HTML report to PDF.

    Tries the following strategies in order:
    1. Qt WebEngine printToPdf (silent, automatic)
    2. System browser (opens for manual print-to-PDF)
    3. Save HTML alongside the requested PDF path

    Args:
        html_content: Full HTML document string.
        output_path:  Desired PDF file path (e.g., "report.pdf").

    Returns:
        True if the PDF was written (strategy 1) or the HTML was opened
        in a browser / saved for the user to print manually (strategies 2-3).
        False only if everything failed.
    """
    output_path = str(Path(output_path).resolve())

    # Ensure parent directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Strategy 1: Qt WebEngine
    if _try_qt_webengine_pdf(html_content, output_path):
        logger.info("PDF exported via Qt WebEngine: %s", output_path)
        return True

    # Strategy 2: System browser
    if _fallback_browser_print(html_content, output_path):
        logger.info(
            "Opened HTML in browser for manual PDF print. HTML saved at: %s",
            Path(output_path).with_suffix(".html"),
        )
        return True

    # Strategy 3: Save HTML
    if _save_html_fallback(html_content, output_path):
        logger.info(
            "Saved HTML report (open and print to PDF): %s",
            Path(output_path).with_suffix(".html"),
        )
        return True

    return False
