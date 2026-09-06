"""The EDID reading path, from stored registry bytes to a declared offer.

Four pieces are pinned here, in the order the bytes travel.

``edid_registry_lookup`` splits a PnP device id into the hardware key that
holds a model and the instance that holds one attached unit. Windows writes
the same display two ways and both reach this function. The interface form
``\\\\?\\DISPLAY#SPT0C98#5&5ebaf23&0&UID4352#{guid}`` used to answer None,
which meant no EDID was read at all for a display Windows had recorded, and
the desktop kept showing "Generic PnP Monitor" while the bytes sat in the
registry. The instance half matters as much as the hardware half: two units of
one model sit under a single hardware key, so reading whichever instance the
registry lists first answers for a display that is not the one asked about.

``parse_edid_chromaticity`` decodes eight ten-bit fractions of 1024 out of
bytes 25 through 34. Every value it produces is an exact binary fraction, so
the assertions here compare without a tolerance. A block that names no gamut,
puts a corner outside the chromaticity diagram, or collapses the three
primaries onto a line is refused rather than repaired.

``characterization_from_edid`` turns one parsed descriptor into an offer or
says which part was missing. Three things stop an offer and each is checked.

``DisplayDetector`` carries the offer beside the panel match and records one
evidence line for it, between the panel line and the HDR line.

No test here touches hardware. The registry is a fake object injected where
the production code already takes ``winreg`` as a parameter, the EDID bytes
are synthetic, and no display is enumerated, no LUT loaded, and no DDC/CI
value written.
"""

from __future__ import annotations

import struct
from datetime import datetime, timezone

import pytest

from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.detection import DisplayDetector, characterization_from_edid
from calibrate_pro.panels import detection as panel_detection
from calibrate_pro.panels.database import PanelDatabase
from calibrate_pro.panels.detection import (
    EDID_ENUM_PATH,
    DisplayInfo,
    _read_edid_value,
    _search_edid_value,
    edid_registry_lookup,
    get_edid_from_registry,
    parse_edid,
    parse_edid_chromaticity,
)

# =============================================================================
# Synthetic EDID blocks
# =============================================================================

EDID_HEADER = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])

#: Ten-bit codes for a wide gamut panel. Each divides by 1024, so the decoded
#: value is an exact binary fraction and comparisons need no tolerance.
WIDE_GAMUT_CODES = {
    "red": (696, 327),
    "green": (271, 707),
    "blue": (154, 61),
    "white": (320, 337),
}

WIDE_GAMUT_XY = {
    "red": (0.6796875, 0.3193359375),
    "green": (0.2646484375, 0.6904296875),
    "blue": (0.150390625, 0.0595703125),
    "white": (0.3125, 0.3291015625),
}

#: Three primaries on one point. Twice the triangle area is zero, which is
#: below the floor the production module admits.
COLLAPSED_CODES = {
    "red": (307, 307),
    "green": (307, 307),
    "blue": (307, 307),
    "white": (320, 337),
}

#: A red corner whose x plus y exceeds one, which is outside the diagram.
OFF_DIAGRAM_CODES = {
    "red": (700, 400),
    "green": (271, 707),
    "blue": (154, 61),
    "white": (320, 337),
}

#: A white point sitting on y equals zero, which no display emits.
ZERO_CORNER_CODES = {
    "red": (696, 327),
    "green": (271, 707),
    "blue": (154, 61),
    "white": (320, 0),
}

#: One corner at a time is moved to these codes, which shift both the high
#: byte and the two packed low bits while leaving a gamut large enough to be
#: admitted, so the isolation check below is about layout and not about area.
MOVED_CODES = {
    "red": (693, 318),
    "green": (266, 698),
    "blue": (149, 54),
    "white": (317, 330),
}

MOVED_XY = {
    "red": (0.6767578125, 0.310546875),
    "green": (0.259765625, 0.681640625),
    "blue": (0.1455078125, 0.052734375),
    "white": (0.3095703125, 0.322265625),
}

MONITOR_NAME_TEXT = b"TEST PANEL\x0a\x20\x20"
SERIAL_TEXT = b"SN12345678\x0a\x20\x20"
SERIAL_NUMBER = 0xDEADBEEF


