"""Whether the ICC in a bundle describes the display the bundle leaves behind.

A cube and a gamma table are instructions. A profile is a description, and the
description has to match the display that exists once the instructions are
loaded. Everything else in the bundle is checked by driving the panel model
through it. Nothing was checking the profile, and four defects rode that gap
into a shipped artifact.

All four presets emitted byte-identical ICC bytes, because ``create_icc_profile``
took no target and read the white and the tone response off the panel record.
The tone curve was written in the encoding direction, so a colour-managed
application asked for mid grey and was sent 0.0334. The chromatic adaptation
tag and the colorants were both computed from a hardcoded D65 source, which is
invisible on the shipped database because all fifty-nine records are D65
panels. The gamma table inside the profile carried a header declaring 1024
channels, with its table starting two bytes past where the structure puts it,
so a reader following that header found nothing usable.

These tests read the bytes. Every assertion decodes the artifact the way a
colour management module would, rather than asking the generator what it
intended. The reader here is strict on purpose: a header the CMMs would reject
must fail here too, which is what ``test_the_reader_rejects_the_header_that_shipped``
establishes.

What this does not establish: whether the panel record matches the display on
the operator's desk. The sensorless path never claims that, and only an
instrument settles it.
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from calibrate_pro.application.actions import PRESET_TARGETS
from calibrate_pro.application.assets import (
    AssetFormat,
    AssetGenerator,
    AssetRequest,
    GeneratedAssets,
)
from calibrate_pro.panels.database import get_database

#: The Profile Connection Space white every v4 display profile adapts into.
PCS_WHITE_XY = (0.3457, 0.3585)

#: s15Fixed16 resolves to about 1.5e-5, and a chromaticity carries three of
#: those through a matrix inversion. A tenth of the smallest gap between two
#: catalogued white points leaves room for that and still fails a real miss.
CHROMATICITY_TOLERANCE = 1e-3

#: One 16 bit gamma table entry, plus the six decimal places the .cal text
#: carries.
QUANTIZATION_TOLERANCE = 3e-5

#: Small enough to generate every preset twice over in a few seconds, large
#: enough that the neutral axis the gamma table comes from has interior levels.
GRID = 17

#: A panel whose native gamut is the sRGB one, and a panel far outside it. The
#: second is what makes a wrong primary visible: a profile that described the
#: target instead of the panel would report 0.6400 for a display whose red sits
#: at 0.6780.
NARROW = "GENERIC_SRGB"
WIDE = "AW3423DW"


def build(panel_key: str, preset_id: str) -> GeneratedAssets:
    """Generate one bundle carrying both the profile and the gamma table."""
    generator = AssetGenerator(database=get_database())
    return generator.generate(
        AssetRequest(
            display_id="test-display",
            panel_key=panel_key,
            preset_id=preset_id,
            formats=(AssetFormat.ICC,),
            lut_size=GRID,
        )
    )


def read_tags(raw: bytes) -> dict[str, bytes]:
    """Split an ICC profile into its tags, by its own tag table."""
    count = struct.unpack(">I", raw[128:132])[0]
    tags: dict[str, bytes] = {}
    for index in range(count):
        signature, offset, size = struct.unpack(">4sII", raw[132 + index * 12 : 144 + index * 12])
        tags[signature.decode("ascii")] = raw[offset : offset + size]
    return tags


def read_s15f16(raw: bytes) -> float:
    return struct.unpack(">i", raw)[0] / 65536.0


def read_xyz(tag: bytes) -> np.ndarray:
    """Decode an XYZType tag into tristimulus values."""
    assert tag[:4] == b"XYZ ", tag[:4]
    return np.array([read_s15f16(tag[8 + 4 * i : 12 + 4 * i]) for i in range(3)])


def read_chad(tag: bytes) -> np.ndarray:
    """Decode the chromatic adaptation tag into its 3x3 matrix."""
    assert tag[:4] == b"sf32", tag[:4]
    return np.array([read_s15f16(tag[8 + 4 * i : 12 + 4 * i]) for i in range(9)]).reshape(3, 3)


def read_trc(tag: bytes) -> np.ndarray:
    """Decode a curveType tag into its sampled table on [0, 1]."""
    assert tag[:4] == b"curv", tag[:4]
    count = struct.unpack(">I", tag[8:12])[0]
    if count == 0:
        return np.linspace(0.0, 1.0, 1024)
    if count == 1:
        exponent = struct.unpack(">H", tag[12:14])[0] / 256.0
        return np.power(np.linspace(0.0, 1.0, 1024), exponent)
    return np.frombuffer(tag[12 : 12 + 2 * count], dtype=">u2").astype(np.float64) / 65535.0


def read_vcgt(tag: bytes) -> np.ndarray:
    """Decode the video card gamma table the way a colour management module does.

    Deliberately strict. The header shape is the whole point of the check, so a
    tag that does not declare three channels of two byte entries raises rather
    than being coerced into something plottable.
    """
    assert tag[:4] == b"vcgt", tag[:4]
    kind = struct.unpack(">I", tag[8:12])[0]
    if kind != 0:
        raise ValueError(f"expected a table, found gamma type {kind}")
    channels, entries, entry_bytes = struct.unpack(">HHH", tag[12:18])
    if channels != 3:
        raise ValueError(f"a display gamma table has three channels, this one declares {channels}")
    if entry_bytes != 2:
        raise ValueError(f"expected two byte entries, this one declares {entry_bytes}")
    body = tag[18 : 18 + channels * entries * entry_bytes]
    if len(body) != channels * entries * entry_bytes:
        raise ValueError("the table is shorter than its header says")
    return np.frombuffer(body, dtype=">u2").astype(np.float64).reshape(channels, entries) / 65535.0


def read_description(tag: bytes) -> str:
    """Decode the mluc description tag's first record."""
    assert tag[:4] == b"mluc", tag[:4]
    length, offset = struct.unpack(">II", tag[20:28])
    return tag[offset : offset + length].decode("utf-16-be").lstrip("\ufeff")


