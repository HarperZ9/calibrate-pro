"""A panel model is never named from a display mode alone.

``identify_display`` fell back to a fingerprint built from resolution and
refresh rate with the manufacturer stripped off, and ``DISPLAY_FINGERPRINTS``
carried two keys in that form. A mode is not an identity. The table itself
lists four panels at 3440x1440@175 and five at 3840x2160@240, so the stripped
lookup resolved that ambiguity by returning whichever one held the bare key:
every 3440x1440@175 display became a Dell Alienware AW3423DW, and every
3840x2160@240 display became an ASUS PG27UCDM, under a comment that said
"assume QD-OLED".

The returned key is not a display label. ``enrich_display_info`` copies the
matched panel's native gamma, peak luminance and gamut onto the display,
``hdr_detect`` reports that panel's peak luminance in nits as the display's,
and ``vcgt_calibration`` builds the correction curve from that gamma. A guessed
identity therefore reached the ramp loaded into the GPU and the brightness
figure shown to the operator. PRODUCT.md: the interface must never convert
modeled, simulated, replayed, or placeholder values into apparent instrument
observations.

The fix is reachable from the display enumeration fix beside it: an adapter
reported with no monitor device carries an empty manufacturer, which is exactly
the input that produced the bare fingerprint.
"""

from __future__ import annotations

import re

import pytest

from calibrate_pro.panels import detection
from calibrate_pro.panels.detection import DisplayInfo

# Panels the database holds for the two contested modes, with the peak
# luminance and native gamma that would be copied onto a display named as one.
AW3423DW_GAMMA = 2.21
AW3423DW_PEAK = 1000.0


@pytest.fixture(autouse=True)
def no_registry_edid(monkeypatch):
    """Keep identification on the fingerprint path.

    ``get_edid_from_registry`` reads Windows hardware state. That is a side
    effect, it is unavailable off Windows, and it is a different identification
    method from the one under test.
    """
    monkeypatch.setattr(detection, "get_edid_from_registry", lambda device_id: None)


def _display(
    width: int = 3440,
    height: int = 1440,
    refresh: int = 175,
    manufacturer: str = "",
    monitor_name: str = "",
) -> DisplayInfo:
    """A display carrying a mode, with the identity fields under test empty."""
    return DisplayInfo(
        device_name="\\\\.\\DISPLAY1",
        device_string="NVIDIA GeForce RTX 4090",
        monitor_name=monitor_name,
        device_id="",
        is_primary=True,
        is_active=True,
        width=width,
        height=height,
        refresh_rate=refresh,
        bit_depth=32,
        position_x=0,
        position_y=0,
        manufacturer=manufacturer,
    )


# ---------------------------------------------------------------------------
# The mode alone does not name a panel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "width,height,refresh",
    [(3440, 1440, 175), (3840, 2160, 240)],
)
def test_a_display_with_no_manufacturer_is_not_identified(width, height, refresh):
    """These are the two modes that used to carry a bare fingerprint key."""
    display = _display(width, height, refresh)

    assert detection.identify_display(display) is None


def test_an_unknown_manufacturer_is_not_identified_as_another_vendors_panel():
    """Falling back past the manufacturer named an ASUS panel for an Acer display."""
    display = _display(3840, 2160, 240, manufacturer="Acer")

    assert detection.identify_display(display) is None


def test_a_mode_shared_by_several_vendors_stays_ambiguous():
    """Four panels in the table share 3440x1440@175, so the mode decides nothing."""
    sharing_the_mode = [key for key in detection.DISPLAY_FINGERPRINTS if key.startswith("3440x1440@175")]

    assert len(sharing_the_mode) > 1
    assert detection.identify_display(_display()) is None


def test_the_fingerprint_table_holds_no_manufacturer_free_keys():
    """A bare key reintroduces the defect wherever it is added."""
    bare = [key for key in detection.DISPLAY_FINGERPRINTS if "_" not in key]

    assert bare == [], f"these keys name a panel from a mode alone: {bare}"


def test_every_fingerprint_key_carries_a_mode_and_a_manufacturer():
    """The key format is the guard, so it is checked rather than assumed."""
    pattern = re.compile(r"^\d+x\d+@\d+_.+$")

    malformed = [key for key in detection.DISPLAY_FINGERPRINTS if not pattern.match(key)]

    assert malformed == []


# ---------------------------------------------------------------------------
# A manufacturer still identifies the panel it always did
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "manufacturer,expected",
    [
        ("Dell", "AW3423DW"),
        ("DEL", "AW3423DW"),
        ("Samsung", "G85SB"),
        ("MSI", "MEG342C"),
        ("Corsair", "XENEON34"),
    ],
)
def test_a_known_manufacturer_at_that_mode_still_identifies_its_own_panel(manufacturer, expected):
    """The manufacturer is what separated these four panels all along."""
    display = _display(manufacturer=manufacturer)

    assert detection.identify_display(display) == expected


def test_the_fingerprint_still_carries_the_manufacturer_when_there_is_one():
    """The lookup key is unchanged for a display that has an EDID vendor."""
    assert detection.get_display_fingerprint(_display(manufacturer="Dell")) == ("3440x1440@175_Dell")


def test_the_fingerprint_falls_back_to_the_mode_when_there_is_no_manufacturer():
    """The bare form is still built. It just no longer matches anything."""
    fingerprint = detection.get_display_fingerprint(_display())

    assert fingerprint == "3440x1440@175"
    assert fingerprint not in detection.DISPLAY_FINGERPRINTS


# ---------------------------------------------------------------------------
# What the guessed identity used to put on the display record
# ---------------------------------------------------------------------------


def test_an_unidentified_display_reports_no_panel_measurements(monkeypatch):
    """The panel's gamma and peak brightness are not copied onto an unknown display."""
    monkeypatch.setattr(detection, "detect_connection_type", lambda device_id: "Unknown")

    display = detection.enrich_display_info(_display())

    assert display.panel_database_key == ""
    assert display.max_luminance == 0.0
    assert display.native_gamma != AW3423DW_GAMMA


def test_an_identified_display_still_carries_its_panel_data(monkeypatch):
    """The enrichment path is intact for a display the manufacturer identifies."""
    monkeypatch.setattr(detection, "detect_connection_type", lambda device_id: "Unknown")

    display = detection.enrich_display_info(_display(manufacturer="Dell"))

    assert display.panel_database_key == "AW3423DW"
    assert display.max_luminance == AW3423DW_PEAK
    assert display.native_gamma == AW3423DW_GAMMA


def test_the_manufacturer_guard_holds_on_its_own(monkeypatch):
    """The empty table and the guard are independent defenses.

    Either one alone refuses the bare lookup, so a test that only checks the
    table would pass with the guard deleted. This drives the guard against a
    bare key put back into the table, which is the edit that reintroduces the
    defect on a table maintained by hand.
    """
    monkeypatch.setitem(detection.DISPLAY_FINGERPRINTS, "3440x1440@175", "AW3423DW")

    assert detection.identify_display(_display()) is None
    assert detection.identify_display(_display(manufacturer="Dell")) == "AW3423DW"
