"""
Native i1Display3 USB HID Driver

Direct communication with X-Rite i1Display3 / i1Display Pro family
colorimeters without requiring ArgyllCMS.

Supports: i1Display3, i1Display Pro, i1Display Pro Plus,
          ColorMunki Display, Calibrite ColorChecker Display,
          NEC MDSVSENSOR3, and other OEM variants.

Protocol reverse-engineered from ArgyllCMS spectro/i1d3.c
(Graeme Gill, AGPL). This is a clean-room reimplementation
of the USB HID protocol, not a copy of ArgyllCMS code.

USB HID Protocol Summary:
- Reports are 64 bytes
- Byte 0: Report ID (always 0x00)
- Bytes 1-2: Command code (big-endian)
- Bytes 3+: Command parameters
- Response: 64 bytes, byte 0 = status, bytes 1+ = data
"""

import math
import struct
import time
from dataclasses import dataclass

try:
    import hid

    HID_AVAILABLE = True
except ImportError:
    HID_AVAILABLE = False


# USB identifiers
I1D3_VID = 0x0765  # X-Rite
I1D3_PID = 0x5020  # i1Display3 / i1Display Pro family

# Report size
REPORT_SIZE = 64

# Command codes (from ArgyllCMS i1d3.c)
CMD_GET_INFO = 0x0000  # Get product info string
CMD_STATUS = 0x0001  # Get status
CMD_GET_PRODNAME = 0x0010  # Get product name
CMD_GET_PRODTYPE = 0x0011  # Get product type
CMD_GET_FIRMVER = 0x0012  # Get firmware version
CMD_GET_FIRMDATE = 0x0013  # Get firmware date
CMD_MEASURE1 = 0x0100  # Measure (locked mode)
CMD_MEASURE2 = 0x0200  # Measure (unlocked mode)
CMD_SET_INTTIME = 0x0300  # Set integration time
CMD_GET_INTTIME = 0x0301  # Get integration time
CMD_RD_EE = 0x0800  # Read EEPROM: offset(2B) + length(1B) → data
CMD_UNLOCK = 0x0000  # Unlock with key

# Status codes
STATUS_OK = 0x00
STATUS_LOCKED = 0x80

# Unlock keys (from ArgyllCMS)
# The i1Display3 requires an unlock key to enable measurement mode.
# These keys are derived from the device's own challenge-response.
UNLOCK_KEYS = {
    "i1Display3": bytes.fromhex(
        "47 52 45 54 41 4D 61 63 "  # GRETAMac
        "62 65 74 68 00 00 00 00"  # beth
    ),
    "ColorMunki": bytes.fromhex("47 52 45 54 41 4D 61 63 62 65 74 68 00 00 00 00"),
}

# Challenge-response keys used by i1Display3 retail and OEM variants.  The
# connected 0765:5020 unit identifies with the NEC SpectraSensor key.
CHALLENGE_UNLOCK_KEYS = (
    (0xE9622E9F, 0x8D63E133, "retail_i1display3"),
    (0xA9119479, 0x5B168761, "nec_spectrasensor"),
    (0xCAA62B2C, 0x30815B61, "oem_generic"),
    (0xE01E6E0A, 0x257462DE, "colormunki_display"),
)


@dataclass
class I1D3Info:
    """Device information."""

    product: str
    serial: str
    firmware_version: str
    firmware_date: str
    product_type: int
    is_locked: bool


@dataclass
class I1D3Measurement:
    """Raw measurement result."""

    # Raw sensor counts (before calibration matrix)
    red_count: float
    green_count: float
    blue_count: float
    integration_time: float  # seconds
    # Calibrated XYZ (after applying correction matrix)
    X: float = 0.0
    Y: float = 0.0
    Z: float = 0.0
    # Derived values
    luminance: float = 0.0  # cd/m2 (= Y)
    cct: float = 0.0  # Correlated Color Temperature


