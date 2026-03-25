"""
Tests for the cross-platform display backend layer.

Covers:
- Platform selection via get_platform_backend()
- Mock display detection on all backends
- Gamma ramp format validation (Nx3, values 0-65535)
- Graceful degradation when platform libraries unavailable
- Base class contract enforcement
- EDID parsing
- xrandr output parsing
- Linux startup helpers
- macOS startup helpers
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional
from unittest import mock

import numpy as np
import pytest

from calibrate_pro.platform.base import DisplayInfo, PlatformBackend
from calibrate_pro.platform import get_platform_backend


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture
def linear_ramp_256():
    """A linear identity ramp: 256 entries, 0 to 65535."""
    return list(np.linspace(0, 65535, 256, dtype=np.uint16))


@pytest.fixture
def gamma_22_ramp_256():
    """A gamma-2.2 ramp: 256 entries, 0 to 65535."""
    t = np.linspace(0, 1, 256)
    return list((t ** 2.2 * 65535).astype(np.uint16))


@pytest.fixture
def mock_display_info():
    """A valid DisplayInfo for testing."""
    return DisplayInfo(
        index=0,
        name="Test Display",
        device_path="/test/display0",
        is_primary=True,
        width=2560,
        height=1440,
        refresh_rate=144,
        bit_depth=10,
        position_x=0,
        position_y=0,
        manufacturer="TST",
        model="TestPanel",
        serial="SN12345",
        current_icc_profile=None,
    )


# =====================================================================
# DisplayInfo dataclass
# =====================================================================

class TestDisplayInfo:
    """Tests for the DisplayInfo dataclass."""

    def test_required_fields(self):
        info = DisplayInfo(
            index=0, name="Monitor", device_path="/dev/0",
            is_primary=True, width=1920, height=1080, refresh_rate=60,
        )
        assert info.index == 0
        assert info.name == "Monitor"
        assert info.is_primary is True
        assert info.width == 1920
        assert info.height == 1080
        assert info.refresh_rate == 60

    def test_default_fields(self):
        info = DisplayInfo(
            index=0, name="Monitor", device_path="/dev/0",
            is_primary=False, width=3840, height=2160, refresh_rate=120,
        )
        assert info.bit_depth == 8
        assert info.position_x == 0
        assert info.position_y == 0
        assert info.manufacturer == ""
        assert info.model == ""
        assert info.serial == ""
        assert info.current_icc_profile is None

    def test_all_fields_populated(self, mock_display_info):
        d = mock_display_info
        assert d.manufacturer == "TST"
        assert d.model == "TestPanel"
        assert d.serial == "SN12345"
        assert d.bit_depth == 10
        assert d.refresh_rate == 144


# =====================================================================
# Platform selection
# =====================================================================

class TestPlatformSelection:
    """Test that get_platform_backend() returns the correct class."""

    def test_windows_selection(self):
        with mock.patch.object(sys, "platform", "win32"):
            with mock.patch(
                "calibrate_pro.platform.windows.WindowsBackend",
                create=True,
            ) as mock_cls:
                mock_cls.return_value = mock.MagicMock(spec=PlatformBackend)
                backend = get_platform_backend()
                mock_cls.assert_called_once()

    def test_darwin_selection(self):
        with mock.patch.object(sys, "platform", "darwin"):
            with mock.patch(
                "calibrate_pro.platform.macos.MacOSBackend",
                create=True,
            ) as mock_cls:
                mock_cls.return_value = mock.MagicMock(spec=PlatformBackend)
                backend = get_platform_backend()
                mock_cls.assert_called_once()

    def test_linux_selection(self):
        with mock.patch.object(sys, "platform", "linux"):
            with mock.patch(
                "calibrate_pro.platform.linux.LinuxBackend",
                create=True,
            ) as mock_cls:
                mock_cls.return_value = mock.MagicMock(spec=PlatformBackend)
                backend = get_platform_backend()
                mock_cls.assert_called_once()

    def test_linux_variant_selection(self):
        """linux2, linux-armv7l, etc. should all resolve to LinuxBackend."""
        with mock.patch.object(sys, "platform", "linux-armv7l"):
            with mock.patch(
                "calibrate_pro.platform.linux.LinuxBackend",
                create=True,
            ) as mock_cls:
                mock_cls.return_value = mock.MagicMock(spec=PlatformBackend)
                backend = get_platform_backend()
                mock_cls.assert_called_once()

    def test_unsupported_platform_raises(self):
        with mock.patch.object(sys, "platform", "freebsd13"):
            with pytest.raises(RuntimeError, match="Unsupported platform"):
                get_platform_backend()

    def test_current_platform_returns_backend(self):
        """On the current OS, get_platform_backend() should not raise."""
        backend = get_platform_backend()
        assert isinstance(backend, PlatformBackend)


# =====================================================================
# Abstract base class enforcement
# =====================================================================

class TestBaseClassContract:
    """Verify that PlatformBackend enforces the abstract interface."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            PlatformBackend()

    def test_incomplete_subclass_raises(self):
        class IncompleteBackend(PlatformBackend):
            def enumerate_displays(self):
                return []
            # Missing: apply_gamma_ramp, reset_gamma_ramp,
            #          install_icc_profile, get_icc_profile

        with pytest.raises(TypeError):
            IncompleteBackend()

    def test_complete_subclass_instantiates(self):
        class CompleteBackend(PlatformBackend):
            def enumerate_displays(self) -> List[DisplayInfo]:
                return []
            def apply_gamma_ramp(self, di, r, g, b) -> bool:
                return True
            def reset_gamma_ramp(self, di) -> bool:
                return True
            def install_icc_profile(self, pp, di) -> bool:
                return True
            def get_icc_profile(self, di) -> Optional[str]:
                return None

        backend = CompleteBackend()
        assert backend.enumerate_displays() == []
        assert backend.apply_gamma_ramp(0, [], [], []) is True
        assert backend.reset_gamma_ramp(0) is True
        assert backend.install_icc_profile("test.icc", 0) is True
        assert backend.get_icc_profile(0) is None