def _write_chromaticity(raw: bytearray, codes: dict[str, tuple[int, int]]) -> None:
    """Pack eight ten-bit codes into EDID bytes 25 through 34.

    The byte positions are spelled out here rather than imported from the
    production layout table, so a change to that table shows up as a failure
    instead of being followed silently by the test.
    """
    red_x, red_y = codes["red"]
    green_x, green_y = codes["green"]
    blue_x, blue_y = codes["blue"]
    white_x, white_y = codes["white"]
    raw[25] = ((red_x & 3) << 6) | ((red_y & 3) << 4) | ((green_x & 3) << 2) | (green_y & 3)
    raw[26] = ((blue_x & 3) << 6) | ((blue_y & 3) << 4) | ((white_x & 3) << 2) | (white_y & 3)
    high_order = (red_x, red_y, green_x, green_y, blue_x, blue_y, white_x, white_y)
    for offset, code in zip(range(27, 35), high_order):
        raw[offset] = code >> 2


def make_edid(
    *,
    codes: dict[str, tuple[int, int]] | None = None,
    gamma_byte: int = 120,
    feature_byte: int = 0x00,
    monitor_name: bytes | None = MONITOR_NAME_TEXT,
    serial_string: bytes | None = SERIAL_TEXT,
    header: bytes = EDID_HEADER,
) -> bytes:
    """Build one 128 byte EDID block with the fields these tests read.

    ``codes`` left at None writes the ten chromaticity bytes as zeros, which
    is an EDID that declared no primaries.
    """
    raw = bytearray(128)
    raw[0:8] = header
    raw[8] = 0x4C  # manufacturer id "SAM"
    raw[9] = 0x2D
    raw[10] = 0x34  # product code 0x1234, little endian
    raw[11] = 0x12
    raw[12:16] = struct.pack("<I", SERIAL_NUMBER)
    raw[16] = 5  # week
    raw[17] = 34  # year 2024
    raw[18] = 1  # EDID 1.4
    raw[19] = 4
    raw[21] = 60  # 60 cm horizontal
    raw[22] = 34  # 34 cm vertical
    raw[23] = gamma_byte
    raw[24] = feature_byte
    if codes is not None:
        _write_chromaticity(raw, codes)
    if monitor_name is not None:
        raw[54:57] = b"\x00\x00\x00"
        raw[57] = 0xFC
        raw[58] = 0x00
        raw[59:72] = monitor_name
    if serial_string is not None:
        raw[72:75] = b"\x00\x00\x00"
        raw[75] = 0xFF
        raw[76] = 0x00
        raw[77:90] = serial_string
    return bytes(raw)


EDID_WIDE_GAMUT = make_edid(codes=WIDE_GAMUT_CODES)
EDID_SRGB_FLAGGED = make_edid(codes=WIDE_GAMUT_CODES, feature_byte=0x04)
EDID_NO_CHROMATICITY = make_edid(codes=None)
EDID_NO_GAMMA = make_edid(codes=WIDE_GAMUT_CODES, gamma_byte=0xFF)

# =============================================================================
# Fake registry
# =============================================================================

HARDWARE_ID = "SPT0C98"
INSTANCE_ID = "5&5ebaf23&0&UID4352"
SIBLING_INSTANCE_ID = "4&1a2b3c4d&0&UID4353"
DEVICE_PATH_INTERFACE = f"\\\\?\\DISPLAY#{HARDWARE_ID}#{INSTANCE_ID}#{{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}}"
DEVICE_PATH_LEGACY = f"MONITOR\\{HARDWARE_ID}\\{{4d36e96e-e325-11ce-bfc1-08002be10318}}\\0002"

#: A second block, different in one chromaticity code, so a read that answered
#: from the wrong instance is visible in the decoded numbers.
SIBLING_CODES = dict(WIDE_GAMUT_CODES, red=(655, 338))
EDID_SIBLING = make_edid(codes=SIBLING_CODES)


def hardware_path(hardware_id: str = HARDWARE_ID) -> str:
    return f"{EDID_ENUM_PATH}\\{hardware_id}"


def params_path(instance_id: str, hardware_id: str = HARDWARE_ID) -> str:
    return f"{EDID_ENUM_PATH}\\{hardware_id}\\{instance_id}\\Device Parameters"


class _FakeKey:
    """One open registry key, which knows only its own path."""

    def __init__(self, path: str) -> None:
        self.path = path

    def __enter__(self) -> _FakeKey:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False


