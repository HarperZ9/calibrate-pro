"""
Display Detection Module

Detects connected displays using Windows APIs and EDID data.
Provides display information for calibration target selection.
"""

from __future__ import annotations

import ctypes
import re
import struct
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

# =============================================================================
# Windows API Definitions (only loaded on Windows)
# =============================================================================

if sys.platform == "win32":
    from ctypes import wintypes

    # User32.dll
    user32 = ctypes.windll.user32

    # Display device flags
    DISPLAY_DEVICE_ACTIVE = 0x00000001
    DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
    DISPLAY_DEVICE_MIRRORING_DRIVER = 0x00000008
    DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001

    # Monitor info flags
    MONITORINFOF_PRIMARY = 0x00000001
else:
    # Stubs for non-Windows platforms (the Win32 code paths are guarded)
    wintypes = None
    user32 = None
    DISPLAY_DEVICE_ACTIVE = 0x00000001
    DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
    DISPLAY_DEVICE_MIRRORING_DRIVER = 0x00000008
    DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
    MONITORINFOF_PRIMARY = 0x00000001

# EnumDisplayDevices flags
EDD_GET_DEVICE_INTERFACE_NAME = 0x00000001

# Windows-specific ctypes structures (only defined on Windows)
if sys.platform == "win32":

    class DISPLAY_DEVICE(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("DeviceName", wintypes.WCHAR * 32),
            ("DeviceString", wintypes.WCHAR * 128),
            ("StateFlags", wintypes.DWORD),
            ("DeviceID", wintypes.WCHAR * 128),
            ("DeviceKey", wintypes.WCHAR * 128),
        ]

    class DEVMODE(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG),
            ("dmPositionY", wintypes.LONG),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", wintypes.SHORT),
            ("dmDuplex", wintypes.SHORT),
            ("dmYResolution", wintypes.SHORT),
            ("dmTTOption", wintypes.SHORT),
            ("dmCollate", wintypes.SHORT),
            ("dmFormName", wintypes.WCHAR * 32),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD),
            ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD),
            ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD),
            ("dmPanningHeight", wintypes.DWORD),
        ]

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]


if sys.platform == "win32":

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    class MONITORINFOEX(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    # ``EnumDisplayDevicesW`` is a process-shared ctypes function object.
    # Use a layout-neutral pointer so other modules can pass compatible
    # DISPLAY_DEVICE declarations regardless of import order.
    user32.EnumDisplayDevicesW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    user32.EnumDisplayDevicesW.restype = wintypes.BOOL

# =============================================================================
# Display Information
# =============================================================================


@dataclass
class DisplayInfo:
    """Information about a connected display."""

    device_name: str  # Windows device name (e.g., "\\\\.\\DISPLAY1")
    device_string: str  # Friendly name (e.g., "NVIDIA GeForce RTX 4090")
    monitor_name: str  # Monitor model from EDID
    device_id: str  # PnP device ID
    is_primary: bool
    is_active: bool

    # Resolution and position
    width: int
    height: int
    refresh_rate: int
    bit_depth: int
    position_x: int
    position_y: int

    # EDID data
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    year: int = 0

    # Enhanced detection fields
    panel_type: str = ""  # OLED, QD-OLED, WOLED, IPS, VA, TN, Mini-LED
    connection_type: str = ""  # HDMI, DisplayPort, USB-C, DVI
    hdr_capable: bool = False  # HDR10/Dolby Vision support
    wide_gamut: bool = False  # DCI-P3 or wider gamut
    native_gamma: float = 2.2  # Native panel gamma
    max_luminance: float = 0.0  # Peak brightness (cd/m²)
    panel_size_inches: float = 0.0  # Diagonal size in inches
    panel_database_key: str = ""  # Matched panel database key

    # Current ICC profile
    current_profile: str | None = None

    def get_resolution_string(self) -> str:
        """Get resolution as string (e.g., '3840x2160')."""
        return f"{self.width}x{self.height}"

    def get_display_number(self) -> int:
        """Extract display number from device name."""
        match = re.search(r"DISPLAY(\d+)", self.device_name)
        return int(match.group(1)) if match else 0

    def get_aspect_ratio(self) -> str:
        """Calculate aspect ratio string."""
        from math import gcd

        g = gcd(self.width, self.height)
        w, h = self.width // g, self.height // g
        # Normalize common ratios
        if (w, h) == (8, 5):
            return "16:10"
        elif (w, h) == (16, 9):
            return "16:9"
        elif (w, h) == (64, 27):
            return "21:9"
        elif (w, h) == (32, 9):
            return "32:9"
        elif (w, h) == (4, 3):
            return "4:3"
        return f"{w}:{h}"

    def is_ultrawide(self) -> bool:
        """Check if display is ultrawide."""
        aspect = self.width / self.height
        return aspect >= 2.0  # 21:9 or wider

    def is_4k(self) -> bool:
        """Check if display is 4K or higher."""
        return self.width >= 3840 and self.height >= 2160

    def is_high_refresh(self) -> bool:
        """Check if display is high refresh rate."""
        return self.refresh_rate >= 120

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "device_name": self.device_name,
            "device_string": self.device_string,
            "monitor_name": self.monitor_name,
            "device_id": self.device_id,
            "is_primary": self.is_primary,
            "is_active": self.is_active,
            "resolution": self.get_resolution_string(),
            "refresh_rate": self.refresh_rate,
            "bit_depth": self.bit_depth,
            "position": (self.position_x, self.position_y),
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial": self.serial,
            "year": self.year,
            "aspect_ratio": self.get_aspect_ratio(),
            "panel_type": self.panel_type,
            "connection_type": self.connection_type,
            "hdr_capable": self.hdr_capable,
            "wide_gamut": self.wide_gamut,
            "native_gamma": self.native_gamma,
            "max_luminance": self.max_luminance,
            "panel_size_inches": self.panel_size_inches,
            "panel_database_key": self.panel_database_key,
            "current_profile": self.current_profile,
        }


# =============================================================================
# Cross-Platform Display Detection
# =============================================================================


def _enumerate_displays_cross_platform() -> list[DisplayInfo]:
    """Enumerate displays on macOS/Linux via the platform backend."""
    try:
        from calibrate_pro.platform import get_platform_backend

        backend = get_platform_backend()
        platform_displays = backend.enumerate_displays()

        results = []
        for pd in platform_displays:
            di = DisplayInfo(
                device_name=pd.device_path,
                device_string=pd.name,
                monitor_name=pd.name,
                device_id=pd.device_path,
                is_primary=pd.is_primary,
                is_active=True,
                width=pd.width,
                height=pd.height,
                refresh_rate=pd.refresh_rate,
                bit_depth=pd.bit_depth,
                position_x=pd.position_x,
                position_y=pd.position_y,
            )
            di.manufacturer = pd.manufacturer
            di.model = pd.model
            di.serial = pd.serial
            di.current_profile = pd.current_icc_profile
            results.append(di)
        return results

    except Exception as e:
        import logging

        logging.getLogger(__name__).error("Cross-platform display detection failed: %s", e)
        return []


# =============================================================================
# Display Detection
# =============================================================================


def enumerate_displays() -> list[DisplayInfo]:
    """
    Enumerate all connected displays.

    On Windows, uses Win32 EnumDisplayDevices directly.
    On macOS/Linux, delegates to the platform backend and converts
    the result to the detection module's DisplayInfo format.

    Returns:
        List of DisplayInfo for each active display
    """
    import sys

    if sys.platform != "win32":
        return _enumerate_displays_cross_platform()

    displays = []

    # Enumerate display adapters (Windows-specific)
    adapter_index = 0
    while True:
        adapter = DISPLAY_DEVICE()
        adapter.cb = ctypes.sizeof(adapter)

        if not user32.EnumDisplayDevicesW(None, adapter_index, ctypes.byref(adapter), 0):
            break

        adapter_index += 1

        # Skip mirroring drivers
        if adapter.StateFlags & DISPLAY_DEVICE_MIRRORING_DRIVER:
            continue

        # Get current display settings
        devmode = DEVMODE()
        devmode.dmSize = ctypes.sizeof(devmode)

        if user32.EnumDisplaySettingsW(adapter.DeviceName, -1, ctypes.byref(devmode)):
            # Enumerate monitors attached to this adapter
            monitor_index = 0
            while True:
                monitor = DISPLAY_DEVICE()
                monitor.cb = ctypes.sizeof(monitor)

                if not user32.EnumDisplayDevicesW(
                    adapter.DeviceName, monitor_index, ctypes.byref(monitor), EDD_GET_DEVICE_INTERFACE_NAME
                ):
                    break

                monitor_index += 1

                if not (monitor.StateFlags & DISPLAY_DEVICE_ACTIVE):
                    continue

                # Parse device ID for EDID info
                manufacturer, model = parse_device_id(monitor.DeviceID)

                display = DisplayInfo(
                    device_name=adapter.DeviceName,
                    device_string=adapter.DeviceString,
                    monitor_name=monitor.DeviceString,
                    device_id=monitor.DeviceID,
                    is_primary=bool(adapter.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE),
                    is_active=bool(adapter.StateFlags & DISPLAY_DEVICE_ACTIVE),
                    width=devmode.dmPelsWidth,
                    height=devmode.dmPelsHeight,
                    refresh_rate=devmode.dmDisplayFrequency,
                    bit_depth=devmode.dmBitsPerPel,
                    position_x=devmode.dmPositionX,
                    position_y=devmode.dmPositionY,
                    manufacturer=manufacturer,
                    model=model,
                )

                # Get current ICC profile
                display.current_profile = get_display_profile(adapter.DeviceName)

                displays.append(display)

    return displays


