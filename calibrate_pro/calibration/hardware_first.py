"""
Hardware-First Calibration Workflow

The professional approach to display calibration:
1. SETUP: Configure monitor OSD to optimal mode (Custom/User, disable dynamic features)
2. HARDWARE: Iteratively adjust DDC/CI controls (brightness, contrast, RGB gains/offsets)
   with colorimeter feedback to get as close to reference as possible
3. PROFILE: Measure the hardware-calibrated display and build a residual correction LUT
4. APPLY: Apply the small correction LUT for the remaining errors

This produces better results than software-only calibration because:
- Hardware adjustments affect the entire signal chain (all content, all apps)
- The correction LUT only needs to fix small residual errors (fewer quantization artifacts)
- Gamma and contrast are set at the native level (better tonal response)
"""

import logging
import time
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Callable, Tuple
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class HardwareFirstResult:
    """Result of a hardware-first calibration."""
    success: bool = False
    message: str = ""

    # Hardware phase results
    ddc_adjustments: List[str] = field(default_factory=list)
    initial_brightness: int = 0
    final_brightness: int = 0
    initial_rgb_gains: Tuple[int, int, int] = (100, 100, 100)
    final_rgb_gains: Tuple[int, int, int] = (100, 100, 100)
    white_point_achieved: Tuple[float, float] = (0.0, 0.0)
    luminance_achieved: float = 0.0

    # Profile phase results
    lut_path: Optional[str] = None
    icc_path: Optional[str] = None
    avg_de_before_lut: float = 0.0
    avg_de_after_lut: float = 0.0

    # Metadata
    display_name: str = ""
    panel_type: str = ""
    instrument: str = ""