class FakeRegistry:
    """Enough of winreg to answer the EDID reads, with nothing that writes.

    The production helpers take the module as a parameter, so this is injected
    rather than patched over the real one. Only reads exist here: there is no
    SetValueEx, no CreateKey and no DeleteKey to call by accident.
    """

    HKEY_LOCAL_MACHINE = "HKEY_LOCAL_MACHINE"

    def __init__(
        self,
        *,
        values: dict[str, bytes] | None = None,
        subkeys: dict[str, list[str]] | None = None,
    ) -> None:
        self.values = dict(values or {})
        self.subkeys = dict(subkeys or {})
        self.opened: list[str] = []

    def OpenKey(self, hive: str, path: str) -> _FakeKey:  # noqa: N802
        if hive != self.HKEY_LOCAL_MACHINE:
            raise OSError(2, "only HKEY_LOCAL_MACHINE is stubbed")
        if path not in self.values and path not in self.subkeys:
            raise OSError(2, f"no such key: {path}")
        self.opened.append(path)
        return _FakeKey(path)

    def QueryValueEx(self, key: _FakeKey, name: str) -> tuple[bytes, int]:  # noqa: N802
        if name != "EDID":
            raise OSError(2, f"no such value: {name}")
        if key.path not in self.values:
            raise OSError(2, f"key carries no EDID: {key.path}")
        return self.values[key.path], 3

    def EnumKey(self, key: _FakeKey, index: int) -> str:  # noqa: N802
        names = self.subkeys.get(key.path, [])
        if index >= len(names):
            raise OSError(259, "no more data")
        return names[index]


def two_instance_registry() -> FakeRegistry:
    """One hardware key holding two attached units, the sibling listed first."""
    return FakeRegistry(
        values={
            params_path(SIBLING_INSTANCE_ID): EDID_SIBLING,
            params_path(INSTANCE_ID): EDID_WIDE_GAMUT,
        },
        subkeys={hardware_path(): [SIBLING_INSTANCE_ID, INSTANCE_ID]},
    )


# =============================================================================
# Display detector fixtures
# =============================================================================

DISPLAY_ONE = "\\\\.\\DISPLAY1"
UNMATCHED_MODEL = "NoSuchPanel9000"
FIXED_MOMENT = datetime(2026, 9, 6, 12, 0, 0, tzinfo=timezone.utc)


def make_display(*, device_name: str = DISPLAY_ONE, device_id: str = DEVICE_PATH_INTERFACE) -> DisplayInfo:
    return DisplayInfo(
        device_name=device_name,
        device_string="Test Adapter",
        monitor_name=UNMATCHED_MODEL,
        device_id=device_id,
        is_primary=True,
        is_active=True,
        width=3840,
        height=2160,
        refresh_rate=240,
        bit_depth=32,
        position_x=0,
        position_y=0,
        manufacturer="Test",
        model=UNMATCHED_MODEL,
        serial="SN-PRIVATE-0002",
    )


def build_detector(displays, **kwargs) -> DisplayDetector:
    kwargs.setdefault("clock", lambda: FIXED_MOMENT)
    kwargs.setdefault("database", PanelDatabase())
    return DisplayDetector(enumerator=lambda: list(displays), **kwargs)


def observe(**kwargs):
    return build_detector([make_display()], **kwargs).detect().dashboard.displays[0]


# =============================================================================
# parse_edid_chromaticity
# =============================================================================