def parse_device_id(device_id: str) -> tuple[str, str]:
    """
    Parse manufacturer and model from device ID.

    Args:
        device_id: PnP device ID string

    Returns:
        (manufacturer, model) tuple
    """
    manufacturer = ""
    model = ""

    # Device ID formats:
    # - MONITOR\{vendor}{product}\{serial}     (e.g., MONITOR\SAM0F9E\{...})
    # - \\?\DISPLAY#{vendor}{product}#{serial} (e.g., \\?\DISPLAY#SAM72F2#...)
    match = re.search(r"(?:MONITOR\\|DISPLAY#)([A-Z]{3})([A-F0-9]{4})", device_id, re.IGNORECASE)
    if match:
        vendor_code = match.group(1).upper()
        product_code = match.group(2).upper()

        # Map vendor codes
        vendor_map = {
            "SAM": "Samsung",
            "AUS": "ASUS",
            "DEL": "Dell",
            "LGD": "LG",
            "GSM": "LG",
            "ACR": "Acer",
            "BNQ": "BenQ",
            "AOC": "AOC",
            "VSC": "ViewSonic",
            "PHL": "Philips",
            "NEC": "NEC",
            "EIZ": "EIZO",
            "HWP": "HP",
            "MSI": "MSI",
            "SNY": "Sony",
        }

        manufacturer = vendor_map.get(vendor_code, vendor_code)
        model = product_code

    return manufacturer, model


# =============================================================================
# Enhanced EDID Detection (Reads raw EDID from registry)
# =============================================================================


def get_edid_from_registry(device_id: str) -> bytes | None:
    """
    Read raw EDID data from Windows registry.

    This works even when Windows shows "Generic PnP Monitor" because
    the raw EDID is still stored in the registry.

    Args:
        device_id: PnP device ID string

    Returns:
        Raw EDID bytes (128 or 256 bytes) or None
    """
    import winreg

    try:
        # Extract the monitor key from device ID
        # Format: MONITOR\XXX####\{guid}_##
        match = re.search(r"MONITOR\\([A-Z]{3}[A-F0-9]{4})\\", device_id, re.IGNORECASE)
        if not match:
            return None

        monitor_key = match.group(1).upper()

        # Search in HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Enum\DISPLAY
        base_path = r"SYSTEM\CurrentControlSet\Enum\DISPLAY"

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base_path) as display_key:
            # Enumerate display subkeys
            for i in range(100):
                try:
                    subkey_name = winreg.EnumKey(display_key, i)

                    # Check if this matches our monitor
                    if monitor_key in subkey_name.upper():
                        subkey_path = f"{base_path}\\{subkey_name}"

                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path) as monitor_type_key:
                            # Enumerate instance subkeys
                            for j in range(10):
                                try:
                                    instance_name = winreg.EnumKey(monitor_type_key, j)
                                    instance_path = f"{subkey_path}\\{instance_name}\\Device Parameters"

                                    try:
                                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, instance_path) as params_key:
                                            edid, _ = winreg.QueryValueEx(params_key, "EDID")
                                            if edid and len(edid) >= 128:
                                                return bytes(edid)
                                    except FileNotFoundError:
                                        pass

                                except OSError:
                                    break

                except OSError:
                    break

    except Exception:
        pass

    return None


def parse_edid(edid: bytes) -> dict:
    """
    Parse EDID data to extract display information.

    Args:
        edid: Raw EDID bytes (128 or 256 bytes)

    Returns:
        Dictionary with parsed EDID data
    """
    result = {
        "manufacturer": "",
        "manufacturer_code": "",
        "product_code": 0,
        "serial_number": 0,
        "week": 0,
        "year": 0,
        "version": "",
        "monitor_name": "",
        "serial_string": "",
        "horizontal_cm": 0,
        "vertical_cm": 0,
        "gamma": 0.0,
        "native_resolution": (0, 0),
        "max_refresh": 0,
    }

    if not edid or len(edid) < 128:
        return result

    # Check EDID header (bytes 0-7: 00 FF FF FF FF FF FF 00)
    if edid[0:8] != bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00]):
        return result

    # Manufacturer ID (bytes 8-9) - 3 letters encoded in 15 bits
    mfg_id = (edid[8] << 8) | edid[9]
    char1 = ((mfg_id >> 10) & 0x1F) + ord("A") - 1
    char2 = ((mfg_id >> 5) & 0x1F) + ord("A") - 1
    char3 = (mfg_id & 0x1F) + ord("A") - 1
    result["manufacturer_code"] = chr(char1) + chr(char2) + chr(char3)

    # Map manufacturer codes to names
    vendor_map = {
        "SAM": "Samsung",
        "AUS": "ASUS",
        "DEL": "Dell",
        "LGD": "LG Display",
        "GSM": "LG Electronics",
        "ACR": "Acer",
        "BNQ": "BenQ",
        "AOC": "AOC",
        "VSC": "ViewSonic",
        "PHL": "Philips",
        "NEC": "NEC",
        "EIZ": "EIZO",
        "HWP": "HP",
        "MSI": "MSI",
        "SNY": "Sony",
        "CMN": "Chi Mei Innolux",
        "BOE": "BOE",
        "AUO": "AU Optronics",
        "SDC": "Samsung Display",
    }
    result["manufacturer"] = vendor_map.get(str(result["manufacturer_code"]), str(result["manufacturer_code"]))

    # Product code (bytes 10-11, little-endian)
    result["product_code"] = edid[10] | (edid[11] << 8)

    # Serial number (bytes 12-15, little-endian)
    result["serial_number"] = struct.unpack("<I", edid[12:16])[0]

    # Week and year of manufacture (bytes 16-17)
    result["week"] = edid[16]
    result["year"] = edid[17] + 1990

    # EDID version (bytes 18-19)
    result["version"] = f"{edid[18]}.{edid[19]}"

    # Display size in cm (bytes 21-22)
    result["horizontal_cm"] = edid[21]
    result["vertical_cm"] = edid[22]

    # Gamma (byte 23) - stored as (gamma * 100) - 100
    if edid[23] != 0xFF:
        result["gamma"] = (edid[23] + 100) / 100.0

    # Preferred timing (bytes 54-71) - first detailed timing descriptor
    if len(edid) >= 71:
        pixel_clock = struct.unpack("<H", edid[54:56])[0] * 10000  # kHz
        if pixel_clock > 0:
            h_active = edid[56] | ((edid[58] & 0xF0) << 4)
            v_active = edid[59] | ((edid[61] & 0xF0) << 4)
            result["native_resolution"] = (h_active, v_active)

            # Calculate refresh rate
            h_total = h_active + (edid[57] | ((edid[58] & 0x0F) << 8))
            v_total = v_active + (edid[60] | ((edid[61] & 0x0F) << 8))
            if h_total > 0 and v_total > 0:
                result["max_refresh"] = round(pixel_clock / (h_total * v_total))

    # Parse descriptor blocks (bytes 54-125, 4 blocks of 18 bytes each)
    for block_start in [54, 72, 90, 108]:
        if len(edid) < block_start + 18:
            break

        block = edid[block_start : block_start + 18]

        # Check if this is a text descriptor (starts with 00 00 00)
        if block[0:3] == bytes([0x00, 0x00, 0x00]):
            tag = block[3]
            text = block[5:18].decode("ascii", errors="ignore").strip()

            if tag == 0xFC:  # Monitor name
                result["monitor_name"] = text.replace("\n", "").strip()
            elif tag == 0xFF:  # Serial string
                result["serial_string"] = text.replace("\n", "").strip()

    return result


def get_display_fingerprint(display: DisplayInfo) -> str:
    """
    Create a fingerprint for display identification.

    Uses resolution, refresh rate, and position to create a unique identifier
    that can be matched against known panel profiles.

    Args:
        display: DisplayInfo object

    Returns:
        Fingerprint string (e.g., "3840x2160@240_ASUS")
    """
    fingerprint = f"{display.width}x{display.height}@{display.refresh_rate}"
    if display.manufacturer:
        fingerprint += f"_{display.manufacturer}"
    return fingerprint


