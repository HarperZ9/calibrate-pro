"""What the sensorless path is allowed to report about a display it never read.

This lane produces the one number in the product that an operator can mistake
for a measurement. It is model output, so the whole question is whether the
figure describes their display or something else, and the tests here are the
controls on that.

The reference-table floor is the defect they exist to keep out. The simulation
compares its output against the ColorChecker's own Lab column, and that column
does not round-trip exactly through an sRGB encode, so a residual near 0.65 dE
appears for every panel before any panel property is considered. Printed as a
predicted accuracy it told an operator their display scores 0.65 when the
figure described the chart. Every panel in the shipped database landed within
0.001 of the same value, which is the shape of a constant rather than a
measurement, and no test caught it because nothing compared two panels.

Subtracting a reference display's run removes that term. What survives is the
part the panel record determines, which is gamut reproduction. The controls at
the end are the ones that matter most: a display whose grey is badly wrong
scores zero here, and the result has to say so in the words that reach a
surface, because a figure of zero beside no caveat is a claim this path cannot
support.
"""

from __future__ import annotations

import dataclasses

import pytest

from calibrate_pro.application.actions import PRESET_TARGETS
from calibrate_pro.application.prediction import (
    METRIC_NAME,
    MODEL_NAME,
    MODELLED_TARGET,
    VERIFICATION_SOURCE,
    predict_accuracy,
    reference_panel,
    target_is_modelled,
    uncovered_result,
)
from calibrate_pro.application.results import verification_note
from calibrate_pro.core.colorchecker import COLORCHECKER_PATCHES
from calibrate_pro.panels.builtin_panels import get_builtin_panels
from calibrate_pro.panels.panel_types import ChromaticityCoord, GammaCurve, PanelCharacterization
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.verification.provenance import EvidenceKind

MODELLED = "calibration.preset.srgb_web"
UNMODELLED = "calibration.preset.dci_p3"

#: The residual the old comparison carried, measured across the whole shipped
#: database before it was removed. Kept as a number rather than a story so a
#: change that reintroduced it fails rather than reads plausibly.
REFERENCE_TABLE_FLOOR = 0.6455

#: Below the last place a dE figure is ever rendered at, and far below anything
#: an instrument resolves. Used where the arithmetic cancels exactly and only
#: float noise is left.
NOISE = 1e-9


@pytest.fixture(scope="module")
def engine() -> SensorlessEngine:
    return SensorlessEngine(get_builtin_panels())


def figures(engine: SensorlessEngine, panel: PanelCharacterization, preset: str = MODELLED) -> tuple[float, float]:
    result = predict_accuracy(engine, panel, preset)
    assert result.average_delta_e.value is not None
    assert result.maximum_delta_e.value is not None
    return (result.average_delta_e.value, result.maximum_delta_e.value)


def with_primaries(**changes: ChromaticityCoord) -> PanelCharacterization:
    """The reference panel with some of its primaries moved."""
    panel = reference_panel()
    return dataclasses.replace(panel, native_primaries=dataclasses.replace(panel.native_primaries, **changes))


def gamuts() -> dict[tuple[tuple[float, float], ...], list[str]]:
    """The shipped panels, grouped by the only properties that reach the figure.

    Sweeping all fifty-nine records means simulating twenty-four patches
    fifty-nine times, and the figure is determined by the primaries and the
    white alone. Grouping is not sampling: the count is asserted against the
    whole database, so a record introducing a gamut nothing else carries is
    swept without this file being edited.
    """
    grouped: dict[tuple[tuple[float, float], ...], list[str]] = {}
    for key, panel in get_builtin_panels().items():
        primaries = panel.native_primaries
        signature = (
            (primaries.red.x, primaries.red.y),
            (primaries.green.x, primaries.green.y),
            (primaries.blue.x, primaries.blue.y),
            (primaries.white.x, primaries.white.y),
        )
        grouped.setdefault(signature, []).append(key)
    return grouped


