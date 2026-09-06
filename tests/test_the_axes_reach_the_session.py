"""What an operator selects on one axis, and what the session then holds.

A target is three independent choices. Until this pass the only tests covering
them called ``resolve_target`` and ``cube_for`` directly, which is the layer
below the one an operator touches. That gap shipped a real defect: the terminal
checked a target id against the preset table alone, so every composed target
reached ``generate-profiles`` and was refused as unknown while the four presets
went through. The arithmetic was right the whole time and nothing exercised the
path between the flag and the bundle.

So these tests drive the path rather than the arithmetic. An axis edit goes in
as the slug a control carries, and what comes out is read from the target the
session went on to hold, from the manifest a run published, or from the refusal
an operator was handed. Two modules that had no direct coverage at all are
covered here for the same reason: ``target_editing`` decides what an edit means
and ``tone_response`` decides what a curve does, and a wrong answer from either
reaches a bundle without anything else noticing.

Three controls are built in. Every slug the window offers is put through the
session to prove a control cannot name something the session refuses. Every
composed target id is read back into the slugs that spell it, so a renamed slug
cannot quietly mean something else. And the two bundles in
:class:`TestWhatTheManifestSaysTheCurveWas` are generated from tone responses
whose single reported exponent agrees to within 0.03, which is what makes the
kind field load-bearing rather than decorative.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from calibrate_pro.application.assets import MANIFEST_FILENAME
from calibrate_pro.application.outcomes import ActionError, ActionSuccess, refusal_message
from calibrate_pro.application.results import TargetSelection
from calibrate_pro.application.target_editing import (
    AXES,
    DEFAULT_TARGET_SLUGS,
    GAMUT_AXIS,
    TONE_AXIS,
    WHITE_AXIS,
    canonical_target_id,
    target_slugs,
    white_point_slug,
    with_axis,
)
from calibrate_pro.application.target_selection import (
    CUSTOM_CCT_MAX_K,
    CUSTOM_CCT_MIN_K,
    GAMUT_SLUGS,
    PRESET_TARGETS,
    TONE_RESPONSES,
    TONE_SLUGS,
    WHITE_SLUGS,
    TargetSelectionError,
    compose_target_id,
    resolve_target,
)
from calibrate_pro.commands.session_args import COMPOSE_HINT, parse
from calibrate_pro.core.tone_response import (
    BT1886,
    L_STAR,
    POWER,
    SRGB,
    ToneResponse,
    bt1886,
    power_law,
)
from calibrate_pro.gui.pages.calibrate import (
    GAMUT,
    SELECTABLE,
    TONE_RESPONSE,
    UNSET_TARGET_ITEM,
    WHITE_POINT,
)
from calibrate_pro.workflow import CalibrationMethod
from tests.session_support import PRESET, arguments, build_cli_service, run

#: The preset every axis test edits from, and the three slugs that spell it.
#: Written out rather than read back through the code under test, so an edit
#: that changed the wrong axis has something independent to disagree with.
BASE_TARGET = "calibration.preset.srgb_web"
BASE_SLUGS = ("srgb", "d65", "g2.2")

#: One slug per axis that the base target does not already carry, so an edit
#: that quietly did nothing is visible as an equality rather than a difference.
EDITS = ((GAMUT_AXIS, 0, "bt2020"), (WHITE_AXIS, 1, "d50"), (TONE_AXIS, 2, "g2.6"))

#: The GUI field index for each axis, paired with the catalogue behind it.
FIELDS = ((GAMUT, GAMUT_AXIS), (WHITE_POINT, WHITE_AXIS), (TONE_RESPONSE, TONE_AXIS))

#: Where two tone responses are compared. The signal range is sampled densely
#: enough that a difference confined to one segment of a piecewise curve is
#: still found.
SAMPLES = 4096
SIGNAL = np.linspace(0.0, 1.0, SAMPLES)

#: Where a curve and a power law of the same reported exponent disagree by a
#: factor rather than by an offset. Both emit almost nothing here, so the
#: absolute difference stays small while the ratio runs past twenty, which is
#: why a single exponent cannot stand in for a curve.
SHADOWS = np.array([0.01, 0.02, 0.05])

#: Where the sRGB nominal exponent is defined, and the one drive it is claimed
#: to be right at.
HALF = np.array([0.5])


def outcome_value(outcome: Any) -> Any:
    """The value one action produced, or a failure naming the refusal instead."""
    assert isinstance(outcome, ActionSuccess), f"the session refused: {outcome}"
    return outcome.value


def refusal(outcome: Any) -> str:
    """The sentence one refused action handed back, as an operator reads it."""
    assert isinstance(outcome, ActionError), f"the session performed it: {outcome}"
    return refusal_message(outcome)


def aimed_session(tmp_path: Path, name: str) -> Any:
    """A session holding the base preset, ready for one axis to be edited."""
    service = build_cli_service(tmp_path / f"session-{name}")
    outcome_value(service.detect())
    outcome_value(service.select_method(CalibrationMethod.SENSORLESS))
    outcome_value(service.set_target(BASE_TARGET))
    return service


def curve(tone: ToneResponse) -> np.ndarray:
    """One tone response sampled across the whole signal range."""
    return tone.to_linear(SIGNAL)


@pytest.fixture
def page(qapp: object) -> Iterator[Any]:
    from calibrate_pro.gui.pages.calibrate import CalibratePage

    built = CalibratePage()
    try:
        yield built
    finally:
        built.close()


# What one edit means -------------------------------------------------------


class TestWhatAnEditToOneAxisLeavesAlone:
    """An edit names one part of a target. The other two are already chosen."""

    @pytest.mark.parametrize(("axis", "index", "slug"), EDITS)
    def test_the_named_axis_moves_and_the_other_two_stay(self, axis: str, index: int, slug: str) -> None:
        """The whole contract of an axis control, held down one axis at a time.

        The defect this guards against does not look like a crash. A white
        point edit that also reset the gamut would produce a bundle the
        operator did not ask for and every surface would report it correctly,
        because the target really would be the one that was composed.
        """
        edited = target_slugs(with_axis(BASE_TARGET, axis, slug))

        assert edited[index] == slug
        untouched = [position for position in range(3) if position != index]
        assert [edited[position] for position in untouched] == [BASE_SLUGS[position] for position in untouched]

    def test_an_edit_against_nothing_held_fills_from_the_stated_defaults(self) -> None:
        """A session with no target yet still ends up holding a whole one.

        One part is not a target this build can generate against, so the other
        two come from ``DEFAULT_TARGET_SLUGS``. What matters is that they come
        from the constant every surface prints back, rather than from whatever
        the first axis to be touched happened to leave behind.
        """
        assert target_slugs(with_axis(None, GAMUT_AXIS, "bt2020")) == ("bt2020", *DEFAULT_TARGET_SLUGS[1:])
        assert target_slugs(with_axis(None, WHITE_AXIS, "d50")) == ("srgb", "d50", "g2.2")

    def test_an_axis_no_target_has_is_refused_naming_the_three_it_does(self) -> None:
        with pytest.raises(TargetSelectionError) as raised:
            with_axis(BASE_TARGET, "brightness", "high")

        for axis in AXES:
            assert axis in str(raised.value)


class TestWhichNameOneTargetEndsUpWith:
    """Two spellings for one target would put two names in the record."""

    @pytest.mark.parametrize("preset_id", sorted(PRESET_TARGETS))
    def test_a_composed_target_carrying_a_preset_s_parts_is_named_for_the_preset(self, preset_id: str) -> None:
        """Every preset is reachable by composing it, and collapses back onto it.

        This is what stops an operator who set three selectors to sRGB, D65 and
        2.2 from holding a different name for the target the sRGB Web button
        sets, when the correction and the digest are the same.
        """
        assert canonical_target_id(*target_slugs(preset_id)) == preset_id

    def test_a_combination_no_preset_names_keeps_its_composed_spelling(self) -> None:
        composed = canonical_target_id("bt2020", "d50", "g2.4")

        assert composed == compose_target_id("bt2020", "d50", "g2.4")
        assert composed not in PRESET_TARGETS

    def test_every_composed_target_reads_back_into_the_slugs_that_spell_it(self) -> None:
        """The whole product of the three axes, round tripped through the id.

        The inverse tables are derived from the forward ones, which is only
        well defined while every forward table stays injective. Two slugs given
        the same label would make this fail rather than silently resolve one
        stored target id into the other one's parts.
        """
        for gamut in GAMUT_SLUGS:
            for white in WHITE_SLUGS:
                for tone in TONE_SLUGS:
                    slugs = (gamut, white, tone)
                    assert target_slugs(compose_target_id(*slugs)) == slugs


class TestReadingAWhitePointBackFromItsLabel:
    """A control shows a label. The session holds one, and it has to invert."""

    @pytest.mark.parametrize("slug", sorted(WHITE_SLUGS))
    def test_every_illuminant_round_trips_through_the_label_it_is_shown_as(self, slug: str) -> None:
        assert white_point_slug(WHITE_SLUGS[slug]) == slug

    @pytest.mark.parametrize("kelvin", (CUSTOM_CCT_MIN_K, 6300, CUSTOM_CCT_MAX_K))
    def test_a_colour_temperature_round_trips_through_the_number_it_is_named_for(self, kelvin: int) -> None:
        """A temperature has no illuminant entry, so it reads back off its own number.

        D63 is why this cannot be answered by matching the nearest daylight
        illuminant: it is the DCI projector white and it is not on the locus,
        and 6300 K lands 0.0185 away in y.
        """
        assert white_point_slug(f"{kelvin}K") == f"cct{kelvin}"

    def test_a_white_point_no_axis_carries_is_refused_naming_what_it_does(self) -> None:
        with pytest.raises(TargetSelectionError) as raised:
            white_point_slug("D42")

        message = str(raised.value)
        assert "D65" in message
        assert "6300K" in message


# What a curve does ---------------------------------------------------------


class TestWhatTheToneResponsesActuallyApply:
    """Three of the four kinds are not power laws, and one number cannot carry them."""

    def test_the_srgb_curve_is_not_the_power_law_its_single_number_reports(self) -> None:
        """The reason the manifest carries a kind beside the exponent.

        sRGB reports 2.224 as its nominal exponent, which rounds to the 2.2 a
        reader with one gamma field would write down. That number is defined by
        agreeing at half drive and is not claimed to hold anywhere else, so the
        curves are checked there and then near black, where the piecewise
        linear segment lives and where the disagreement is a factor of twenty
        rather than a small offset.
        """
        srgb = TONE_RESPONSES["sRGB"]
        nominal = power_law(srgb.nominal_exponent)
        assert abs(srgb.nominal_exponent - 2.2) < 0.03

        assert srgb.to_linear(HALF) == pytest.approx(nominal.to_linear(HALF), rel=1e-9)
        assert np.abs(curve(srgb) - curve(nominal)).max() > 0.002
        assert (srgb.to_linear(SHADOWS) / nominal.to_linear(SHADOWS)).min() > 2.5

    def test_bt1886_at_a_zero_black_is_the_power_law_the_presets_shipped_under(self) -> None:
        assert np.allclose(curve(bt1886(0.0)), curve(power_law(2.4)), atol=1e-12)

    def test_bt1886_at_a_measured_black_departs_from_that_power_law(self) -> None:
        """The whole reason the standard exists, and the reason the kind is stored.

        A panel with a real black of 0.05 cd/m2 follows a different curve, and
        near black it asks for tens of times the light a 2.4 power law would. A
        bundle recording only ``2.4`` would describe a correction it did not
        apply.
        """
        measured = bt1886(0.05)
        power = power_law(2.4)

        assert np.abs(curve(measured) - curve(power)).max() > 0.01
        assert (measured.to_linear(SHADOWS) / power.to_linear(SHADOWS)).min() > 4.0

    @pytest.mark.parametrize("label", sorted(TONE_RESPONSES))
    def test_every_curve_maps_no_drive_to_no_light_and_full_drive_to_full(self, label: str) -> None:
        """Normalisation, which is what makes the four kinds interchangeable.

        bt1886_eotf answers in cd/m2 and reaches 100 at full drive. Handed to
        the engine unscaled it would ask the panel for a hundred times the
        light it can emit, so the endpoints are the property to hold.
        """
        ends = TONE_RESPONSES[label].to_linear(np.array([0.0, 1.0]))

        assert ends == pytest.approx([0.0, 1.0], abs=1e-12)

    @pytest.mark.parametrize("label", sorted(TONE_RESPONSES))
    def test_the_curve_never_leaves_the_range_the_correction_works_in(self, label: str) -> None:
        sampled = curve(TONE_RESPONSES[label])

        assert sampled.min() >= 0.0
        assert sampled.max() <= 1.0
        assert np.all(np.diff(sampled) >= 0.0)

    @pytest.mark.parametrize("label", sorted(TONE_RESPONSES))
    def test_only_a_power_law_answers_to_being_one(self, label: str) -> None:
        """What decides whether a target reaches the engine as a number or a curve.

        A curve answering yes here would go through as its nominal exponent,
        which is the failure the exponent is documented as never doing.
        """
        tone = TONE_RESPONSES[label]

        assert tone.is_power_law is (tone.kind == POWER)


class TestWhatACurveThisBuildCannotApplyDoes:
    """A tone response outside what the correction drives is refused at construction."""

    def test_a_kind_this_build_does_not_carry_is_refused_naming_the_four(self) -> None:
        with pytest.raises(ValueError) as raised:
            ToneResponse(label="PQ", kind="pq")

        message = str(raised.value)
        for kind in (POWER, SRGB, L_STAR, BT1886):
            assert kind in message

    @pytest.mark.parametrize("exponent", (0.9, 3.3))
    def test_an_exponent_outside_the_range_this_build_applies_is_refused(self, exponent: float) -> None:
        with pytest.raises(ValueError) as raised:
            power_law(exponent)

        assert "1.0 to 3.2" in str(raised.value)

    def test_a_bt1886_black_at_or_above_its_peak_is_refused(self) -> None:
        """The one parameter pair BT.1886 cannot be evaluated at.

        A black equal to the peak makes the curve emit nothing anywhere, and
        the normalisation would then divide by zero rather than produce a
        correction nobody could read as wrong.
        """
        with pytest.raises(ValueError):
            bt1886(100.0)
        with pytest.raises(ValueError):
            bt1886(0.05, peak_luminance=0.0)

    def test_a_table_of_one_point_is_refused(self) -> None:
        with pytest.raises(ValueError):
            power_law(2.2).table(points=1)


# What a bundle records -----------------------------------------------------


class TestWhatTheManifestSaysTheCurveWas:
    """Two targets one gamma field cannot tell apart, published side by side."""

    def bundle(self, tmp_path: Path, tone_slug: str) -> tuple[dict[str, Any], bytes]:
        directory = tmp_path / tone_slug
        code, _ = run(
            "generate-profiles",
            build_cli_service(tmp_path / f"session-{tone_slug}"),
            target=None,
            gamut="srgb",
            white_point="d65",
            tone_response=tone_slug,
            output=str(directory),
        )
        assert code == 0, "the publishing run this test depends on was refused"
        manifest = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
        cube = next(path for path in directory.iterdir() if path.suffix == ".cube")
        return manifest, cube.read_bytes()

    def test_two_curves_one_gamma_field_cannot_separate_are_separated_by_the_kind(self, tmp_path: Path) -> None:
        """The manifest field earning its place, proved on the artifacts.

        Both bundles report a gamma within 0.03 of 2.2. One applies a power law
        and the other applies the piecewise sRGB curve, and the cubes are
        different files. A reader holding only the exponent would call these
        the same correction.
        """
        power, power_cube = self.bundle(tmp_path, "g2.2")
        piecewise, piecewise_cube = self.bundle(tmp_path, "srgb")

        assert power["target"]["tone_response_kind"] == POWER
        assert piecewise["target"]["tone_response_kind"] == SRGB
        assert abs(power["target"]["applied_gamma_exponent"] - piecewise["target"]["applied_gamma_exponent"]) < 0.03
        assert power_cube != piecewise_cube

    def test_the_kind_recorded_is_the_kind_the_target_carries(self, tmp_path: Path) -> None:
        for tone_slug, label in (("lstar", "L*"), ("bt1886", "BT.1886")):
            manifest, _cube = self.bundle(tmp_path, tone_slug)

            assert manifest["target"]["tone_response"] == label
            assert manifest["target"]["tone_response_kind"] == TONE_RESPONSES[label].kind


# What the command line aims at ---------------------------------------------


class TestHowACommandLineNamesATarget:
    """The four flags a calibration can be aimed with, read where they are read."""

    @pytest.mark.parametrize(
        ("flag", "attribute", "value"),
        (
            ("--target", "target", "srgb_web"),
            ("--gamut", "gamut", "bt2020"),
            ("--white-point", "white_point", "d50"),
            ("--tone-response", "tone_response", "g2.4"),
        ),
    )
    def test_each_flag_parses_to_the_attribute_the_command_reads(self, flag: str, attribute: str, value: str) -> None:
        """The parser and the command have to agree on one spelling each.

        ``--white-point`` arrives as ``white_point``, and a command reading
        ``whitepoint`` would find nothing and silently leave that axis at its
        default. That is a target the operator named and the bundle did not
        apply, which is the failure this package refuses to ship.
        """
        assert getattr(parse("verify", [flag, value]), attribute) == value

    @pytest.mark.parametrize("command", ("verify", "generate-profiles"))
    def test_a_line_naming_no_target_is_refused_before_a_display_is_touched(
        self,
        command: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The refusal belongs to the parser, so nothing is detected first.

        A command refusing after dispatch has already enumerated the operator's
        panels. Someone who mistyped one flag would watch that happen before
        being told.
        """
        argv = ["out"] if command == "generate-profiles" else []
        with pytest.raises(SystemExit):
            parse(command, argv)

        printed = capsys.readouterr().err
        assert "--target" in printed
        assert COMPOSE_HINT in printed

    def test_an_axis_flag_alone_is_a_target(self) -> None:
        """One axis aims a line. The other two take the stated defaults."""
        assert parse("verify", ["--gamut", "bt2020"]).gamut == "bt2020"

    def test_asking_for_two_characterizations_at_once_is_refused(self, tmp_path: Path) -> None:
        """A display cannot be recorded as generic and as its own declaration.

        Both flags perform, and each refuses a display that already matched a
        panel record. Passing both would have the second overwrite what the
        first recorded, so the line is refused rather than resolved.
        """
        code, _printed = run(
            "verify",
            build_cli_service(tmp_path / "session"),
            generic=True,
            edid=True,
        )

        assert code != 0