def chromaticity(xyz: np.ndarray) -> tuple[float, float]:
    total = float(xyz.sum())
    return (float(xyz[0]) / total, float(xyz[1]) / total)


def declared_space(tags: dict[str, bytes], tag_name: str) -> np.ndarray:
    """Undo the profile's own adaptation, recovering what it says it measured.

    A v4 display profile stores everything adapted into the PCS and carries the
    matrix it used. Inverting that matrix is how a reader recovers the display
    the profile is describing, so it is how these tests read the claim back.
    """
    return np.linalg.inv(read_chad(tags["chad"])) @ read_xyz(tags[tag_name])


def profile_tags(panel_key: str, preset_id: str) -> dict[str, bytes]:
    return read_tags(build(panel_key, preset_id).assets[AssetFormat.ICC])


def cal_columns(payload: bytes) -> np.ndarray:
    """Parse the .cal the bundle ships into a 3 by N array of R, G, B."""
    rows = []
    reading = False
    for line in payload.decode("ascii").splitlines():
        if line.strip() == "BEGIN_DATA":
            reading = True
            continue
        if line.strip() == "END_DATA":
            break
        if reading and line.strip():
            rows.append([float(value) for value in line.split()])
    table = np.array(rows)
    return table[:, 1:4].T


class TestWhatTheProfileSaysTheToneResponseIs:
    """The tone curve has one legal direction and one legal exponent."""

    @pytest.mark.parametrize("preset_id", sorted(PRESET_TARGETS))
    def test_the_curve_runs_device_to_linear(self, preset_id: str) -> None:
        """A TRC maps device code to light, so it falls below the diagonal.

        The shipped curve was ``x ** (1 / panel_gamma)``, which is the encoding
        direction and sits above the diagonal everywhere. Half of the input
        range is enough to separate the two: at 0.25 a 2.2 curve reads 0.047
        and its inverse reads 0.53.
        """
        tags = profile_tags(NARROW, preset_id)
        curve = read_trc(tags["rTRC"])
        samples = np.linspace(0.05, 0.95, 19)
        values = np.interp(samples, np.linspace(0.0, 1.0, len(curve)), curve)
        assert np.all(values < samples), "the tone curve is inverted; it encodes instead of decoding"

    @pytest.mark.parametrize("preset_id", sorted(PRESET_TARGETS))
    def test_the_curve_is_the_exponent_the_bundle_declares(self, preset_id: str) -> None:
        """Fitting the stored table has to return the manifest's exponent."""
        bundle = build(NARROW, preset_id)
        curve = read_trc(read_tags(bundle.assets[AssetFormat.ICC])["rTRC"])
        x = np.linspace(0.0, 1.0, len(curve))
        interior = (x > 0.05) & (x < 1.0)
        fitted = np.polyfit(np.log(x[interior]), np.log(np.clip(curve[interior], 1e-12, None)), 1)[0]
        assert fitted == pytest.approx(bundle.applied_gamma_exponent, abs=0.01)

    def test_all_three_channels_carry_the_same_curve(self) -> None:
        """Nothing in the sensorless path justifies a per-channel difference."""
        tags = profile_tags(WIDE, "calibration.preset.srgb_web")
        red, green, blue = (read_trc(tags[name]) for name in ("rTRC", "gTRC", "bTRC"))
        assert np.array_equal(red, green)
        assert np.array_equal(red, blue)


