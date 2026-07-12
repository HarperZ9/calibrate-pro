"""Read-only startup monitor for saved calibration plans.

Startup code is intentionally observation-only.  It may inventory displays and
report saved calibration state, but it never applies DWM LUTs, gamma ramps,
DDC/CI values, ICC profiles, or launches a privileged helper.  Display changes
must enter the confirmed :mod:`calibrate_pro.actuation` workflow from an
interactive application surface.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

from calibrate_pro.utils.startup_manager import CalibrationConfig, DisplayCalibrationState, StartupManager

_LOG_INITIALIZED = False
_DISPLAY_DEVICE_ACTIVE = 0x00000001


def _get_logger() -> logging.Logger:
    """Return the lazily initialized startup-monitor logger."""
    global _LOG_INITIALIZED
    logger = logging.getLogger("CalibratePro.StartupMonitor")
    if not _LOG_INITIALIZED:
        log_dir = Path(os.environ.get("APPDATA", "")) / "CalibratePro" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "calibration_service.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        _LOG_INITIALIZED = True
    return logger


class DISPLAY_DEVICE(ctypes.Structure):
    """Win32 display inventory record used only for read-only enumeration."""

    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


def _enumerate_active_displays() -> list[dict[str, object]]:
    """Return read-only identity data for active Windows display adapters."""
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    results: list[dict[str, object]] = []
    device = DISPLAY_DEVICE()
    device.cb = ctypes.sizeof(device)
    index = 0
    while user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
        if device.StateFlags & _DISPLAY_DEVICE_ACTIVE:
            results.append(
                {
                    "device_name": device.DeviceName,
                    "device_string": device.DeviceString,
                    "device_id": device.DeviceID,
                    "state_flags": int(device.StateFlags),
                }
            )
        index += 1
    return results


def saved_calibration_inventory() -> tuple[DisplayCalibrationState, ...]:
    """Return saved plans without executing or modifying any of them."""
    manager = StartupManager()
    config: CalibrationConfig = manager.config
    return tuple(config.displays[key] for key in sorted(config.displays))


def report_saved_calibrations() -> int:
    """Log saved plan availability and return the number of pending plans."""
    logger = _get_logger()
    saved = saved_calibration_inventory()
    if not saved:
        logger.info("No saved display calibration plans found.")
        return 0
    for state in saved:
        logger.info(
            "Saved calibration pending interactive confirmation: display=%s id=%d hdr=%s lut=%s",
            state.display_name,
            state.display_id,
            state.hdr_mode,
            state.lut_path or "none",
        )
    logger.info("%d saved calibration plan(s) require interactive confirmation.", len(saved))
    return len(saved)


def apply_saved_calibrations() -> bool:
    """Compatibility shim that explicitly refuses automatic display mutation."""
    report_saved_calibrations()
    _get_logger().warning(
        "Automatic startup application is disabled; open Calibrate Pro to preview and confirm a fresh plan."
    )
    return False


def run_service(silent: bool = True) -> None:
    """Monitor display topology and report pending plans without actuating."""
    logger = _get_logger()
    if not silent:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(console)

    logger.info("Calibrate Pro read-only startup monitor starting")
    report_saved_calibrations()
    previous_ids = {str(item["device_name"]) for item in _enumerate_active_displays()}

    try:
        while True:
            time.sleep(30)
            current_ids = {str(item["device_name"]) for item in _enumerate_active_displays()}
            if current_ids != previous_ids:
                logger.info("Display topology changed; saved plans still require interactive confirmation.")
                report_saved_calibrations()
            previous_ids = current_ids
    except KeyboardInterrupt:
        logger.info("Startup monitor stopped by user.")


def start_service_command(args: list[str] | None = None) -> int:
    """Run the read-only startup monitor or print saved-plan inventory."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="calibration_loader",
        description="Calibrate Pro read-only startup monitor",
    )
    subparsers = parser.add_subparsers(dest="command")
    service = subparsers.add_parser("start-service", help="Monitor topology without changing display state")
    service.add_argument("--silent", action="store_true", help="Log to file without console output")
    subparsers.add_parser("inspect", aliases=["apply"], help="Report plans awaiting interactive confirmation")
    parsed = parser.parse_args(args)

    if parsed.command == "start-service":
        run_service(silent=parsed.silent)
        return 0
    if parsed.command in {"inspect", "apply"}:
        report_saved_calibrations()
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(start_service_command())
