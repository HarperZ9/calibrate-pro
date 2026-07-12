"""
sRGB Gamut Clamp Proposal Builder

Wide-gamut displays (QD-OLED, P3, etc.) show oversaturated colors in
non-color-managed applications -- games, browsers, the Windows desktop.
This is the single most common complaint from wide-gamut display owners.

This service builds an sRGB gamut-clamp proposal. Applying it system-wide
requires an interactive preview and a freshly confirmed actuation plan.

The clamp LUT maps the panel's native gamut to sRGB using Oklab
perceptual compression (no hue shifts in blue/purple).
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class GamutClamp:
    """
    System-wide gamut clamp proposal builder.

    Generates or clears a staged sRGB compression LUT proposal without
    changing display state.
    """

    def __init__(self, display_index: int = 0):
        self.display_index = display_index
        self._active = False
        self._lut_path: Path | None = None
        self._staged = False

    @property
    def is_active(self) -> bool:
        """Whether a clamp has been confirmed as active (never inferred here)."""
        return self._active

    @property
    def has_staged_proposal(self) -> bool:
        """Whether a clamp proposal is ready for preview and confirmation."""
        return self._staged

    def enable(self, panel_key: str | None = None) -> bool:
        """
        Stage an sRGB gamut-clamp proposal for the display.

        Generates or reuses an sRGB compression LUT. This method never applies
        the LUT to the display.

        Args:
            panel_key: Panel database key (auto-detects if None)

        Returns:
            True if a proposal was staged successfully
        """
        # Generate the clamp LUT if we don't have one cached
        if self._lut_path is None or not self._lut_path.exists():
            self._lut_path = self._generate_clamp_lut(panel_key)
            if self._lut_path is None:
                return False

        self._staged = True
        logger.info("Staged gamut-clamp proposal for display %d", self.display_index)
        return True

    def disable(self) -> bool:
        """Clear the staged proposal without changing display state."""
        self._staged = False
        return True

    def toggle(self, panel_key: str | None = None) -> bool:
        """Toggle proposal staging. Returns whether a proposal is staged."""
        if self._staged:
            self.disable()
            return False
        return self.enable(panel_key)

    def _generate_clamp_lut(self, panel_key: str | None = None) -> Path | None:
        """Generate an sRGB compression LUT for the panel."""
        try:
            from calibrate_pro.panels.database import PanelDatabase
            from calibrate_pro.sensorless.neuralux import SensorlessEngine

            # Find panel
            db = PanelDatabase()
            if panel_key:
                panel = db.get_panel(panel_key)
            else:
                panel = db.get_fallback()

            if panel is None:
                return None

            # Generate sRGB target LUT using Oklab perceptual mapping
            engine = SensorlessEngine()
            engine.current_panel = panel
            lut = engine.create_3d_lut(panel, size=33, target="sRGB")

            # Save to temp location
            clamp_dir = Path(os.environ.get("APPDATA", Path.home())) / "CalibratePro" / "clamp"
            clamp_dir.mkdir(parents=True, exist_ok=True)
            lut_path = clamp_dir / f"srgb_clamp_{self.display_index}.cube"
            lut.save(lut_path)

            return lut_path

        except Exception as e:
            logger.error("Clamp LUT generation failed: %s", e)
            return None


def get_clamp_for_display(display_index: int = 0) -> GamutClamp:
    """Get a GamutClamp instance for a display."""
    return GamutClamp(display_index)