# =====================================================================
# Gamma ramp validation
# =====================================================================

class TestGammaRampFormat:
    """Validate gamma ramp data format requirements."""

    def test_linear_ramp_length(self, linear_ramp_256):
        assert len(linear_ramp_256) == 256

    def test_linear_ramp_range(self, linear_ramp_256):
        arr = np.array(linear_ramp_256, dtype=np.uint16)
        assert arr.min() == 0
        assert arr.max() == 65535

    def test_linear_ramp_monotonic(self, linear_ramp_256):
        arr = np.array(linear_ramp_256)
        diffs = np.diff(arr)
        assert np.all(diffs >= 0), "Linear ramp must be monotonically increasing"

    def test_gamma_22_ramp_range(self, gamma_22_ramp_256):
        arr = np.array(gamma_22_ramp_256, dtype=np.uint16)
        assert arr[0] == 0
        assert arr[-1] == 65535

    def test_gamma_22_ramp_shape(self, gamma_22_ramp_256):
        """Gamma 2.2 midpoint should be significantly below linear midpoint."""
        arr = np.array(gamma_22_ramp_256, dtype=np.float64) / 65535.0
        midpoint = arr[128]
        # For gamma 2.2, (0.5)^2.2 ~ 0.2176
        assert 0.15 < midpoint < 0.30, f"Gamma 2.2 midpoint {midpoint} not in expected range"

    def test_ramp_as_nx3_array(self, linear_ramp_256):
        """The standard ramp format: Nx3 numpy array with values 0-1 float."""
        r = np.array(linear_ramp_256, dtype=np.float64) / 65535.0
        g = np.array(linear_ramp_256, dtype=np.float64) / 65535.0
        b = np.array(linear_ramp_256, dtype=np.float64) / 65535.0

        ramp = np.column_stack([r, g, b])
        assert ramp.shape == (256, 3)
        assert ramp.min() >= 0.0
        assert ramp.max() <= 1.0

    def test_ramp_uint16_round_trip(self, linear_ramp_256):
        """Converting float -> uint16 -> float should preserve precision."""
        original = np.array(linear_ramp_256, dtype=np.uint16)
        as_float = original.astype(np.float64) / 65535.0
        back = (as_float * 65535.0).astype(np.uint16)
        np.testing.assert_array_equal(original, back)


# =====================================================================
# macOS backend tests
# =====================================================================