class TestChromaticityDecoding:
    def test_every_corner_decodes_to_its_exact_fraction_of_1024(self):
        """Ten-bit codes over 1024 are exact binary fractions, so no tolerance."""
        points = parse_edid_chromaticity(EDID_WIDE_GAMUT)

        assert points == WIDE_GAMUT_XY

    @pytest.mark.parametrize("corner", ["red", "green", "blue", "white"])
    def test_each_corner_is_read_from_its_own_bytes(self, corner):
        """A layout that crossed two corners would pass the whole-dict check
        only if it crossed them symmetrically. This checks them one at a time
        against a block where that corner alone was moved.
        """
        moved = dict(WIDE_GAMUT_CODES)
        moved[corner] = MOVED_CODES[corner]
        points = parse_edid_chromaticity(make_edid(codes=moved))

        assert points is not None
        assert points[corner] == MOVED_XY[corner]
        for other in ("red", "green", "blue", "white"):
            if other != corner:
                assert points[other] == WIDE_GAMUT_XY[other]

    def test_the_two_low_bits_reach_the_decoded_value(self):
        """Bytes 25 and 26 carry the low bits. Dropping them loses a quarter of
        a thousandth, which this pair of codes makes visible.
        """
        low_bits_set = dict(WIDE_GAMUT_CODES, red=(697, 327))
        points = parse_edid_chromaticity(make_edid(codes=low_bits_set))

        assert points is not None
        assert points["red"] == (0.6806640625, 0.3193359375)

    def test_an_unwritten_block_is_read_as_absent(self):
        assert parse_edid_chromaticity(EDID_NO_CHROMATICITY) is None

    def test_collapsed_primaries_are_refused(self):
        """Three primaries on one point enclose no gamut."""
        assert parse_edid_chromaticity(make_edid(codes=COLLAPSED_CODES)) is None

    def test_a_corner_outside_the_diagram_is_refused(self):
        assert parse_edid_chromaticity(make_edid(codes=OFF_DIAGRAM_CODES)) is None

    def test_a_corner_at_zero_is_refused(self):
        assert parse_edid_chromaticity(make_edid(codes=ZERO_CORNER_CODES)) is None

    def test_a_block_too_short_to_hold_the_bytes_is_refused(self):
        assert parse_edid_chromaticity(EDID_WIDE_GAMUT[:34]) is None

    def test_empty_input_is_refused(self):
        assert parse_edid_chromaticity(b"") is None

    def test_a_declared_gamut_and_a_degenerate_one_do_not_answer_alike(self):
        """FALSE-SUCCESS CONTROL.

        Catches a decoder replaced by a stub that answers the same way every
        time. One that always returns the decoded dict fails the collapsed
        block; one that always returns None fails the wide gamut block. The
        two halves are asserted together so neither can be dropped alone.
        """
        declared = parse_edid_chromaticity(EDID_WIDE_GAMUT)
        degenerate = parse_edid_chromaticity(make_edid(codes=COLLAPSED_CODES))

        assert declared == WIDE_GAMUT_XY
        assert degenerate is None


# =============================================================================
# parse_edid
# =============================================================================


class TestParseEdid:
    def test_chromaticity_is_carried_on_the_result(self):
        assert parse_edid(EDID_WIDE_GAMUT)["chromaticity"] == WIDE_GAMUT_XY

    def test_an_unwritten_block_leaves_chromaticity_none(self):
        assert parse_edid(EDID_NO_CHROMATICITY)["chromaticity"] is None

    def test_the_srgb_flag_is_read_when_bit_0x04_is_set(self):
        assert parse_edid(EDID_SRGB_FLAGGED)["srgb_default"] is True

    def test_the_srgb_flag_is_clear_when_bit_0x04_is_clear(self):
        assert parse_edid(EDID_WIDE_GAMUT)["srgb_default"] is False

    @pytest.mark.parametrize("feature_byte", [0x00, 0x02, 0x08, 0xFB])
    def test_other_feature_bits_do_not_set_the_srgb_flag(self, feature_byte):
        """Byte 24 carries five other flags. Reading the byte as a boolean
        would report sRGB for a display that set standby support or preferred
        timing mode instead.
        """
        assert parse_edid(make_edid(codes=WIDE_GAMUT_CODES, feature_byte=feature_byte))["srgb_default"] is False

    def test_the_srgb_flag_follows_that_one_bit_and_nothing_else(self):
        """FALSE-SUCCESS CONTROL.

        The two blocks differ in exactly one byte, and that byte differs in
        exactly one bit. A reader that returns a constant, reads the wrong
        byte, or reads the wrong bit of byte 24 fails one side of this.
        """
        clear = bytearray(EDID_WIDE_GAMUT)
        flagged = bytearray(EDID_WIDE_GAMUT)
        flagged[24] = clear[24] | 0x04
        assert bytes(flagged)[:24] == bytes(clear)[:24]
        assert bytes(flagged)[25:] == bytes(clear)[25:]

        assert parse_edid(bytes(clear))["srgb_default"] is False
        assert parse_edid(bytes(flagged))["srgb_default"] is True

    def test_the_rest_of_the_block_still_decodes(self):
        """Control for the two fields above: the surrounding parse is intact,
        so a failure there is about the flag and not about the block.
        """
        info = parse_edid(EDID_WIDE_GAMUT)

        assert info["manufacturer_code"] == "SAM"
        assert info["manufacturer"] == "Samsung"
        assert info["product_code"] == 0x1234
        assert info["gamma"] == pytest.approx(2.2)
        assert info["monitor_name"] == "TEST PANEL"
        assert info["year"] == 2024
        assert info["version"] == "1.4"

    def test_a_block_with_a_bad_header_declares_nothing(self):
        broken = make_edid(codes=WIDE_GAMUT_CODES, header=bytes(8))
        info = parse_edid(broken)

        assert info["chromaticity"] is None
        assert info["srgb_default"] is False
        assert info["manufacturer_code"] == ""


