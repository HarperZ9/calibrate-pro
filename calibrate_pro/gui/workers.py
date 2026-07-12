"""
Background Workers - Calibrate Pro

Thread-based workers for long-running calibration operations and
color management state tracking.
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import QThread, Signal

# Calibration Worker Thread


class CalibrationWorker(QThread):
    """Background thread for running calibration."""

    progress = Signal(str, float)  # message, progress (0-1)
    finished = Signal(object)  # result object
    error = Signal(str)  # error message

    def __init__(
        self, display_index: int = 0, apply_ddc: bool = False, profile_name: str = None, display_name: str = None
    ):
        super().__init__()
        self.display_index = display_index
        self.apply_ddc = apply_ddc
        self.profile_name = profile_name
        self.display_name = display_name
        self._result = None

    def run(self):
        try:
            from calibrate_pro.workflow import ApplyPlan, CalibrationMethod

            self.progress.emit("Building calibration preview", 0.5)
            plan = ApplyPlan(
                display_id=str(self.display_index),
                method=CalibrationMethod.SENSORLESS,
                target_whitepoint="D65",
                target_gamma="2.2",
                target_gamut="sRGB",
            )
            result = SimpleNamespace(
                success=True,
                preview_only=True,
                message="Preview ready — no display settings were changed. Explicit confirmation is required.",
                plan=plan,
            )
            self.progress.emit("Preview ready", 1.0)
            self.finished.emit(result)

        except Exception as e:
            self.error.emit(str(e))


# Color Management Status Tracker


class ColorManagementStatus:
    """Tracks the current state of color management (ICC profiles and LUTs)."""

    def __init__(self):
        self.active_icc_profile: str | None = None
        self.active_lut: str | None = None
        self.lut_method: str | None = None  # dwm_lut, NVAPI, etc.
        self.displays: dict[str, dict[str, Any]] = {}

    def set_icc_profile(self, display_id: str, profile_path: str):
        if display_id not in self.displays:
            self.displays[display_id] = {}
        self.displays[display_id]["icc_profile"] = profile_path
        self.active_icc_profile = profile_path

    def set_lut(self, display_id: str, lut_path: str, method: str = "dwm_lut"):
        if display_id not in self.displays:
            self.displays[display_id] = {}
        self.displays[display_id]["lut"] = lut_path
        self.displays[display_id]["lut_method"] = method
        self.active_lut = lut_path
        self.lut_method = method

    def clear_lut(self, display_id: str):
        if display_id in self.displays:
            self.displays[display_id].pop("lut", None)
            self.displays[display_id].pop("lut_method", None)
        self.active_lut = None
        self.lut_method = None

    def is_active(self) -> bool:
        return self.active_icc_profile is not None or self.active_lut is not None

    def get_status_text(self) -> str:
        parts = []
        if self.active_icc_profile:
            name = Path(self.active_icc_profile).stem if self.active_icc_profile else "None"
            parts.append(f"ICC: {name}")
        if self.active_lut:
            name = Path(self.active_lut).stem if self.active_lut else "None"
            parts.append(f"LUT: {name} ({self.lut_method})")
        return " | ".join(parts) if parts else "No color management active"
