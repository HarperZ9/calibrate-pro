"""What a DDC/CI backup has to hold before the sensorless engine may write.

The sensorless engine changes monitor controls over DDC/CI in two places: the
OSD auto-setup (picture mode, colour preset, gamma, brightness, contrast, black
levels or gains) and the correction step (colour preset, brightness, contrast,
RGB gains). A write is allowed only when the engine itself has just read the
current value of every control that write can touch. A flag that says "a
backup was made" is never enough: the engine checks the backup it holds.
"""

from __future__ import annotations

from typing import Any

# Name -> VCPCode attribute. These are read for the backup and written back by
# restore_original_settings().
BACKUP_CODES: dict[str, str] = {
    "brightness": "BRIGHTNESS",
    "contrast": "CONTRAST",
    "red_gain": "RED_GAIN",
    "green_gain": "GREEN_GAIN",
    "blue_gain": "BLUE_GAIN",
    "color_preset": "COLOR_PRESET",
    "red_black_level": "RED_BLACK_LEVEL",
    "green_black_level": "GREEN_BLACK_LEVEL",
    "blue_black_level": "BLUE_BLACK_LEVEL",
    "image_mode": "IMAGE_MODE",
    "gamma": "GAMMA",
}

CORRECTION_WRITES = ("color_preset", "brightness", "contrast", "red_gain", "green_gain", "blue_gain")

_GENERIC_SETUP_WRITES = ("brightness", "contrast", "red_gain", "green_gain", "blue_gain")
_PANEL_SETUP_WRITES = ("brightness", "contrast", "red_black_level", "green_black_level", "blue_black_level")


def auto_setup_writes(recommendations: Any) -> tuple[str, ...]:
    """The controls `DDCCIController.auto_setup_for_calibration` writes for these recommendations."""
    if not recommendations:
        return _GENERIC_SETUP_WRITES
    names = list(_PANEL_SETUP_WRITES)
    if getattr(recommendations, "picture_mode_vcp", None) is not None:
        names.append("image_mode")
    if getattr(recommendations, "color_preset_vcp", None) is not None:
        names.append("color_preset")
    if getattr(recommendations, "gamma_vcp_value", None) is not None:
        names.append("gamma")
    return tuple(names)


def missing_from_backup(backup: dict[str, Any] | None, names) -> list[str]:
    """The names in `names` that the backup does not hold a readable current value for."""
    backup = backup or {}
    missing = []
    for name in names:
        entry = backup.get(name)
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("current"), int)
            or isinstance(entry.get("current"), bool)
        ):
            missing.append(name)
    return missing
