"""
macOS Platform Backend

Full implementation using Apple frameworks via PyObjC:
- CoreGraphics (Quartz) for display enumeration and gamma ramps
- IOKit for EDID reading (manufacturer, model, serial)
- ColorSync for ICC profile management

Requires: pyobjc-framework-Quartz, pyobjc-framework-CoreFoundation

macOS gamma tables:
    CGSetDisplayTransferByTable accepts float arrays (0.0-1.0) with
    up to 1024 entries per channel. We use 256 entries for consistency
    with the Windows VCGT path.

ICC profiles:
    Installed to ~/Library/ColorSync/Profiles/ (per-user, no admin needed)
    or /Library/ColorSync/Profiles/ (system-wide, needs admin).
    Associated with displays via ColorSync device profile APIs.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from calibrate_pro.platform.base import (
    DisplayInfo as PlatformDisplayInfo,
)
from calibrate_pro.platform.base import (
    PlatformBackend,
)

logger = logging.getLogger(__name__)


def _have_quartz() -> bool:
    """Check if Quartz (CoreGraphics) bindings are available."""
    try:
        import Quartz  # noqa: F401

        return True
    except ImportError:
        return False


class MacOSBackend(PlatformBackend):
    """
    macOS implementation using CoreGraphics, IOKit, and ColorSync.

    Falls back gracefully if pyobjc is not installed.
    """

    # ------------------------------------------------------------------
    # Display enumeration
    # ------------------------------------------------------------------

    def enumerate_displays(self) -> list[PlatformDisplayInfo]:
        """Enumerate active displays via CoreGraphics."""
        try:
            import Quartz
        except ImportError:
            logger.error("pyobjc-framework-Quartz not installed. Run: pip install pyobjc-framework-Quartz")
            return []

        max_displays = 16
        (err, display_ids, count) = Quartz.CGGetActiveDisplayList(max_displays, None, None)
        if err != 0:
            logger.error("CGGetActiveDisplayList failed: error %d", err)
            return []

        results: list[PlatformDisplayInfo] = []
        main_display = Quartz.CGMainDisplayID()

        for i, did in enumerate(display_ids[:count]):
            # Resolution and refresh rate
            mode = Quartz.CGDisplayCopyDisplayMode(did)
            if mode:
                width = Quartz.CGDisplayModeGetWidth(mode)
                height = Quartz.CGDisplayModeGetHeight(mode)
                refresh = Quartz.CGDisplayModeGetRefreshRate(mode)
                if refresh == 0:
                    refresh = 60  # Default for displays that don't report
            else:
                bounds = Quartz.CGDisplayBounds(did)
                width = int(bounds.size.width)
                height = int(bounds.size.height)
                refresh = 60

            # Position
            bounds = Quartz.CGDisplayBounds(did)
            pos_x = int(bounds.origin.x)
            pos_y = int(bounds.origin.y)

            # EDID info (manufacturer, model, serial)
            manufacturer, model, serial = self._read_edid_info(did)

            # Display name
            name = model or f"Display {i + 1}"
            if manufacturer and manufacturer not in name:
                name = f"{manufacturer} {name}"

            # Current ICC profile
            icc_path = self._get_colorsync_profile_path(did)

            results.append(
                PlatformDisplayInfo(
                    index=i,
                    name=name,
                    device_path=str(did),
                    is_primary=(did == main_display),
                    width=width,
                    height=height,
                    refresh_rate=int(refresh),
                    bit_depth=Quartz.CGDisplayBitsPerPixel(did) if hasattr(Quartz, "CGDisplayBitsPerPixel") else 8,
                    position_x=pos_x,
                    position_y=pos_y,
                    manufacturer=manufacturer,
                    model=model,
                    serial=serial,
                    current_icc_profile=icc_path,
                )
            )

        return results

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
        """Apply gamma ramp via CGSetDisplayTransferByTable."""
        try:
            import Quartz
        except ImportError:
            logger.error("pyobjc-framework-Quartz not installed")
            return False

        did = self._get_display_id(display_index)
        if did is None:
            return False

        # Convert 0-65535 int arrays to 0.0-1.0 float arrays
        table_size = len(red)
        r_table = [r / 65535.0 for r in red]
        g_table = [g / 65535.0 for g in green]
        b_table = [b / 65535.0 for b in blue]

        err = Quartz.CGSetDisplayTransferByTable(did, table_size, r_table, g_table, b_table)
        if err != 0:
            logger.error("CGSetDisplayTransferByTable failed: error %d", err)
            return False

        logger.info("Gamma ramp applied to display %d (CGDirectDisplayID %d)", display_index, did)
        return True

    def reset_gamma_ramp(self, display_index: int) -> bool:
        """Reset gamma ramp to ColorSync defaults."""
        try:
            import Quartz
        except ImportError:
            return False

        # CGDisplayRestoreColorSyncSettings resets ALL displays
        Quartz.CGDisplayRestoreColorSyncSettings()
        logger.info("Gamma ramps reset to ColorSync defaults")
        return True

    # ------------------------------------------------------------------
    # ICC profile management
    # ------------------------------------------------------------------

    def install_icc_profile(
        self,
        profile_path: str,
        display_index: int,
    ) -> bool:
        """Install ICC profile to ~/Library/ColorSync/Profiles/."""
        src = Path(profile_path)
        if not src.exists():
            logger.error("ICC profile not found: %s", profile_path)
            return False

        # Per-user ColorSync directory (no admin needed)
        dest_dir = Path.home() / "Library" / "ColorSync" / "Profiles"
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest = dest_dir / src.name
        try:
            shutil.copy2(str(src), str(dest))
            logger.info("ICC profile installed to %s", dest)
        except Exception as e:
            logger.error("Failed to copy ICC profile: %s", e)
            return False

        # Try to associate with the display via ColorSync
        try:
            self._associate_profile_with_display(dest, display_index)
        except Exception as e:
            logger.warning(
                "Profile copied but could not auto-associate: %s. "
                "Set it manually in System Settings > Displays > Color.",
                e,
            )

        return True

    def get_icc_profile(self, display_index: int) -> str | None:
        """Get the active ICC profile path for a display."""
        did = self._get_display_id(display_index)
        if did is None:
            return None
        return self._get_colorsync_profile_path(did)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_display_id(self, display_index: int) -> int | None:
        """Get CGDirectDisplayID for a display index."""
        try:
            import Quartz

            max_displays = 16
            (err, display_ids, count) = Quartz.CGGetActiveDisplayList(max_displays, None, None)
            if err == 0 and display_index < count:
                return display_ids[display_index]
        except Exception as e:
            logger.debug("Failed to get display ID: %s", e)
        return None

    def _read_edid_info(self, display_id: int) -> tuple:
        """Read manufacturer, model, serial from display via CoreGraphics."""
        manufacturer = ""
        model = ""
        serial = ""

        try:
            import Quartz

            vendor_id = Quartz.CGDisplayVendorNumber(display_id)
            product_id = Quartz.CGDisplayModelNumber(display_id)
            serial_num = Quartz.CGDisplaySerialNumber(display_id)

            # Map common vendor IDs (PNP ID encoded as big-endian)
            vendor_map = {
                1128: "Apple",
                1262: "Samsung",
                2513: "Acer",
                3502: "BenQ",
                4098: "HP",
                4137: "LG",
                4268: "Dell",
                4743: "Lenovo",
                5765: "Sony",
                6476: "ViewSonic",
                7789: "ASUS",
                8478: "Gigabyte",
                1189: "EIZO",
            }
            manufacturer = vendor_map.get(vendor_id, "")

            # Try to get display name via IOKit display info dictionary
            try:
                # CGDisplayIOServicePort is deprecated but still works on macOS < 14
                service = Quartz.CGDisplayIOServicePort(display_id)
                if service:
                    info = Quartz.IODisplayCreateInfoDictionary(service, Quartz.kIODisplayOnlyPreferredName)
                    if info:
                        names = info.get("DisplayProductName", {})
                        if names:
                            # Get first available localized name
                            model = str(list(names.values())[0])
            except Exception:
                pass

            if not model:
                model = f"Display {product_id}" if product_id else ""

            serial = str(serial_num) if serial_num else ""

        except Exception as e:
            logger.debug("Display info read failed: %s", e)

        return manufacturer, model, serial

    def _get_colorsync_profile_path(self, display_id: int) -> str | None:
        """Get the current ColorSync profile path for a display."""
        try:
            import Quartz

            # CGDisplayCopyColorSpace returns a CGColorSpaceRef
            # We can get the ICC profile data from it
            colorspace = Quartz.CGDisplayCopyColorSpace(display_id)
            if colorspace:
                # Try to get the profile name
                name = Quartz.CGColorSpaceCopyName(colorspace)
                if name:
                    # Check common profile locations
                    for profiles_dir in [
                        Path.home() / "Library" / "ColorSync" / "Profiles",
                        Path("/Library/ColorSync/Profiles"),
                        Path("/System/Library/ColorSync/Profiles"),
                    ]:
                        if profiles_dir.exists():
                            for p in profiles_dir.glob("*.icc"):
                                if str(name) in p.stem:
                                    return str(p)
                            for p in profiles_dir.glob("*.icm"):
                                if str(name) in p.stem:
                                    return str(p)
        except Exception as e:
            logger.debug("ColorSync profile query failed: %s", e)
        return None

    def _associate_profile_with_display(self, profile_path: Path, display_index: int):
        """Associate an ICC profile with a display via ColorSync."""
        try:
            import Quartz  # noqa: F401 — ensure pyobjc-framework-Quartz is available
            from ColorSync import (
                ColorSyncDeviceSetCustomProfiles,
                kColorSyncDeviceDefaultProfileID,
                kColorSyncDisplayDeviceClass,
            )
            from Foundation import NSURL, NSDictionary

            did = self._get_display_id(display_index)
            if did is None:
                return

            profile_url = NSURL.fileURLWithPath_(str(profile_path))
            profile_info = NSDictionary.dictionaryWithObject_forKey_(profile_url, kColorSyncDeviceDefaultProfileID)

            # Create UUID from display ID
            import uuid

            display_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"display-{did}"))

            ColorSyncDeviceSetCustomProfiles(
                kColorSyncDisplayDeviceClass,
                display_uuid,
                profile_info,
            )
            logger.info("ICC profile associated with display %d via ColorSync", display_index)

        except ImportError:
            logger.debug("ColorSync framework not available for profile association")
        except Exception as e:
            logger.debug("ColorSync profile association failed: %s", e)


# =============================================================================
# macOS Startup Persistence (launchd)
# =============================================================================


def enable_macos_startup(silent: bool = True) -> bool:
    """Register Calibrate Pro as a macOS login item via launchd plist."""
    import plistlib
    import sys

    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.quantauniverse.calibratepro.plist"

    if getattr(sys, "frozen", False):
        program = [str(Path(sys.executable))]
    else:
        program = [sys.executable, "-m", "calibrate_pro.startup.calibration_loader", "start-service"]
        if silent:
            program.append("--silent")

    plist = {
        "Label": "com.quantauniverse.calibratepro",
        "ProgramArguments": program,
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(Path.home() / "Library" / "Logs" / "CalibrateProOut.log"),
        "StandardErrorPath": str(Path.home() / "Library" / "Logs" / "CalibrateProErr.log"),
    }

    try:
        with open(plist_path, "wb") as f:
            plistlib.dump(plist, f)
        logger.info("macOS startup registered: %s", plist_path)
        return True
    except Exception as e:
        logger.error("Failed to register macOS startup: %s", e)
        return False


def disable_macos_startup() -> bool:
    """Remove Calibrate Pro from macOS login items."""
    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.quantauniverse.calibratepro.plist"
    try:
        if plist_path.exists():
            plist_path.unlink()
            logger.info("macOS startup removed: %s", plist_path)
        return True
    except Exception as e:
        logger.error("Failed to remove macOS startup: %s", e)
        return False


def is_macos_startup_enabled() -> bool:
    """Check if Calibrate Pro is registered as a macOS login item."""
    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.quantauniverse.calibratepro.plist"
    return plist_path.exists()
