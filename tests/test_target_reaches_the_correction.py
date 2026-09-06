"""Whether the target a bundle is labelled for is the target it corrects for.

Every surface in this product reports the target: the plan prints it, the
manifest records it, the bundle is named after it. None of that is evidence.
The correction is a cube of numbers, and the only way to know which target it
serves is to drive the panel model with it and read the white that comes back.

That check was missing, and the defect it would have caught shipped. The white
point label was unpacked from the preset and never reached the engine, so the
photography preset, whose only difference from the sRGB one is a D50 white,
produced a byte-identical cube on every panel in the database while the
manifest said D50. A declared value was presented as a property of a computed
artifact, which is the one thing PRODUCT.md forbids outright.

What the assertions here establish is bounded. The panel model that decodes
the cube is the same model the correction was built from, so this proves the
arithmetic carries the target end to end. It says nothing about whether the
panel record describes the display on the operator's desk. Only an instrument
establishes that, and the sensorless path never claims it.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from calibrate_pro.application.actions import PRESET_TARGETS
from calibrate_pro.application.assets import _cube_changes_output
from calibrate_pro.application.target_selection import (
    GAMUT_MODES,
    TARGET_WHITES,
    TONE_RESPONSE_EXPONENTS,
    TargetSelectionError,
    compose_target_id,
    resolve_part,
    resolve_target,
)
from calibrate_pro.core.color_math import primaries_to_xyz_matrix
from calibrate_pro.core.lut_engine import LUT3D, headroom_scale
from calibrate_pro.panels.builtin_panels import get_builtin_panels
from calibrate_pro.panels.panel_types import ChromaticityCoord, PanelCharacterization
from calibrate_pro.sensorless.neuralux import SensorlessEngine

#: Tightest white-point tolerance the calibration target catalogue asks for,
#: in delta xy. The arithmetic should land far inside it, and asserting at the
#: product's own tolerance says what a miss would actually cost.
WHITE_TOLERANCE = 0.003

#: Small enough to build the cubes these tests need in a few seconds, large
#: enough that the neutral axis carries several intermediate levels.
GRID = 17

#: Panels that exercise the two gamut paths the engine chooses between for an
#: sRGB target: the matrix path a narrow panel takes, and the perceptual path
#: a wide one takes.
NARROW = "GENERIC_SRGB"
WIDE = "AW3423DW"


def engine() -> SensorlessEngine:
    return SensorlessEngine(get_builtin_panels())


def panel_named(key: str) -> PanelCharacterization:
    return get_builtin_panels()[key]


def warm_panel() -> PanelCharacterization:
    """A record whose native white sits at D50, which no shipped record does.

    Every panel in the database is D65, so the adaptation the engine performs
    is the identity on all fifty-nine of them and a defect in it would show
    nowhere. A measured characterization lands wherever the display actually
    is, which is the case this stands in for.
    """
    reference = panel_named(NARROW)
    return dataclasses.replace(
        reference,
        model_pattern="warm-reference",
        native_primaries=dataclasses.replace(reference.native_primaries, white=ChromaticityCoord(0.3457, 0.3585)),
    )


def displayed(panel: PanelCharacterization, lut: LUT3D, level: int) -> tuple[tuple[float, float], float]:
    """The chromaticity and luminance the panel model shows for one grey level.

    This is the panel's own behaviour applied to the cube: decode each channel
    with the gamma the record claims, then convert through the record's
    primaries. It is the same model the correction was built against, so it
    reads back what the arithmetic asked the panel for.
    """
    grid = np.asarray(lut.data, dtype=float)
    code = grid[level, level, level]
    primaries = panel.native_primaries
    panel_to_xyz = primaries_to_xyz_matrix(
        primaries.red.as_tuple(),
        primaries.green.as_tuple(),
        primaries.blue.as_tuple(),
        primaries.white.as_tuple(),
    )
    linear = np.array(
        [
            code[0] ** panel.gamma_red.gamma,
            code[1] ** panel.gamma_green.gamma,
            code[2] ** panel.gamma_blue.gamma,
        ]
    )
    xyz = panel_to_xyz @ linear
    total = float(xyz.sum())
    return (float(xyz[0] / total), float(xyz[1] / total)), float(xyz[1])


def cube_for(panel: PanelCharacterization, target_id: str) -> LUT3D:
    """Build one target's cube through the same translation the generator uses.

    Takes a preset id or a composed one, because the generator does, and a
    check that only ever saw presets would not cover the ids an operator
    building a target from the three axes actually produces.
    """
    target = resolve_target(target_id)
    return engine().create_3d_lut(
        panel,
        size=GRID,
        hdr_mode=target.hdr,
        target=target.gamut_mode,
        target_gamma=target.exponent,
        target_tone=target.engine_tone,
        target_white=target.white,
    )


class TestTheWhiteTheCorrectionActuallyDrivesTo:
    """The label on the bundle, checked against the cube inside it."""

    @pytest.mark.parametrize("preset_id", sorted(PRESET_TARGETS))
    @pytest.mark.parametrize("panel_key", [NARROW, WIDE])
    def test_every_preset_drives_the_white_its_manifest_declares(self, preset_id: str, panel_key: str) -> None:
        """Each shipped target, on the two gamut paths, against its own label."""
        panel = panel_named(panel_key)
        aim = TARGET_WHITES[PRESET_TARGETS[preset_id][1]]

        (x, y), _luminance = displayed(panel, cube_for(panel, preset_id), GRID - 1)

        assert abs(x - aim[0]) < WHITE_TOLERANCE
        assert abs(y - aim[1]) < WHITE_TOLERANCE

    def test_two_presets_that_differ_only_in_white_produce_different_corrections(self) -> None:
        """The regression, stated as the comparison nothing was making.

        These two presets carry the same gamut and the same tone response, so
        the white point is the entire difference between them. When the label
        never reached the engine they came out byte-identical on all
        fifty-nine records, and every surface still reported D50.
        """
        srgb_web = PRESET_TARGETS["calibration.preset.srgb_web"]
        photography = PRESET_TARGETS["calibration.preset.photography"]
        assert (srgb_web[0], srgb_web[2], srgb_web[3]) == (photography[0], photography[2], photography[3])
        assert srgb_web[1] != photography[1]

        for panel_key in (NARROW, WIDE):
            panel = panel_named(panel_key)
            d65 = np.asarray(cube_for(panel, "calibration.preset.srgb_web").data, dtype=float)
            d50 = np.asarray(cube_for(panel, "calibration.preset.photography").data, dtype=float)

            assert np.max(np.abs(d65 - d50)) > 0.01, f"{panel_key} corrects D50 and D65 the same"

    def test_the_white_holds_down_the_grey_axis(self) -> None:
        """A white point that only lands at full scale is a tinted greyscale.

        The correction is linear, so this holds by construction until a
        channel clamps. It is asserted because clamping is exactly what used
        to happen, and it happened at the top of the axis first.
        """
        panel = panel_named(NARROW)
        aim = TARGET_WHITES["D50"]

        cube = cube_for(panel, "calibration.preset.photography")

        for level in range(4, GRID):
            (x, y), _luminance = displayed(panel, cube, level)
            assert abs(x - aim[0]) < WHITE_TOLERANCE, f"grey level {level} drifts in x"
            assert abs(y - aim[1]) < WHITE_TOLERANCE, f"grey level {level} drifts in y"

    def test_a_panel_whose_native_white_is_not_the_target_is_adapted_onto_it(self) -> None:
        """The case no shipped record reaches, which every measured one does."""
        panel = warm_panel()
        aim = TARGET_WHITES["D65"]

        for preset_id in ("calibration.preset.srgb_web", "calibration.preset.rec709"):
            (x, y), _luminance = displayed(panel, cube_for(panel, preset_id), GRID - 1)

            assert abs(x - aim[0]) < WHITE_TOLERANCE, preset_id
            assert abs(y - aim[1]) < WHITE_TOLERANCE, preset_id

    def test_the_native_gamut_mode_moves_the_white_without_touching_the_gamut(self) -> None:
        """The mode the catalogue defines and no preset selects yet.

        It is the one path that corrects white while leaving the panel's
        primaries where they are, so a defect in it would not show through any
        preset this build offers.
        """
        panel = warm_panel()
        aim = (0.3127, 0.3290)

        lut = engine().create_3d_lut(panel, size=GRID, target="native", target_gamma=2.2, target_white=aim)

        (x, y), _luminance = displayed(panel, lut, GRID - 1)
        assert abs(x - aim[0]) < WHITE_TOLERANCE
        assert abs(y - aim[1]) < WHITE_TOLERANCE


class TestWhatAimingAtAnotherWhiteCosts:
    """The luminance a white point spends, and where the fit puts it."""

    def test_moving_the_white_costs_luminance_rather_than_accuracy(self) -> None:
        """A display cannot make more light, so the correction pulls down.

        Clamping instead kept full luminance and missed the white, which is
        the trade the wrong way round: an operator who asked for D50 wanted
        D50, and a calibrated display being dimmer than an uncalibrated one is
        the ordinary cost of asking.
        """
        panel = panel_named(NARROW)

        _white, at_native = displayed(panel, cube_for(panel, "calibration.preset.srgb_web"), GRID - 1)
        _adapted, at_d50 = displayed(panel, cube_for(panel, "calibration.preset.photography"), GRID - 1)

        assert at_native == pytest.approx(1.0, abs=1e-9)
        assert 0.5 < at_d50 < at_native

    def test_a_correction_that_already_fits_is_left_alone(self) -> None:
        """Every panel this build ships is at the target white already.

        The fit has to be the identity for them, or the whole database's
        corrections would change to buy headroom nothing needs.
        """
        assert headroom_scale(np.eye(3)) == 1.0
        assert headroom_scale(np.eye(3) * 0.5) == 1.0

    def test_a_correction_asking_for_more_light_than_the_panel_has_is_scaled_to_fit(self) -> None:
        """One scalar over the whole correction, so no ratio moves."""
        asking = np.diag([1.25, 1.0, 1.0])

        scale = headroom_scale(asking)

        assert scale == pytest.approx(0.8)
        assert float(np.max((asking * scale) @ np.ones(3))) == pytest.approx(1.0)

    def test_no_channel_is_driven_past_full_scale_anywhere_on_the_grey_axis(self) -> None:
        """The clamp is for colours the panel cannot reach, not for its white."""
        panel = panel_named(NARROW)

        grid = np.asarray(cube_for(panel, "calibration.preset.photography").data, dtype=float)

        axis = np.array([grid[level, level, level] for level in range(GRID)])
        assert float(np.max(axis)) <= 1.0
        assert float(np.max(axis[-1])) == pytest.approx(1.0), "the brightest channel should reach full drive"


class TestATargetThisBuildCannotTranslate:
    """What happens to a label nothing maps, which used to be a silent default."""

    #: A label no axis carries, so refusing it says something. It is checked
    #: against all three tables below rather than assumed, because the label
    #: this test used to pass was D93, and D93 became a white point an
    #: operator can select while the assertion went on reading as a refusal.
    UNMAPPED = "D97"

    @pytest.mark.parametrize(
        ("known", "part"),
        [(TARGET_WHITES, "white point"), (GAMUT_MODES, "gamut"), (TONE_RESPONSE_EXPONENTS, "tone response")],
    )
    def test_an_unmapped_label_is_refused_rather_than_defaulted(self, known: object, part: str) -> None:
        """The default is how the defect arose, so there is no longer one.

        A target added to the catalogue without a translation now fails at
        generation. Before, it produced a bundle labelled for the target it
        was asked for and corrected for whatever the default happened to be.
        """
        assert self.UNMAPPED not in known  # type: ignore[operator]

        with pytest.raises(TargetSelectionError) as refused:
            resolve_part(known, self.UNMAPPED, part)  # type: ignore[arg-type]

        message = str(refused.value)
        assert part in message
        assert self.UNMAPPED in message
        for label in known:  # type: ignore[attr-defined]
            assert label in message

    @pytest.mark.parametrize("preset_id", sorted(PRESET_TARGETS))
    def test_every_shipped_preset_translates(self, preset_id: str) -> None:
        """The refusal must not be reachable from a target this build offers."""
        target = resolve_target(preset_id)

        assert target.gamut_mode
        assert target.exponent > 0
        assert len(target.white) == 2

    def test_a_target_id_nothing_carries_is_refused(self) -> None:
        """The composed grammar refuses a slug the same way a label is refused."""
        for target_id in ("calibration.preset.nothing", "calibration.target.custom/srgb/d65", "not/a/target/id"):
            with pytest.raises(TargetSelectionError):
                resolve_target(target_id)


class TestATargetComposedFromTheThreeAxes:
    """A target an operator builds, checked the same way a preset is.

    The preset list is four rows. Every other target this build can aim at is
    reached by composing a gamut, a white point and a tone response, and those
    combinations are the ones no shipped bundle exercises. What follows drives
    the panel model with them and reads back what the cube actually does.
    """

    def test_a_composed_white_point_reaches_the_correction(self) -> None:
        """The axis the preset table never varies past D50 and D65."""
        panel = panel_named(NARROW)
        target_id = compose_target_id("srgb", "d55", "g2.2")
        aim = TARGET_WHITES["D55"]

        (x, y), _luminance = displayed(panel, cube_for(panel, target_id), GRID - 1)

        assert abs(x - aim[0]) < WHITE_TOLERANCE
        assert abs(y - aim[1]) < WHITE_TOLERANCE

    def test_a_colour_temperature_is_aimed_at_the_locus_not_the_nearest_illuminant(self) -> None:
        """6300 K and D63 are different whites, and the cube has to show it.

        D63 is the DCI projector white and is not on the daylight locus, so it
        is the one white in the catalogue where a build that answered a
        temperature with the nearest illuminant would be off by six times the
        tolerance. For the daylight series the two agree to within 0.0002 and
        this test would prove nothing.
        """
        panel = panel_named(NARROW)
        target_id = compose_target_id("srgb", "cct6300", "g2.2")

        (x, y), _luminance = displayed(panel, cube_for(panel, target_id), GRID - 1)
        dci = TARGET_WHITES["D63"]

        assert abs(y - dci[1]) > WHITE_TOLERANCE
        assert resolve_target(target_id).white_label == "6300K"

    @pytest.mark.parametrize("slug", ["d50", "d55", "d60", "d63", "d65", "d75", "d93"])
    def test_every_named_white_point_reaches_the_correction(self, slug: str) -> None:
        """All seven, because only two of them appear in a shipped preset."""
        panel = panel_named(NARROW)
        target = resolve_target(compose_target_id("srgb", slug, "g2.2"))

        (x, y), _luminance = displayed(panel, cube_for(panel, target.target_id), GRID - 1)

        assert abs(x - target.white[0]) < WHITE_TOLERANCE, slug
        assert abs(y - target.white[1]) < WHITE_TOLERANCE, slug

    def test_a_curve_target_moves_the_cube_off_the_power_law(self) -> None:
        """sRGB piecewise is not gamma 2.2, and the cube has to show that.

        The two are within a few percent over most of the range and diverge
        near black, so a build that silently applied the exponent instead of
        the curve would look right and be wrong exactly where the curve is
        the reason to ask for it.
        """
        panel = panel_named(NARROW)

        power = np.asarray(cube_for(panel, compose_target_id("srgb", "d65", "g2.2")).data, dtype=float)
        curve = np.asarray(cube_for(panel, compose_target_id("srgb", "d65", "srgb")).data, dtype=float)

        assert np.max(np.abs(power - curve)) > 0.005

    def test_a_composed_gamut_the_preset_list_does_not_offer_is_built(self) -> None:
        """Adobe RGB is in the catalogue, in no preset, and now reachable."""
        panel = panel_named(WIDE)

        native = np.asarray(cube_for(panel, compose_target_id("native", "d65", "g2.2")).data, dtype=float)
        adobe = np.asarray(cube_for(panel, compose_target_id("adobe-rgb", "d65", "g2.2")).data, dtype=float)

        assert np.max(np.abs(native - adobe)) > 0.01


class TestWhatTheApplyPathWasToldAboutThisBundle:
    """The flag that decides whether a calibration is offered for applying."""

    def test_a_panel_already_on_its_target_produces_a_cube_that_changes_nothing(self) -> None:
        """The generic record is exactly sRGB at D65, so this target is a no-op.

        The flag is not cosmetic. ``build_actuating_plan`` refuses a bundle
        that moves no output code, and it should refuse this one.
        """
        cube = cube_for(panel_named(NARROW), "calibration.preset.srgb_web")

        assert _cube_changes_output(cube) is False

    def test_the_same_panel_aimed_at_another_white_has_something_to_apply(self) -> None:
        """What the missing white point cost, stated where an operator met it.

        This bundle used to reach the apply path reporting that it moved no
        output code, so the product told the operator there was nothing to
        apply while the manifest beside it declared D50. The correction it
        should have carried moves a fifth of full scale.
        """
        cube = cube_for(panel_named(NARROW), "calibration.preset.photography")

        assert _cube_changes_output(cube) is True