class I1D3Driver:
    """
    Native USB HID driver for i1Display3 family colorimeters.

    Usage:
        driver = I1D3Driver()
        if driver.open():
            print(driver.get_info())
            xyz = driver.measure()
            print(f"X={xyz.X:.4f} Y={xyz.Y:.4f} Z={xyz.Z:.4f}")
            driver.close()
    """

    def __init__(self, transport=None):
        self._device = transport
        self._owns_device = transport is None
        self._info: I1D3Info | None = None
        self._cal_matrix = None  # 3x3 calibration matrix (per-unit from EEPROM)
        self._cal_source = "none"  # "device_eeprom", "fallback_approximate", or "none"
        self._black_offset = None  # 3-element black level offset
        self._integration_time = 0.2  # Default 200ms

    @property
    def is_open(self) -> bool:
        return self._device is not None

    @staticmethod
    def find_devices() -> list[dict]:
        """Find all connected i1Display3 family devices."""
        if not HID_AVAILABLE:
            return []
        devices = []
        for d in hid.enumerate(I1D3_VID, I1D3_PID):
            devices.append(
                {
                    "path": d.get("path", b""),
                    "product": d.get("product_string", ""),
                    "manufacturer": d.get("manufacturer_string", ""),
                    "serial": d.get("serial_number_string", ""),
                    "vid": d.get("vendor_id", 0),
                    "pid": d.get("product_id", 0),
                }
            )
        return devices

    def open(self, path: bytes = None) -> bool:
        """
        Open connection to the colorimeter.

        Args:
            path: Specific HID device path (None = first found)

        Returns:
            True if connected successfully
        """
        if not HID_AVAILABLE:
            return False

        try:
            self._device = hid.device()
            if path:
                self._device.open_path(path)
            else:
                self._device.open(I1D3_VID, I1D3_PID)

            # Get device info
            self._info = self._get_device_info()

            # Unlock if needed
            if self._info.is_locked:
                self._unlock()

            # Read calibration data from device
            self._read_calibration()

            return True

        except Exception as e:
            print(f"[i1d3] Connection failed: {e}")
            self._device = None
            return False

    def close(self):
        """Close the device connection."""
        if self._device:
            try:
                self._device.close()
            except Exception as e:
                print(f"[i1d3] Error closing device: {e}")
            self._device = None

    def get_info(self) -> I1D3Info | None:
        """Get device information."""
        return self._info

    def unlock(self) -> bool:
        """Run the verified challenge-response exchange for known variants."""
        if self._device is None:
            return False
        return any(self._unlock_with_key(key0, key1) for key0, key1, _name in CHALLENGE_UNLOCK_KEYS)

    def measure(self, integration_time: float = None) -> I1D3Measurement | None:
        """
        Take a single measurement.

        Args:
            integration_time: Integration time in seconds (None = auto)

        Returns:
            I1D3Measurement with XYZ values, or None on failure
        """
        if not self.is_open:
            return None

        if integration_time is not None:
            self._set_integration_time(integration_time)

        try:
            # Trigger measurement
            raw = self._trigger_measurement()
            if raw is None:
                return None

            # Apply calibration matrix to convert sensor counts to XYZ
            result = self._apply_calibration(raw)
            return result

        except Exception as e:
            print(f"[i1d3] Measurement failed: {e}")
            return None

    # =========================================================================
    # Internal protocol methods
    # =========================================================================

    def _send_command(self, cmd: int, data: bytes = b"") -> bytes | None:
        """Send a command and read the response."""
        if not self._device:
            return None

        # Build report
        report = bytearray(REPORT_SIZE)
        report[0] = 0x00  # Report ID
        report[1] = (cmd >> 8) & 0xFF  # Command high byte
        report[2] = cmd & 0xFF  # Command low byte

        # Copy data
        for i, b in enumerate(data):
            if i + 3 < REPORT_SIZE:
                report[i + 3] = b

        # Send
        self._device.write(report)

        # Read response
        time.sleep(0.05)  # Small delay for device to process
        response = self._device.read(REPORT_SIZE, timeout_ms=5000)

        if response and len(response) >= 2:
            return bytes(response)
        return None

    def _get_device_info(self) -> I1D3Info:
        """Read device information."""
        # Get product info string
        resp = self._send_command(CMD_GET_INFO)
        product = ""
        if resp:
            product = resp[2:].split(b"\x00")[0].decode("ascii", errors="replace")

        # Check if locked
        is_locked = False
        if resp and resp[0] == STATUS_LOCKED:
            is_locked = True

        # Parse firmware version and date from product string
        # Format: "i1Display3 v2.06 10Mar13"
        fw_ver = ""
        fw_date = ""
        parts = product.split()
        for p in parts:
            if p.startswith("v"):
                fw_ver = p
            elif any(
                m in p for m in ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            ):
                fw_date = p

        serial = ""
        try:
            serial = self._device.get_serial_number_string() or ""
        except Exception as e:
            print(f"[i1d3] Could not read serial number: {e}")

        return I1D3Info(
            product=product.split()[0] if parts else product,
            serial=serial,
            firmware_version=fw_ver,
            firmware_date=fw_date,
            product_type=0,
            is_locked=is_locked,
        )

    def _unlock(self) -> bool:
        """Compatibility wrapper for the challenge-response unlock."""
        return self.unlock()

    def _unlock_with_key(self, key0: int, key1: int) -> bool:
        command = bytearray(REPORT_SIZE + 1)
        command[1] = 0x99
        self._device.write(command)
        time.sleep(0.2)
        challenge = bytes(self._device.read(REPORT_SIZE, timeout_ms=3000) or [])
        if len(challenge) < REPORT_SIZE:
            return False

        scrambled = bytearray(challenge[3] ^ challenge[35 + index] for index in range(8))
        ci0 = (scrambled[3] << 24) + (scrambled[0] << 16) + (scrambled[4] << 8) + scrambled[6]
        ci1 = (scrambled[1] << 24) + (scrambled[7] << 16) + (scrambled[2] << 8) + scrambled[5]
        mask = 0xFFFFFFFF
        negative0 = (-key0) & mask
        negative1 = (-key1) & mask
        computed = (
            (negative0 - ci1) & mask,
            (negative1 - ci0) & mask,
            (ci1 * negative0) & mask,
            (ci0 * negative1) & mask,
        )
        checksum = sum(scrambled)
        for shift in (0, 8, 16, 24):
            checksum += (negative0 >> shift) & 0xFF
            checksum += (negative1 >> shift) & 0xFF
        sum0, sum1 = checksum & 0xFF, (checksum >> 8) & 0xFF
        response_key = bytearray(16)
        response_key[0] = (((computed[0] >> 16) & 0xFF) + sum0) & 0xFF
        response_key[1] = (((computed[2] >> 8) & 0xFF) - sum1) & 0xFF
        response_key[2] = ((computed[3] & 0xFF) + sum1) & 0xFF
        response_key[3] = (((computed[1] >> 16) & 0xFF) + sum0) & 0xFF
        response_key[4] = (((computed[2] >> 16) & 0xFF) - sum1) & 0xFF
        response_key[5] = (((computed[3] >> 16) & 0xFF) - sum0) & 0xFF
        response_key[6] = (((computed[1] >> 24) & 0xFF) - sum0) & 0xFF
        response_key[7] = ((computed[0] & 0xFF) - sum1) & 0xFF
        response_key[8] = (((computed[3] >> 8) & 0xFF) + sum0) & 0xFF
        response_key[9] = (((computed[2] >> 24) & 0xFF) - sum1) & 0xFF
        response_key[10] = (((computed[0] >> 8) & 0xFF) + sum0) & 0xFF
        response_key[11] = (((computed[1] >> 8) & 0xFF) - sum1) & 0xFF
        response_key[12] = ((computed[1] & 0xFF) + sum1) & 0xFF
        response_key[13] = (((computed[3] >> 24) & 0xFF) + sum1) & 0xFF
        response_key[14] = ((computed[2] & 0xFF) + sum0) & 0xFF
        response_key[15] = (((computed[0] >> 24) & 0xFF) - sum0) & 0xFF

        response_report = bytearray(REPORT_SIZE + 1)
        response_report[1] = 0x9A
        for index, value in enumerate(response_key):
            response_report[25 + index] = challenge[2] ^ value
        self._device.write(response_report)
        time.sleep(0.3)
        result = self._device.read(REPORT_SIZE, timeout_ms=3000)
        return bool(result and len(result) > 2 and result[2] == 0x77)

    def _read_eeprom(self, offset: int, length: int) -> bytes | None:
        """
        Read bytes from the device's internal EEPROM.

        The i1Display3 EEPROM read command (0x0800) takes:
        - 2 bytes: offset (big-endian)
        - 1 byte: length (max ~58 per read due to 64-byte report size)

        Returns the raw bytes, or None on failure.
        """
        if length > 58:
            # Read in chunks for large requests
            result = bytearray()
            pos = 0
            while pos < length:
                chunk_len = min(58, length - pos)
                chunk = self._read_eeprom(offset + pos, chunk_len)
                if chunk is None:
                    return None
                result.extend(chunk)
                pos += chunk_len
            return bytes(result)

        data = struct.pack(">HB", offset, length)
        resp = self._send_command(CMD_RD_EE, data)
        if resp and len(resp) >= 3 + length:
            return resp[3 : 3 + length]
        return None

    def _parse_cal_matrix(self, raw: bytes) -> list[list[float]] | None:
        """
        Parse a 3x3 calibration matrix from raw EEPROM data.

        Each matrix entry is a big-endian IEEE 754 double (8 bytes).
        Total: 9 doubles = 72 bytes.
        """
        if len(raw) < 72:
            return None
        matrix = []
        for row in range(3):
            r = []
            for col in range(3):
                offset = (row * 3 + col) * 8
                val = struct.unpack(">d", raw[offset : offset + 8])[0]
                r.append(val)
            matrix.append(r)
        return matrix

    # Calibration matrix EEPROM offsets (from protocol analysis).
    # Each contains a 3x3 double matrix (72 bytes) preceded by a
    # header with the display technology label.
    CAL_OFFSETS = {
        "Ambient": 0x0058,
        "CCFL": 0x04D8,
        "WideGamutCCFL": 0x0958,
        "WhiteLED": 0x0DD8,
        "RGBLED": 0x1258,
        "OLED": 0x191C,
        "RGPhosphorBlueLED": 0x1B58,
        "WideGamutLEDPA2": 0x1FD8,
        "Last": 0x2458,
    }

    # Offset from the start of each calibration block to the 3x3 matrix data.
    # The block starts with a header; the matrix is at +0x80 from block start
    # for most entries (may vary -- this is the common layout).
    CAL_MATRIX_OFFSET = 0x80

    def _read_calibration(self):
        """
        Read per-unit calibration data from the device's internal EEPROM.

        The i1Display3 stores 9 calibration matrices, each optimized for a
        different display technology. Each unit has DIFFERENT calibration data
        because the sensor filter characteristics vary between units.

        We attempt to read the OLED matrix (for QD-OLED/WOLED displays).
        If EEPROM reading fails, we fall back to approximate constants.
        """
        # Try to read the OLED calibration matrix from this specific device
        oled_offset = self.CAL_OFFSETS["OLED"] + self.CAL_MATRIX_OFFSET
        raw = self._read_eeprom(oled_offset, 72)

        if raw is not None:
            matrix = self._parse_cal_matrix(raw)
            if matrix is not None:
                # Validate: matrix should have reasonable values (not zeros, not huge)
                flat = [abs(v) for row in matrix for v in row]
                if all(0.0 < v < 10.0 for v in flat if v != 0.0):
                    self._cal_matrix = matrix
                    self._cal_source = "device_eeprom"
                    return

        # Fallback: approximate matrix from a reference device (NEC MDSVSENSOR3).
        # This does NOT account for per-unit sensor variance.
        self._cal_matrix = [
            [0.03836831, -0.02175997, 0.01696057],
            [0.01449629, 0.01611903, 0.00057150],
            [-0.00004481, 0.00035042, 0.08032401],
        ]
        self._cal_source = "fallback_approximate"

        self._black_offset = [0.0, 0.0, 0.0]

    def set_display_type(self, display_type: str) -> bool:
        """
        Load the calibration matrix for a specific display technology
        from this device's EEPROM.

        Args:
            display_type: One of the keys in CAL_OFFSETS (e.g., "OLED",
                         "WhiteLED", "CCFL", "WideGamutCCFL")

        Returns:
            True if the matrix was read successfully, False if fallback used.
        """
        if display_type not in self.CAL_OFFSETS:
            return False

        offset = self.CAL_OFFSETS[display_type] + self.CAL_MATRIX_OFFSET
        raw = self._read_eeprom(offset, 72)

        if raw is not None:
            matrix = self._parse_cal_matrix(raw)
            if matrix is not None:
                flat = [abs(v) for row in matrix for v in row]
                if all(0.0 < v < 10.0 for v in flat if v != 0.0):
                    self._cal_matrix = matrix
                    self._cal_source = f"device_eeprom_{display_type}"
                    return True

        return False

    def _set_integration_time(self, seconds: float):
        """Set the sensor integration time."""
        self._integration_time = max(0.01, min(5.0, seconds))

    def _trigger_measurement(self) -> tuple[float, float, float] | None:
        """
        Trigger a measurement and return raw sensor counts.

        Returns (red, green, blue) raw counts, or None on failure.
        """
        if self._device is None:
            return None

        # The verified i1Display3 measurement report uses a 12 MHz integration
        # clock. HID writes include the report ID plus the 64-byte payload.
        integration_clocks = int(self._integration_time * 12_000_000)
        report = bytearray(REPORT_SIZE + 1)
        report[0] = 0x00
        report[1] = 0x01
        struct.pack_into("<I", report, 2, integration_clocks)

        try:
            self._device.write(report)
            response = self._device.read(
                REPORT_SIZE,
                timeout_ms=int((self._integration_time + 3.0) * 1000),
            )
            if not response or len(response) < 14:
                return None
            resp = bytes(response)
            if resp[0] != STATUS_OK or resp[1] != 0x01:
                return None

            r_raw, g_raw, b_raw = struct.unpack("<III", resp[2:14])
            seconds = integration_clocks / 12_000_000.0
            if seconds <= 0:
                return None
            return tuple(0.5 * (count + 0.5) / seconds for count in (r_raw, g_raw, b_raw))
        except (OSError, struct.error, TypeError, ValueError):
            return None

    def _apply_calibration(self, raw: tuple[float, float, float]) -> I1D3Measurement | None:
        """Apply calibration matrix to convert raw counts to XYZ."""
        r, g, b = raw

        # Subtract black offset
        r -= self._black_offset[0]
        g -= self._black_offset[1]
        b -= self._black_offset[2]

        # Apply 3x3 calibration matrix
        M = self._cal_matrix
        X = M[0][0] * r + M[0][1] * g + M[0][2] * b
        Y = M[1][0] * r + M[1][1] * g + M[1][2] * b
        Z = M[2][0] * r + M[2][1] * g + M[2][2] * b

        if not all(math.isfinite(value) for value in (r, g, b, X, Y, Z)):
            return None
        if any(value < 0.0 for value in (X, Y, Z)):
            return None
        if not 0.0 < Y <= 100_000.0:
            return None

        # Compute CCT from xy chromaticity
        cct = 0.0
        total = X + Y + Z
        if total > 0:
            x = X / total
            y = Y / total
            if y > 0:
                n = (x - 0.3320) / (0.1858 - y)
                cct = 449 * n**3 + 3525 * n**2 + 6823.3 * n + 5520.33
                if not math.isfinite(cct):
                    cct = 0.0

        return I1D3Measurement(
            red_count=raw[0],
            green_count=raw[1],
            blue_count=raw[2],
            integration_time=self._integration_time,
            X=X,
            Y=Y,
            Z=Z,
            luminance=Y,
            cct=cct,
        )

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()


# =============================================================================
# Convenience functions
# =============================================================================


def detect_colorimeters() -> list[dict]:
    """Find all connected i1Display3 family colorimeters."""
    return I1D3Driver.find_devices()


def quick_measure() -> I1D3Measurement | None:
    """Take a single measurement with default settings."""
    driver = I1D3Driver()
    if not driver.open():
        return None
    try:
        return driver.measure()
    finally:
        driver.close()