class TestMacOSBackend:
    """Tests for macOS backend (importable on any platform)."""

    def test_import_succeeds(self):
        from calibrate_pro.platform.macos import MacOSBackend
        assert MacOSBackend is not None

    def test_instantiation(self):
        from calibrate_pro.platform.macos import MacOSBackend
        backend = MacOSBackend()
        assert isinstance(backend, PlatformBackend)

    def test_enumerate_without_quartz_returns_empty(self):
        """When pyobjc is missing, enumerate_displays returns []."""
        from calibrate_pro.platform.macos import MacOSBackend
        backend = MacOSBackend()

        with mock.patch.dict(sys.modules, {"Quartz": None}):
            with mock.patch("builtins.__import__", side_effect=_import_blocker("Quartz")):
                result = backend.enumerate_displays()
                assert result == []

    def test_apply_gamma_without_quartz_returns_false(self):
        """When pyobjc is missing, apply_gamma_ramp returns False."""
        from calibrate_pro.platform.macos import MacOSBackend
        backend = MacOSBackend()

        with mock.patch.dict(sys.modules, {"Quartz": None}):
            with mock.patch("builtins.__import__", side_effect=_import_blocker("Quartz")):
                result = backend.apply_gamma_ramp(0, [0]*256, [0]*256, [0]*256)
                assert result is False

    def test_reset_gamma_without_quartz_returns_false(self):
        from calibrate_pro.platform.macos import MacOSBackend
        backend = MacOSBackend()

        with mock.patch.dict(sys.modules, {"Quartz": None}):
            with mock.patch("builtins.__import__", side_effect=_import_blocker("Quartz")):
                result = backend.reset_gamma_ramp(0)
                assert result is False

    def test_get_icc_without_quartz_returns_none(self):
        from calibrate_pro.platform.macos import MacOSBackend
        backend = MacOSBackend()

        # _get_display_id will fail without Quartz, returning None
        with mock.patch.dict(sys.modules, {"Quartz": None}):
            with mock.patch("builtins.__import__", side_effect=_import_blocker("Quartz")):
                result = backend.get_icc_profile(0)
                assert result is None

    def test_startup_helpers_importable(self):
        from calibrate_pro.platform.macos import (
            enable_macos_startup,
            disable_macos_startup,
            is_macos_startup_enabled,
        )
        assert callable(enable_macos_startup)
        assert callable(disable_macos_startup)
        assert callable(is_macos_startup_enabled)


# =====================================================================
# Linux backend tests
# =====================================================================

class TestLinuxBackend:
    """Tests for Linux backend (importable on any platform)."""

    def test_import_succeeds(self):
        from calibrate_pro.platform.linux import LinuxBackend
        assert LinuxBackend is not None

    def test_instantiation(self):
        from calibrate_pro.platform.linux import LinuxBackend
        backend = LinuxBackend()
        assert isinstance(backend, PlatformBackend)

    def test_enumerate_without_xrandr_returns_empty(self):
        """When xrandr is unavailable, enumerate should fall back gracefully."""
        from calibrate_pro.platform.linux import LinuxBackend
        backend = LinuxBackend()

        with mock.patch("calibrate_pro.platform.linux._run_cmd", return_value=None):
            with mock.patch("pathlib.Path.exists", return_value=False):
                result = backend.enumerate_displays()
                assert result == []

    def test_enumerate_xrandr_parses_output(self):
        """Test xrandr output parsing with mock data."""
        from calibrate_pro.platform.linux import LinuxBackend
        backend = LinuxBackend()

        xrandr_output = (
            "Screen 0: minimum 8 x 8, current 5120 x 1440, maximum 32767 x 32767\n"
            "DP-1 connected primary 2560x1440+0+0 (normal left inverted right x axis y axis) 597mm x 336mm\n"
            "   2560x1440     59.95*+  143.97    119.98\n"
            "   1920x1080     60.00    50.00\n"
            "HDMI-1 connected 2560x1440+2560+0 (normal left inverted right x axis y axis) 597mm x 336mm\n"
            "   2560x1440     59.95*+\n"
            "DP-2 disconnected (normal left inverted right x axis y axis)\n"
        )

        def mock_run_cmd(cmd, timeout=10):
            if cmd[0] == "xrandr":
                return xrandr_output
            return None

        with mock.patch("calibrate_pro.platform.linux._run_cmd", side_effect=mock_run_cmd):
            with mock.patch.object(backend, "_build_drm_edid_map", return_value={}):
                with mock.patch.object(backend, "_get_colord_profile", return_value=None):
                    result = backend.enumerate_displays()

        assert len(result) == 2
        assert result[0].device_path == "DP-1"
        assert result[0].is_primary is True
        assert result[0].width == 2560
        assert result[0].height == 1440
        assert result[0].refresh_rate == 59
        assert result[0].position_x == 0
        assert result[1].device_path == "HDMI-1"
        assert result[1].is_primary is False
        assert result[1].position_x == 2560

    def test_apply_gamma_without_tools_returns_false(self):
        """When both python-xlib and xrandr are missing, returns False."""
        from calibrate_pro.platform.linux import LinuxBackend
        backend = LinuxBackend()

        ramp = list(range(0, 65536, 256))[:256]

        with mock.patch("calibrate_pro.platform.linux._run_cmd", return_value=None):
            with mock.patch.dict(sys.modules, {"Xlib": None, "Xlib.ext": None, "Xlib.ext.randr": None}):
                result = backend.apply_gamma_ramp(0, ramp, ramp, ramp)
                assert result is False

    def test_reset_gamma_without_tools_returns_false(self):
        from calibrate_pro.platform.linux import LinuxBackend
        backend = LinuxBackend()

        with mock.patch("calibrate_pro.platform.linux._run_cmd", return_value=None):
            with mock.patch.dict(sys.modules, {"Xlib": None}):
                result = backend.reset_gamma_ramp(0)
                assert result is False

    def test_get_icc_without_colord_returns_none(self):
        from calibrate_pro.platform.linux import LinuxBackend
        backend = LinuxBackend()

        with mock.patch("calibrate_pro.platform.linux._run_cmd", return_value=None):
            result = backend.get_icc_profile(0)
            assert result is None

    def test_install_icc_nonexistent_file_returns_false(self):
        from calibrate_pro.platform.linux import LinuxBackend
        backend = LinuxBackend()

        result = backend.install_icc_profile("/nonexistent/profile.icc", 0)
        assert result is False

    def test_install_icc_copies_to_user_dir(self, tmp_path):
        """ICC profile install should copy to ~/.local/share/icc/."""
        from calibrate_pro.platform.linux import LinuxBackend
        backend = LinuxBackend()

        # Create a fake profile
        fake_profile = tmp_path / "test_profile.icc"
        fake_profile.write_bytes(b"\x00" * 128)

        dest_dir = tmp_path / "icc_dest"

        with mock.patch("pathlib.Path.home", return_value=tmp_path):
            with mock.patch.object(backend, "_register_colord_profile"):
                with mock.patch("calibrate_pro.platform.linux._run_cmd", return_value=None):
                    result = backend.install_icc_profile(str(fake_profile), 0)

        assert result is True
        installed = tmp_path / ".local" / "share" / "icc" / "test_profile.icc"
        assert installed.exists()

    def test_startup_helpers_importable(self):
        from calibrate_pro.platform.linux import (
            enable_linux_startup,
            disable_linux_startup,
            is_linux_startup_enabled,
        )
        assert callable(enable_linux_startup)
        assert callable(disable_linux_startup)
        assert callable(is_linux_startup_enabled)