# What the session does with a slug it cannot use ---------------------------


class TestWhatARefusedEditLeavesTheSessionHolding:
    """A refusal that moved the target would be worse than the refusal."""

    @pytest.mark.parametrize(
        ("action", "slug", "named"),
        (
            ("select_target_gamut", "chartreuse", "bt2020"),
            ("select_target_white_point", "d42", "d65"),
            ("select_target_tone_response", "g9.9", "g2.2"),
        ),
    )
    def test_a_slug_no_axis_carries_is_refused_naming_what_that_axis_does(
        self,
        tmp_path: Path,
        action: str,
        slug: str,
        named: str,
    ) -> None:
        """The operator gets the catalogue, not "the action could not be completed".

        The sentence comes from the resolver, which is the one place that knows
        what the axis carries. Wording it again at the action layer would be a
        second sentence to keep level with the first.
        """
        service = aimed_session(tmp_path, action)

        message = refusal(getattr(service, action)(slug))

        assert slug in message
        assert named in message

    def test_the_target_a_refused_edit_did_not_change_is_still_the_one_held(self, tmp_path: Path) -> None:
        """Read by making the next edit and seeing what it composed against.

        If the refusal had dropped the target, the following white point edit
        would compose against the sRGB defaults and land on the same answer by
        coincidence. So the session is moved off the defaults first: the gamut
        is BT.2020 and the tone response is 2.6 before anything is refused.
        """
        service = aimed_session(tmp_path, "undisturbed")
        outcome_value(service.select_target_gamut("bt2020"))
        outcome_value(service.select_target_tone_response("g2.6"))

        refusal(service.select_target_gamut("chartreuse"))
        after = outcome_value(service.select_target_white_point("d50"))

        assert (after.gamut, after.white_point, after.tone_response) == ("BT.2020", "D50", "2.6")

    @pytest.mark.parametrize("kelvin", (CUSTOM_CCT_MIN_K - 100, CUSTOM_CCT_MAX_K + 100))
    def test_a_temperature_outside_what_this_build_calibrates_to_names_the_range(
        self,
        tmp_path: Path,
        kelvin: int,
    ) -> None:
        """Below 4000 K the resolver would leave the daylight locus for the Planckian one."""
        service = aimed_session(tmp_path, f"cct{kelvin}")

        message = refusal(service.select_custom_white_point(kelvin))

        assert str(CUSTOM_CCT_MIN_K) in message
        assert str(CUSTOM_CCT_MAX_K) in message

    def test_a_temperature_inside_the_range_is_held_and_reported_by_its_number(self, tmp_path: Path) -> None:
        service = aimed_session(tmp_path, "cct-held")

        selected = outcome_value(service.select_custom_white_point(5400))

        assert selected.white_point == "5400K"
        assert target_slugs(selected.preset_id) == ("srgb", "cct5400", "g2.2")


