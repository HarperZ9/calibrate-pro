"""Read-only compatibility surface for the retired LUT auto-loader.

Automatic LUT application at process startup is intentionally disabled.  The
interactive confirmed-actuation workflow owns every display mutation, while
this module can only report saved plans and legacy startup-registration state.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from calibrate_pro.utils.startup_manager import StartupManager

_DISABLED_MESSAGE = (
    "Legacy LUT auto-load is disabled. Use Calibrate Pro to preview and confirm "
    "a fresh apply plan; startup registration is managed only by StartupManager."
)


def setup_logging() -> logging.Logger:
    """Configure the read-only startup inventory logger."""
    log_dir = Path(os.environ.get("APPDATA", "")) / "CalibratePro" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_dir / "autoload.log"), logging.StreamHandler()],
    )
    return logging.getLogger("CalibratePro.AutoLoad")


def load_calibration_luts() -> bool:
    """Report saved LUT plans without loading or changing display state."""
    logger = setup_logging()
    displays = StartupManager().config.displays
    for key in sorted(displays):
        state = displays[key]
        logger.info(
            "Pending plan: display=%s id=%d lut=%s",
            state.display_name,
            state.display_id,
            state.lut_path or "none",
        )
    logger.warning(_DISABLED_MESSAGE)
    return False


def create_startup_shortcut() -> tuple[bool, str]:
    """Refuse the duplicate legacy startup-registration writer."""
    return False, _DISABLED_MESSAGE


def remove_startup() -> bool:
    """Refuse the duplicate legacy startup-registration writer."""
    setup_logging().warning(_DISABLED_MESSAGE)
    return False


def check_startup_enabled() -> tuple[bool, str | None]:
    """Read the retired legacy value without creating, changing, or deleting it."""
    if os.name != "nt":
        return False, None
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "CalibratePro_LUT_AutoLoad")
            return True, str(value)
    except (FileNotFoundError, OSError):
        return False, None


def main(args: list[str] | None = None) -> int:
    """Expose inventory/status commands; mutation flags fail explicitly."""
    import argparse

    parser = argparse.ArgumentParser(description="Calibrate Pro retired LUT auto-loader")
    parser.add_argument("--install", action="store_true", help="Report how startup is now managed")
    parser.add_argument("--uninstall", action="store_true", help="Report how startup is now managed")
    parser.add_argument("--status", action="store_true", help="Read legacy startup status")
    parser.add_argument("--load", action="store_true", help="Inventory saved LUT plans without applying")
    parsed = parser.parse_args(args)

    if parsed.install or parsed.uninstall:
        print(_DISABLED_MESSAGE)
        return 2
    if parsed.status:
        enabled, path = check_startup_enabled()
        print(f"Legacy auto-load value: {'present' if enabled else 'absent'}{f' ({path})' if path else ''}")
        return 0
    load_calibration_luts()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