class TestWhatTheProfileSaysTheWhiteIs:
    """The white a profile claims has to be the white the bundle drives to."""

    @pytest.mark.parametrize("preset_id", sorted(PRESET_TARGETS))
    def test_the_colorants_sum_to_the_connection_space_white(self, preset_id: str) -> None:
        """A reader that adds the three colorants is reading the PCS white.

        This is what makes the profile self consistent. It held before the fix
        too, because the colorants were normalized to a white and adapted from
        the same one. What it did not hold to was the white the bundle declared.
        """
        tags = profile_tags(WIDE, preset_id)
        total = sum(read_xyz(tags[name]) for name in ("rXYZ", "gXYZ", "bXYZ"))
        assert chromaticity(total) == pytest.approx(PCS_WHITE_XY, abs=CHROMATICITY_TOLERANCE)

    @pytest.mark.parametrize("preset_id", sorted(PRESET_TARGETS))
    @pytest.mark.parametrize("panel_key", [NARROW, WIDE])
    def test_undoing_the_adaptation_returns_the_declared_white(self, panel_key: str, preset_id: str) -> None:
        """The adaptation tag has to encode the declared white, not a constant.

        Both the tag and the colorants were computed from a hardcoded D65
        source. On this database that is the identity, because every record is
        a D65 panel, so the photography preset shipped a profile whose numbers
        described a D65 display while its manifest said D50.
        """
        bundle = build(panel_key, preset_id)
        tags = read_tags(bundle.assets[AssetFormat.ICC])
        colorant_sum = sum(declared_space(tags, name) for name in ("rXYZ", "gXYZ", "bXYZ"))
        expected = {"D65": (0.3127, 0.3290), "D50": (0.3457, 0.3585)}[bundle.white_point]
        assert chromaticity(colorant_sum) == pytest.approx(expected, abs=CHROMATICITY_TOLERANCE)

    def test_the_media_white_point_tag_is_the_connection_space_white(self) -> None:
        """A v4 display profile stores wtpt already adapted, so it reads D50."""
        tags = profile_tags(WIDE, "calibration.preset.photography")
        assert chromaticity(read_xyz(tags["wtpt"])) == pytest.approx(PCS_WHITE_XY, abs=CHROMATICITY_TOLERANCE)


class TestWhatTheProfileSaysTheGamutIs:
    """The primaries stay the panel's own, because the apply cannot move them."""

    @pytest.mark.parametrize("panel_key", [NARROW, WIDE])
    @pytest.mark.parametrize("channel", ["r", "g", "b"])
    def test_the_colorant_is_the_panel_primary(self, panel_key: str, channel: str) -> None:
        """What the graphics card loads is a per-channel curve.

        No per-channel curve moves a primary, so after an apply the display
        still has the chromaticities the panel record lists. A profile naming
        the target's primaries instead would tell a colour-managed application
        that a P3 panel is already sRGB, and the application would send it
        sRGB numbers with nothing left to correct them.
        """
        panel = get_database().get_panel(panel_key)
        tags = profile_tags(panel_key, "calibration.preset.srgb_web")
        recovered = chromaticity(declared_space(tags, f"{channel}XYZ"))
        native = getattr(panel.native_primaries, {"r": "red", "g": "green", "b": "blue"}[channel])
        assert recovered == pytest.approx(native.as_tuple(), abs=CHROMATICITY_TOLERANCE)

    def test_a_wide_panel_does_not_report_the_narrow_target(self) -> None:
        """The control the previous test needs: the two gamuts really differ."""
        narrow = chromaticity(declared_space(profile_tags(NARROW, "calibration.preset.srgb_web"), "rXYZ"))
        wide = chromaticity(declared_space(profile_tags(WIDE, "calibration.preset.srgb_web"), "rXYZ"))
        assert abs(narrow[0] - wide[0]) > 10 * CHROMATICITY_TOLERANCE