# =============================================================================
# edid_registry_lookup and the two readers
# =============================================================================


class TestRegistryLookup:
    def test_an_interface_path_names_the_hardware_key_and_the_instance(self):
        """FALSE-SUCCESS CONTROL.

        This form used to answer None, so no EDID was read for any display
        Windows had recorded under a device interface path. A lookup replaced
        by ``return None`` fails here, and so does one that matches the
        hardware id but drops the instance.
        """
        assert edid_registry_lookup(DEVICE_PATH_INTERFACE) == (HARDWARE_ID, INSTANCE_ID)

    def test_a_lowercase_interface_path_resolves_to_the_uppercase_key(self):
        assert edid_registry_lookup(DEVICE_PATH_INTERFACE.lower()) == (HARDWARE_ID, INSTANCE_ID.lower())

    def test_a_legacy_path_names_the_hardware_key_and_no_instance(self):
        """The class id sitting where the instance would be is not an instance."""
        assert edid_registry_lookup(DEVICE_PATH_LEGACY) == (HARDWARE_ID, None)

    def test_a_path_that_names_no_display_answers_none(self):
        assert edid_registry_lookup("USB\\VID_0765&PID_5020\\0001") is None

    def test_an_empty_device_id_answers_none(self):
        assert edid_registry_lookup("") is None


class TestReadEdidValue:
    def test_the_named_instance_answers_with_its_own_bytes(self):
        registry = two_instance_registry()

        assert _read_edid_value(registry, f"{EDID_ENUM_PATH}\\{HARDWARE_ID}\\{INSTANCE_ID}") == EDID_WIDE_GAMUT

    def test_an_instance_with_no_edid_value_answers_none(self):
        registry = FakeRegistry(subkeys={hardware_path(): [INSTANCE_ID]})

        assert _read_edid_value(registry, f"{EDID_ENUM_PATH}\\{HARDWARE_ID}\\{INSTANCE_ID}") is None

    def test_a_truncated_edid_value_answers_none(self):
        """Under 128 bytes is not an EDID block, and half of one is not read."""
        registry = FakeRegistry(values={params_path(INSTANCE_ID): EDID_WIDE_GAMUT[:64]})

        assert _read_edid_value(registry, f"{EDID_ENUM_PATH}\\{HARDWARE_ID}\\{INSTANCE_ID}") is None

    def test_a_missing_key_answers_none_rather_than_raising(self):
        registry = FakeRegistry()

        assert _read_edid_value(registry, f"{EDID_ENUM_PATH}\\{HARDWARE_ID}\\{INSTANCE_ID}") is None


class TestSearchEdidValue:
    def test_the_first_instance_carrying_an_edid_answers(self):
        registry = two_instance_registry()

        assert _search_edid_value(registry, HARDWARE_ID) == EDID_SIBLING

    def test_an_instance_with_no_edid_is_skipped_rather_than_ending_the_walk(self):
        registry = FakeRegistry(
            values={params_path(INSTANCE_ID): EDID_WIDE_GAMUT},
            subkeys={hardware_path(): [SIBLING_INSTANCE_ID, INSTANCE_ID]},
        )

        assert _search_edid_value(registry, HARDWARE_ID) == EDID_WIDE_GAMUT

    def test_a_hardware_key_with_no_instances_answers_none(self):
        registry = FakeRegistry(subkeys={hardware_path(): []})

        assert _search_edid_value(registry, HARDWARE_ID) is None

    def test_an_absent_hardware_key_answers_none(self):
        assert _search_edid_value(FakeRegistry(), HARDWARE_ID) is None


