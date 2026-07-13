"""Render the deterministic Calibrate Pro simulated preview to a PNG."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_API"] = "pyside6"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from calibrate_pro.gui.app import CalibrateProWindow


def install_preview_font() -> str:
    """Load a Windows UI font explicitly for reliable offscreen text rendering."""
    fonts_dir = Path(os.environ.get("WINDIR", "")) / "Fonts"
    for filename in ("segoeui.ttf", "arial.ttf"):
        font_id = QFontDatabase.addApplicationFont(str(fonts_dir / filename))
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                return families[0]
    return ""


def render_preview(output_path: Path) -> int:
    """Render one populated 1440 by 900 preview and validate the output."""
    app = QApplication.instance() or QApplication([])
    font_family = install_preview_font()
    if not font_family:
        return 1

    window = CalibrateProWindow(preview_mode=True)
    window.resize(1440, 900)
    window.show()

    for _ in range(100):
        app.processEvents()
        if window.dashboard.preview_populated:
            break

    if not window.dashboard.preview_populated:
        window.close()
        return 1

    for _ in range(20):
        app.processEvents()

    card_item = window.dashboard._cards_layout.itemAt(0)
    card = card_item.widget() if card_item is not None else None
    if card is None or not card.isVisible() or card.height() < 100:
        window.close()
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    saved = window.grab().save(str(output_path), "PNG")
    app.processEvents()
    window.close()
    app.processEvents()

    if not saved or not output_path.is_file() or output_path.stat().st_size == 0:
        return 1

    print(f"{output_path} {output_path.stat().st_size} bytes font={font_family} layout=settled")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="PNG output path")
    args = parser.parse_args(argv)
    return render_preview(args.out.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
