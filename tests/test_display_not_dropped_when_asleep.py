"""A display Windows still owns is not dropped because its panel went dark.

``enumerate_displays`` walked the graphics adapters, and for each one asked
Windows for the monitor devices hanging off it. Every display it reported came
from a monitor device, so an adapter that reported none contributed nothing.

That is not the same condition as "no display". An adapter holds an active
desktop with no enumerable monitor device whenever the panel is asleep or
switched off at the wall, and whenever the mode comes from an indirect display
driver. Windows still counts that desktop in ``GetSystemMetrics(SM_CMONITORS)``,
still enumerates it through ``EnumDisplayMonitors``, still accepts a gamma ramp
for it, and still resolves an ICC profile for it. The tool reported no displays
at all and had nothing to calibrate.

The fix reports the adapter in that case. The direction it must not go is the
other one: the adapter's ``DeviceString`` names the graphics card, so writing it
into ``monitor_name`` would report an RTX 4090 as the panel being calibrated.
PRODUCT.md: the interface must never convert modeled, simulated, replayed, or
placeholder values into apparent instrument observations. Every monitor-specific
field stays empty, which is what the rest of the package already reads as
unknown.

These tests drive the record builders directly with stand-in structures, so they
cover the decision on every platform rather than only where ``DISPLAY_DEVICE``
can be constructed.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from calibrate_pro.panels import detection

ACTIVE = detection.DISPLAY_DEVICE_ACTIVE
PRIMARY = detection.DISPLAY_DEVICE_PRIMARY_DEVICE

ADAPTER_NAME = "\\\\.\\DISPLAY1"
ADAPTER_STRING = "NVIDIA GeForce RTX 4090"
MONITOR_ID = "MONITOR\\DEL41E6\\{4d36e96e-e325-11ce-bfc1-08002be10318}\\0007"


def _adapter(state: int = ACTIVE | PRIMARY) -> SimpleNamespace:
    """Stands in for the DISPLAY_DEVICE describing a graphics adapter."""
    return SimpleNamespace(
        DeviceName=ADAPTER_NAME,
        DeviceString=ADAPTER_STRING,
        StateFlags=state,
        DeviceID="",
    )


def _monitor(
    name: str = "AW3423DWF",
    device_id: str = MONITOR_ID,
    state: int = ACTIVE,
) -> SimpleNamespace:
    """Stands in for the DISPLAY_DEVICE describing a monitor on that adapter."""
    return SimpleNamespace(DeviceString=name, DeviceID=device_id, StateFlags=state)


def _devmode(width: int = 3440, height: int = 1440) -> SimpleNamespace:
    """Stands in for the DEVMODE carrying the adapter's current mode."""
    return SimpleNamespace(
        dmPelsWidth=width,
        dmPelsHeight=height,
        dmDisplayFrequency=165,
        dmBitsPerPel=32,
        dmPositionX=0,
        dmPositionY=0,
    )


@pytest.fixture
def profile_calls(monkeypatch):
    """Record the ICC lookups instead of reading them off the OS."""
    calls: list[str] = []

    def fake(device_name: str) -> str:
        calls.append(device_name)
        return "C:\\Windows\\System32\\spool\\drivers\\color\\AW3423DWF.icm"

    monkeypatch.setattr(detection, "get_display_profile", fake)
    return calls


# ---------------------------------------------------------------------------
# The adapter is reported when no monitor device can be enumerated
# ---------------------------------------------------------------------------


def test_an_active_adapter_with_no_monitor_device_is_still_reported(profile_calls):
    """The panel is asleep. The desktop, the gamma ramp and the profile are not."""
    displays = detection._displays_for_adapter(_adapter(), _devmode(), [])

    assert len(displays) == 1
    assert displays[0].device_name == ADAPTER_NAME


def test_monitor_devices_that_are_all_inactive_fall_back_to_the_adapter(profile_calls):
    """Windows reports the device and marks it inactive when the panel sleeps."""
    monitors = [_monitor(state=0), _monitor(name="Generic PnP Monitor", state=0)]

    displays = detection._displays_for_adapter(_adapter(), _devmode(), monitors)

    assert len(displays) == 1
    assert displays[0].monitor_name == ""


def test_the_fallback_record_leaves_every_monitor_field_empty(profile_calls):
    """Nothing was read off a monitor, so nothing may be reported as read."""
    display = detection._displays_for_adapter(_adapter(), _devmode(), [])[0]

    assert display.monitor_name == ""
    assert display.device_id == ""
    assert display.manufacturer == ""
    assert display.model == ""