class TestGetEdidFromRegistry:
    @pytest.fixture
    def on_windows(self, monkeypatch):
        monkeypatch.setattr(panel_detection.sys, "platform", "win32")

    @pytest.fixture
    def registry(self, monkeypatch, on_windows):
        fake = two_instance_registry()
        monkeypatch.setitem(__import__("sys").modules, "winreg", fake)
        return fake

    def test_an_interface_path_reads_the_instance_it_names(self, registry):
        """FALSE-SUCCESS CONTROL, and the most important one in this file.

        Two failures are caught at once. A lookup that answers None for the
        interface form reads no EDID at all, which is the defect that was
        fixed. An implementation that keeps the hardware id but discards the
        instance walks the key and returns the sibling listed first, whose
        red primary differs, so the decoded bytes say which unit answered.
        """
        raw = get_edid_from_registry(DEVICE_PATH_INTERFACE)

        assert raw == EDID_WIDE_GAMUT
        assert raw != EDID_SIBLING
        assert parse_edid_chromaticity(raw)["red"] == WIDE_GAMUT_XY["red"]
        assert registry.opened == [params_path(INSTANCE_ID)]

    def test_a_legacy_path_walks_the_hardware_key(self, registry):
        """No instance was named, so the model is answered for, not the unit."""
        raw = get_edid_from_registry(DEVICE_PATH_LEGACY)

        assert raw == EDID_SIBLING
        assert hardware_path() in registry.opened

    def test_a_device_id_that_names_no_display_answers_none(self, registry):
        assert get_edid_from_registry("USB\\VID_0765&PID_5020\\0001") is None
        assert registry.opened == []

    def test_an_unrecorded_display_answers_none(self, on_windows, monkeypatch):
        monkeypatch.setitem(__import__("sys").modules, "winreg", FakeRegistry())

        assert get_edid_from_registry(DEVICE_PATH_INTERFACE) is None

    def test_no_registry_is_read_off_windows(self, monkeypatch):
        monkeypatch.setattr(panel_detection.sys, "platform", "linux")

        assert get_edid_from_registry(DEVICE_PATH_INTERFACE) is None


# =============================================================================
# characterization_from_edid
# =============================================================================


class TestCharacterizationFromEdid:
    def test_a_complete_descriptor_becomes_a_declared_offer(self):
        declared, evidence = characterization_from_edid(parse_edid(EDID_WIDE_GAMUT))

        assert declared is not None
        assert declared.kind is CharacterizationKind.EDID_DECLARED
        assert declared.provenance == "edid:SAM1234 TEST PANEL"
        assert declared.red_xy == ("0.6797", "0.3193")
        assert declared.green_xy == ("0.2646", "0.6904")
        assert declared.blue_xy == ("0.1504", "0.0596")
        assert declared.white_xy == ("0.3125", "0.3291")
        assert declared.nominal_gamma == "2.2000"
        assert evidence == "edid:declared SAM1234 TEST PANEL"

    def test_the_offer_names_the_model_and_not_the_unit(self):
        """Provenance reaches every surface that prints where numbers came
        from, so the serial number and the serial string stay out of it.
        """
        declared, evidence = characterization_from_edid(parse_edid(EDID_WIDE_GAMUT))

        assert declared is not None
        for private in ("SN12345678", str(SERIAL_NUMBER), f"{SERIAL_NUMBER:X}"):
            assert private not in declared.provenance
            assert private not in evidence

    def test_a_descriptor_with_no_chromaticity_is_refused(self):
        declared, evidence = characterization_from_edid(parse_edid(EDID_NO_CHROMATICITY))

        assert declared is None
        assert evidence == "edid:no-chromaticity (the descriptor declared no primaries)"

    def test_a_descriptor_flagged_srgb_is_refused(self):
        declared, evidence = characterization_from_edid(parse_edid(EDID_SRGB_FLAGGED))

        assert declared is None
        assert evidence == (
            "edid:srgb-default (the descriptor declares the sRGB primaries the generic record already holds)"
        )

    def test_a_descriptor_with_no_gamma_is_refused(self):
        declared, evidence = characterization_from_edid(parse_edid(EDID_NO_GAMMA))

        assert declared is None
        assert evidence == "edid:no-gamma (the descriptor declared no transfer characteristic)"

    def test_the_three_refusals_are_told_apart(self):
        """FALSE-SUCCESS CONTROL.

        Catches a stub that always refuses, one that always offers, and one
        that refuses with a single reason for every cause. The offer and the
        three distinct refusals are asserted in one place so no branch can be
        collapsed into another without failing here.
        """
        answers = [
            characterization_from_edid(parse_edid(block))
            for block in (EDID_WIDE_GAMUT, EDID_NO_CHROMATICITY, EDID_SRGB_FLAGGED, EDID_NO_GAMMA)
        ]
        offers = [declared is not None for declared, _ in answers]
        reasons = [evidence for _, evidence in answers]

        assert offers == [True, False, False, False]
        assert len(set(reasons)) == 4


