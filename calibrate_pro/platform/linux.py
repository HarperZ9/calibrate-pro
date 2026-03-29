"""
Linux Platform Backend

Full implementation using standard Linux tools and APIs:
- xrandr / python-xlib for display detection and gamma ramps (X11)
- /sys/class/drm/ for display info and EDID parsing (DRM/KMS)
- colord (D-Bus) for ICC profile management
- subprocess fallback for xrandr/colormgr CLI tools

Gamma ramps:
    XRRSetCrtcGamma accepts uint16 arrays (0-65535).  Ramp size varies
    by driver (typically 256 or 1024).  We query the actual size first
    and interpolate our 256-entry tables if needed.

ICC profiles:
    Installed to ~/.local/share/icc/ (per-user, no root needed) or
    /usr/share/color/icc/ (system-wide, requires root).
    Associated with displays via colord D-Bus API or colormgr CLI.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path

from calibrate_pro.platform.base import (
    DisplayInfo as PlatformDisplayInfo,
)
from calibrate_pro.platform.base import (
    PlatformBackend,
)

logger = logging.getLogger(__name__)


# =====================================================================
# Helpers
# =====================================================================


def _run_cmd(cmd: list[str], timeout: int = 10) -> str | None:
    """Run a shell command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout
        logger.debug("Command %s failed (rc=%d): %s", cmd, result.returncode, result.stderr)
    except FileNotFoundError:
        logger.debug("Command not found: %s", cmd[0])
    except subprocess.TimeoutExpired:
        logger.debug("Command timed out: %s", cmd)
    except Exception as e:
        logger.debug("Command error: %s", e)
    return None


def _parse_edid_name(edid_bytes: bytes) -> tuple[str, str, str]:
    """
    Parse manufacturer, model name, and serial from raw EDID bytes.

    Returns (manufacturer, model, serial).
    """
    manufacturer = ""
    model = ""
    serial = ""

    if len(edid_bytes) < 128:
        return manufacturer, model, serial

    # Manufacturer ID: bytes 8-9 (compressed ASCII, 3 chars)
    try:
        mfg_raw = (edid_bytes[8] << 8) | edid_bytes[9]
        c1 = chr(((mfg_raw >> 10) & 0x1F) + ord("A") - 1)
        c2 = chr(((mfg_raw >> 5) & 0x1F) + ord("A") - 1)
        c3 = chr((mfg_raw & 0x1F) + ord("A") - 1)
        manufacturer = f"{c1}{c2}{c3}"
    except Exception:
        pass

    # Parse descriptor blocks (bytes 54-125, four 18-byte blocks)
    for i in range(4):
        offset = 54 + i * 18
        block = edid_bytes[offset : offset + 18]
        if len(block) < 18:
            break

        # Check if this is a descriptor block (first 3 bytes are 0x00)
        if block[0] == 0 and block[1] == 0 and block[2] == 0:
            tag = block[3]
            # 0xFC = Monitor name, 0xFF = Serial string
            text = block[5:18].split(b"\n")[0].decode("ascii", errors="replace").strip()
            if tag == 0xFC:
                model = text
            elif tag == 0xFF:
                serial = text

    return manufacturer, model, serial


def _read_drm_edid(card_path: Path) -> bytes | None:
    """Read raw EDID from /sys/class/drm/<card>/edid."""
    edid_path = card_path / "edid"
    try:
        if edid_path.exists():
            data = edid_path.read_bytes()
            if len(data) >= 128:
                return data
    except (PermissionError, OSError) as e:
        logger.debug("Cannot read %s: %s", edid_path, e)
    return None


# =====================================================================
# xrandr output parser
# =====================================================================