def test_the_fallback_record_does_not_report_the_graphics_card_as_the_panel(profile_calls):
    """``DeviceString`` names the adapter. Copying it across invents a monitor."""
    display = detection._displays_for_adapter(_adapter(), _devmode(), [])[0]

    assert display.device_string == ADAPTER_STRING
    assert ADAPTER_STRING not in (display.monitor_name, display.model)


def test_the_fallback_record_carries_the_mode_windows_reported(profile_calls):
    """The mode came from EnumDisplaySettingsW, so it is a real reading."""
    display = detection._displays_for_adapter(_adapter(), _devmode(2560, 1440), [])[0]

    assert (display.width, display.height) == (2560, 1440)
    assert display.refresh_rate == 165
    assert display.bit_depth == 32


def test_the_fallback_record_keeps_the_primary_flag(profile_calls):
    """The primary display drives which panel the calibration targets first."""
    primary = detection._displays_for_adapter(_adapter(), _devmode(), [])[0]
    secondary = detection._displays_for_adapter(_adapter(state=ACTIVE), _devmode(), [])[0]

    assert primary.is_primary is True
    assert secondary.is_primary is False


# ---------------------------------------------------------------------------
# The fallback does not invent displays that are not there
# ---------------------------------------------------------------------------


def test_an_inactive_adapter_is_not_reported(profile_calls):
    """A detached adapter holds no desktop, so there is nothing to calibrate."""
    assert detection._displays_for_adapter(_adapter(state=0), _devmode(), []) == []


@pytest.mark.parametrize("width,height", [(0, 1440), (3440, 0), (0, 0)])
def test_an_adapter_with_no_mode_is_not_reported(profile_calls, width, height):
    """A desktop with no geometry has no patch area to put a color on."""
    devmode = _devmode(width, height)

    assert detection._displays_for_adapter(_adapter(), devmode, []) == []


def test_nothing_is_reported_when_the_adapter_is_both_inactive_and_modeless(profile_calls):
    """The two guards are independent, so neither one alone carries the refusal."""
    assert detection._displays_for_adapter(_adapter(state=0), _devmode(0, 0), []) == []


# ---------------------------------------------------------------------------
# A real monitor device is still preferred, and still read the same way
# ---------------------------------------------------------------------------


def test_a_monitor_device_is_used_in_place_of_the_fallback(profile_calls):
    """The fallback is the last resort, not a second entry beside the monitor."""
    displays = detection._displays_for_adapter(_adapter(), _devmode(), [_monitor()])

    assert len(displays) == 1
    assert displays[0].monitor_name == "AW3423DWF"
    assert displays[0].device_id == MONITOR_ID


def test_a_monitor_device_still_supplies_the_manufacturer_and_model(profile_calls):
    """The EDID vendor and product codes are parsed out of the device ID."""
    display = detection._displays_for_adapter(_adapter(), _devmode(), [_monitor()])[0]

    assert display.manufacturer == "Dell"
    assert display.model == "41E6"


def test_two_active_monitor_devices_are_both_reported(profile_calls):
    """One adapter can drive more than one panel."""
    monitors = [_monitor(), _monitor(name="U2723QE", device_id="MONITOR\\DEL41F0\\x")]

    displays = detection._displays_for_adapter(_adapter(), _devmode(), monitors)

    assert [d.monitor_name for d in displays] == ["AW3423DWF", "U2723QE"]


def test_an_inactive_monitor_device_is_skipped_when_an_active_one_is_present(profile_calls):
    """A panel Windows marks inactive is not a target, and does not mask the rest."""
    monitors = [_monitor(name="Asleep", state=0), _monitor()]

    displays = detection._displays_for_adapter(_adapter(), _devmode(), monitors)

    assert [d.monitor_name for d in displays] == ["AW3423DWF"]


# ---------------------------------------------------------------------------
# The ICC profile lookup
# ---------------------------------------------------------------------------


def test_the_profile_is_resolved_once_for_the_adapter(profile_calls):
    """The profile is per adapter, and the lookup reads the OS colour store."""
    monitors = [_monitor(), _monitor(name="U2723QE", device_id="MONITOR\\DEL41F0\\x")]

    detection._displays_for_adapter(_adapter(), _devmode(), monitors)

    assert profile_calls == [ADAPTER_NAME]


def test_the_fallback_record_carries_the_adapter_profile(profile_calls):
    """Windows keeps the profile for a display whose panel is asleep."""
    display = detection._displays_for_adapter(_adapter(), _devmode(), [])[0]

    assert display.current_profile is not None
    assert profile_calls == [ADAPTER_NAME]


def test_no_profile_is_resolved_when_no_display_is_reported(profile_calls):
    """A refused adapter does not reach the colour store at all."""
    detection._displays_for_adapter(_adapter(state=0), _devmode(), [])

    assert profile_calls == []