# Known display fingerprints for automatic matching
# Format: "WIDTHxHEIGHT@REFRESH_MANUFACTURER": "PANEL_DATABASE_KEY"
DISPLAY_FINGERPRINTS = {
    # ===========================================
    # QD-OLED Monitors (Samsung Display panels)
    # ===========================================
    # ASUS PG27UCDM - 4K 240Hz QD-OLED 27"
    "3840x2160@240_ASUS": "PG27UCDM",
    "3840x2160@240_AUS": "PG27UCDM",
    # ASUS PG32UCDM - 4K 240Hz QD-OLED 32"
    "3840x2160@240_ASUS_32": "PG32UCDM",
    # Samsung Odyssey G8 G80SD - 4K 240Hz QD-OLED 32"
    "3840x2160@240_Samsung": "G80SD",
    "3840x2160@240_SAM": "G80SD",
    # Samsung Odyssey G85SB - 4K 240Hz QD-OLED 34"
    "3440x1440@175_Samsung": "G85SB",
    "3440x1440@175_SAM": "G85SB",
    # Dell Alienware AW3225QF - 4K 240Hz QD-OLED 32"
    "3840x2160@240_Dell": "AW3225QF",
    "3840x2160@240_DEL": "AW3225QF",
    # Dell Alienware AW3423DW - 3440x1440 175Hz QD-OLED 34"
    "3440x1440@175_Dell": "AW3423DW",
    "3440x1440@175_DEL": "AW3423DW",
    "3440x1440@175": "AW3423DW",
    # Gigabyte AORUS FO32U2P - 4K 240Hz QD-OLED 32"
    "3840x2160@240_Gigabyte": "FO32U2P",
    # Samsung Odyssey G95SC - 5120x1440 240Hz QD-OLED 49"
    "5120x1440@240_Samsung": "G95SC",
    "5120x1440@240_SAM": "G95SC",
    # MSI MEG 342C - 3440x1440 175Hz QD-OLED 34"
    "3440x1440@175_MSI": "MEG342C",
    # Corsair Xeneon 34 - 3440x1440 175Hz QD-OLED 34"
    "3440x1440@175_Corsair": "XENEON34",
    # Default for unidentified 4K 240Hz (assume QD-OLED)
    "3840x2160@240": "PG27UCDM",
    # ===========================================
    # WOLED Monitors (LG Display panels)
    # ===========================================
    # LG 27GR95QE - 2560x1440 240Hz WOLED 27"
    "2560x1440@240_LG": "27GR95QE",
    "2560x1440@240_GSM": "27GR95QE",
    # LG C3 OLED TVs (42/48/55")
    "3840x2160@120_LG": "LG_C3",
    "3840x2160@120_GSM": "LG_C3",
    # LG C4 OLED TVs (42/48/55/65")
    "3840x2160@144_LG": "LG_C4",
    "3840x2160@144_GSM": "LG_C4",
    # ===========================================
    # IPS/Mini-LED Monitors
    # ===========================================
    # Sony INZONE M9 - 4K 144Hz IPS+FALD
    "3840x2160@144_Sony": "INZONE_M9",
    "3840x2160@144_SNY": "INZONE_M9",
    # LG 27GP950-B - 4K 160Hz Nano-IPS
    "3840x2160@160_LG": "27GP950",
    "3840x2160@160_GSM": "27GP950",
    # BenQ PD3220U - 4K 60Hz IPS (Professional)
    "3840x2160@60_BenQ": "PD3220U",
    "3840x2160@60_BNQ": "PD3220U",
    # ASUS ProArt PA32UCG - 4K 120Hz Mini-LED
    "3840x2160@120_ASUS": "PA32UCG",
    "3840x2160@120_AUS": "PA32UCG",
    # Samsung Odyssey G7/G5 Ultrawides (VA)
    "3440x1440@120_Samsung": "ODYSSEY_G7_UW",
    "3440x1440@120_SAM": "ODYSSEY_G7_UW",
    "3440x1440@144_Samsung": "ODYSSEY_G7_UW",
    "3440x1440@144_SAM": "ODYSSEY_G7_UW",
    "3440x1440@165_Samsung": "ODYSSEY_G7_UW",
    "3440x1440@165_SAM": "ODYSSEY_G7_UW",
    # ===========================================
    # Professional / Photo Editing Monitors
    # ===========================================
    # Dell U2723QE - 4K 60Hz IPS (sRGB professional)
    "3840x2160@60_Dell": "U2723QE",
    "3840x2160@60_DEL": "U2723QE",
    # BenQ SW271C - 4K 60Hz IPS (Photo editing)
    "3840x2160@60_BenQ_SW": "SW271C",
    "3840x2160@60_BNQ_SW": "SW271C",
    # EIZO CG2700S - 2560x1440 60Hz IPS (Professional reference)
    "2560x1440@60_EIZO": "CG2700S",
    "2560x1440@60_EIZ": "CG2700S",
    # Dell U3423WE - 3440x1440 60Hz IPS (Ultrawide professional)
    "3440x1440@60_Dell": "U3423WE",
    "3440x1440@60_DEL": "U3423WE",
    # ViewSonic VP2786-4K - 4K 60Hz IPS (Professional)
    "3840x2160@60_ViewSonic": "VP2786",
    "3840x2160@60_VSC": "VP2786",
    # ===========================================
    # Gaming IPS / Nano-IPS Monitors
    # ===========================================
    # ASUS VG27AQ1A - 2K 170Hz IPS (Gaming)
    "2560x1440@170_ASUS": "VG27AQ1A",
    "2560x1440@170_AUS": "VG27AQ1A",
    # LG 27GP850-B - 2K 165Hz Nano IPS (Gaming)
    "2560x1440@165_LG": "27GP850",
    "2560x1440@165_GSM": "27GP850",
    # MSI MAG 274QRF-QD - 2K 165Hz QD-IPS
    "2560x1440@165_MSI": "274QRF_QD",
    # Gigabyte M28U - 4K 144Hz IPS (Budget 4K gaming)
    "3840x2160@144_Gigabyte": "M28U",
    # ===========================================
    # Gaming VA Monitors
    # ===========================================
    # Samsung Odyssey G7 27" - 2K 240Hz VA (Gaming)
    "2560x1440@240_Samsung": "ODYSSEY_G7_27",
    "2560x1440@240_SAM": "ODYSSEY_G7_27",
    # Dell S2722DGM - 2K 165Hz VA (Budget gaming)
    "2560x1440@165_Dell": "S2722DGM",
    "2560x1440@165_DEL": "S2722DGM",
    # ===========================================
    # QD-OLED TVs
    # ===========================================
    # Sony A95L - 4K 120Hz QD-OLED TV
    "3840x2160@120_Sony": "SONY_A95L",
    "3840x2160@120_SNY": "SONY_A95L",
    # Samsung S95D - 4K 144Hz QD-OLED TV
    "3840x2160@144_Samsung": "S95D",
    "3840x2160@144_SAM": "S95D",
    # ===========================================
    # QD-OLED Ultrawide Monitors
    # ===========================================
    # ASUS PG34WCDM - 3440x1440 240Hz QD-OLED
    "3440x1440@240_ASUS": "PG34WCDM",
    "3440x1440@240_AUS": "PG34WCDM",
    # ===========================================
    # WOLED Monitors
    # ===========================================
    # LG 32GS95UE - 4K 240Hz WOLED 32"
    "3840x2160@240_LG_32": "32GS95UE",
    "3840x2160@240_GSM_32": "32GS95UE",
}

# =============================================================================
# Panel Type Detection
# =============================================================================

# Known OLED models (for panel type detection when EDID doesn't specify)
KNOWN_OLED_MODELS = {
    # QD-OLED
    "PG27UCDM",
    "PG32UCDM",
    "G80SD",
    "G85SB",
    "G95SC",
    "AW3423DW",
    "AW3225QF",
    "MEG342C",
    "XENEON34",
    "FO32U2P",
    "PG34WCDM",
    "QD-OLED",
    # WOLED
    "27GR95QE",
    "45GR95QE",
    "32GS95UE",
    "C1",
    "C2",
    "C3",
    "C4",
    "G1",
    "G2",
    "G3",
    "G4",
    "A80K",
    "A90K",
    "A95K",
    "A80L",
    "A95L",
    "S95B",
    "S95C",
    "S95D",
}

KNOWN_MINI_LED_MODELS = {
    "PA32UCG",
    "XDR",
    "Pro Display XDR",
    "INZONE_M9",
    "M32U",
    "PG32UCDP",
    "PD32M",
    "U32R59",
    "M80C",
    "NEO G9",
}


def detect_panel_type(model_name: str, manufacturer: str, edid_info: dict | None = None) -> str:
    """
    Detect panel type from model name and EDID information.

    Args:
        model_name: Monitor model name
        manufacturer: Manufacturer name
        edid_info: Parsed EDID data (optional)

    Returns:
        Panel type string: QD-OLED, WOLED, IPS, VA, TN, Mini-LED, or Unknown
    """
    model_upper = model_name.upper()
    mfg_upper = manufacturer.upper()

    # Check for explicit OLED in name
    if "QD-OLED" in model_upper or "QDOLED" in model_upper:
        return "QD-OLED"
    if "OLED" in model_upper:
        # Samsung OLED = QD-OLED, LG = WOLED
        if "SAMSUNG" in mfg_upper or "SAM" in mfg_upper:
            return "QD-OLED"
        elif "LG" in mfg_upper or "GSM" in mfg_upper:
            return "WOLED"
        return "OLED"

    # Check known OLED models
    for known in KNOWN_OLED_MODELS:
        if known.upper() in model_upper:
            # Determine QD-OLED vs WOLED
            if any(
                x in mfg_upper for x in ["SAMSUNG", "SAM", "DELL", "DEL", "ASUS", "AUS", "MSI", "CORSAIR", "GIGABYTE"]
            ):
                return "QD-OLED"
            elif any(x in mfg_upper for x in ["LG", "GSM", "SONY", "SNY"]):
                return "WOLED"
            return "OLED"

    # Check known Mini-LED models
    for known in KNOWN_MINI_LED_MODELS:
        if known.upper() in model_upper:
            return "Mini-LED"

    if "MINI LED" in model_upper or "MINILED" in model_upper:
        return "Mini-LED"

    # Check for Nano-IPS (LG wide gamut IPS)
    if "GP950" in model_upper or "GP95" in model_upper:
        return "Nano-IPS"

    # Check panel characteristics from EDID if available
    if edid_info:
        # High contrast + low black = likely OLED
        # Wide gamut primaries can indicate panel type
        pass

    # Default based on manufacturer trends
    if any(x in mfg_upper for x in ["BENQ", "BNQ", "EIZO", "EIZ", "NEC"]):
        return "IPS"  # Professional monitors typically IPS
    if "AOC" in mfg_upper:
        return "VA"  # AOC commonly uses VA

    return "Unknown"


