"""
Panel Characterization Database

Contains factory-measured panel characteristics for sensorless calibration.
Supports auto-detection via EDID model matching.
"""

import json
import re
from pathlib import Path

from calibrate_pro.panels.builtin_panels import get_builtin_panels

# Re-export all dataclasses so existing `from calibrate_pro.panels.database import X` works
from calibrate_pro.panels.panel_types import (  # noqa: F401
    ChromaticityCoord,
    DDCRecommendations,
    GammaCurve,
    PanelCapabilities,
    PanelCharacterization,
    PanelPrimaries,
)


class PanelDatabase:
    """
    Database of panel characterizations for sensorless calibration.

    Loads panel data from JSON files and provides lookup by EDID model.
    """

    def __init__(self, profiles_dir: Path | None = None):
        """
        Initialize the panel database.

        Args:
            profiles_dir: Directory containing JSON profile files.
                         Defaults to ./profiles relative to this file.
        """
        if profiles_dir is None:
            profiles_dir = Path(__file__).parent / "profiles"

        self.profiles_dir = profiles_dir
        self.panels: dict[str, PanelCharacterization] = {}

        # Load built-in panels
        self._load_builtin_panels()

        # Load JSON profiles if directory exists
        if profiles_dir.exists():
            self._load_json_profiles()

    def _load_builtin_panels(self):
        """Load built-in panel characterizations."""
        self.panels.update(get_builtin_panels())

    def _load_json_profiles(self):
        """Load panel profiles from JSON files in profiles directory."""
        for json_file in self.profiles_dir.glob("*.json"):
            try:
                with open(json_file, encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, list):
                    # File contains multiple panels
                    for panel_data in data:
                        panel = PanelCharacterization.from_dict(panel_data)
                        self.panels[panel.model_pattern.split("|")[0]] = panel
                else:
                    # Single panel
                    panel = PanelCharacterization.from_dict(data)
                    self.panels[panel.model_pattern.split("|")[0]] = panel

            except Exception as e:
                print(f"Warning: Failed to load {json_file}: {e}")

    def find_panel(self, model_string: str) -> PanelCharacterization | None:
        """
        Find panel characterization by model string (from EDID).

        Args:
            model_string: Display model string from EDID

        Returns:
            PanelCharacterization if found, None otherwise
        """
        # First, try exact match on known panel names
        for key, panel in self.panels.items():
            if key != "GENERIC_SRGB":  # Skip generic fallback
                if re.search(panel.model_pattern, model_string, re.IGNORECASE):
                    return panel

        return None

    def get_panel(self, model_key: str) -> PanelCharacterization | None:
        """Get panel by exact key name."""
        return self.panels.get(model_key)

    def get_fallback(self) -> PanelCharacterization:
        """Get generic fallback panel profile."""
        return self.panels["GENERIC_SRGB"]

    def list_panels(self) -> list[str]:
        """List all available panel keys."""
        return [k for k in self.panels if k != "GENERIC_SRGB"]

    def add_panel(self, key: str, panel: PanelCharacterization):
        """Add or update a panel characterization."""
        self.panels[key] = panel

    def get_ddc_recommendations(self, panel_key: str) -> DDCRecommendations | None:
        """
        Get DDC/CI hardware calibration recommendations for a panel.

        Args:
            panel_key: Panel key in the database (e.g., "PG27UCDM", "LG_C3")

        Returns:
            DDCRecommendations if the panel has DDC data, None otherwise
        """
        panel = self.panels.get(panel_key)
        if panel is not None:
            return panel.ddc
        return None

    def save_panel(self, key: str, filename: str | None = None):
        """Save a panel characterization to JSON file."""
        if key not in self.panels:
            raise ValueError(f"Panel '{key}' not found in database")

        panel = self.panels[key]
        if filename is None:
            filename = f"{key.lower().replace(' ', '_')}.json"

        filepath = self.profiles_dir / filename

        # Ensure directory exists
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(panel.to_dict(), f, indent=2)

        return filepath


# Global database instance
_database: PanelDatabase | None = None

def get_database() -> PanelDatabase:
    """Get the global panel database instance."""
    global _database
    if _database is None:
        _database = PanelDatabase()
    return _database