class TestWhatTheFigureIsMeasuredAgainst:
    """The reference run, which is what stops the chart entering the number."""

    def test_a_display_with_exact_srgb_primaries_scores_zero(self, engine: SensorlessEngine) -> None:
        """The assertion the whole rewrite rests on.

        Under the old comparison this same panel scored the reference table's
        own round-trip and the product printed it as predicted accuracy. A
        display that reproduces the target exactly has no residual, and any
        number here other than zero is a property of the chart.
        """
        assert figures(engine, reference_panel()) == pytest.approx((0.0, 0.0), abs=NOISE)

    def test_the_old_reference_table_floor_is_gone_from_every_gamut_shipped(self, engine: SensorlessEngine) -> None:
        """Every gamut the database carries, against the constant they reported.

        The defect was invisible on any single panel. It only showed as a
        defect when two panels that differ produced the same answer, so what is
        checked here is the whole spread rather than one record.
        """
        grouped = gamuts()
        assert sum(len(keys) for keys in grouped.values()) == len(get_builtin_panels())

        for keys in grouped.values():
            panel = get_builtin_panels()[keys[0]]
            average, _maximum = figures(engine, panel)
            assert average < REFERENCE_TABLE_FLOOR / 10, f"{keys[0]} still carries the reference table's residual"

    def test_the_reference_display_is_built_here_rather_than_looked_up(self) -> None:
        """An edit to a panel record must not move what every figure means.

        The baseline is the zero of this scale. Reading it out of the database
        would let one record's correction silently restate every other panel's
        score, and nothing comparing two panels would notice, which is exactly
        how the reference-table floor survived.
        """
        panel = reference_panel()

        assert panel.native_primaries.red == ChromaticityCoord(0.6400, 0.3300)
        assert panel.native_primaries.green == ChromaticityCoord(0.3000, 0.6000)
        assert panel.native_primaries.blue == ChromaticityCoord(0.1500, 0.0600)
        assert panel.native_primaries.white == ChromaticityCoord(0.3127, 0.3290)
        assert (panel.gamma_red.gamma, panel.gamma_green.gamma, panel.gamma_blue.gamma) == (2.2, 2.2, 2.2)
        assert panel.model_pattern not in get_builtin_panels()


class TestWhatMovesTheFigureAndWhatDoesNot:
    """The two panel properties that reach the number, and the one that cannot."""

    def test_a_panel_narrower_than_the_target_reports_a_residual(self, engine: SensorlessEngine) -> None:
        """Colours the panel cannot reach are the real sensorless limit.

        This is the case the figure exists to report. The correction can map
        primaries, and it cannot invent a colour outside the ones the panel has.
        """
        narrow = with_primaries(
            red=ChromaticityCoord(0.60, 0.34),
            green=ChromaticityCoord(0.32, 0.56),
            blue=ChromaticityCoord(0.16, 0.08),
        )

        average, maximum = figures(engine, narrow)

        assert average > 0.2
        assert maximum > 3.0

    def test_a_native_white_away_from_the_target_reports_a_residual(self, engine: SensorlessEngine) -> None:
        """A D50 panel driven to a D65 target, adapted rather than measured."""
        average, maximum = figures(engine, with_primaries(white=ChromaticityCoord(0.3457, 0.3585)))

        assert average > 0.3
        assert maximum > 8.0

    def test_a_display_whose_grey_is_badly_wrong_scores_the_same_as_a_perfect_one(
        self, engine: SensorlessEngine
    ) -> None:
        """The blindness, pinned as a fact rather than left as an assumption.

        A panel tracking 2.6 on red and 1.9 on green is a visibly colour-cast
        display. It scores zero here, because the correction encodes for the
        gamma the record claims and the panel decodes with the same number, so
        the two cancel before anything is compared. This test exists so that a
        later change which quietly starts folding tone response into the figure
        has to say so rather than pass.
        """
        cast = dataclasses.replace(
            reference_panel(),
            gamma_red=GammaCurve(gamma=2.6),
            gamma_green=GammaCurve(gamma=1.9),
            gamma_blue=GammaCurve(gamma=2.3),
        )

        assert figures(engine, cast) == pytest.approx(figures(engine, reference_panel()), abs=NOISE)
        assert figures(engine, cast) == pytest.approx((0.0, 0.0), abs=NOISE)

    @pytest.mark.parametrize("gamma", [1.8, 2.0, 2.4, 2.6, 3.0])
    def test_no_stated_gamma_moves_the_figure(self, engine: SensorlessEngine, gamma: float) -> None:
        """The same blindness across the range a panel record can carry."""
        curve = GammaCurve(gamma=gamma)
        panel = dataclasses.replace(reference_panel(), gamma_red=curve, gamma_green=curve, gamma_blue=curve)

        assert figures(engine, panel) == pytest.approx((0.0, 0.0), abs=NOISE)