def run_hardware_first_calibration(
    display_index: int = 0,
    target_luminance: float = 120.0,
    target_whitepoint: Tuple[float, float] = (0.3127, 0.3290),
    target_gamma: float = 2.2,
    measure_fn: Optional[Callable[[], Optional[np.ndarray]]] = None,
    display_fn: Optional[Callable[[float, float, float], None]] = None,
    progress_fn: Optional[Callable[[str, float], None]] = None,
    output_dir: Optional[str] = None,
) -> HardwareFirstResult:
    """
    Run the complete hardware-first calibration workflow.

    Args:
        display_index: Which display to calibrate
        target_luminance: Target white luminance in cd/m2
        target_whitepoint: Target white point (x, y) chromaticity
        target_gamma: Target gamma (2.2 for sRGB, 2.4 for BT.1886)
        measure_fn: Function that returns measured XYZ, or None. Called after display_fn.
        display_fn: Function to show a color patch (r, g, b) in 0-1 range
        progress_fn: Progress callback (message, fraction 0-1)
        output_dir: Where to save calibration files

    Returns:
        HardwareFirstResult with all calibration data
    """
    result = HardwareFirstResult()

    if output_dir is None:
        output_dir = os.path.expanduser("~/Documents/Calibrate Pro/Calibrations")
    os.makedirs(output_dir, exist_ok=True)

    def report(msg, frac):
        logger.info(msg)
        result.ddc_adjustments.append(msg)
        if progress_fn:
            progress_fn(msg, frac)

    # =====================================================================
    # Phase 1: SETUP — Configure monitor OSD
    # =====================================================================
    report("Phase 1: Configuring monitor hardware...", 0.0)

    try:
        from calibrate_pro.hardware.ddc_ci import DDCCIController, VCPCode
        ddc = DDCCIController()
        monitors = ddc.enumerate_monitors()

        if display_index >= len(monitors):
            result.message = f"Display {display_index} not found ({len(monitors)} available)"
            return result

        monitor = monitors[display_index]
        result.display_name = monitor.get("name", f"Display {display_index}")

        # Read current state
        try:
            brightness = ddc.get_vcp(monitor, VCPCode.BRIGHTNESS)
            result.initial_brightness = brightness[0] if brightness else 50
        except Exception:
            result.initial_brightness = 50

        try:
            r_gain = ddc.get_vcp(monitor, VCPCode.RED_GAIN)
            g_gain = ddc.get_vcp(monitor, VCPCode.GREEN_GAIN)
            b_gain = ddc.get_vcp(monitor, VCPCode.BLUE_GAIN)
            result.initial_rgb_gains = (
                r_gain[0] if r_gain else 100,
                g_gain[0] if g_gain else 100,
                b_gain[0] if b_gain else 100,
            )
        except Exception:
            result.initial_rgb_gains = (100, 100, 100)

        report(f"Initial: brightness={result.initial_brightness}, "
               f"RGB=({result.initial_rgb_gains[0]},{result.initial_rgb_gains[1]},{result.initial_rgb_gains[2]})", 0.05)

        # Auto-setup monitor OSD via DDC/CI
        ddc_rec = None
        try:
            from calibrate_pro.panels.detection import enumerate_displays, identify_display
            from calibrate_pro.panels.database import PanelDatabase

            displays = enumerate_displays()
            if display_index < len(displays):
                db = PanelDatabase()
                panel_key = identify_display(displays[display_index])
                panel = db.get_panel(panel_key) if panel_key else None

                if panel:
                    result.panel_type = panel.panel_type
                    result.display_name = panel.name
                    ddc_rec = panel.ddc if hasattr(panel, 'ddc') else None
        except Exception as e:
            logger.debug("Panel identification failed: %s", e)

        report(f"Auto-configuring {result.display_name} for calibration...", 0.08)
        changes = ddc.auto_setup_for_calibration(
            monitor, ddc_recommendations=ddc_rec,
            log_fn=lambda msg: report(f"  {msg}", 0.10),
        )
        for change in changes:
            result.ddc_adjustments.append(change)

        # =====================================================================
        # Phase 2: HARDWARE CALIBRATION — Iterative DDC with measurements
        # =====================================================================

        if measure_fn is None or display_fn is None:
            report("No colorimeter/display function. Skipping hardware measurement loop.", 0.15)
            report("Using panel database for sensorless hardware settings.", 0.15)

            # Sensorless: set reasonable defaults
            ddc.set_vcp(monitor, VCPCode.BRIGHTNESS, 50)
            ddc.set_vcp(monitor, VCPCode.CONTRAST, 80)
            result.final_brightness = 50
            result.final_rgb_gains = result.initial_rgb_gains

        else:
            # === Brightness calibration ===
            report("Phase 2a: Calibrating brightness...", 0.15)
            current_brightness = result.initial_brightness

            for iteration in range(8):
                display_fn(1.0, 1.0, 1.0)  # White patch
                xyz = measure_fn()
                if xyz is None:
                    break

                luminance = xyz[1]
                report(f"  Brightness={current_brightness}: Y={luminance:.1f} cd/m2 (target {target_luminance:.0f})", 0.15 + iteration * 0.02)

                if abs(luminance - target_luminance) / max(target_luminance, 1) < 0.05:
                    report(f"  Brightness converged at {current_brightness}", 0.30)
                    break

                # Proportional adjustment
                ratio = target_luminance / max(luminance, 0.1)
                adjustment = int((ratio - 1.0) * current_brightness * 0.5)
                adjustment = max(-10, min(10, adjustment))
                new_brightness = max(0, min(100, current_brightness + adjustment))

                if new_brightness != current_brightness:
                    try:
                        ddc.set_vcp(monitor, VCPCode.BRIGHTNESS, new_brightness)
                        current_brightness = new_brightness
                        time.sleep(0.5)
                    except Exception:
                        break

            result.final_brightness = current_brightness

            # === White balance calibration ===
            report("Phase 2b: Calibrating white balance...", 0.30)
            current_r, current_g, current_b = result.initial_rgb_gains

            for iteration in range(20):
                display_fn(1.0, 1.0, 1.0)  # White patch
                xyz = measure_fn()
                if xyz is None:
                    break

                # Compute chromaticity
                s = xyz[0] + xyz[1] + xyz[2]
                if s <= 0:
                    break
                mx, my = xyz[0] / s, xyz[1] / s

                dx = target_whitepoint[0] - mx
                dy = target_whitepoint[1] - my
                error = (dx**2 + dy**2)**0.5

                report(f"  Iter {iteration+1}: xy=({mx:.4f},{my:.4f}), error={error:.4f}, "
                       f"RGB=({current_r},{current_g},{current_b})", 0.30 + iteration * 0.015)

                if error < 0.003:
                    report(f"  White balance converged after {iteration+1} iterations", 0.58)
                    result.white_point_achieved = (mx, my)
                    break

                # RGB gain adjustment based on chromaticity error
                # Red affects x positively, Green affects y positively, Blue affects both negatively
                scale = 40
                r_adj = int(dx * scale * 2)
                g_adj = int(dy * scale * 2)
                b_adj = int((-dx - dy) * scale)

                # Clamp adjustments
                r_adj = max(-5, min(5, r_adj))
                g_adj = max(-5, min(5, g_adj))
                b_adj = max(-5, min(5, b_adj))

                new_r = max(0, min(100, current_r + r_adj))
                new_g = max(0, min(100, current_g + g_adj))
                new_b = max(0, min(100, current_b + b_adj))

                if (new_r, new_g, new_b) != (current_r, current_g, current_b):
                    try:
                        ddc.set_vcp(monitor, VCPCode.RED_GAIN, new_r)
                        ddc.set_vcp(monitor, VCPCode.GREEN_GAIN, new_g)
                        ddc.set_vcp(monitor, VCPCode.BLUE_GAIN, new_b)
                        current_r, current_g, current_b = new_r, new_g, new_b
                        time.sleep(0.5)
                    except Exception:
                        break

            result.final_rgb_gains = (current_r, current_g, current_b)

            # Final measurement
            display_fn(1.0, 1.0, 1.0)
            xyz = measure_fn()
            if xyz is not None:
                result.luminance_achieved = xyz[1]
                s = sum(xyz)
                if s > 0:
                    result.white_point_achieved = (xyz[0]/s, xyz[1]/s)

        # =====================================================================
        # Phase 3: PROFILE — Measure the hardware-calibrated display
        # =====================================================================
        report("Phase 3: Profiling hardware-calibrated display...", 0.60)

        if measure_fn is not None and display_fn is not None:
            from calibrate_pro.calibration.native_loop import (
                profile_display, build_correction_lut
            )

            def profile_progress(msg, frac):
                report(msg, 0.60 + frac * 0.25)

            profile = profile_display(
                measure_fn=lambda r, g, b: measure_fn(),
                display_fn=display_fn,
                n_steps=17,
                progress_fn=profile_progress,
            )

            report(f"Profile: WP ({profile.white_xy[0]:.4f}, {profile.white_xy[1]:.4f}), "
                   f"Y={profile.white_Y:.1f} cd/m2", 0.85)

            # Build residual correction LUT
            report("Building residual correction LUT...", 0.85)
            lut = build_correction_lut(profile, size=33)
            lut.title = f"Calibrate Pro - {result.display_name} (Hardware+Software)"

            lut_path = os.path.join(output_dir, f"{result.display_name.replace(' ', '_')}_hwcal.cube")
            lut.save(lut_path)
            result.lut_path = lut_path
            report(f"LUT saved: {lut_path}", 0.90)

            # Apply via DWM
            try:
                from calibrate_pro.lut_system.dwm_lut import DwmLutController
                dwm_ctrl = DwmLutController()
                if dwm_ctrl.is_available:
                    dwm_ctrl.load_lut_file(display_index, lut_path)
                    report("Residual LUT applied via DWM.", 0.95)
            except Exception as e:
                report(f"DWM LUT application: {e}", 0.95)
        else:
            # Sensorless: generate LUT from panel database
            report("Generating sensorless correction LUT...", 0.85)
            try:
                from calibrate_pro.sensorless.neuralux import SensorlessEngine
                from calibrate_pro.panels.database import PanelDatabase

                db = PanelDatabase()
                displays = enumerate_displays()
                if display_index < len(displays):
                    panel_key = identify_display(displays[display_index])
                    panel = db.get_panel(panel_key) if panel_key else db.get_fallback()
                else:
                    panel = db.get_fallback()

                engine = SensorlessEngine()
                engine.current_panel = panel
                lut = engine.create_3d_lut(panel, size=33, target="sRGB")
                lut_path = os.path.join(output_dir, f"sensorless_calibration.cube")
                lut.save(lut_path)
                result.lut_path = lut_path
                report(f"Sensorless LUT saved: {lut_path}", 0.90)
            except Exception as e:
                report(f"Sensorless LUT generation failed: {e}", 0.90)

        result.success = True
        result.message = (
            f"Hardware-first calibration complete.\n"
            f"Brightness: {result.initial_brightness} -> {result.final_brightness}\n"
            f"RGB: ({result.initial_rgb_gains[0]},{result.initial_rgb_gains[1]},{result.initial_rgb_gains[2]}) "
            f"-> ({result.final_rgb_gains[0]},{result.final_rgb_gains[1]},{result.final_rgb_gains[2]})\n"
            f"White point: ({result.white_point_achieved[0]:.4f}, {result.white_point_achieved[1]:.4f})\n"
            f"Luminance: {result.luminance_achieved:.1f} cd/m2"
        )

    except Exception as e:
        result.message = f"Hardware calibration failed: {e}"
        logger.error("Hardware-first calibration failed: %s", e, exc_info=True)

    report(result.message, 1.0)
    return result