def _parse_xrandr_output(xrandr_text: str) -> list[dict]:
    """
    Parse xrandr --query output into a list of connected display dicts.

    Each dict has keys: name, width, height, refresh, primary, pos_x, pos_y.
    """
    displays = []
    # Match connected outputs with resolution
    # e.g.: "DP-1 connected primary 2560x1440+0+0 ..."
    #        "HDMI-1 connected 1920x1080+2560+0 ..."
    pattern = re.compile(
        r"^(\S+)\s+connected\s+"
        r"(primary\s+)?"
        r"(\d+)x(\d+)\+(\d+)\+(\d+)"
        r".*?"
        r"$",
        re.MULTILINE,
    )

    for match in pattern.finditer(xrandr_text):
        output_name = match.group(1)
        is_primary = match.group(2) is not None
        width = int(match.group(3))
        height = int(match.group(4))
        pos_x = int(match.group(5))
        pos_y = int(match.group(6))

        # Find the active mode's refresh rate
        # Look for lines with * (current) after this output
        refresh = 60
        out_start = match.end()
        # Find the next output line or end of string
        next_output = re.search(r"^\S+\s+(connected|disconnected)", xrandr_text[out_start:], re.MULTILINE)
        mode_section = xrandr_text[out_start : out_start + next_output.start() if next_output else len(xrandr_text)]

        # Match active mode: "   2560x1440     59.95*+  143.97 ..."
        rate_match = re.search(r"(\d+\.\d+)\*", mode_section)
        if rate_match:
            refresh = int(float(rate_match.group(1)))

        displays.append(
            {
                "name": output_name,
                "width": width,
                "height": height,
                "refresh": refresh,
                "primary": is_primary,
                "pos_x": pos_x,
                "pos_y": pos_y,
            }
        )

    return displays


# =====================================================================
# Linux Backend
# =====================================================================


