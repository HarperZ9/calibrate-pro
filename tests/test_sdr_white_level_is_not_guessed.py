"""The SDR white level is a number Windows reports, or it is nothing.

_get_sdr_white_level used to end with `return 200.0`, so a display whose
registry carried no SDR content brightness printed "SDR white level: 200 cd/m2"
as though the OS had been asked and answered. The docstring called 200 a
typical value, which is what a guess looks like written down.

These tests patch winreg and the display enumeration. Nothing here reads the
real registry, enumerates a display, or touches a colorimeter.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.windows


def _hdr_detect():
    """Import lazily. The module imports winreg, which Linux collection lacks."""
    from calibrate_pro.display import hdr_detect

    return hdr_detect


class TestAnUnreportedLevelIsAbsent:
    def test_an_unreadable_key_gives_none_not_200(self, monkeypatch):
        mod = _hdr_detect()

        def no_key(*_args, **_kwargs):
            raise OSError("registry unavailable")

        monkeypatch.setattr(mod.winreg, "OpenKey", no_key)
        assert mod._get_sdr_white_level("display-1") is None

    def test_a_key_without_the_value_gives_none_not_200(self, monkeypatch):
        mod = _hdr_detect()

        monkeypatch.setattr(mod.winreg, "OpenKey", lambda *_a, **_k: object())
        monkeypatch.setattr(mod.winreg, "EnumKey", lambda *_a: "0000")
        monkeypatch.setattr(mod.winreg, "CloseKey", lambda *_a: None)

        def missing_value(*_args):
            raise FileNotFoundError

        monkeypatch.setattr(mod.winreg, "QueryValueEx", missing_value)
        assert mod._get_sdr_white_level("display-1") is None

    def test_a_reported_level_is_returned(self, monkeypatch):
        """Control. A real registry value must still come back."""
        mod = _hdr_detect()

        monkeypatch.setattr(mod.winreg, "OpenKey", lambda *_a, **_k: object())
        monkeypatch.setattr(mod.winreg, "EnumKey", lambda *_a: "0000")
        monkeypatch.setattr(mod.winreg, "CloseKey", lambda *_a: None)
        monkeypatch.setattr(mod.winreg, "QueryValueEx", lambda *_a: (480, 4))

        assert mod._get_sdr_white_level("display-1") == 480.0


class TestTheStatusLineSaysWhichItIs:
    def _state(self, mod, level):
        return mod.HDRDisplayState(
            display_index=0,
            display_name="Panel",
            device_path="display-1",
            hdr_enabled=True,
            hdr_capable=True,
            peak_luminance=0.0,
            sdr_white_level=level,
            color_space="BT2020_PQ",
            bit_depth=10,
        )

    def test_an_absent_level_is_named_absent(self, monkeypatch, capsys):
        mod = _hdr_detect()
        monkeypatch.setattr(mod, "detect_hdr_state", lambda: [self._state(mod, None)])
        mod.print_hdr_status()
        out = capsys.readouterr().out
        assert "not reported by the OS" in out
        assert "200" not in out

    def test_a_real_level_still_prints(self, monkeypatch, capsys):
        """Control."""
        mod = _hdr_detect()
        monkeypatch.setattr(mod, "detect_hdr_state", lambda: [self._state(mod, 480.0)])
        mod.print_hdr_status()
        assert "SDR white level: 480 cd/m2" in capsys.readouterr().out