# What the window offers ----------------------------------------------------


class TestWhatTheTargetSelectorsOffer:
    """A control naming something the session refuses is a control that lies."""

    @pytest.mark.parametrize(("field", "axis"), FIELDS)
    def test_each_selector_lists_its_whole_catalogue_in_order_under_an_unset_item(
        self,
        page: Any,
        field: int,
        axis: str,
    ) -> None:
        """The list is built from the catalogue, and the slug travels as item data.

        Reading the label back to find the slug would break on the two gamuts
        that share primaries, since ``sRGB`` and ``Rec.709`` are separate names
        for one set of numbers and separate rows here.
        """
        combo = page._target_combos[field]
        catalogue = SELECTABLE[field]()

        assert combo.itemText(0) == UNSET_TARGET_ITEM
        assert combo.itemData(0) is None
        assert combo.count() == len(catalogue) + 1
        listed = [(combo.itemData(index), combo.itemText(index)) for index in range(1, combo.count())]
        assert listed == list(catalogue)

    @pytest.mark.parametrize(("field", "axis"), FIELDS)
    def test_every_slug_a_selector_offers_is_one_the_session_performs(
        self,
        page: Any,
        tmp_path: Path,
        field: int,
        axis: str,
    ) -> None:
        """The control against the session, rather than against the same table.

        This is the check that would have caught the composed-target defect:
        each offered slug is put through the action the control is bound to,
        and a slug the session refuses fails here rather than in an operator's
        hands.
        """
        service = aimed_session(tmp_path, f"offered-{field}")
        action = {
            GAMUT: service.select_target_gamut,
            WHITE_POINT: service.select_target_white_point,
            TONE_RESPONSE: service.select_target_tone_response,
        }[field]

        for slug, label in SELECTABLE[field]():
            selected = outcome_value(action(slug))
            shown = (selected.gamut, selected.white_point, selected.tone_response)[field]
            assert shown == label