def detect_connection_type(device_id: str) -> str:
    """
    Detect connection type from device ID.

    Args:
        device_id: PnP device ID string

    Returns:
        Connection type: HDMI, DisplayPort, USB-C, DVI, VGA, or Unknown
    """
    device_upper = device_id.upper()

    # Check for common connection identifiers in device path
    if "DP" in device_upper or "DISPLAYPORT" in device_upper:
        return "DisplayPort"
    if "HDMI" in device_upper:
        return "HDMI"
    if "USB" in device_upper or "USBC" in device_upper or "TYPE-C" in device_upper:
        return "USB-C"
    if "DVI" in device_upper:
        return "DVI"
    if "VGA" in device_upper or "DSUB" in device_upper:
        return "VGA"

    # Check based on adapter string (GPU output)
    # This is less reliable but can give hints
    return "Unknown"


def calculate_panel_size(h_cm: int, v_cm: int) -> float:
    """
    Calculate diagonal panel size in inches from EDID dimensions.

    Args:
        h_cm: Horizontal size in centimeters
        v_cm: Vertical size in centimeters

    Returns:
        Diagonal size in inches
    """
    import math

    if h_cm <= 0 or v_cm <= 0:
        return 0.0
    diagonal_cm = math.sqrt(h_cm**2 + v_cm**2)
    return round(diagonal_cm / 2.54, 1)


def enrich_display_info(display: DisplayInfo) -> DisplayInfo:
    """
    Enrich display info with panel database data and enhanced detection.

    Args:
        display: Basic DisplayInfo from enumeration

    Returns:
        Enriched DisplayInfo with panel type, capabilities, etc.
    """
    from calibrate_pro.panels.database import PanelDatabase

    # Get EDID data
    edid_data = get_edid_from_registry(display.device_id)
    edid_info = parse_edid(edid_data) if edid_data else {}

    # Update with EDID data
    if edid_info.get("monitor_name"):
        if "Generic" in display.monitor_name:
            display.monitor_name = edid_info["monitor_name"]
    if edid_info.get("manufacturer"):
        display.manufacturer = edid_info["manufacturer"]
    if edid_info.get("gamma", 0) > 0:
        display.native_gamma = edid_info["gamma"]
    if edid_info.get("year", 0) > 0:
        display.year = edid_info["year"]

    # Calculate panel size
    h_cm = edid_info.get("horizontal_cm", 0)
    v_cm = edid_info.get("vertical_cm", 0)
    display.panel_size_inches = calculate_panel_size(h_cm, v_cm)

    # Detect panel type
    display.panel_type = detect_panel_type(display.monitor_name, display.manufacturer, edid_info)

    # Detect connection type
    display.connection_type = detect_connection_type(display.device_id)

    # Try to match with panel database
    db = PanelDatabase()
    panel = None
    matched_key = None

    # Method 1: Try monitor name match
    if display.monitor_name:
        panel = db.find_panel(display.monitor_name)
        if panel:
            # Find the actual key for this panel
            for key, p in db.panels.items():
                if p is panel:
                    matched_key = key
                    break

    # Method 2: Try fingerprint
    if not panel:
        matched_key = identify_display(display)
        if matched_key:
            panel = db.get_panel(matched_key)

    # If matched, enrich with database data
    if panel:
        display.panel_database_key = matched_key or panel.model_pattern.split("|")[0]
        display.panel_type = panel.panel_type
        display.hdr_capable = panel.capabilities.hdr_capable
        display.wide_gamut = panel.capabilities.wide_gamut
        display.max_luminance = panel.capabilities.max_luminance_hdr
        display.native_gamma = panel.gamma_red.gamma  # Use red channel as reference

    # Infer capabilities from resolution/refresh if not matched
    if not panel:
        # High refresh + 4K likely modern gaming monitor with HDR
        if display.refresh_rate >= 120 and display.width >= 3840:
            display.hdr_capable = True
            display.wide_gamut = True
        # 10-bit color depth suggests wide gamut
        if display.bit_depth >= 10:
            display.wide_gamut = True

    return display


def enumerate_displays_enhanced() -> list[DisplayInfo]:
    """
    Enumerate all displays with enhanced detection and panel matching.

    Returns:
        List of enriched DisplayInfo objects
    """
    displays = enumerate_displays()
    return [enrich_display_info(display) for display in displays]


def identify_display(display: DisplayInfo) -> str | None:
    """
    Attempt to identify display using multiple methods.

    Order of identification:
    1. Monitor name from Windows (if not "Generic PnP Monitor")
    2. EDID monitor name from registry
    3. Display fingerprint matching

    Args:
        display: DisplayInfo object

    Returns:
        Panel database key (e.g., "PG27UCDM") or None
    """
    from calibrate_pro.panels.database import PanelDatabase

    db = PanelDatabase()

    # Method 1: Try Windows monitor name
    if display.monitor_name and "Generic" not in display.monitor_name:
        panel = db.find_panel(display.monitor_name)
        if panel:
            return panel.model_pattern.split("|")[0]

    # Method 2: Try EDID from registry
    edid_data = get_edid_from_registry(display.device_id)
    if edid_data:
        edid_info = parse_edid(edid_data)

        if edid_info["monitor_name"]:
            panel = db.find_panel(edid_info["monitor_name"])
            if panel:
                return panel.model_pattern.split("|")[0]

        # Try manufacturer + product code
        search_string = f"{edid_info['manufacturer']} {edid_info['product_code']:04X}"
        panel = db.find_panel(search_string)
        if panel:
            return panel.model_pattern.split("|")[0]

    # Method 3: Try fingerprint matching
    fingerprint = get_display_fingerprint(display)
    if fingerprint in DISPLAY_FINGERPRINTS:
        return DISPLAY_FINGERPRINTS[fingerprint]

    # Try partial fingerprint (without manufacturer)
    base_fingerprint = f"{display.width}x{display.height}@{display.refresh_rate}"
    if base_fingerprint in DISPLAY_FINGERPRINTS:
        return DISPLAY_FINGERPRINTS[base_fingerprint]

    return None


def get_enhanced_display_info(display_number: int | None = None) -> list[dict]:
    """
    Get enhanced display information including EDID data.

    Args:
        display_number: Optional display number (1-based), or None for all

    Returns:
        List of dictionaries with enhanced display info
    """
    displays = enumerate_displays()
    results = []

    for display in displays:
        if display_number is not None and display.get_display_number() != display_number:
            continue

        info = display.to_dict()

        # Add EDID data
        edid_data = get_edid_from_registry(display.device_id)
        if edid_data:
            edid_info = parse_edid(edid_data)
            info["edid"] = edid_info

            # Override with EDID data if better
            if edid_info["monitor_name"] and "Generic" in display.monitor_name:
                info["monitor_name"] = edid_info["monitor_name"]
            if edid_info["manufacturer"]:
                info["manufacturer"] = edid_info["manufacturer"]

        # Add identification
        info["identified_panel"] = identify_display(display)
        info["fingerprint"] = get_display_fingerprint(display)

        results.append(info)

    return results


def get_primary_display() -> DisplayInfo | None:
    """Get the primary display."""
    displays = enumerate_displays()
    for display in displays:
        if display.is_primary:
            return display
    return displays[0] if displays else None


def get_display_by_name(device_name: str) -> DisplayInfo | None:
    """Get display by device name."""
    displays = enumerate_displays()
    for display in displays:
        if display.device_name == device_name:
            return display
    return None


def get_display_by_number(number: int) -> DisplayInfo | None:
    """Get display by number (1-based)."""
    displays = enumerate_displays()
    for display in displays:
        if display.get_display_number() == number:
            return display
    return None


# =============================================================================
# ICC Profile Management
# =============================================================================

# GDI32.dll for ICC profile operations
try:
    gdi32 = ctypes.windll.gdi32
    mscms = ctypes.windll.mscms

    gdi32.CreateDCW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
    ]
    gdi32.CreateDCW.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.GetICMProfileW.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
    ]
    gdi32.GetICMProfileW.restype = wintypes.BOOL
    gdi32.SetICMProfileW.argtypes = [wintypes.HDC, wintypes.LPWSTR]
    gdi32.SetICMProfileW.restype = wintypes.BOOL
    gdi32.GetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
    gdi32.GetDeviceGammaRamp.restype = wintypes.BOOL
    gdi32.SetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]
    gdi32.SetDeviceGammaRamp.restype = wintypes.BOOL

    # Define profile functions
    WCS_PROFILE_MANAGEMENT_SCOPE_CURRENT_USER = 0
    COLORPROFILESUBTYPE_NONE = 0
    COLORPROFILETYPE_ICC = 1

    class WCS_PROFILE(ctypes.Structure):
        _fields_ = [
            ("dwType", wintypes.DWORD),
            ("pProfileData", ctypes.c_void_p),
            ("cbDataSize", wintypes.DWORD),
        ]

    HAS_MSCMS = True