# =====================================================================
# EDID parsing (Linux helper)
# =====================================================================

class TestLinuxEdidParsing:
    """Test the EDID parser used by the Linux backend."""

    def test_parse_valid_edid(self):
        from calibrate_pro.platform.linux import _parse_edid_name

        # Construct a minimal valid EDID block (128 bytes)
        edid = bytearray(128)
        # EDID header
        edid[0:8] = b'\x00\xff\xff\xff\xff\xff\xff\x00'
        # Manufacturer ID "TST" -> T=0x14, S=0x13, T=0x14
        # Compressed: ((0x14 << 10) | (0x13 << 5) | 0x14) = 0x5274
        edid[8] = 0x52
        edid[9] = 0x74

        # Descriptor block 1 (offset 54): monitor name (tag 0xFC)
        edid[54] = 0x00
        edid[55] = 0x00
        edid[56] = 0x00
        edid[57] = 0xFC  # Monitor name tag
        edid[58] = 0x00
        name_bytes = b'Test Monitor\n'
        edid[59:59 + len(name_bytes)] = name_bytes

        # Descriptor block 2 (offset 72): serial string (tag 0xFF)
        edid[72] = 0x00
        edid[73] = 0x00
        edid[74] = 0x00
        edid[75] = 0xFF  # Serial string tag
        edid[76] = 0x00
        serial_bytes = b'SN00001\n'
        edid[77:77 + len(serial_bytes)] = serial_bytes

        manufacturer, model, serial = _parse_edid_name(bytes(edid))
        assert manufacturer == "TST"
        assert model == "Test Monitor"
        assert serial == "SN00001"

    def test_parse_short_edid_returns_empty(self):
        from calibrate_pro.platform.linux import _parse_edid_name
        manufacturer, model, serial = _parse_edid_name(b'\x00' * 64)
        assert manufacturer == ""
        assert model == ""
        assert serial == ""

    def test_parse_empty_edid_returns_empty(self):
        from calibrate_pro.platform.linux import _parse_edid_name
        manufacturer, model, serial = _parse_edid_name(b'')
        assert manufacturer == ""
        assert model == ""
        assert serial == ""


# =====================================================================
# xrandr output parser (Linux helper)
# =====================================================================