class TestWhatTheResultSaysAboutItself:
    """The words that travel with the number to every surface that renders it."""

    def test_the_note_states_that_nothing_was_measured(self, engine: SensorlessEngine) -> None:
        """A limitation replaces the default note, so it has to carry it.

        ``verification_note`` returns the limitation in place of the sentence it
        would otherwise print. A limitation that only described the metric would
        therefore delete the statement that no display was read, on the one path
        where that statement is the whole point.
        """
        note = verification_note(predict_accuracy(engine, reference_panel(), MODELLED))

        assert "No display was measured and no sensor was read" in note
        assert MODEL_NAME in note

    def test_the_note_names_the_error_the_figure_does_not_cover(self, engine: SensorlessEngine) -> None:
        """Zero beside no caveat reads as a display that needs no calibration."""
        note = verification_note(predict_accuracy(engine, reference_panel(), MODELLED))

        assert "Tone response is outside it" in note
        assert "Measure to establish grey" in note

    def test_the_result_names_what_was_measured(self, engine: SensorlessEngine) -> None:
        """Both paths report dE, and they are not the same quantity.

        A surface printing a number and a unit would show a modelled gamut
        residual and a measured colour error under one label, so the result
        carries the name of its own metric to every surface.
        """
        result = predict_accuracy(engine, reference_panel(), MODELLED)

        assert result.metric == METRIC_NAME
        assert result.source == VERIFICATION_SOURCE

    def test_every_figure_is_labelled_estimated_and_names_the_model(self, engine: SensorlessEngine) -> None:
        result = predict_accuracy(engine, reference_panel(), MODELLED)

        assert result.evidence is EvidenceKind.ESTIMATED
        assert result.patch_count == len(COLORCHECKER_PATCHES)
        assert {patch.delta_e.evidence for patch in result.patches} == {EvidenceKind.ESTIMATED}
        assert {patch.delta_e.source for patch in result.patches} == {MODEL_NAME}
        assert result.average_delta_e.source == MODEL_NAME


class TestTheTargetsThisPathAnswersFor:
    """One target is simulated, and the rest get no number at all."""

    def test_only_the_target_the_simulation_models_is_covered(self) -> None:
        covered = [preset for preset in PRESET_TARGETS if target_is_modelled(preset)]

        assert covered == [MODELLED]
        assert PRESET_TARGETS[MODELLED][:3] == MODELLED_TARGET

    def test_an_unmodelled_target_reports_no_figure_rather_than_a_caveated_one(self, engine: SensorlessEngine) -> None:
        """A number computed for the wrong target reads as an accuracy claim.

        The refusal is taken before the engine is entered, so a session aiming
        at DCI-P3 spends nothing to arrive at it.
        """
        result = predict_accuracy(engine, reference_panel(), UNMODELLED)

        assert result.evidence is EvidenceKind.NOT_MEASURED
        assert result.average_delta_e.value is None
        assert result.maximum_delta_e.value is None
        assert result.patches == ()
        assert result.metric == ""

    def test_a_preset_this_build_does_not_carry_is_uncovered_too(self, engine: SensorlessEngine) -> None:
        """An unknown id is not a target the simulation quietly claims."""
        assert not target_is_modelled("calibration.preset.no-such-target")
        unknown = predict_accuracy(engine, reference_panel(), "calibration.preset.no-such-target")
        assert unknown.average_delta_e.value is None

    def test_the_uncovered_result_says_which_target_the_model_holds(self) -> None:
        note = verification_note(uncovered_result(UNMODELLED))

        assert "sRGB primaries" in note
        assert "no predicted accuracy is reported" in note