class TestWhatChoosingARowDoes:
    """The window, its session, and the trip between them.

    These run against the real bound window rather than a page holding stubs.
    The page does not answer for itself: a selection leaves as a slug and what
    comes back is redrawn onto all three selectors. A page keeping its own
    answer would look identical until the session refused something, which is
    the failure worth catching.
    """

    def aimed(self, window: Any) -> Any:
        """The calibrate page of a window whose session will take a target."""
        outcome_value(window.service.select_method(CalibrationMethod.SENSORLESS))
        return window.calibrate_page

    @pytest.mark.parametrize(("field", "axis"), FIELDS)
    def test_a_row_chosen_on_a_selector_is_the_target_the_session_answers_with(
        self,
        window: Any,
        field: int,
        axis: str,
    ) -> None:
        """The trip out and back, read off the control the operator touched.

        The page redraws from what the session answered, so a selector still
        showing the chosen row afterwards is showing the session's answer and
        not its own. Sending the label instead of the slug would compose an id
        nothing resolves and leave the selector back on unset.
        """
        page = self.aimed(window)
        slug, label = SELECTABLE[field]()[-1]
        combo = page._target_combos[field]

        combo.setCurrentIndex(combo.findData(slug))

        assert combo.currentData() == slug
        assert combo.currentText() == label

    def test_editing_one_selector_leaves_the_other_two_showing_what_they_showed(
        self,
        window: Any,
    ) -> None:
        """Three controls, one target, and no axis moved that nobody touched."""
        page = self.aimed(window)
        for field, slug in ((GAMUT, "bt2020"), (TONE_RESPONSE, "g2.6")):
            combo = page._target_combos[field]
            combo.setCurrentIndex(combo.findData(slug))

        white = page._target_combos[WHITE_POINT]
        white.setCurrentIndex(white.findData("d50"))

        shown = tuple(page._target_combos[field].currentData() for field in (GAMUT, WHITE_POINT, TONE_RESPONSE))
        assert shown == ("bt2020", "d50", "g2.6")

    def test_the_unset_row_asks_for_nothing_and_the_selector_returns(self, window: Any) -> None:
        """Landing on it says no more than that, so the held target is redrawn.

        A page letting the unset row through would send no slug to an action
        that requires one, and the three selectors would then disagree with the
        target named below them.
        """
        page = self.aimed(window)
        combo = page._target_combos[GAMUT]
        combo.setCurrentIndex(combo.findData("bt2020"))

        combo.setCurrentIndex(0)

        assert combo.currentData() == "bt2020"


