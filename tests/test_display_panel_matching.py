"""``detect_displays`` matches each display against its own model string.

The lookup was written against one fixed model, so every display a session
detected came back carrying that monitor's characterization: its panel type,
its manufacturer, and, whenever EDID colorimetry was unreadable, its primaries.
A display the database has never heard of reported ``has_panel_profile`` true
along with the rest of it.

EDID is what the database patterns are written against, so EDID is what decides
the match here, and the name the bus reports is the fallback. The case that
matters most is the display nothing matches, because that is where a profile
belonging to another monitor used to become this one's stated characterization.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.windows

#: A model the bundled database knows, and one it does not.
KNOWN_MODEL = "AW3423DW"
UNKNOWN_MODEL = "Contoso ZX9"

#: The model the lookup used to be hardcoded to, and the maker it belongs to.
FORMERLY_HARDCODED_MODEL = "PG27UCDM"
FORMERLY_HARDCODED_MAKER = "ASUS"

#: What the bus reports for all three displays, so only EDID can tell them
#: apart. A real driver hands back exactly this for an unmatched monitor.
BUS_NAME = "Generic PnP Monitor"


def _edid_naming(model: str) -> bytes:
    """Build a 128 byte EDID whose monitor name descriptor carries ``model``."""
    edid = bytearray(128)
    edid[0:8] = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])
    edid[54:59] = bytes([0x00, 0x00, 0x00, 0xFC, 0x00])
    edid[59:72] = model.encode("ascii").ljust(13)[:13]
    return bytes(edid)


#: Index 0 is named only by EDID, index 1 is a display the database does not
#: know, and index 2 has no readable EDID so only the bus name is left.
EDID_BY_INDEX: dict[int, bytes | None] = {
    0: _edid_naming(KNOWN_MODEL),
    1: _edid_naming(UNKNOWN_MODEL),
    2: None,
}
BUS_NAME_BY_INDEX = {0: BUS_NAME, 1: BUS_NAME, 2: KNOWN_MODEL}


class _ThreeAttachedDisplays:
    """Stand in for the DDC/CI controller without touching a bus."""

    available = True

    def enumerate_monitors(self) -> list[dict[str, str]]:
        return [{"name": BUS_NAME_BY_INDEX[i]} for i in sorted(BUS_NAME_BY_INDEX)]


@pytest.fixture
def detected(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Run the detection pass against stubs, so no display is touched."""
    from calibrate_pro.hardware import ddc_ci, sensorless_calibration

    monkeypatch.setattr(ddc_ci, "DDCCIController", _ThreeAttachedDisplays)
    monkeypatch.setattr(sensorless_calibration, "get_edid_from_registry", EDID_BY_INDEX.get)
    # Colorimetry stays unreadable on purpose. That is the branch where a panel
    # profile supplies the primaries, and so the branch where the wrong profile
    # became a statement about this display's colour.
    monkeypatch.setattr(sensorless_calibration, "parse_edid_colorimetry", lambda _edid: None)
    return sensorless_calibration.detect_displays()


def test_a_display_is_matched_by_its_own_edid_rather_than_a_fixed_model(detected: list[Any]) -> None:
    """Two displays the bus names identically resolve to different profiles."""
    matched, unmatched = detected[0], detected[1]

    assert matched.name == unmatched.name == BUS_NAME
    assert matched.has_panel_profile is True
    assert matched.manufacturer == "Dell"
    assert matched.panel_type == "QD-OLED"
    assert unmatched.has_panel_profile is False


def test_an_unknown_display_is_reported_as_unknown(detected: list[Any]) -> None:
    """Nothing matched, so nothing is claimed about the panel or its colour."""
    unmatched = detected[1]

    assert unmatched.panel_type == "Unknown"
    assert unmatched.manufacturer == ""
    assert unmatched.edid_primaries == {}


def test_no_display_inherits_the_model_the_lookup_was_pinned_to(detected: list[Any]) -> None:
    """The regression: none of the three is characterized as the pinned model.

    The database still holds that model, and it is still the right answer for
    the monitor it describes. What must not happen is it answering for a
    display whose EDID and bus name both say otherwise.
    """
    from calibrate_pro.panels.database import get_database

    pinned = get_database().find_panel(FORMERLY_HARDCODED_MODEL)
    assert pinned is not None, "the model the lookup was pinned to is still in the database"
    assert pinned.manufacturer == FORMERLY_HARDCODED_MAKER

    assert [display.manufacturer for display in detected] == ["Dell", "", "Dell"]


def test_the_bus_name_is_used_when_edid_cannot_be_read(detected: list[Any]) -> None:
    """A display with no readable EDID still resolves from what the bus said."""
    from_bus_name = detected[2]

    assert EDID_BY_INDEX[2] is None
    assert from_bus_name.has_panel_profile is True
    assert from_bus_name.manufacturer == "Dell"
