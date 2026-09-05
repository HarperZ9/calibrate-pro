"""Display capabilities are not inferred from the display mode.

``enrich_display_info`` ended with two guesses for a display it could not match
to a panel database entry.

The first read a display wider than 3840 pixels above 120 Hz as HDR capable and
wide gamut, because a panel with that mode is usually a recent gaming monitor.
Usually is not evidence, and the record has no field to mark a value as guessed.

The second read ``bit_depth >= 10`` as ten-bit colour. ``bit_depth`` holds
DEVMODE's ``dmBitsPerPel``, which counts bits per pixel rather than bits per
channel, so an ordinary 8-bit sRGB desktop reports 32 there. The comparison was
therefore true for every display, and every unmatched display was reported wide
gamut whatever panel it actually was. That one is a unit confusion rather than
a heuristic: the field cannot carry the fact being read out of it.

Both fields have a real source. The gamut follows from the EDID chromaticity
primaries, which ``PanelProfile.create_from_edid`` already reads, and HDR
support follows from the panel database entry or from ``display.hdr_detect``.
Leaving the fields at ``False`` sends a caller to those. PRODUCT.md: the
interface must never convert modeled, simulated, replayed, or placeholder
values into apparent instrument observations.
"""

from __future__ import annotations

import pytest

from calibrate_pro.panels import detection
from calibrate_pro.panels.detection import DisplayInfo


@pytest.fixture(autouse=True)
def no_hardware_reads(monkeypatch):
    """Keep the enrichment off the Windows registry and out of hardware state."""
    monkeypatch.setattr(detection, "get_edid_from_registry", lambda device_id: None)
    monkeypatch.setattr(detection, "detect_connection_type", lambda device_id: "Unknown")


def _display(
    width: int,
    height: int,
    refresh: int,
    manufacturer: str = "Acer",
    bit_depth: int = 32,
) -> DisplayInfo:
    """A display with a mode and a manufacturer that has no database entry.

    ``bit_depth`` defaults to 32 because that is what Windows reports for an
    ordinary desktop: DEVMODE counts bits per pixel.
    """
    return DisplayInfo(
        device_name="\\\\.\\DISPLAY1",
        device_string="NVIDIA GeForce RTX 4090",
        monitor_name="",
        device_id="",
        is_primary=True,
        is_active=True,
        width=width,
        height=height,
        refresh_rate=refresh,
        bit_depth=bit_depth,
        position_x=0,
        position_y=0,
        manufacturer=manufacturer,
    )


def test_an_unmatched_4k_high_refresh_display_is_not_reported_hdr_capable():
    """The mode that used to imply HDR: 4K at 240Hz."""
    display = detection.enrich_display_info(_display(3840, 2160, 240))

    assert display.panel_database_key == ""
    assert display.hdr_capable is False


def test_an_unmatched_4k_high_refresh_display_is_not_reported_wide_gamut():
    """The same branch set both fields, so both are checked."""
    display = detection.enrich_display_info(_display(3840, 2160, 240))

    assert display.wide_gamut is False


def test_an_sdr_desktop_is_not_reported_wide_gamut_from_bits_per_pixel():
    """32 bits per pixel is 8 bits per channel, which is the sRGB case."""
    sdr = _display(1920, 1080, 60)
    assert sdr.bit_depth == 32, "the guard reads dmBitsPerPel, not bits per channel"

    display = detection.enrich_display_info(sdr)

    assert display.wide_gamut is False


@pytest.mark.parametrize("bit_depth", [8, 10, 16, 24, 32])
def test_no_bit_depth_alone_makes_a_display_wide_gamut(bit_depth):
    """Whatever the field holds, it does not carry the primaries."""
    display = detection.enrich_display_info(_display(2560, 1440, 144, bit_depth=bit_depth))

    assert display.wide_gamut is False


def test_an_unmatched_display_reports_no_peak_luminance():
    """Peak brightness in nits comes from a panel entry or a measurement."""
    display = detection.enrich_display_info(_display(3840, 2160, 240))

    assert display.max_luminance == 0.0


def test_a_matched_display_still_reports_the_panels_own_capabilities():
    """The database entry is evidence, and it is still read."""
    display = detection.enrich_display_info(_display(3440, 1440, 175, manufacturer="Dell"))

    assert display.panel_database_key == "AW3423DW"
    assert display.hdr_capable is True
    assert display.wide_gamut is True
    assert display.max_luminance == 1000.0