class TestTheGammaTableInsideTheProfile:
    """The profile's table and the .cal beside it are one calibration."""

    def test_the_header_is_the_one_a_colour_management_module_reads(self) -> None:
        """Three channels, and an entry width counted in bytes.

        The shipped header packed four fields holding the entry count three
        times and then the number 16. A reader took that as 1024 channels of
        1024 byte entries and started the table two bytes late.
        """
        tag = profile_tags(WIDE, "calibration.preset.srgb_web")["vcgt"]
        channels, entries, entry_bytes = struct.unpack(">HHH", tag[12:18])
        assert (channels, entry_bytes) == (3, 2)
        assert entries == 1024
        assert len(tag) >= 18 + channels * entries * entry_bytes

    def test_the_reader_rejects_the_header_that_shipped(self) -> None:
        """A false success control: this reader can actually fail.

        Rebuild the pre-fix header over a valid body. If the strictness above
        were decorative, this would parse and every check in this class would
        pass on a tag no colour management module can use.
        """
        tag = profile_tags(WIDE, "calibration.preset.srgb_web")["vcgt"]
        broken = tag[:12] + struct.pack(">HHHH", 1024, 1024, 1024, 16) + tag[18:]
        with pytest.raises(ValueError, match="three channels"):
            read_vcgt(broken)

    @pytest.mark.parametrize("preset_id", sorted(PRESET_TARGETS))
    def test_the_profile_table_matches_the_cal_the_bundle_ships(self, preset_id: str) -> None:
        """Two artifacts, one curve.

        Both come from the neutral axis of the same cube. Shipping a profile
        whose embedded table disagrees with the .cal would leave the display in
        one state and describe it in another, depending on which file the
        operator loaded.
        """
        bundle = build(WIDE, preset_id)
        embedded = read_vcgt(read_tags(bundle.assets[AssetFormat.ICC])["vcgt"])
        exported = cal_columns(bundle.gamma_table)
        assert embedded.shape == exported.shape
        assert np.allclose(embedded, exported, atol=QUANTIZATION_TOLERANCE)

    def test_the_table_is_stored_one_channel_after_another(self) -> None:
        """Planar, not interleaved.

        Read interleaved, a monotone ramp becomes three copies of a sawtooth,
        which is what the second writer in this repo produced. Each decoded
        channel rising from near zero to near one is what rules that out.
        """
        table = read_vcgt(profile_tags(WIDE, "calibration.preset.srgb_web")["vcgt"])
        for channel in table:
            assert np.all(np.diff(channel) >= -QUANTIZATION_TOLERANCE)
            assert channel[0] < 0.01
            assert channel[-1] > 0.99


class TestEveryPresetShipsItsOwnProfile:
    """Four targets, four descriptions, and no two identical files."""

    @pytest.mark.parametrize("panel_key", [NARROW, WIDE])
    def test_no_two_presets_emit_the_same_bytes(self, panel_key: str) -> None:
        """The defect that started this: one profile served all four presets."""
        emitted = {preset: build(panel_key, preset).assets[AssetFormat.ICC] for preset in PRESET_TARGETS}
        assert len(set(emitted.values())) == len(PRESET_TARGETS)

    @pytest.mark.parametrize("preset_id", sorted(PRESET_TARGETS))
    def test_the_description_names_the_display_and_the_target(self, preset_id: str) -> None:
        """Windows lists profiles by this string, and four of them install."""
        bundle = build(WIDE, preset_id)
        description = read_description(read_tags(bundle.assets[AssetFormat.ICC])["desc"])
        assert bundle.panel_name in description
        assert PRESET_TARGETS[preset_id][0] in description
        assert bundle.white_point in description
        assert bundle.tone_response in description
