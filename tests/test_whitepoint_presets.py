"""A white point preset answers with its own illuminant, or it refuses.

The module these cover shipped three presets that answered with D65. Their enum
values are the strings a menu shows ("Illuminant A"), the two lookup tables are
keyed by the illuminant's short name ("A"), and the lookup read the value
against the tables. It missed on all three and fell through to a daylight
default, so the catalogue published tungsten as 6505 K and handed out D65's
chromaticity for it.

Nothing had ever imported this module in a test, which is the whole reason a
wrong number reached two shipping surfaces. The controls below are written
against the specific failure, because a test that only checks D65 passes on
exactly the build that was broken.
"""

from __future__ import annotations

import argparse

import pytest

from calibrate_pro.commands.list_targets import list_targets
from calibrate_pro.targets.whitepoint import (
    ILLUMINANT_CCT,
    ILLUMINANT_KEY,
    ILLUMINANT_XY,
    WhitepointPreset,
    WhitepointTarget,
)

D65_XY = ILLUMINANT_XY["D65"]

#: The presets that name a fixed illuminant, with the values a reference table
#: gives for each. Written out rather than read from the tables under test, so
#: the assertion has an independent source and a corrupted table cannot satisfy
#: itself.
EXPECTED = [
    (WhitepointPreset.D50, 5003, (0.34567, 0.35850)),
    (WhitepointPreset.D55, 5503, (0.33242, 0.34743)),
    (WhitepointPreset.D60, 6000, (0.32168, 0.33767)),
    (WhitepointPreset.D65, 6504, (0.31270, 0.32900)),
    (WhitepointPreset.D75, 7504, (0.29902, 0.31485)),
    (WhitepointPreset.D93, 9305, (0.28315, 0.29711)),
    (WhitepointPreset.DCI, 6300, (0.31400, 0.35100)),
    (WhitepointPreset.ACES, 6000, (0.32168, 0.33767)),
    (WhitepointPreset.A, 2856, (0.44757, 0.40745)),
    (WhitepointPreset.B, 4874, (0.34842, 0.35161)),
    (WhitepointPreset.C, 6774, (0.31006, 0.31616)),
]

NO_FIXED_WHITE = [
    WhitepointPreset.NATIVE,
    WhitepointPreset.CUSTOM_CCT,
    WhitepointPreset.CUSTOM_XY,
]


@pytest.mark.parametrize(("preset", "cct", "xy"), EXPECTED, ids=lambda value: getattr(value, "name", ""))
def test_preset_resolves_to_its_own_illuminant(preset: WhitepointPreset, cct: int, xy: tuple[float, float]) -> None:
    target = WhitepointTarget(preset=preset)
    assert target.get_cct() == pytest.approx(cct, abs=1)
    assert target.get_xy() == pytest.approx(xy, abs=1e-5)


def test_illuminant_a_is_tungsten_and_not_daylight() -> None:
    """The defect itself, named.

    A build resolving the preset by its enum value returns 6505 K here, because
    the miss falls through to D65 and the CCT is then computed back out of D65's
    chromaticity. Both halves are asserted: the right number, and specifically
    not the wrong one that shipped.
    """
    target = WhitepointTarget(preset=WhitepointPreset.A)
    assert target.get_cct() == pytest.approx(2856, abs=1)
    assert target.get_cct() != pytest.approx(6505, abs=2)
    assert target.get_xy() == pytest.approx((0.44757, 0.40745), abs=1e-5)
    assert target.get_xy() != pytest.approx(D65_XY, abs=1e-4)


@pytest.mark.parametrize("preset", [WhitepointPreset.A, WhitepointPreset.B, WhitepointPreset.C])
def test_preset_whose_value_is_not_its_table_key_still_resolves(preset: WhitepointPreset) -> None:
    """The three presets the lookup missed on.

    Control: this fails on any build that indexes the tables with
    ``preset.value``, because none of these three values is a table key. It is
    separate from the parametrized sweep above so the reason they are special
    survives in the test name.
    """
    assert preset.value not in ILLUMINANT_XY
    assert preset.value not in ILLUMINANT_CCT
    target = WhitepointTarget(preset=preset)
    assert target.get_xy() != pytest.approx(D65_XY, abs=1e-4)


