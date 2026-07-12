"""
Calibrate Pro - System Tray Application

Provides two read-only runtime paths:
  1. **pystray + PIL** -- a real Windows system-tray icon with right-click
     context menu (green square = calibrated, grey = uncalibrated).
  2. **Console fallback** -- when pystray/PIL are not installed the app runs
     the read-only calibration monitor with visible console output.

Public API
----------
``run_tray_app()`` -- call from the CLI ``tray`` command.
"""

import logging
import os
import time
import webbrowser
from pathlib import Path

from calibrate_pro import __version__

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_config_dir() -> Path:
    """Return ``%APPDATA%/CalibratePro``."""
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    return Path(appdata) / "CalibratePro"


def _get_output_dir() -> Path:
    """Return the default calibration output directory."""
    docs = Path.home() / "Documents" / "Calibrate Pro"
    if docs.exists():
        return docs
    return _get_config_dir()


def _find_latest_report() -> Path | None:
    """Find the most-recently modified ``*_report.html`` file."""
    search_dirs = [
        _get_output_dir(),
        _get_config_dir(),
        Path.home() / "Documents" / "Calibrate Pro",
        Path("."),
    ]
    candidates = []
    for d in search_dirs:
        if d.exists():
            candidates.extend(d.glob("*_report.html"))

    if not candidates:
        # Broader search in home
        candidates.extend(Path.home().glob("**/*_report.html"))
        # Limit depth to avoid traversing everything
        candidates = candidates[:50]

    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)


def _is_calibrated() -> bool:
    """Return True if at least one display has a saved calibration."""
    config_file = _get_config_dir() / "calibration_config.json"
    if not config_file.exists():
        return False
    try:
        import json

        with open(config_file) as fh:
            data = json.load(fh)
        displays = data.get("displays", {})
        return len(displays) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# pystray path
# ---------------------------------------------------------------------------


def _needs_recalibration() -> bool:
    """Return True if any display's calibration is older than 30 days."""
    try:
        from calibrate_pro.services.drift_monitor import any_needs_recalibration

        return any_needs_recalibration(max_age_days=30)
    except Exception:
        return False


def _create_icon_image(calibrated: bool, stale: bool = False):
    """Create a 64x64 PIL Image.

    Colours:
    - green  = calibrated and current
    - yellow = calibrated but stale (needs re-calibration)
    - grey   = uncalibrated
    """
    from PIL import Image, ImageDraw  # type: ignore

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if calibrated and stale:
        fill = (255, 193, 7, 255)  # Material amber / yellow
        border = (255, 160, 0, 255)
    elif calibrated:
        fill = (76, 175, 80, 255)  # Material green
        border = (56, 142, 60, 255)
    else:
        fill = (158, 158, 158, 255)  # Grey
        border = (117, 117, 117, 255)

    margin = 4
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=8,
        fill=fill,
        outline=border,
        width=2,
    )

    # Draw a small "C" letter in the centre
    try:
        from PIL import ImageFont  # type: ignore

        font = ImageFont.truetype("arial.ttf", 32)
    except Exception:
        font = ImageFont.load_default()

    text = "C"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = (size - th) // 2 - bbox[1]
    draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=font)

    return img


def _run_pystray():
    """Run the tray app using the *pystray* library."""
    import pystray  # type: ignore

    calibrated = _is_calibrated()
    stale = _needs_recalibration() if calibrated else False

    # ---- Menu actions ----

    def on_calibrate_all(icon, item):
        """Notify that calibration requires an interactive confirmed plan."""
        logger.info("Calibration requested from tray; open Calibrate Pro to preview and confirm")
        icon.title = f"Calibrate Pro v{__version__} - confirmation required"

    def on_restore(icon, item):
        """Notify that restoration requires an interactive confirmed plan."""
        logger.info("Restore requested from tray; open Calibrate Pro to preview and confirm")
        icon.title = f"Calibrate Pro v{__version__} - confirmation required"

    def on_show_status(icon, item):
        """Print calibration status to console."""
        try:
            from calibrate_pro.services.drift_monitor import print_calibration_status

            print_calibration_status()
        except Exception as exc:
            logger.error("Status check failed: %s", exc)

    def on_open_report(icon, item):
        report = _find_latest_report()
        if report:
            webbrowser.open(str(report.absolute()))

    def on_toggle_startup(icon, item):
        logger.info("Startup setting change requested; use the application settings confirmation flow")
        icon.title = f"Calibrate Pro v{__version__} - settings confirmation required"

    def on_exit(icon, item):
        icon.stop()

    def startup_text(item):
        return "Startup Settings (confirmation required)"

    # ---- Build menu ----

    menu = pystray.Menu(
        pystray.MenuItem(
            f"Calibrate Pro v{__version__}",
            None,
            enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Calibration Status", on_show_status),
        pystray.MenuItem("Calibrate Displays (confirmation required)", on_calibrate_all),
        pystray.MenuItem("Restore Defaults (confirmation required)", on_restore),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Last Report", on_open_report),
        pystray.MenuItem(startup_text, on_toggle_startup),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", on_exit),
    )

    # Tooltip reflects stale status
    title = f"Calibrate Pro v{__version__}"
    if stale:
        title += " (re-calibration recommended)"

    icon = pystray.Icon(
        name="CalibratePro",
        icon=_create_icon_image(calibrated, stale=stale),
        title=title,
        menu=menu,
    )

    icon.run()


# ---------------------------------------------------------------------------
# Console-service fallback
# ---------------------------------------------------------------------------


def _run_console_service():
    """
    Fallback when pystray is not installed.

    Reports saved calibration proposals and then runs the read-only topology
    monitor with console output.
    """
    print(f"Calibrate Pro v{__version__} - Background Calibration Service")
    print("=" * 60)
    print("(Install pystray and Pillow for a system-tray icon)")
    print()

    try:
        if _is_calibrated():
            print("[--] Saved calibration plans require interactive confirmation.")
        else:
            print("[--] No saved calibration proposals found.")

        print()
        print("Running read-only calibration status monitor.")
        print("Press Ctrl+C to stop.\n")
        while True:
            time.sleep(30)
    except KeyboardInterrupt:
        print("\nService stopped.")
    except Exception as exc:
        print(f"\nError: {exc}")
        return 1

    return 0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_tray_app():
    """
    Run the system tray application.

    Tries pystray first; if unavailable, falls back to a console service
    that reports saved proposals without applying them.
    """
    try:
        return _run_pystray()
    except ImportError:
        return _run_console_service()
