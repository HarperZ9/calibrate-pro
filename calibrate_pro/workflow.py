"""Pure calibration workflow state and capability gating."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
DDC_WRITE_CODES = frozenset(
    {
        "BRIGHTNESS",
        "CONTRAST",
        "RED_GAIN",
        "GREEN_GAIN",
        "BLUE_GAIN",
        "RED_BLACK_LEVEL",
        "GREEN_BLACK_LEVEL",
        "BLUE_BLACK_LEVEL",
    }
)


class WorkflowStage(str, Enum):
    """Ordered user-visible calibration stages."""

    DETECT = "detect"
    METHOD = "method"
    PREVIEW = "preview"
    APPLY = "apply"
    VERIFY = "verify"
    SAVE_REPORT = "save_report"


class CalibrationMethod(str, Enum):
    """Supported calibration evidence paths."""

    SENSORLESS = "sensorless"
    MEASURED = "measured"


class DwmLutKind(str, Enum):
    """Windows DWM LUT processing domains."""

    SDR = "sdr"
    HDR = "hdr"


def _validate_asset_pair(path: str | None, digest: str | None, *, path_name: str, digest_name: str) -> None:
    if path is None:
        if digest is not None:
            raise ValueError(f"{digest_name} requires {path_name}")
        return
    if not isinstance(path, str) or not path.strip():
        raise ValueError(f"{path_name} must be a non-empty path")
    if digest is None:
        raise ValueError(f"{path_name} requires {digest_name}")
    if not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
        raise ValueError(f"{digest_name} must be a canonical lowercase SHA-256 digest")


@dataclass(frozen=True)
class ApplyPlan:
    """A complete immutable proposal, including exact external-asset digests."""

    display_id: str
    method: CalibrationMethod
    target_whitepoint: str
    target_gamma: str
    target_gamut: str
    ddc_changes: tuple[tuple[str, int], ...] = ()
    icc_profile_path: str | None = None
    icc_profile_sha256: str | None = None
    vcgt_path: str | None = None
    vcgt_sha256: str | None = None
    dwm_lut_path: str | None = None
    dwm_lut_kind: DwmLutKind | None = None
    dwm_lut_sha256: str | None = None
    clear_existing_lut: bool = False
    output_files: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, text_value in (
            ("display_id", self.display_id),
            ("target_whitepoint", self.target_whitepoint),
            ("target_gamma", self.target_gamma),
            ("target_gamut", self.target_gamut),
        ):
            if type(text_value) is not str:
                raise TypeError(f"{name} must be an exact string")
            if not text_value.strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.method, CalibrationMethod):
            raise TypeError("method must be a CalibrationMethod")
        if type(self.clear_existing_lut) is not bool:
            raise TypeError("clear_existing_lut must be an exact boolean")
        if type(self.output_files) is not tuple:
            raise TypeError("output_files must be an exact tuple")
        for output_file in self.output_files:
            if type(output_file) is not str:
                raise TypeError("each output file must be an exact string")
            if not output_file.strip():
                raise ValueError("each output file must be non-empty")
        if type(self.ddc_changes) is not tuple:
            raise TypeError("ddc_changes must be an exact tuple")
        seen_ddc_codes: set[str] = set()
        for change in self.ddc_changes:
            if type(change) is not tuple or len(change) != 2:
                raise TypeError("each DDC change must be an exact two-item tuple")
            code, value = change
            if type(code) is not str or code not in DDC_WRITE_CODES:
                raise ValueError("DDC code must be a canonical allowlisted calibration control")
            if code in seen_ddc_codes:
                raise ValueError(f"duplicate DDC code: {code}")
            seen_ddc_codes.add(code)
            if type(value) is not int:
                raise TypeError("DDC target value must be an exact integer")
            if not 0 <= value <= 65535:
                raise ValueError("DDC target value must be between 0 and 65535")
        _validate_asset_pair(
            self.icc_profile_path,
            self.icc_profile_sha256,
            path_name="icc_profile_path",
            digest_name="icc_profile_sha256",
        )
        _validate_asset_pair(
            self.vcgt_path,
            self.vcgt_sha256,
            path_name="vcgt_path",
            digest_name="vcgt_sha256",
        )
        _validate_asset_pair(
            self.dwm_lut_path,
            self.dwm_lut_sha256,
            path_name="dwm_lut_path",
            digest_name="dwm_lut_sha256",
        )
        if self.dwm_lut_path is None:
            if self.dwm_lut_kind is not None:
                raise ValueError("dwm_lut_kind requires dwm_lut_path")
        elif not isinstance(self.dwm_lut_kind, DwmLutKind):
            raise ValueError("dwm_lut_path requires dwm_lut_kind")
        if self.clear_existing_lut and self.dwm_lut_path is not None:
            raise ValueError("clear_existing_lut cannot be combined with dwm_lut_path")


@dataclass(frozen=True)
class CapabilityState:
    """Detected support for workflow, write, and authoritative-capture capabilities."""

    sensor_available: bool
    ddc_available: bool
    dwm_lut_available: bool
    dwm_state_capture_available: bool
    profile_write_available: bool
    vcgt_available: bool

    def __post_init__(self) -> None:
        for name, value in (
            ("sensor_available", self.sensor_available),
            ("ddc_available", self.ddc_available),
            ("dwm_lut_available", self.dwm_lut_available),
            ("dwm_state_capture_available", self.dwm_state_capture_available),
            ("profile_write_available", self.profile_write_available),
            ("vcgt_available", self.vcgt_available),
        ):
            if type(value) is not bool:
                raise TypeError(f"{name} must be an exact boolean")

    def disabled_reason(self, method: CalibrationMethod) -> str | None:
        if not isinstance(method, CalibrationMethod):
            raise TypeError("method must be a CalibrationMethod")
        if method is CalibrationMethod.MEASURED and not self.sensor_available:
            return "Measured calibration requires a supported colorimeter."
        return None

    def validate(self, plan: ApplyPlan) -> None:
        reason = self.disabled_reason(plan.method)
        if reason is not None:
            raise ValueError(reason)
        dwm_requested = plan.dwm_lut_path is not None or plan.clear_existing_lut
        checks = (
            (bool(plan.ddc_changes), self.ddc_available, "DDC/CI writes are unavailable for this display."),
            (dwm_requested, self.dwm_lut_available, "DWM LUT writes are unavailable for this display."),
            (
                dwm_requested,
                self.dwm_state_capture_available,
                "DWM LUT application requires authoritative prior-state capture.",
            ),
            (
                plan.icc_profile_path is not None,
                self.profile_write_available,
                "ICC profile association is unavailable.",
            ),
            (plan.vcgt_path is not None, self.vcgt_available, "Display gamma ramp application is unavailable."),
        )
        for requested, available, reason in checks:
            if requested and not available:
                raise ValueError(reason)


class WorkflowController:
    """Pure state machine; it never imports or invokes an actuator."""

    def __init__(self, capabilities: CapabilityState) -> None:
        self.capabilities = capabilities
        self.stage = WorkflowStage.DETECT
        self.method: CalibrationMethod | None = None
        self.preview: ApplyPlan | None = None

    def detect_complete(self) -> None:
        if self.stage is not WorkflowStage.DETECT:
            raise ValueError("detect can complete only from the detect stage")
        self.stage = WorkflowStage.METHOD

    def select_method(self, method: CalibrationMethod) -> None:
        if self.stage is not WorkflowStage.METHOD:
            raise ValueError("method selection requires the method stage")
        reason = self.capabilities.disabled_reason(method)
        if reason is not None:
            raise ValueError(reason)
        self.method = method
        self.stage = WorkflowStage.PREVIEW

    def set_preview(self, plan: ApplyPlan) -> None:
        if self.stage is not WorkflowStage.PREVIEW:
            raise ValueError("preview data requires the preview stage")
        if not isinstance(plan.method, CalibrationMethod):
            raise TypeError("plan method must be a CalibrationMethod")
        if plan.method is not self.method:
            raise ValueError("preview method does not match the selected method")
        if not isinstance(plan.display_id, str) or not plan.display_id.strip():
            raise ValueError("preview requires a non-empty display_id")
        self.capabilities.validate(plan)
        self.preview = plan

    def confirm_apply(self) -> None:
        if self.stage is not WorkflowStage.PREVIEW or self.preview is None:
            raise ValueError("apply requires a completed preview")
        self.stage = WorkflowStage.APPLY

    def apply_complete(self) -> None:
        if self.stage is not WorkflowStage.APPLY:
            raise ValueError("apply completion requires the apply stage")
        self.stage = WorkflowStage.VERIFY

    def verify_complete(self) -> None:
        if self.stage is not WorkflowStage.VERIFY:
            raise ValueError("verification completion requires the verify stage")
        self.stage = WorkflowStage.SAVE_REPORT