# =============================================================================
# DisplayDetector
# =============================================================================


class TestDetectorCarriesTheDeclaration:
    def test_the_observation_carries_the_declared_offer(self):
        observation = observe(edid_reader=lambda _display: EDID_WIDE_GAMUT)

        assert observation.edid_characterization is not None
        assert observation.edid_characterization.kind is CharacterizationKind.EDID_DECLARED
        assert observation.edid_characterization.provenance == "edid:SAM1234 TEST PANEL"

    def test_the_declaration_does_not_become_the_characterization(self):
        """A descriptor is a manufacturer's claim about a model. Accepting one
        is an operator decision, so the match stays UNKNOWN beside the offer.
        """
        observation = observe(edid_reader=lambda _display: EDID_WIDE_GAMUT)

        assert observation.characterization.kind is CharacterizationKind.UNKNOWN
        assert observation.characterization.red_xy is None

    def test_the_reader_is_given_the_display_it_is_asked_about(self):
        seen = []

        def reader(display):
            seen.append(display.device_id)
            return EDID_WIDE_GAMUT

        observe(edid_reader=reader)

        assert seen == [DEVICE_PATH_INTERFACE]

    def test_the_edid_evidence_sits_between_the_panel_and_hdr_lines(self):
        """FALSE-SUCCESS CONTROL.

        The evidence tuple is read in order by the surfaces that print it, so
        position is part of the contract. A build that appended the EDID line
        after the capability lines, dropped it, or emitted it before the panel
        match fails here even though every line is still present.
        """
        observation = observe(edid_reader=lambda _display: EDID_WIDE_GAMUT)
        evidence = observation.evidence

        panel_index = evidence.index("panel-match:none")
        edid_index = evidence.index("edid:declared SAM1234 TEST PANEL")
        hdr_index = evidence.index("hdr:not-queried")

        assert edid_index == panel_index + 1
        assert hdr_index == edid_index + 1
        assert evidence[0] == "enumerator:panels.detection.enumerate_displays"
        assert evidence[1] == "mode:3840x2160@240Hz"
        assert all(line.startswith("capability:") for line in evidence[hdr_index + 1 :])

    def test_a_reader_that_answers_none_leaves_the_offer_absent(self):
        observation = observe(edid_reader=lambda _display: None)

        assert observation.edid_characterization is None
        assert "edid:absent (the platform stored no descriptor for this display)" in observation.evidence

    def test_an_unwired_reader_says_so_rather_than_claiming_absence(self):
        """Nothing was read, which is a different fact from nothing being there."""
        observation = observe()

        assert observation.edid_characterization is None
        assert "edid:not-read (no descriptor reader was wired for this session)" in observation.evidence

    def test_a_raising_reader_names_the_failure_and_keeps_the_display(self):
        def reader(_display):
            raise OSError("registry hive unavailable")

        observation = observe(edid_reader=reader)

        assert observation.edid_characterization is None
        assert "edid:read-failed (OSError: registry hive unavailable)" in observation.evidence
        assert observation.platform_display_id == DISPLAY_ONE

    def test_a_reader_returning_the_wrong_type_is_reported(self):
        observation = observe(edid_reader=lambda _display: "not bytes")

        assert observation.edid_characterization is None
        assert "edid:reader-returned-unexpected-type" in observation.evidence

    def test_a_refused_descriptor_leaves_the_offer_absent_and_says_why(self):
        observation = observe(edid_reader=lambda _display: EDID_SRGB_FLAGGED)

        assert observation.edid_characterization is None
        assert any(line.startswith("edid:srgb-default") for line in observation.evidence)

    def test_the_offer_and_its_absence_do_not_look_alike(self):
        """FALSE-SUCCESS CONTROL.

        Catches a detector that hardwires ``edid_characterization`` either way.
        One that always sets None fails the first half; one that always builds
        an offer fails the second, where the reader answered nothing at all.
        """
        offered = observe(edid_reader=lambda _display: EDID_WIDE_GAMUT)
        absent = observe(edid_reader=lambda _display: None)

        assert offered.edid_characterization is not None
        assert absent.edid_characterization is None
        assert len(offered.evidence) == len(absent.evidence)