class TestWhatTheWhiteSelectorShowsForATemperature:
    """Every colour temperature is a value the catalogue does not list."""

    def held(self, target_id: str) -> TargetSelection:
        target = resolve_target(target_id)
        return TargetSelection(
            preset_id=target_id,
            gamut=target.gamut_label,
            white_point=target.white_label,
            tone_response=target.tone_label,
        )

    def test_a_temperature_is_added_to_the_selector_rather_than_dropped(self, page: Any) -> None:
        """A selector staying on D65 would name a white the bundle is not aimed at."""
        catalogue = page._catalogue_items[WHITE_POINT]

        page.render_target(self.held(compose_target_id("srgb", "cct5400", "g2.2")))

        combo = page._target_combos[WHITE_POINT]
        assert combo.count() == catalogue + 1
        assert combo.currentText() == "5400K"
        assert combo.currentData() == "cct5400"

    def test_a_second_temperature_replaces_the_first_rather_than_stacking(self, page: Any) -> None:
        """One trailing row at most, so the list does not grow per temperature tried."""
        catalogue = page._catalogue_items[WHITE_POINT]

        page.render_target(self.held(compose_target_id("srgb", "cct5400", "g2.2")))
        page.render_target(self.held(compose_target_id("srgb", "cct6300", "g2.2")))

        combo = page._target_combos[WHITE_POINT]
        assert combo.count() == catalogue + 1
        assert combo.currentText() == "6300K"

    def test_returning_to_a_listed_illuminant_drops_the_trailing_row(self, page: Any) -> None:
        catalogue = page._catalogue_items[WHITE_POINT]

        page.render_target(self.held(compose_target_id("srgb", "cct5400", "g2.2")))
        page.render_target(self.held(BASE_TARGET))

        combo = page._target_combos[WHITE_POINT]
        assert combo.count() == catalogue
        assert combo.currentData() == "d65"