def test_no_preset_but_d65_answers_with_d65s_chromaticity() -> None:
    """Control against a silent default returning.

    A fallback that answers D65 for anything it cannot resolve passes every
    D65 test in this file and fails this one. It is the shape of the original
    defect rather than its specific values, so it catches a reintroduction that
    picks a different preset to break.
    """
    for preset, _cct, _xy in EXPECTED:
        resolved = WhitepointTarget(preset=preset).get_xy()
        if preset is WhitepointPreset.D65:
            assert resolved == pytest.approx(D65_XY, abs=1e-6)
        else:
            assert resolved != pytest.approx(D65_XY, abs=1e-4), f"{preset.name} answered with D65"


@pytest.mark.parametrize("preset", NO_FIXED_WHITE, ids=lambda value: value.name)
def test_preset_naming_no_fixed_white_refuses(preset: WhitepointPreset) -> None:
    """Native and the custom presets have no white of their own to give."""
    target = WhitepointTarget(preset=preset)
    with pytest.raises(ValueError, match="no chromaticity of its own"):
        target.get_xy()


@pytest.mark.parametrize("preset", NO_FIXED_WHITE, ids=lambda value: value.name)
def test_explicit_values_outrank_a_preset_with_no_white(preset: WhitepointPreset) -> None:
    """The refusal is about missing data, not about the preset."""
    assert WhitepointTarget(preset=preset, xy=(0.30, 0.31)).get_xy() == pytest.approx((0.30, 0.31))
    assert WhitepointTarget(preset=preset, cct=5000.0).get_cct() == pytest.approx(5000.0)


def test_explicit_xy_outranks_the_preset() -> None:
    target = WhitepointTarget(preset=WhitepointPreset.D65, xy=(0.40, 0.41))
    assert target.get_xy() == pytest.approx((0.40, 0.41))


def test_explicit_cct_outranks_the_preset() -> None:
    target = WhitepointTarget(preset=WhitepointPreset.D65, cct=5000.0)
    assert target.get_cct() == pytest.approx(5000.0)
    assert target.get_xy() != pytest.approx(D65_XY, abs=1e-4)


def test_duv_offsets_around_the_presets_own_temperature() -> None:
    """A Duv on Illuminant A must bend around 2856 K, not around D65.

    Control: the old code guarded the offset behind the same failing membership
    test, so a build with the original bug applies no offset here at all and the
    two chromaticities come back equal.
    """
    plain = WhitepointTarget(preset=WhitepointPreset.A).get_xy()
    offset = WhitepointTarget(preset=WhitepointPreset.A, duv=0.003).get_xy()
    assert offset != pytest.approx(plain, abs=1e-6)
    assert offset != pytest.approx(D65_XY, abs=1e-4)


def test_every_mapped_preset_carries_both_table_rows() -> None:
    """The import-time guard, asserted rather than trusted.

    A preset added to the map without a row in both tables raises at import, so
    this documents the invariant the module builds on and fails loudly if the
    guard is ever removed.
    """
    assert ILLUMINANT_KEY, "the map is built at import and cannot be empty"
    for preset, key in ILLUMINANT_KEY.items():
        assert key in ILLUMINANT_XY, f"{preset.name} maps to {key!r}, absent from ILLUMINANT_XY"
        assert key in ILLUMINANT_CCT, f"{preset.name} maps to {key!r}, absent from ILLUMINANT_CCT"


def test_no_preset_naming_a_fixed_white_is_missing_from_the_map() -> None:
    """A new illuminant preset has to be mapped, not left to a default."""
    unmapped = set(WhitepointPreset) - set(ILLUMINANT_KEY) - set(NO_FIXED_WHITE)
    assert not unmapped, f"these presets resolve to nothing: {sorted(p.name for p in unmapped)}"


def test_the_catalogue_publishes_tungsten_as_tungsten(capsys: pytest.CaptureFixture[str]) -> None:
    """The shipping surface the wrong number reached.

    ``list-targets`` prints the white point reference block, and the MCP server
    reports the same figure as structured data. This asserts on the rendered
    line, so a regression in either the table or the printer is caught where an
    operator would actually read it.
    """
    assert list_targets(argparse.Namespace()) == 0
    printed = capsys.readouterr().out
    assert "Illuminant A" in printed
    line = next(row for row in printed.splitlines() if "Illuminant A" in row)
    assert "2856K" in line
    assert "6505K" not in line
