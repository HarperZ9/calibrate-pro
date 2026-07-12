"""Synchronous, offline PDF export for Calibrate Pro HTML reports.

The primary path renders with Qt's rich-text engine and PrintSupport. If no Qt
application is active, or PDF conversion fails, the report is saved as HTML
beside the requested PDF without launching an external browser.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _try_qt_printsupport_pdf(html_content: str, output_path: str) -> bool:
    """Synchronously render HTML through QTextDocument and QPrinter."""
    try:
        from PySide6.QtCore import QMarginsF
        from PySide6.QtGui import QFontDatabase, QPageLayout, QPageSize, QTextDocument
        from PySide6.QtPrintSupport import QPrinter, QPrinterInfo
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            return False
        if not QFontDatabase.families():
            logger.debug("Qt has no usable fonts; refusing to emit an unreadable PDF")
            return False

        pdf_printer_names = sorted(
            (name for name in QPrinterInfo.availablePrinterNames() if "pdf" in name.casefold()),
            key=str.casefold,
        )
        if not pdf_printer_names:
            logger.debug("No local PDF printer identity is available for deterministic QPrinter setup")
            return False
        printer_name = next(
            (name for name in pdf_printer_names if name.casefold() == "microsoft print to pdf"),
            pdf_printer_names[0],
        )
        printer_info = QPrinterInfo.printerInfo(printer_name)
        if printer_info.isNull():
            return False

        printer = QPrinter(printer_info, QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(output_path)
        printer.setResolution(300)
        printer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        printer.setPageMargins(QMarginsF(15.0, 15.0, 15.0, 15.0), QPageLayout.Unit.Millimeter)

        document = QTextDocument()
        document.setDocumentMargin(0.0)
        document.setHtml(html_content)
        document.print_(printer)

        output = Path(output_path)
        if output.is_file() and output.stat().st_size > 5:
            with output.open("rb") as stream:
                return stream.read(5) == b"%PDF-"
        return False
    except ImportError:
        logger.debug("PySide6 PrintSupport is not available for PDF export")
        return False
    except Exception as exc:
        logger.warning("Qt PrintSupport PDF export failed: %s", exc)
        return False


def _save_html_fallback(html_content: str, output_path: str) -> bool:
    """Save HTML beside the requested PDF path without opening a browser."""
    try:
        html_path = Path(output_path).with_suffix(".html")
        html_path.write_text(html_content, encoding="utf-8")
        return True
    except Exception as exc:
        logger.error("Could not save HTML fallback: %s", exc)
        return False


def export_report_pdf(html_content: str, output_path: str) -> bool:
    """
    Export an HTML report to PDF.

    The function first attempts synchronous Qt PrintSupport output. If that is
    unavailable, it saves HTML alongside the requested PDF path. It never opens
    a browser automatically.

    Args:
        html_content: Full HTML document string.
        output_path:  Desired PDF file path (e.g., "report.pdf").

    Returns:
        True if either the PDF or the HTML fallback was written; otherwise False.
    """
    output_path = str(Path(output_path).resolve())

    # Ensure parent directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if _try_qt_printsupport_pdf(html_content, output_path):
        logger.info("PDF exported via Qt PrintSupport: %s", output_path)
        return True

    if _save_html_fallback(html_content, output_path):
        logger.info(
            "Saved HTML report fallback (open and print to PDF manually): %s",
            Path(output_path).with_suffix(".html"),
        )
        return True

    return False