except Exception:
    HAS_MSCMS = False


class _NativeState(Enum):
    PENDING = "pending"
    ENTERED = "entered"
    OPEN = "open"
    CLOSED = "closed"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class _OwnerClaim(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    RETAINED = "retained"
    CLAIMED = "claimed"


class _NativeAction(Enum):
    ACQUIRE = "acquire"
    DELETE = "delete"


_DISPLAY_DC_REGISTRY_LOCK = threading.RLock()
_DISPLAY_DC_REGISTRY_CHANGED = threading.Condition(_DISPLAY_DC_REGISTRY_LOCK)


@dataclass(frozen=True)
class _NativeAttempt:
    """One immutable native action isolated from caller-thread cancellation.

    Tracing is not suppressed. Same-process code that injects inside this worker,
    including through ``sys.monitoring``, is trusted and outside this boundary:
    interruption between a native return and Python publication has no honest way
    to reconstruct the native result.
    """

    token: object
    action: _NativeAction
    done: threading.Event
    started: threading.Event
    worker: threading.Thread


@dataclass(init=False)
class _RetainedDisplayDc:
    api: Any
    device_name: str
    dc: object | None
    state: _NativeState
    claim: _OwnerClaim
    action: _NativeAction
    attempt: _NativeAttempt | None
    claimant: object | None
    terminal_cleanup_token: object | None
    detail: str
    error: BaseException | None

    def __init__(
        self,
        api: Any,
        device_name: str,
        dc: object | None = None,
        outcome: str = "pre-entry",
        detail: str = "",
        error: BaseException | None = None,
        worker: threading.Thread | None = None,
        done: threading.Event | None = None,
        active: bool = False,
    ) -> None:
        del worker, done
        legacy_states = {
            "pre-entry": _NativeState.PENDING,
            "pending": _NativeState.PENDING,
            "entered": _NativeState.ENTERED,
            "open": _NativeState.OPEN,
            "closed": _NativeState.CLOSED,
            "failed": _NativeState.FAILED,
            "uncertain": _NativeState.UNCERTAIN,
        }
        self.api = api
        self.device_name = device_name
        self.dc = dc
        self.state = legacy_states[outcome]
        self.claim = (
            _OwnerClaim.ACTIVE
            if active
            else _OwnerClaim.PENDING
            if self.state in {_NativeState.PENDING, _NativeState.ENTERED}
            else _OwnerClaim.RETAINED
        )
        self.action = _NativeAction.ACQUIRE
        self.attempt = None
        self.claimant = None
        self.terminal_cleanup_token = None
        self.detail = detail
        self.error = error

    @property
    def outcome(self) -> str:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            return "pre-entry" if self.state is _NativeState.PENDING else self.state.value

    @outcome.setter
    def outcome(self, value: str) -> None:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            self.state = _NativeState.PENDING if value == "pre-entry" else _NativeState(value)
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()

    @property
    def active(self) -> bool:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            return self.claim is _OwnerClaim.ACTIVE

    @active.setter
    def active(self, value: bool) -> None:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            self.claim = _OwnerClaim.ACTIVE if value else _OwnerClaim.RETAINED
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()

    @property
    def worker(self) -> threading.Thread | None:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            return self.attempt.worker if self.attempt is not None else None

    @property
    def done(self) -> threading.Event | None:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            return self.attempt.done if self.attempt is not None else None


_RETAINED_DISPLAY_DCS: list[_RetainedDisplayDc] = []
_DELETE_DC_MAX_ATTEMPTS = 2
_DISPLAY_DC_DRAIN_CAP = 64
_DISPLAY_DC_REGISTRY_CAP = 64
_NATIVE_WORKER_JOIN_SECONDS = 2.0


def _display_owner_is_registered_locked(owner: _RetainedDisplayDc) -> bool:
    return any(record is owner for record in _RETAINED_DISPLAY_DCS)


def _retire_display_dc_owner_locked(owner: _RetainedDisplayDc) -> None:
    _RETAINED_DISPLAY_DCS[:] = [record for record in _RETAINED_DISPLAY_DCS if record is not owner]
    owner.claimant = None
    owner.terminal_cleanup_token = None
    _DISPLAY_DC_REGISTRY_CHANGED.notify_all()


def _remove_display_dc_owner(owner: _RetainedDisplayDc) -> None:
    with _DISPLAY_DC_REGISTRY_CHANGED:
        _retire_display_dc_owner_locked(owner)


def _retire_closed_display_dc_owners_locked() -> None:
    for owner in tuple(_RETAINED_DISPLAY_DCS):
        if owner.state is _NativeState.CLOSED:
            _retire_display_dc_owner_locked(owner)


def _reserve_display_dc_owner(owner: _RetainedDisplayDc) -> _NativeAttempt:
    try:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            _retire_closed_display_dc_owners_locked()
            if _display_owner_is_registered_locked(owner):
                attempt = owner.attempt
                if attempt is None:
                    attempt = _new_display_dc_attempt_locked(owner, _NativeAction.ACQUIRE)
                return attempt
            if len(_RETAINED_DISPLAY_DCS) >= _DISPLAY_DC_REGISTRY_CAP:
                raise RuntimeError("display DC owner registry capacity is exhausted")
            owner.state = _NativeState.PENDING
            owner.claim = _OwnerClaim.PENDING
            owner.action = _NativeAction.ACQUIRE
            owner.attempt = None
            owner.claimant = None
            owner.error = None
            attempt = _new_display_dc_attempt_locked(owner, _NativeAction.ACQUIRE)
            _RETAINED_DISPLAY_DCS.append(owner)
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
            return attempt
    except BaseException:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            if _display_owner_is_registered_locked(owner):
                owner.claim = _OwnerClaim.RETAINED
                owner.claimant = None
                _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
        raise


def _attempt_matches_locked(
    owner: _RetainedDisplayDc,
    token: object,
    action: _NativeAction,
) -> bool:
    return owner.attempt is not None and owner.attempt.token is token and owner.action is action


def _acquire_display_dc_worker(
    owner: _RetainedDisplayDc,
    token: object,
    done: threading.Event,
) -> None:
    with _DISPLAY_DC_REGISTRY_CHANGED:
        if not _attempt_matches_locked(owner, token, _NativeAction.ACQUIRE):
            done.set()
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
            return
        owner.state = _NativeState.ENTERED
        _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
    try:
        dc = owner.api.CreateDCW("DISPLAY", owner.device_name, None, None)
    except BaseException as error:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            if _attempt_matches_locked(owner, token, _NativeAction.ACQUIRE):
                owner.error = error
                owner.state = _NativeState.FAILED
    else:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            if _attempt_matches_locked(owner, token, _NativeAction.ACQUIRE):
                owner.dc = dc
                owner.error = None if dc else RuntimeError("GDI could not create a display device context")
                owner.state = _NativeState.OPEN if dc else _NativeState.FAILED
    finally:
        terminal_attempt: _NativeAttempt | None = None
        with _DISPLAY_DC_REGISTRY_CHANGED:
            done.set()
            if owner.attempt is not None and owner.attempt.token is token and owner.terminal_cleanup_token is token:
                terminal_attempt = owner.attempt
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
        if terminal_attempt is not None:
            _launch_display_terminal_cleanup(owner, terminal_attempt)


def _delete_display_dc_worker(
    owner: _RetainedDisplayDc,
    token: object,
    done: threading.Event,
) -> None:
    with _DISPLAY_DC_REGISTRY_CHANGED:
        if not _attempt_matches_locked(owner, token, _NativeAction.DELETE):
            done.set()
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
            return
        owner.state = _NativeState.ENTERED
        _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
    try:
        deleted = bool(owner.api.DeleteDC(owner.dc))
    except BaseException as error:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            if _attempt_matches_locked(owner, token, _NativeAction.DELETE):
                owner.error = error
                owner.state = _NativeState.UNCERTAIN
    else:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            if _attempt_matches_locked(owner, token, _NativeAction.DELETE):
                owner.error = None
                owner.state = _NativeState.CLOSED if deleted else _NativeState.OPEN
    finally:
        terminal_attempt: _NativeAttempt | None = None
        with _DISPLAY_DC_REGISTRY_CHANGED:
            done.set()
            if owner.attempt is not None and owner.attempt.token is token and owner.terminal_cleanup_token is token:
                terminal_attempt = owner.attempt
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
        if terminal_attempt is not None:
            _launch_display_terminal_cleanup(owner, terminal_attempt)


def _new_display_dc_attempt_locked(
    owner: _RetainedDisplayDc,
    action: _NativeAction,
) -> _NativeAttempt:
    current = owner.attempt
    if owner.state in {_NativeState.PENDING, _NativeState.ENTERED} and current is not None:
        if current.action is action:
            return current
        raise RuntimeError("display DC native action cannot replace an in-flight attempt")
    if owner.state is _NativeState.ENTERED and current is None:
        raise RuntimeError("display DC native state has no immutable attempt")
    token = object()
    done = threading.Event()
    started = threading.Event()
    target = _acquire_display_dc_worker if action is _NativeAction.ACQUIRE else _delete_display_dc_worker
    worker = threading.Thread(target=target, args=(owner, token, done), daemon=True)
    attempt = _NativeAttempt(token=token, action=action, done=done, started=started, worker=worker)
    owner.action = action
    owner.attempt = attempt
    owner.state = _NativeState.PENDING
    owner.error = None
    _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
    return attempt


def _start_display_dc_attempt(owner: _RetainedDisplayDc, attempt: _NativeAttempt) -> None:
    try:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            if owner.attempt is not attempt:
                raise RuntimeError("display DC native attempt ownership changed before start")
            if attempt.started.is_set() or attempt.done.is_set() or attempt.worker.ident is not None:
                return
            attempt.worker.start()
            attempt.started.set()
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
    except BaseException as start_error:
        try:
            _await_display_dc_attempt(owner, attempt)
        except BaseException as reconciliation_error:
            add_note = getattr(start_error, "add_note", None)
            if callable(add_note):
                add_note(f"display DC native start reconciliation also failed: {reconciliation_error}")
        raise


def _await_display_dc_attempt(owner: _RetainedDisplayDc, attempt: _NativeAttempt) -> bool:
    with _DISPLAY_DC_REGISTRY_CHANGED:
        started = attempt.started.is_set() or attempt.done.is_set() or attempt.worker.ident is not None
    if not started:
        return False
    attempt.worker.join(timeout=_NATIVE_WORKER_JOIN_SECONDS)
    if attempt.worker.is_alive():
        raise RuntimeError("display DC native worker did not terminate within the bounded wait")
    if not attempt.done.is_set():
        raise RuntimeError("display DC native worker exited without publishing a terminal state")
    return True


def _reconcile_display_dc_attempt(owner: _RetainedDisplayDc, attempt: _NativeAttempt) -> None:
    if not _await_display_dc_attempt(owner, attempt):
        _start_display_dc_attempt(owner, attempt)
    if not _await_display_dc_attempt(owner, attempt):
        raise RuntimeError("display DC native attempt remained unstarted during reconciliation")


def _await_display_dc_worker(owner: _RetainedDisplayDc) -> None:
    with _DISPLAY_DC_REGISTRY_CHANGED:
        attempt = owner.attempt
    if attempt is not None:
        _reconcile_display_dc_attempt(owner, attempt)


def _acquire_display_dc(
    device_name: str,
    *,
    owner: _RetainedDisplayDc | None = None,
) -> _RetainedDisplayDc:
    if owner is None:
        owner = _RetainedDisplayDc(api=gdi32, device_name=device_name)
    attempt: _NativeAttempt | None = None
    start_requested = False
    try:
        attempt = _reserve_display_dc_owner(owner)
        start_requested = True
        _start_display_dc_attempt(owner, attempt)
        _await_display_dc_attempt(owner, attempt)
    except BaseException as primary_error:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            published_attempt = attempt if attempt is not None else owner.attempt
        if start_requested and published_attempt is not None:
            try:
                _reconcile_display_dc_attempt(owner, published_attempt)
            except BaseException as reconciliation_error:
                add_note = getattr(primary_error, "add_note", None)
                if callable(add_note):
                    add_note(f"display DC acquisition reconciliation also failed: {reconciliation_error}")
        with _DISPLAY_DC_REGISTRY_CHANGED:
            if owner.state is _NativeState.OPEN:
                owner.claim = _OwnerClaim.RETAINED
            elif owner.state is _NativeState.FAILED:
                _retire_display_dc_owner_locked(owner)
            else:
                owner.claim = _OwnerClaim.RETAINED
        raise

    with _DISPLAY_DC_REGISTRY_CHANGED:
        if owner.state is _NativeState.OPEN and owner.dc:
            return owner
        error = owner.error or RuntimeError("GDI could not create a display device context")
        if owner.state is _NativeState.FAILED:
            _retire_display_dc_owner_locked(owner)
    raise error


class _DisplayDcClaimGuard:
    def __init__(
        self,
        owner: _RetainedDisplayDc,
        token: object,
        *,
        cleanup_handoff: bool = False,
    ) -> None:
        self.owner = owner
        self.token = token
        self._cleanup_handoff = cleanup_handoff
        self._acquired = False
        self._evaluated = False
        self._rollback_claim = _OwnerClaim.RETAINED

    def __enter__(self) -> _DisplayDcClaimGuard:
        return self

    @property
    def acquired(self) -> bool:
        if not self._evaluated:
            try:
                self._acquire()
            except BaseException:
                self._rollback()
                raise
            self._evaluated = True
        return self._acquired

    def _acquire(self) -> None:
        try:
            with _DISPLAY_DC_REGISTRY_CHANGED:
                while True:
                    owner = self.owner
                    if owner.state is _NativeState.CLOSED:
                        _retire_display_dc_owner_locked(owner)
                        return
                    if not _display_owner_is_registered_locked(owner):
                        if owner.dc is None:
                            return
                        if len(_RETAINED_DISPLAY_DCS) >= _DISPLAY_DC_REGISTRY_CAP:
                            raise RuntimeError("display DC owner registry capacity is exhausted")
                        _RETAINED_DISPLAY_DCS.append(owner)
                    if owner.claim is not _OwnerClaim.CLAIMED:
                        self._rollback_claim = owner.claim
                        publication_complete = False
                        try:
                            owner.claimant = self.token
                            owner.claim = _OwnerClaim.CLAIMED
                            self._acquired = True
                            publication_complete = True
                        finally:
                            if not publication_complete and owner.claimant is self.token:
                                self._rollback_locked(owner)
                        _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
                        return
                    if owner.claimant is self.token:
                        self._acquired = True
                        return
                    notified = _DISPLAY_DC_REGISTRY_CHANGED.wait(timeout=_NATIVE_WORKER_JOIN_SECONDS)
                    if not notified and owner.claim is _OwnerClaim.CLAIMED:
                        raise RuntimeError("display DC owner cleanup claim did not resolve within the bounded wait")
        except BaseException:
            self._rollback()
            raise

    def __exit__(self, *_args: object) -> None:
        self._rollback()

    def _rollback(self) -> None:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            self._rollback_locked(self.owner)

    def _rollback_locked(self, owner: _RetainedDisplayDc) -> None:
        if owner.claimant is not self.token:
            return
        if self._cleanup_handoff and _display_owner_is_registered_locked(owner):
            if owner.state is _NativeState.CLOSED or (owner.state is _NativeState.FAILED and owner.dc is None):
                _retire_display_dc_owner_locked(owner)
                return
            attempt = owner.attempt
            if (
                owner.terminal_cleanup_token is None
                and owner.state in {_NativeState.PENDING, _NativeState.ENTERED}
                and attempt is not None
                and (attempt.started.is_set() or attempt.done.is_set() or attempt.worker.ident is not None)
            ):
                _arm_display_terminal_cleanup_locked(owner, attempt)
                return
            owner.claim = _OwnerClaim.RETAINED
        else:
            owner.claim = self._rollback_claim
        owner.claimant = None
        _DISPLAY_DC_REGISTRY_CHANGED.notify_all()


def _claim_display_dc_owner(
    owner: _RetainedDisplayDc,
    claim_token: object,
    *,
    cleanup_handoff: bool = False,
) -> _DisplayDcClaimGuard:
    return _DisplayDcClaimGuard(owner, claim_token, cleanup_handoff=cleanup_handoff)


def _invoke_delete_dc(owner: _RetainedDisplayDc) -> bool:
    while True:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            if owner.state is _NativeState.CLOSED:
                return True
            if owner.state is _NativeState.UNCERTAIN:
                raise owner.error or RuntimeError("display DC native outcome is uncertain")
            if owner.state in {_NativeState.PENDING, _NativeState.ENTERED}:
                attempt = owner.attempt
                if attempt is None:
                    raise RuntimeError("display DC native attempt was not published")
            else:
                attempt = _new_display_dc_attempt_locked(owner, _NativeAction.DELETE)
        _reconcile_display_dc_attempt(owner, attempt)
        if attempt.action is _NativeAction.DELETE:
            break
    with _DISPLAY_DC_REGISTRY_CHANGED:
        if owner.error is not None:
            raise owner.error
        return owner.state is _NativeState.CLOSED


def _close_display_dc(
    owner: _RetainedDisplayDc,
    *,
    claim_token: object | None = None,
) -> BaseException | None:
    def close_once(token: object) -> tuple[BaseException | None, bool]:
        try:
            with _claim_display_dc_owner(owner, token, cleanup_handoff=True) as claim:
                if not claim.acquired:
                    return None, False
                return _close_claimed_display_dc(owner), False
        except BaseException as claim_error:
            return claim_error, True

    token = claim_token if claim_token is not None else object()
    cleanup_error, escaped_cleanup = close_once(token)
    if cleanup_error is None:
        return None

    with _DISPLAY_DC_REGISTRY_CHANGED:
        state = owner.state
        recoverable_owner = (
            _display_owner_is_registered_locked(owner)
            and owner.terminal_cleanup_token is None
            and (
                (state is _NativeState.OPEN and owner.dc is not None)
                or (state in {_NativeState.PENDING, _NativeState.ENTERED} and owner.attempt is not None)
            )
        )
    if not recoverable_owner or (not escaped_cleanup and isinstance(cleanup_error, Exception)):
        return cleanup_error

    recovery_error, _recovery_escaped = close_once(object())
    if recovery_error is None:
        return cleanup_error
    if isinstance(cleanup_error, Exception) and not isinstance(recovery_error, Exception):
        add_note = getattr(recovery_error, "add_note", None)
        if callable(add_note):
            add_note(f"display DC cleanup also failed: {cleanup_error}")
        return recovery_error
    add_note = getattr(cleanup_error, "add_note", None)
    if callable(add_note) and recovery_error is not cleanup_error:
        detail = str(recovery_error).strip() or type(recovery_error).__name__
        add_note(f"display DC boundary recovery also failed: {detail}")
    return cleanup_error


def _close_claimed_display_dc(owner: _RetainedDisplayDc) -> BaseException | None:
    errors: list[BaseException] = []
    with _DISPLAY_DC_REGISTRY_CHANGED:
        in_flight = owner.attempt if owner.state in {_NativeState.PENDING, _NativeState.ENTERED} else None
    if in_flight is not None:
        try:
            _reconcile_display_dc_attempt(owner, in_flight)
        except BaseException as error:
            errors.append(error)

    for _attempt_number in range(_DELETE_DC_MAX_ATTEMPTS):
        with _DISPLAY_DC_REGISTRY_CHANGED:
            state = owner.state
        if state is _NativeState.CLOSED:
            break
        if state in {_NativeState.ENTERED, _NativeState.UNCERTAIN}:
            break
        if state is _NativeState.FAILED and owner.dc is None:
            break
        try:
            deleted = _invoke_delete_dc(owner)  # DeleteDC is isolated in the bound immutable attempt.
        except BaseException as error:
            errors.append(error)
            with _DISPLAY_DC_REGISTRY_CHANGED:
                state = owner.state
            if state in {_NativeState.PENDING, _NativeState.ENTERED, _NativeState.UNCERTAIN}:
                break
            continue
        if deleted:
            break

    with _DISPLAY_DC_REGISTRY_CHANGED:
        state = owner.state
        control_error = next((error for error in errors if not isinstance(error, Exception)), None)
        if state is _NativeState.CLOSED:
            _retire_display_dc_owner_locked(owner)
            return control_error
        if state is _NativeState.FAILED and owner.dc is None:
            _retire_display_dc_owner_locked(owner)
        elif state in {_NativeState.PENDING, _NativeState.ENTERED}:
            attempt = owner.attempt
            if attempt is not None and (
                attempt.started.is_set() or attempt.done.is_set() or attempt.worker.ident is not None
            ):
                _arm_display_terminal_cleanup_locked(owner, attempt)
            else:
                owner.claim = _OwnerClaim.RETAINED
                owner.claimant = None
        else:
            owner.claim = _OwnerClaim.RETAINED
            owner.claimant = None
        _DISPLAY_DC_REGISTRY_CHANGED.notify_all()

    if state is _NativeState.OPEN:
        cleanup_error: BaseException = RuntimeError(
            f"GDI display device context remains open after {_DELETE_DC_MAX_ATTEMPTS} DeleteDC attempts"
        )
    else:
        cleanup_error = errors[-1] if errors else RuntimeError("GDI display device context release is uncertain")
    if control_error is not None:
        add_note = getattr(control_error, "add_note", None)
        if callable(add_note):
            add_note(str(cleanup_error))
        cleanup_error = control_error
    with _DISPLAY_DC_REGISTRY_CHANGED:
        owner.detail = str(cleanup_error).strip() or type(cleanup_error).__name__
    return cleanup_error


def _arm_display_terminal_cleanup_locked(
    owner: _RetainedDisplayDc,
    attempt: _NativeAttempt,
) -> None:
    if owner.attempt is not attempt:
        raise RuntimeError("display DC terminal cleanup cannot arm a replaced attempt")
    owner.terminal_cleanup_token = attempt.token
    owner.claim = _OwnerClaim.RETAINED
    owner.claimant = None
    _DISPLAY_DC_REGISTRY_CHANGED.notify_all()


def _launch_display_terminal_cleanup(
    owner: _RetainedDisplayDc,
    attempt: _NativeAttempt,
) -> None:
    callback = threading.Thread(
        target=_run_display_terminal_cleanup,
        args=(owner, attempt),
        daemon=True,
    )
    try:
        callback.start()
    except BaseException as callback_error:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            owner.detail = f"display DC terminal cleanup callback failed to start: {callback_error}"
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()


def _run_display_terminal_cleanup(
    owner: _RetainedDisplayDc,
    attempt: _NativeAttempt,
) -> None:
    attempt.worker.join()
    with _DISPLAY_DC_REGISTRY_CHANGED:
        if owner.terminal_cleanup_token is not attempt.token:
            return
        owner.terminal_cleanup_token = None
        if owner.state is _NativeState.CLOSED or (owner.state is _NativeState.FAILED and owner.dc is None):
            _retire_display_dc_owner_locked(owner)
            return
        if owner.state is not _NativeState.OPEN:
            owner.detail = "display DC terminal cleanup published a non-cleanable native state"
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
            return
        owner.claim = _OwnerClaim.RETAINED
        owner.claimant = None
        _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
    cleanup_error = _close_display_dc(owner)
    if cleanup_error is not None:
        with _DISPLAY_DC_REGISTRY_CHANGED:
            owner.detail = str(cleanup_error).strip() or type(cleanup_error).__name__
            _DISPLAY_DC_REGISTRY_CHANGED.notify_all()


def _drain_retained_display_dcs() -> None:
    errors: list[str] = []
    control_errors: list[BaseException] = []
    cleanup_candidates: list[_RetainedDisplayDc] = []
    pending_attempts: list[tuple[_RetainedDisplayDc, _NativeAttempt]] = []
    retained_count = 0
    with _DISPLAY_DC_REGISTRY_CHANGED:
        _retire_closed_display_dc_owners_locked()
        for owner in tuple(_RETAINED_DISPLAY_DCS):
            if owner.claim is not _OwnerClaim.RETAINED:
                continue
            retained_count += 1
            if owner.state is _NativeState.FAILED and owner.dc is None:
                _retire_display_dc_owner_locked(owner)
                continue
            if len(cleanup_candidates) + len(pending_attempts) >= _DISPLAY_DC_DRAIN_CAP:
                continue
            if owner.state in {_NativeState.PENDING, _NativeState.ENTERED}:
                attempt = owner.attempt
                if attempt is None:
                    errors.append("display DC transitional owner has no immutable attempt")
                    continue
                if (
                    owner.state is _NativeState.PENDING
                    and owner.dc is None
                    and attempt.worker.ident is None
                    and not attempt.started.is_set()
                    and not attempt.done.is_set()
                ):
                    _retire_display_dc_owner_locked(owner)
                    continue
                _arm_display_terminal_cleanup_locked(owner, attempt)
                pending_attempts.append((owner, attempt))
            elif owner.state is _NativeState.OPEN:
                cleanup_candidates.append(owner)
            elif owner.state is _NativeState.UNCERTAIN:
                errors.append(owner.detail or "display DC native outcome is uncertain")
        _DISPLAY_DC_REGISTRY_CHANGED.notify_all()

    incomplete = False
    for owner, attempt in pending_attempts:
        try:
            _reconcile_display_dc_attempt(owner, attempt)
        except BaseException as pending_error:
            incomplete = True
            detail = f"display DC cleanup incomplete while exact native worker is running: {pending_error}"
            if isinstance(pending_error, Exception):
                errors.append(detail)
            else:
                control_errors.append(pending_error)
            with _DISPLAY_DC_REGISTRY_CHANGED:
                owner.detail = detail
                _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
            continue
        cleanup_candidates.append(owner)

    for owner in cleanup_candidates:
        cleanup_error = _close_display_dc(owner)
        if cleanup_error is None:
            continue
        if not isinstance(cleanup_error, Exception):
            control_errors.append(cleanup_error)
        else:
            errors.append(owner.detail or str(cleanup_error))

    with _DISPLAY_DC_REGISTRY_CHANGED:
        _retire_closed_display_dc_owners_locked()
        remaining = [
            owner
            for owner in _RETAINED_DISPLAY_DCS
            if owner.claim in {_OwnerClaim.RETAINED, _OwnerClaim.CLAIMED}
            and owner.state
            in {
                _NativeState.PENDING,
                _NativeState.ENTERED,
                _NativeState.OPEN,
                _NativeState.UNCERTAIN,
            }
        ]
    if retained_count > _DISPLAY_DC_DRAIN_CAP:
        errors.append("display DC retained-owner drain cap exceeded")
    if control_errors:
        control_error = control_errors[0]
        details = "; ".join(errors)
        add_note = getattr(control_error, "add_note", None)
        if details and callable(add_note):
            add_note(f"display DC retained-owner drain also reported: {details}")
        raise control_error
    if incomplete or remaining:
        details = "; ".join(errors) or "retained display DC ownership remains unresolved"
        raise RuntimeError(details)


@contextmanager
def _display_dc(device_name: str) -> Iterator[object]:
    """Own one synchronized GDI display DC and fail closed on uncertain release."""
    owner = _RetainedDisplayDc(api=gdi32, device_name=device_name)
    primary_error: BaseException | None = None
    cleanup_error: BaseException | None = None
    registered = False
    try:
        _drain_retained_display_dcs()
        try:
            try:
                owner = _acquire_display_dc(device_name, owner=owner)
                registered = True
                with _DISPLAY_DC_REGISTRY_CHANGED:
                    if owner.state is not _NativeState.OPEN:
                        raise RuntimeError("display DC acquisition did not publish an open owner")
                    owner.claim = _OwnerClaim.ACTIVE
                    _DISPLAY_DC_REGISTRY_CHANGED.notify_all()
                dc = owner.dc
                yield dc
            except BaseException as exc:
                primary_error = exc
        finally:
            with _DISPLAY_DC_REGISTRY_CHANGED:
                registered = registered or _display_owner_is_registered_locked(owner)
            if registered:
                cleanup_error = _close_display_dc(owner)
    except BaseException as boundary_error:
        if primary_error is None:
            primary_error = boundary_error
        else:
            cleanup_error = boundary_error
        with _DISPLAY_DC_REGISTRY_CHANGED:
            registered = registered or _display_owner_is_registered_locked(owner)
        retry_error = _close_display_dc(owner) if registered else None
        if retry_error is not None:
            if cleanup_error is None:
                cleanup_error = retry_error
            else:
                detail = str(retry_error).strip() or type(retry_error).__name__
                add_note = getattr(cleanup_error, "add_note", None)
                if callable(add_note):
                    add_note(f"display DC boundary cleanup also failed: {detail}")

    if primary_error is not None:
        if cleanup_error is not None:
            detail = str(cleanup_error).strip() or type(cleanup_error).__name__
            if isinstance(primary_error, Exception) and not isinstance(cleanup_error, Exception):
                add_note = getattr(cleanup_error, "add_note", None)
                if callable(add_note):
                    add_note(f"display operation also failed: {primary_error or type(primary_error).__name__}")
                raise cleanup_error from primary_error
            add_note = getattr(primary_error, "add_note", None)
            if callable(add_note):
                add_note(f"display DC cleanup also failed: {detail}")
        raise primary_error
    if cleanup_error is not None:
        raise cleanup_error


def get_display_profile(device_name: str) -> str | None:
    """
    Get the current ICC profile for a display.

    Args:
        device_name: Windows device name

    Returns:
        Path to current ICC profile or None
    """
    if not HAS_MSCMS:
        return None

    try:
        with _display_dc(device_name) as dc:
            # Get profile filename
            buffer_size = wintypes.DWORD(260)
            buffer = ctypes.create_unicode_buffer(260)

            result = gdi32.GetICMProfileW(dc, ctypes.byref(buffer_size), buffer)

            if result:
                return buffer.value

    except Exception:
        pass

    return None


def set_display_profile(device_name: str, profile_path: str) -> bool:
    """
    Set the ICC profile for a display.

    Args:
        device_name: Windows device name
        profile_path: Path to ICC profile

    Returns:
        True if successful
    """
    if not HAS_MSCMS:
        return False

    try:
        with _display_dc(device_name) as dc:
            # Set the profile
            result = gdi32.SetICMProfileW(dc, profile_path)
            return bool(result)

    except Exception:
        return False


def install_profile(profile_path: str, set_as_default: bool = True) -> bool:
    """
    Install an ICC profile to the system.

    Args:
        profile_path: Path to ICC profile
        set_as_default: Set as default for associated displays

    Returns:
        True if successful
    """
    if not HAS_MSCMS:
        return False

    try:
        from calibrate_pro.profiles import profile_installer

        source = Path(profile_path).absolute()
        if not profile_installer._is_exact_profile_basename(source.name):
            return False
        if profile_installer._is_transactional_profile_cache_name(source.name):
            return False
        destination = profile_installer.get_profile_directory() / source.name
        if profile_installer._path_resolves_to_transactional_profile_cache(destination):
            return False

        success, _message = profile_installer.install_profile(source)
        return success
    except Exception:
        return False


def get_color_directory() -> Path:
    """Get the Windows color profile directory."""
    return Path(r"C:\WINDOWS\System32\spool\drivers\color")


def list_installed_profiles() -> list[Path]:
    """List all installed ICC profiles."""
    color_dir = get_color_directory()
    if color_dir.exists():
        return list(color_dir.glob("*.icc")) + list(color_dir.glob("*.icm"))
    return []


# =============================================================================
# Gamma Ramp
# =============================================================================

if sys.platform == "win32":

    class GAMMA_RAMP(ctypes.Structure):
        """Windows gamma ramp structure (256 entries per channel)."""

        _fields_ = [
            ("Red", wintypes.WORD * 256),
            ("Green", wintypes.WORD * 256),
            ("Blue", wintypes.WORD * 256),
        ]


def get_gamma_ramp(device_name: str) -> tuple | None:
    """
    Get the current gamma ramp for a display.

    Returns:
        (red, green, blue) arrays of 256 16-bit values
    """
    try:
        with _display_dc(device_name) as dc:
            ramp = GAMMA_RAMP()
            result = gdi32.GetDeviceGammaRamp(dc, ctypes.byref(ramp))

            if result:
                import numpy as np

                red = np.array(ramp.Red[:], dtype=np.uint16)
                green = np.array(ramp.Green[:], dtype=np.uint16)
                blue = np.array(ramp.Blue[:], dtype=np.uint16)
                return (red, green, blue)

    except Exception:
        pass

    return None


def set_gamma_ramp(device_name: str, red: np.ndarray, green: np.ndarray, blue: np.ndarray) -> bool:
    """
    Set the gamma ramp for a display.

    Args:
        device_name: Windows device name
        red, green, blue: Arrays of 256 values (normalized 0-1 or 0-65535)

    Returns:
        True if successful
    """
    import numpy as np

    try:
        with _display_dc(device_name) as dc:
            # Normalize to 16-bit
            if red.max() <= 1.0:
                red = (red * 65535).astype(np.uint16)
                green = (green * 65535).astype(np.uint16)
                blue = (blue * 65535).astype(np.uint16)

            ramp = GAMMA_RAMP()

            for i in range(256):
                ramp.Red[i] = int(red[i])
                ramp.Green[i] = int(green[i])
                ramp.Blue[i] = int(blue[i])

            result = gdi32.SetDeviceGammaRamp(dc, ctypes.byref(ramp))
            return bool(result)

    except Exception:
        return False


def reset_gamma_ramp(device_name: str) -> bool:
    """Reset gamma ramp to linear (identity)."""
    import numpy as np

    linear = np.linspace(0, 65535, 256, dtype=np.uint16)
    return set_gamma_ramp(device_name, linear, linear, linear)


# =============================================================================
# Convenience Functions
# =============================================================================


def get_display_name(display: DisplayInfo) -> str:
    """
    Get a human-readable display name, resolving 'Generic PnP Monitor'
    to the actual panel name from the database when possible.

    Args:
        display: DisplayInfo object

    Returns:
        Readable name like "ASUS PG27UCDM" or "Samsung Odyssey G7"
    """
    # If Windows already gave us a real name, use it
    if display.monitor_name and "Generic" not in display.monitor_name:
        return display.monitor_name

    # Try panel database match
    panel_key = identify_display(display)
    if panel_key:
        from calibrate_pro.panels.database import PanelDatabase

        db = PanelDatabase()
        panel = db.get_panel(panel_key)
        if panel and panel.manufacturer != "Generic":
            return panel.name

    # Fall back to manufacturer + model code
    if display.manufacturer and display.model:
        return f"{display.manufacturer} {display.model}"

    return display.monitor_name or "Display"


def print_display_info():
    """Print information about all connected displays with enhanced detection."""
    displays = enumerate_displays()

    print(f"\nFound {len(displays)} display(s):\n")

    for i, display in enumerate(displays, 1):
        primary = " (Primary)" if display.is_primary else ""
        name = get_display_name(display)

        print(f"Display {i}{primary}: {name}")
        print(f"  Resolution: {display.width}x{display.height} @ {display.refresh_rate}Hz")
        print(f"  Adapter: {display.device_string}")

        # Panel identification
        panel_key = identify_display(display)
        if panel_key:
            from calibrate_pro.panels.database import PanelDatabase

            db = PanelDatabase()
            panel = db.get_panel(panel_key)
            if panel:
                print(f"  Panel: {panel.name} ({panel.panel_type})")
                if panel.capabilities.wide_gamut:
                    print(f"  Gamut: Wide gamut ({panel.panel_type})")
                if panel.capabilities.hdr_capable:
                    print(f"  HDR: Supported (peak {panel.capabilities.max_luminance_hdr:.0f} cd/m2)")

        if display.current_profile:
            print(f"  ICC Profile: {display.current_profile}")
        print()


if __name__ == "__main__":
    print_display_info()