class TestXrandrParser:
    """Test the xrandr --query output parser."""

    def test_single_display(self):
        from calibrate_pro.platform.linux import _parse_xrandr_output

        text = (
            "Screen 0: minimum 8 x 8, current 2560 x 1440\n"
            "DP-1 connected primary 2560x1440+0+0 (normal) 597mm x 336mm\n"
            "   2560x1440     143.97*+  119.98    59.95\n"
            "   1920x1080     60.00\n"
        )

        result = _parse_xrandr_output(text)
        assert len(result) == 1
        assert result[0]['name'] == "DP-1"
        assert result[0]['primary'] is True
        assert result[0]['width'] == 2560
        assert result[0]['height'] == 1440
        assert result[0]['refresh'] == 143

    def test_multiple_displays(self):
        from calibrate_pro.platform.linux import _parse_xrandr_output

        text = (
            "Screen 0: minimum 8 x 8, current 5120 x 1440\n"
            "eDP-1 connected primary 1920x1080+0+0 (normal) 309mm x 174mm\n"
            "   1920x1080     60.01*+  59.97    59.96\n"
            "HDMI-1 connected 3840x2160+1920+0 (normal) 600mm x 340mm\n"
            "   3840x2160     60.00*+  30.00\n"
            "DP-2 disconnected\n"
        )

        result = _parse_xrandr_output(text)
        assert len(result) == 2
        assert result[0]['name'] == "eDP-1"
        assert result[0]['primary'] is True
        assert result[0]['width'] == 1920
        assert result[1]['name'] == "HDMI-1"
        assert result[1]['primary'] is False
        assert result[1]['width'] == 3840
        assert result[1]['pos_x'] == 1920

    def test_no_connected_displays(self):
        from calibrate_pro.platform.linux import _parse_xrandr_output

        text = (
            "Screen 0: minimum 8 x 8, current 0 x 0\n"
            "DP-1 disconnected\n"
            "HDMI-1 disconnected\n"
        )

        result = _parse_xrandr_output(text)
        assert len(result) == 0

    def test_empty_input(self):
        from calibrate_pro.platform.linux import _parse_xrandr_output
        assert _parse_xrandr_output("") == []


# =====================================================================
# Windows backend tests (smoke)
# =====================================================================

class TestWindowsBackend:
    """Basic import/instantiation tests for Windows backend."""

    def test_import_succeeds(self):
        from calibrate_pro.platform.windows import WindowsBackend
        assert WindowsBackend is not None

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_enumerate_on_windows(self):
        from calibrate_pro.platform.windows import WindowsBackend
        backend = WindowsBackend()
        displays = backend.enumerate_displays()
        assert isinstance(displays, list)
        assert len(displays) > 0, "Should detect at least one display"
        assert all(isinstance(d, DisplayInfo) for d in displays)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_display_fields_valid(self):
        from calibrate_pro.platform.windows import WindowsBackend
        backend = WindowsBackend()
        displays = backend.enumerate_displays()
        for d in displays:
            assert d.width > 0
            assert d.height > 0
            assert d.refresh_rate > 0
            assert d.name != ""
            assert d.device_path != ""


# =====================================================================
# Integration: current platform backend
# =====================================================================

class TestCurrentPlatformIntegration:
    """Integration tests that run on whatever platform we're on."""

    def test_backend_has_all_methods(self):
        backend = get_platform_backend()
        assert hasattr(backend, "enumerate_displays")
        assert hasattr(backend, "apply_gamma_ramp")
        assert hasattr(backend, "reset_gamma_ramp")
        assert hasattr(backend, "install_icc_profile")
        assert hasattr(backend, "get_icc_profile")

    def test_enumerate_returns_list(self):
        backend = get_platform_backend()
        result = backend.enumerate_displays()
        assert isinstance(result, list)

    def test_get_icc_invalid_index_returns_none(self):
        backend = get_platform_backend()
        result = backend.get_icc_profile(999)
        assert result is None

    def test_apply_gamma_invalid_index_returns_false(self):
        backend = get_platform_backend()
        ramp = list(range(0, 65536, 256))[:256]
        result = backend.apply_gamma_ramp(999, ramp, ramp, ramp)
        assert result is False

    def test_reset_gamma_invalid_index_returns_false(self):
        backend = get_platform_backend()
        result = backend.reset_gamma_ramp(999)
        assert result is False


# =====================================================================
# Helpers
# =====================================================================

def _import_blocker(blocked_module: str):
    """Return a side_effect for builtins.__import__ that blocks one module."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def blocker(name, *args, **kwargs):
        if name == blocked_module or name.startswith(blocked_module + "."):
            raise ImportError(f"Mocked: {name} not available")
        return real_import(name, *args, **kwargs)

    return blocker