class LinuxBackend(PlatformBackend):
    """
    Linux implementation using xrandr, /sys/class/drm, and colord.

    Falls back gracefully when tools are unavailable:
    - xrandr missing: attempts DRM/KMS enumeration via /sys/class/drm
    - colord missing: copies profiles to ~/.local/share/icc/ directly
    - All failures logged and return empty list / False / None
    """

    # ------------------------------------------------------------------
    # Display enumeration
    # ------------------------------------------------------------------

    def enumerate_displays(self) -> list[PlatformDisplayInfo]:
        """
        Enumerate active displays.

        Strategy:
        1. Try xrandr --query for display list + resolution
        2. Enrich with EDID from /sys/class/drm/ for names
        3. Fall back to pure DRM enumeration if xrandr unavailable
        """
        # Try xrandr first (works on X11, XWayland)
        displays = self._enumerate_xrandr()
        if displays:
            return displays

        # Fall back to DRM/KMS
        displays = self._enumerate_drm()
        if displays:
            return displays

        logger.warning("No display enumeration method available. Install xrandr or ensure /sys/class/drm/ is readable.")
        return []

    def _enumerate_xrandr(self) -> list[PlatformDisplayInfo]:
        """Enumerate displays via xrandr --query."""
        output = _run_cmd(["xrandr", "--query"])
        if output is None:
            return []

        parsed = _parse_xrandr_output(output)
        if not parsed:
            return []

        results: list[PlatformDisplayInfo] = []
        drm_edid_map = self._build_drm_edid_map()

        for idx, d in enumerate(parsed):
            # Try to get EDID info from DRM
            manufacturer = ""
            model = ""
            serial = ""
            edid_key = d["name"].lower().replace("-", "")

            for drm_name, edid_bytes in drm_edid_map.items():
                # DRM names like "card0-DP-1" map to xrandr "DP-1"
                if edid_key in drm_name.lower().replace("-", ""):
                    manufacturer, model, serial = _parse_edid_name(edid_bytes)
                    break

            display_name = model or d["name"]
            if manufacturer and manufacturer not in display_name:
                display_name = f"{manufacturer} {display_name}"

            # Get current ICC profile via colord
            icc_profile = self._get_colord_profile(d["name"])

            results.append(
                PlatformDisplayInfo(
                    index=idx,
                    name=display_name,
                    device_path=d["name"],
                    is_primary=d["primary"],
                    width=d["width"],
                    height=d["height"],
                    refresh_rate=d["refresh"],
                    bit_depth=8,
                    position_x=d["pos_x"],
                    position_y=d["pos_y"],
                    manufacturer=manufacturer,
                    model=model,
                    serial=serial,
                    current_icc_profile=icc_profile,
                )
            )

        return results

    def _enumerate_drm(self) -> list[PlatformDisplayInfo]:
        """Enumerate displays via /sys/class/drm/."""
        drm_base = Path("/sys/class/drm")
        if not drm_base.exists():
            return []

        results: list[PlatformDisplayInfo] = []
        idx = 0

        try:
            for card_dir in sorted(drm_base.iterdir()):
                status_file = card_dir / "status"
                if not status_file.exists():
                    continue

                try:
                    status = status_file.read_text().strip()
                except (PermissionError, OSError):
                    continue

                if status != "connected":
                    continue

                # Parse output name from directory (e.g., "card0-DP-1")
                dir_name = card_dir.name
                parts = dir_name.split("-", 1)
                output_name = parts[1] if len(parts) > 1 else dir_name

                # Read EDID
                manufacturer = ""
                model = ""
                serial = ""
                edid_bytes = _read_drm_edid(card_dir)
                if edid_bytes:
                    manufacturer, model, serial = _parse_edid_name(edid_bytes)

                display_name = model or output_name
                if manufacturer and manufacturer not in display_name:
                    display_name = f"{manufacturer} {display_name}"

                # Try to read modes from /sys/class/drm/<card>/modes
                width, height, refresh = 1920, 1080, 60
                modes_file = card_dir / "modes"
                try:
                    if modes_file.exists():
                        first_mode = modes_file.read_text().strip().split("\n")[0]
                        mode_match = re.match(r"(\d+)x(\d+)", first_mode)
                        if mode_match:
                            width = int(mode_match.group(1))
                            height = int(mode_match.group(2))
                except (PermissionError, OSError):
                    pass

                results.append(
                    PlatformDisplayInfo(
                        index=idx,
                        name=display_name,
                        device_path=output_name,
                        is_primary=(idx == 0),  # First connected = primary heuristic
                        width=width,
                        height=height,
                        refresh_rate=refresh,
                        bit_depth=8,
                        manufacturer=manufacturer,
                        model=model,
                        serial=serial,
                    )
                )
                idx += 1

        except (PermissionError, OSError) as e:
            logger.debug("DRM enumeration error: %s", e)

        return results

    def _build_drm_edid_map(self) -> dict[str, bytes]:
        """Build a map of DRM output name -> EDID bytes."""
        edid_map: dict[str, bytes] = {}
        drm_base = Path("/sys/class/drm")
        if not drm_base.exists():
            return edid_map

        try:
            for card_dir in drm_base.iterdir():
                edid_bytes = _read_drm_edid(card_dir)
                if edid_bytes:
                    edid_map[card_dir.name] = edid_bytes
        except (PermissionError, OSError):
            pass

        return edid_map

    # ------------------------------------------------------------------
    # Gamma ramp
    # ------------------------------------------------------------------

    def apply_gamma_ramp(
        self,
        display_index: int,
        red: list[int],
        green: list[int],
        blue: list[int],
    ) -> bool:
        """
        Apply a gamma ramp on Linux.

        Strategy:
        1. Try python-xlib XRRSetCrtcGamma (direct, full 256-entry LUT)
        2. Fall back to xrandr --gamma (simple 3-value approximation)
        """
        # Try full LUT via python-xlib
        if self._apply_gamma_xlib(display_index, red, green, blue):
            return True

        # Fall back to simple xrandr --gamma
        return self._apply_gamma_xrandr(display_index, red, green, blue)

    def _apply_gamma_xlib(
        self,
        display_index: int,
        red: list[int],
        green: list[int],
        blue: list[int],
    ) -> bool:
        """Apply gamma ramp via python-xlib XRRSetCrtcGamma."""
        try:
            from Xlib import display as xdisplay
            from Xlib.ext import randr
        except ImportError:
            logger.debug("python-xlib not available for gamma ramp")
            return False

        try:
            d = xdisplay.Display()
            screen = d.screen()
            window = screen.root
            res = randr.get_screen_resources(window)

            if display_index >= len(res.crtcs):
                logger.error("Display index %d out of range (have %d CRTCs)", display_index, len(res.crtcs))
                return False

            crtc_id = res.crtcs[display_index]
            gamma_size = randr.get_crtc_gamma_size(d, crtc_id).size

            # Interpolate our 256-entry tables to match the driver's gamma size
            import numpy as np

            r_arr = np.interp(
                np.linspace(0, 255, gamma_size),
                np.arange(256),
                np.array(red, dtype=np.uint16),
            ).astype(np.uint16)
            g_arr = np.interp(
                np.linspace(0, 255, gamma_size),
                np.arange(256),
                np.array(green, dtype=np.uint16),
            ).astype(np.uint16)
            b_arr = np.interp(
                np.linspace(0, 255, gamma_size),
                np.arange(256),
                np.array(blue, dtype=np.uint16),
            ).astype(np.uint16)

            randr.set_crtc_gamma(d, crtc_id, r_arr.tolist(), g_arr.tolist(), b_arr.tolist())
            d.flush()
            d.close()

            logger.info("Gamma ramp applied via python-xlib (CRTC %d, size %d)", crtc_id, gamma_size)
            return True

        except Exception as e:
            logger.debug("python-xlib gamma ramp failed: %s", e)
            return False

    def _apply_gamma_xrandr(
        self,
        display_index: int,
        red: list[int],
        green: list[int],
        blue: list[int],
    ) -> bool:
        """
        Approximate gamma ramp via xrandr --gamma R:G:B.

        This only supports a single gamma exponent per channel, so we
        estimate the gamma from the LUT midpoint vs. linear.
        """
        displays = self._get_xrandr_outputs()
        if display_index >= len(displays):
            return False

        output_name = displays[display_index]

        # Estimate per-channel gamma from the LUT midpoint
        def _estimate_gamma(lut: list[int]) -> float:
            mid = lut[128] / 65535.0  # Actual midpoint value
            if mid <= 0.0 or mid >= 1.0:
                return 1.0
            import math

            # For gamma encoding: output = input^gamma
            # At input=0.5: output = 0.5^gamma
            # So gamma = log(output) / log(0.5)
            return max(0.1, min(10.0, math.log(mid) / math.log(0.5)))

        r_gamma = _estimate_gamma(red)
        g_gamma = _estimate_gamma(green)
        b_gamma = _estimate_gamma(blue)

        result = _run_cmd(
            [
                "xrandr",
                "--output",
                output_name,
                "--gamma",
                f"{r_gamma:.3f}:{g_gamma:.3f}:{b_gamma:.3f}",
            ]
        )

        if result is not None:
            logger.info(
                "Gamma approximation applied via xrandr --gamma %.3f:%.3f:%.3f on %s",
                r_gamma,
                g_gamma,
                b_gamma,
                output_name,
            )
            return True

        logger.error("xrandr --gamma failed for output %s", output_name)
        return False

    def reset_gamma_ramp(self, display_index: int) -> bool:
        """
        Reset gamma ramp to identity.

        Strategy:
        1. Try python-xlib to set linear ramp
        2. Fall back to xrandr --gamma 1:1:1
        3. Fall back to xcalib -c
        """
        # Try python-xlib linear ramp
        linear = list(range(0, 65536, 65536 // 256))[:256]
        if self._apply_gamma_xlib(display_index, linear, linear, linear):
            return True

        # Try xrandr --gamma 1:1:1
        displays = self._get_xrandr_outputs()
        if display_index < len(displays):
            output_name = displays[display_index]
            result = _run_cmd(["xrandr", "--output", output_name, "--gamma", "1:1:1"])
            if result is not None:
                logger.info("Gamma reset via xrandr --gamma 1:1:1 on %s", output_name)
                return True

        # Try xcalib -c
        result = _run_cmd(["xcalib", "-c"])
        if result is not None:
            logger.info("Gamma reset via xcalib -c")
            return True

        logger.error("Failed to reset gamma ramp on display %d", display_index)
        return False

    # ------------------------------------------------------------------
    # ICC profile management
    # ------------------------------------------------------------------

    def install_icc_profile(
        self,
        profile_path: str,
        display_index: int,
    ) -> bool:
        """
        Install an ICC profile on Linux.

        1. Copy to ~/.local/share/icc/
        2. Register with colord via D-Bus or colormgr CLI
        3. Optionally apply VCGT via xcalib for immediate effect
        """
        src = Path(profile_path)
        if not src.exists():
            logger.error("ICC profile not found: %s", profile_path)
            return False

        # Per-user ICC directory
        dest_dir = Path.home() / ".local" / "share" / "icc"
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / src.name
        try:
            shutil.copy2(str(src), str(dest))
            logger.info("ICC profile installed to %s", dest)
        except Exception as e:
            logger.error("Failed to copy ICC profile: %s", e)
            return False

        # Try to register with colord
        self._register_colord_profile(str(dest), display_index)

        # Apply VCGT immediately via xcalib (if on X11)
        _run_cmd(["xcalib", str(dest)])

        return True

    def get_icc_profile(self, display_index: int) -> str | None:
        """
        Get the active ICC profile for a display.

        Strategy:
        1. Query colord via colormgr CLI
        2. Fall back to scanning ~/.local/share/icc/
        """
        displays = self._get_xrandr_outputs()
        if display_index < len(displays):
            output_name = displays[display_index]
            profile = self._get_colord_profile(output_name)
            if profile:
                return profile

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_xrandr_outputs(self) -> list[str]:
        """Get list of connected xrandr output names in order."""
        output = _run_cmd(["xrandr", "--query"])
        if output is None:
            return []

        parsed = _parse_xrandr_output(output)
        return [d["name"] for d in parsed]

    def _get_colord_profile(self, output_name: str) -> str | None:
        """Get the active ICC profile path for an xrandr output via colord."""
        # Try colormgr CLI first
        device_path = self._find_colord_device(output_name)
        if not device_path:
            return None

        profile_output = _run_cmd(["colormgr", "device-get-default-profile", device_path])
        if not profile_output:
            return None

        # Parse "Filename:" from colormgr output
        for line in profile_output.splitlines():
            line = line.strip()
            if line.startswith("Filename:"):
                path = line.split(":", 1)[1].strip()
                if path and Path(path).exists():
                    return path

        return None

    def _find_colord_device(self, output_name: str) -> str | None:
        """Find the colord device object path for an xrandr output."""
        output = _run_cmd(
            [
                "colormgr",
                "find-device-by-property",
                "OutputName",
                output_name,
            ]
        )
        if not output:
            return None

        # Parse "Object Path:" from colormgr output
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("Object Path:"):
                return line.split(":", 1)[1].strip()

        return None

    def _register_colord_profile(self, profile_path: str, display_index: int):
        """Register a profile with colord and set as default for display."""
        displays = self._get_xrandr_outputs()
        if display_index >= len(displays):
            logger.debug("Cannot register colord profile: display index out of range")
            return

        output_name = displays[display_index]

        # Import the profile into colord
        import_output = _run_cmd(["colormgr", "import-profile", profile_path])
        if not import_output:
            logger.debug("colormgr import-profile failed or unavailable")
            return

        # Find the profile object path
        profile_obj = None
        for line in import_output.splitlines():
            line = line.strip()
            if line.startswith("Object Path:"):
                profile_obj = line.split(":", 1)[1].strip()
                break

        if not profile_obj:
            return

        # Find the device
        device_obj = self._find_colord_device(output_name)
        if not device_obj:
            return

        # Add profile to device
        _run_cmd(["colormgr", "device-add-profile", device_obj, profile_obj])

        # Make it the default
        _run_cmd(["colormgr", "device-make-profile-default", device_obj, profile_obj])

        logger.info("ICC profile registered with colord for %s", output_name)


# =============================================================================
# Linux Startup Persistence (systemd user unit / XDG autostart)
# =============================================================================


def enable_linux_startup(silent: bool = True) -> bool:
    """Register Calibrate Pro as an XDG autostart entry."""
    import sys

    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = autostart_dir / "calibrate-pro.desktop"

    if getattr(sys, "frozen", False):
        exec_line = str(Path(sys.executable))
    else:
        args = f"{sys.executable} -m calibrate_pro.startup.calibration_loader start-service"
        if silent:
            args += " --silent"
        exec_line = args

    desktop_entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Calibrate Pro\n"
        "Comment=Display calibration loader\n"
        f"Exec={exec_line}\n"
        "Hidden=false\n"
        "NoDisplay=true\n"
        "X-GNOME-Autostart-enabled=true\n"
    )

    try:
        desktop_path.write_text(desktop_entry)
        logger.info("Linux autostart registered: %s", desktop_path)
        return True
    except Exception as e:
        logger.error("Failed to register Linux autostart: %s", e)
        return False


def disable_linux_startup() -> bool:
    """Remove Calibrate Pro from XDG autostart."""
    desktop_path = Path.home() / ".config" / "autostart" / "calibrate-pro.desktop"
    try:
        if desktop_path.exists():
            desktop_path.unlink()
            logger.info("Linux autostart removed: %s", desktop_path)
        return True
    except Exception as e:
        logger.error("Failed to remove Linux autostart: %s", e)
        return False


def is_linux_startup_enabled() -> bool:
    """Check if Calibrate Pro is registered as an XDG autostart entry."""
    desktop_path = Path.home() / ".config" / "autostart" / "calibrate-pro.desktop"
    return desktop_path.exists()
