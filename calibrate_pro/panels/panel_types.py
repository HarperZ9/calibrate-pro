"""
Panel characterization data types.

Defines the dataclasses used to describe panel characteristics
for sensorless calibration: chromaticity coordinates, primaries,
gamma curves, capabilities, DDC recommendations, and the full
PanelCharacterization container.
"""

import re
from dataclasses import asdict, dataclass, field


@dataclass
class ChromaticityCoord:
    """CIE 1931 xy chromaticity coordinate."""
    x: float
    y: float

    def as_tuple(self) -> tuple[float, float]:
        return (self.x, self.y)

@dataclass
class PanelPrimaries:
    """Native panel primary colors and white point."""
    red: ChromaticityCoord
    green: ChromaticityCoord
    blue: ChromaticityCoord
    white: ChromaticityCoord

@dataclass
class GammaCurve:
    """Per-channel gamma characteristics."""
    gamma: float = 2.2  # Native gamma
    offset: float = 0.0  # Black level offset
    linear_portion: float = 0.0  # Linear segment below this value

@dataclass
class PanelCapabilities:
    """Panel hardware capabilities."""
    max_luminance_sdr: float = 100.0  # SDR peak brightness (cd/m2)
    max_luminance_hdr: float = 400.0  # HDR peak brightness (cd/m2)
    min_luminance: float = 0.0001  # Minimum black level (cd/m2)
    native_contrast: float = 1000000.0  # Native contrast ratio
    bit_depth: int = 10  # Panel bit depth
    hdr_capable: bool = True
    wide_gamut: bool = True
    vrr_capable: bool = True
    local_dimming: bool = False
    local_dimming_zones: int = 0

@dataclass
class DDCRecommendations:
    """DDC/CI hardware calibration recommendations for a specific panel.

    Contains recommended OSD settings and VCP code values to configure
    the monitor into a state suitable for DDC/CI-based calibration.
    """
    picture_mode: str | None = None  # Recommended OSD picture mode name (e.g., "Custom 1", "User", "sRGB")
    picture_mode_vcp: int | None = None  # VCP 0xDB value for the picture mode
    color_preset: str | None = None  # Recommended color preset (e.g., "User 1", "Custom", "Warm")
    color_preset_vcp: int | None = None  # VCP 0x14 value for the color preset
    disable_dynamic_contrast: bool = True  # Should dynamic contrast be disabled
    disable_eco_mode: bool = True  # Should eco/power saving mode be disabled
    initial_brightness: int = 50  # Safe starting brightness (0-100)
    initial_contrast: int = 80  # Safe starting contrast (0-100)
    rgb_gain_range: tuple[int, int] = (0, 100)  # Safe range for RGB gain adjustments
    rgb_offset_range: tuple[int, int] = (0, 100)  # Safe range for RGB offset adjustments
    gamma_preset: str | None = None  # Recommended gamma preset name
    gamma_vcp_value: int | None = None  # VCP 0xF2 value for gamma
    notes: str = ""  # Calibration notes for this monitor

@dataclass
class PanelCharacterization:
    """Complete panel characterization for calibration."""
    manufacturer: str
    model_pattern: str  # Regex pattern to match EDID model
    panel_type: str  # WOLED, QD-OLED, IPS, VA, etc.
    native_primaries: PanelPrimaries
    gamma_red: GammaCurve = field(default_factory=GammaCurve)
    gamma_green: GammaCurve = field(default_factory=GammaCurve)
    gamma_blue: GammaCurve = field(default_factory=GammaCurve)
    capabilities: PanelCapabilities = field(default_factory=PanelCapabilities)
    color_correction_matrix: list[list[float]] | None = None
    uniformity_data: dict | None = None
    ddc: DDCRecommendations | None = None
    notes: str = ""
    display_name: str = ""  # Human-readable product name (e.g., "Odyssey G7 34")

    @property
    def name(self) -> str:
        """Human-readable name: 'ASUS ROG Swift PG27UCDM' or 'Samsung Odyssey G7'."""
        if self.display_name:
            return f"{self.manufacturer} {self.display_name}"
        # Fallback: use the first alternative in model_pattern if it looks like a name
        first = self.model_pattern.split("|")[0]
        # Strip regex characters
        clean = re.sub(r'[\\.*+?^$\[\](){}]', '', first)
        return f"{self.manufacturer} {clean}"

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "manufacturer": self.manufacturer,
            "model_pattern": self.model_pattern,
            "panel_type": self.panel_type,
            "native_primaries": {
                "red": {"x": self.native_primaries.red.x, "y": self.native_primaries.red.y},
                "green": {"x": self.native_primaries.green.x, "y": self.native_primaries.green.y},
                "blue": {"x": self.native_primaries.blue.x, "y": self.native_primaries.blue.y},
                "white": {"x": self.native_primaries.white.x, "y": self.native_primaries.white.y}
            },
            "gamma_red": asdict(self.gamma_red),
            "gamma_green": asdict(self.gamma_green),
            "gamma_blue": asdict(self.gamma_blue),
            "capabilities": asdict(self.capabilities),
            "color_correction_matrix": self.color_correction_matrix,
            "ddc": asdict(self.ddc) if self.ddc else None,
            "notes": self.notes,
            "display_name": self.display_name
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PanelCharacterization":
        """Create from dictionary (JSON deserialization)."""
        primaries = PanelPrimaries(
            red=ChromaticityCoord(**data["native_primaries"]["red"]),
            green=ChromaticityCoord(**data["native_primaries"]["green"]),
            blue=ChromaticityCoord(**data["native_primaries"]["blue"]),
            white=ChromaticityCoord(**data["native_primaries"]["white"])
        )

        ddc_data = data.get("ddc")
        ddc = None
        if ddc_data:
            # Convert list-based tuples back to tuples for range fields
            if "rgb_gain_range" in ddc_data and isinstance(ddc_data["rgb_gain_range"], list):
                ddc_data["rgb_gain_range"] = tuple(ddc_data["rgb_gain_range"])
            if "rgb_offset_range" in ddc_data and isinstance(ddc_data["rgb_offset_range"], list):
                ddc_data["rgb_offset_range"] = tuple(ddc_data["rgb_offset_range"])
            ddc = DDCRecommendations(**ddc_data)

        return cls(
            manufacturer=data["manufacturer"],
            model_pattern=data["model_pattern"],
            panel_type=data["panel_type"],
            native_primaries=primaries,
            gamma_red=GammaCurve(**data.get("gamma_red", {})),
            gamma_green=GammaCurve(**data.get("gamma_green", {})),
            gamma_blue=GammaCurve(**data.get("gamma_blue", {})),
            capabilities=PanelCapabilities(**data.get("capabilities", {})),
            color_correction_matrix=data.get("color_correction_matrix"),
            ddc=ddc,
            notes=data.get("notes", ""),
            display_name=data.get("display_name", "")
        )