# What a whole run does with an axis flag -----------------------------------


def test_a_line_aimed_by_axis_flags_alone_publishes_the_target_it_named(tmp_path: Path) -> None:
    """The defect this file exists for, driven end to end.

    No ``--target``. Two axes named, one left to the default, and a bundle read
    back off disk. The terminal used to refuse this line as an unknown target
    while the four presets went through.
    """
    directory = tmp_path / "bundle"
    code, printed = run(
        "generate-profiles",
        build_cli_service(tmp_path / "session"),
        target=None,
        gamut="adobe-rgb",
        white_point="5400",
        output=str(directory),
    )

    assert code == 0, printed
    manifest = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["preset_id"] == compose_target_id("adobe-rgb", "cct5400", "g2.2")
    assert manifest["target"]["gamut_mode"] == "Adobe RGB"
    assert manifest["target"]["white_point"] == "5400K"
    assert manifest["target"]["tone_response"] == "2.2"


def test_an_axis_flag_beside_a_preset_edits_that_preset(tmp_path: Path) -> None:
    """The ordinary way an operator asks for a preset with one part changed."""
    directory = tmp_path / "bundle"
    code, printed = run(
        "generate-profiles",
        build_cli_service(tmp_path / "session"),
        target=PRESET,
        tone_response="lstar",
        output=str(directory),
    )

    assert code == 0, printed
    manifest = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert manifest["target"]["gamut_mode"] == "sRGB"
    assert manifest["target"]["white_point"] == "D65"
    assert manifest["target"]["tone_response"] == "L*"
    assert manifest["target"]["tone_response_kind"] == L_STAR


def test_the_arguments_helper_matches_what_the_parser_produces() -> None:
    """The tests above build arguments by hand, so the shape is checked once.

    A helper drifting from the parser would let every command test pass against
    a line the terminal cannot produce.
    """
    parsed = parse("verify", ["--target", PRESET, "--gamut", "bt2020"])
    built = arguments(gamut="bt2020")

    assert (parsed.target, parsed.gamut) == (built.target, built.gamut)
    for flag in ("white_point", "tone_response", "display", "generic", "edid"):
        assert hasattr(parsed, flag)