def find_panel_for_display(model_string: str) -> PanelCharacterization | None:
    """Convenience function to find a panel by model string."""
    return get_database().find_panel(model_string)


def create_from_edid(edid_chromaticity: dict, monitor_name: str = "Unknown",
                     manufacturer: str = "Unknown", gamma: float = 2.2) -> PanelCharacterization:
    """
    Create a PanelCharacterization from EDID chromaticity data.

    This is the critical fallback for monitors not in the built-in database.
    EDID reports native primaries and white point, giving us accurate gamut
    information even for unknown panels. Combined with a reasonable gamma
    assumption, this produces significantly better calibration than the
    generic sRGB fallback.

    Args:
        edid_chromaticity: Dict with 'red', 'green', 'blue', 'white' as (x, y) tuples
        monitor_name: Display name from EDID
        manufacturer: Manufacturer name
        gamma: Assumed gamma (2.2 for most IPS/VA, 2.4 for some VA panels)

    Returns:
        PanelCharacterization built from EDID data
    """
    red = edid_chromaticity.get("red", (0.6400, 0.3300))
    green = edid_chromaticity.get("green", (0.3000, 0.6000))
    blue = edid_chromaticity.get("blue", (0.1500, 0.0600))
    white = edid_chromaticity.get("white", (0.3127, 0.3290))

    # Determine panel type heuristic from gamut coverage
    # sRGB red primary is at (0.64, 0.33). Wide gamut panels have red > 0.66
    is_wide_gamut = red[0] > 0.66 or green[1] > 0.65

    # Estimate panel type from gamut width
    if red[0] > 0.675:
        panel_type = "Wide Gamut"  # QD-OLED or similar
    elif red[0] > 0.66:
        panel_type = "DCI-P3"  # P3-class panel
    else:
        panel_type = "sRGB-class"

    # Build a correction matrix based on how far primaries are from sRGB
    # This is an identity-ish matrix with small corrections
    srgb_red = (0.6400, 0.3300)
    srgb_green = (0.3000, 0.6000)
    srgb_blue = (0.1500, 0.0600)

    # Calculate approximate correction magnitudes
    r_shift = abs(red[0] - srgb_red[0]) + abs(red[1] - srgb_red[1])
    g_shift = abs(green[0] - srgb_green[0]) + abs(green[1] - srgb_green[1])
    b_shift = abs(blue[0] - srgb_blue[0]) + abs(blue[1] - srgb_blue[1])

    # Build conservative correction matrix
    ccm = [
        [1.0 + r_shift * 0.5, -g_shift * 0.3, -b_shift * 0.2],
        [-r_shift * 0.1, 1.0 + g_shift * 0.3, -b_shift * 0.15],
        [r_shift * 0.03, -g_shift * 0.5, 1.0 + b_shift * 0.45]
    ]

    return PanelCharacterization(
        manufacturer=manufacturer,
        model_pattern=re.escape(monitor_name),
        panel_type=panel_type,
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(red[0], red[1]),
            green=ChromaticityCoord(green[0], green[1]),
            blue=ChromaticityCoord(blue[0], blue[1]),
            white=ChromaticityCoord(white[0], white[1])
        ),
        gamma_red=GammaCurve(gamma=gamma, offset=0.0, linear_portion=0.0),
        gamma_green=GammaCurve(gamma=gamma, offset=0.0, linear_portion=0.0),
        gamma_blue=GammaCurve(gamma=gamma, offset=0.0, linear_portion=0.0),
        capabilities=PanelCapabilities(
            max_luminance_sdr=250.0,
            max_luminance_hdr=400.0,
            min_luminance=0.1,
            native_contrast=1000.0,
            bit_depth=8,
            hdr_capable=is_wide_gamut,
            wide_gamut=is_wide_gamut,
            vrr_capable=False,
            local_dimming=False
        ),
        color_correction_matrix=ccm,
        notes=f"Auto-generated from EDID data. Primaries: R({red[0]:.4f},{red[1]:.4f}) "
              f"G({green[0]:.4f},{green[1]:.4f}) B({blue[0]:.4f},{blue[1]:.4f}). "
              f"Gamma assumed {gamma}."
    )
