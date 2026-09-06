"""What the sensorless figure says about the display in front of the operator.

Two defects live here, and they are the same defect at two altitudes.

The first is the figure itself. The corrected number lands near zero for every
panel this build handles, because that is what the correction is for. Printed
alone it reads identically on a wide-gamut monitor that needed clamping and on
a display that was already sRGB, so it cannot be evidence that anything
happened. The uncorrected run is the other half: the same measure with an
identity matrix in place of the generated one, which is the display before this
build touched it. The pair is what an operator can read.

The second is which panel gets verified. Three build paths feed the generator,
and two of them replace the panel record before it arrives. A verification that
resolved ``selected_panel_key`` would report figures for a record no correction
was built from. That is not a number that looks slightly off. The generic
record is exact sRGB, so it scores zero against an sRGB reference whatever the
display actually does, and a report built that way calls the calibration
perfect on every display it is ever run against.

Nothing here opens a display, a bus, or an instrument. The engine is arithmetic
over a panel record and the ColorChecker table, and the session is assembled in
memory.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from calibrate_pro.application.assets import AssetGenerator
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.contracts import PanelCharacterization as DeclaredContract
from calibrate_pro.application.declaration import DeclaredCharacterization, declared_from
from calibrate_pro.application.generation import verification_panel
from calibrate_pro.application.measurement import MeasuredCharacterization
from calibrate_pro.application.prediction import (
    DELTA_E_UNIT,
    MODEL_NAME,
    predict_accuracy,
    reference_panel,
    uncovered_result,
)
from calibrate_pro.application.results import (
    CORRECTION_THRESHOLD_DELTA_E,
    VerificationResult,
    correction_note,
)
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.builtin_panels import get_builtin_panels
from calibrate_pro.panels.database import GENERIC_PANEL_KEY, get_database
from calibrate_pro.panels.panel_types import ChromaticityCoord, PanelCharacterization
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

#: The one target the simulation models, and one it does not.
MODELLED = "calibration.preset.srgb_web"
UNMODELLED = "calibration.preset.dci_p3"

#: Below the last place a dE figure is rendered at, and far below anything an
#: instrument resolves. Used where the arithmetic cancels and only float noise
#: is left.
NOISE = 1e-9

#: How near zero the corrected figure has to stay for every gamut here. The
#: correction maps the panel primaries onto sRGB exactly, so anything above
#: this is a residual the model was not supposed to leave behind.
CORRECTED_CEILING = 0.05

#: The three gamuts swept, against a D65 white. sRGB is the target itself, so
#: it is the case where the correction has nothing to do.
SRGB_PRIMARIES = ((0.640, 0.330), (0.300, 0.600), (0.150, 0.060))
P3_PRIMARIES = ((0.680, 0.320), (0.265, 0.690), (0.150, 0.060))
REC2020_PRIMARIES = ((0.708, 0.292), (0.170, 0.797), (0.131, 0.046))

#: Uncorrected averages observed on this build, in dE2000. Asserted with a
#: tolerance rather than exactly, because the claim is the magnitude and the
#: ordering, not a digit an unrelated colour-science fix would move.
EXPECTED_UNCORRECTED = {"sRGB": 0.00, "DCI-P3": 2.24, "Rec.2020": 5.59}
MAGNITUDE_TOLERANCE = 0.25

#: The display every session in this file is working on.
DISPLAY = "TEST-DISPLAY-1"

#: A record the database holds under its own key, wide enough that verifying it
#: instead of a declaration is visible in the figure.
MATCHED_KEY = "AW3423DW"


def panel_with(primaries: tuple[tuple[float, float], ...]) -> PanelCharacterization:
    """The reference panel with its three primaries moved and its white kept."""
    panel = reference_panel()
    red, green, blue = primaries
    return dataclasses.replace(
        panel,
        native_primaries=dataclasses.replace(
            panel.native_primaries,
            red=ChromaticityCoord(*red),
            green=ChromaticityCoord(*green),
            blue=ChromaticityCoord(*blue),
        ),
    )


@pytest.fixture(scope="module")
def engine() -> SensorlessEngine:
    return SensorlessEngine(get_builtin_panels())


@pytest.fixture(scope="module")
def swept(engine: SensorlessEngine) -> dict[str, VerificationResult]:
    """One predicted result per gamut, computed once for the whole module."""
    return {
        "sRGB": predict_accuracy(engine, panel_with(SRGB_PRIMARIES), MODELLED),
        "DCI-P3": predict_accuracy(engine, panel_with(P3_PRIMARIES), MODELLED),
        "Rec.2020": predict_accuracy(engine, panel_with(REC2020_PRIMARIES), MODELLED),
    }


def average_of(result: VerificationResult) -> float:
    assert result.average_delta_e.value is not None
    return result.average_delta_e.value


def uncorrected_average_of(result: VerificationResult) -> float:
    figure = result.uncorrected_average_delta_e
    assert figure is not None and figure.value is not None
    return figure.value


def uncorrected_maximum_of(result: VerificationResult) -> float:
    figure = result.uncorrected_maximum_delta_e
    assert figure is not None and figure.value is not None
    return figure.value


def displayed(report: object) -> list[tuple[float, ...]]:
    """The Lab each simulated patch landed on, in the order the chart runs."""
    assert isinstance(report, dict)
    patches = report["patches"]
    assert isinstance(patches, list) and patches
    return [tuple(float(component) for component in patch["displayed_lab"]) for patch in patches]


def metric(value: float) -> MetricValue:
    return MetricValue(value=value, unit=DELTA_E_UNIT, evidence=EvidenceKind.ESTIMATED, source="tests")


NOT_MEASURED = MetricValue(value=None, unit=DELTA_E_UNIT, evidence=EvidenceKind.NOT_MEASURED)


def built_result(
    *,
    evidence: EvidenceKind = EvidenceKind.ESTIMATED,
    average: MetricValue | None = None,
    maximum: MetricValue | None = None,
    uncorrected_average: MetricValue | None = None,
    uncorrected_maximum: MetricValue | None = None,
) -> VerificationResult:
    """A result assembled by hand, so a rule can be checked without the engine."""
    return VerificationResult(
        source="tests",
        evidence=evidence,
        average_delta_e=average if average is not None else metric(0.0),
        maximum_delta_e=maximum if maximum is not None else metric(0.0),
        patches=(),
        uncorrected_average_delta_e=uncorrected_average,
        uncorrected_maximum_delta_e=uncorrected_maximum,
    )


def declared_panel(primaries: tuple[tuple[float, float], ...]) -> DeclaredCharacterization:
    """A declaration built the way an accepted descriptor arrives at the session."""
    red, green, blue = primaries
    contract = DeclaredContract(
        kind=CharacterizationKind.EDID_DECLARED,
        provenance="edid:ABC1234 Declared Wide Panel",
        red_xy=(f"{red[0]}", f"{red[1]}"),
        green_xy=(f"{green[0]}", f"{green[1]}"),
        blue_xy=(f"{blue[0]}", f"{blue[1]}"),
        white_xy=("0.3127", "0.3290"),
        nominal_gamma="2.2",
    )
    return declared_from(get_database().get_fallback(), contract)


def measured_panel(panel: PanelCharacterization) -> MeasuredCharacterization:
    """An instrument run assembled in memory. No device is opened for it."""
    return MeasuredCharacterization(
        panel=panel,
        instrument="tests: no instrument was opened",
        steps=17,
        patch_count=68,
        white_luminance=250.0,
        black_luminance=0.05,
        contrast_ratio=5000.0,
        white_xy=(0.3127, 0.3290),
        gamma=(2.2, 2.2, 2.2),
        patch_geometry="full-field patches",
    )


def session_on(display: str = DISPLAY, panel_key: str | None = GENERIC_PANEL_KEY) -> SessionState:
    state = SessionState()
    state.selected_display_id = display
    state.selected_panel_key = panel_key
    return state


class TestTheRunThatSimulatesNoCorrection:
    """The engine seam the before figure is taken through."""

    def test_an_identity_correction_moves_a_wide_panel_off_the_corrected_run(self, engine: SensorlessEngine) -> None:
        """The before and after runs have to be two different displays.

        A P3 panel driven with no correction shows oversaturated sRGB content.
        The corrected run maps its primaries onto the target, so the two land
        in different places, and the difference is the whole of what the
        uncorrected figure reports.
        """
        panel = panel_with(P3_PRIMARIES)

        corrected = displayed(engine.verify_calibration(panel))
        bare = displayed(engine.verify_calibration(panel, correction=np.eye(3)))

        assert len(bare) == len(corrected)
        assert bare != corrected
        moved = [
            max(abs(one - other) for one, other in zip(left, right, strict=True))
            for left, right in zip(bare, corrected, strict=True)
        ]
        assert max(moved) > 1.0

    def test_an_identity_correction_leaves_an_srgb_panel_where_it_already_was(self, engine: SensorlessEngine) -> None:
        """The control on the run above: the matrix is what differs, nothing else.

        A panel whose primaries are the target primaries gets an identity
        correction computed for it anyway, so handing one in has to change
        nothing. If the two runs differed here, the before figure would be
        carrying some other difference between the code paths.
        """
        panel = panel_with(SRGB_PRIMARIES)

        corrected = displayed(engine.verify_calibration(panel))
        bare = displayed(engine.verify_calibration(panel, correction=np.eye(3)))

        assert len(bare) == len(corrected)
        moved = [
            max(abs(one - other) for one, other in zip(left, right, strict=True))
            for left, right in zip(bare, corrected, strict=True)
        ]
        assert max(moved) < 1e-6

    @pytest.mark.parametrize(
        "correction",
        [np.eye(4), np.zeros((3, 2)), np.ones(3), np.eye(3).reshape(9)],
        ids=["four-by-four", "three-by-two", "one-dimensional", "flattened"],
    )
    def test_a_correction_that_is_not_three_by_three_is_refused(
        self, engine: SensorlessEngine, correction: np.ndarray
    ) -> None:
        """A matrix of the wrong shape must not reach the chain.

        Numpy would broadcast some of these into a result rather than raising,
        which would produce a plausible before figure computed by arithmetic
        nobody wrote down.
        """
        with pytest.raises(ValueError, match="correction must be a 3x3 matrix"):
            engine.verify_calibration(panel_with(P3_PRIMARIES), correction=correction)

    def test_the_correction_argument_is_not_ignored(self, engine: SensorlessEngine) -> None:
        """FALSE-SUCCESS CONTROL.

        Catches an implementation that accepts ``correction`` and then computes
        its own matrix regardless, which is the shape of the defect this whole
        file is about: the before run would be the after run under another
        name, every uncorrected figure would equal its corrected one, and every
        display would read as needing no calibration.

        The identity run is compared against the computed run on the same panel
        and against the corrected run on an sRGB panel. Ignoring the argument
        makes the first pair equal; returning a fixed answer for every panel
        makes the second pair equal. Both are asserted apart.
        """
        wide = panel_with(P3_PRIMARIES)

        bare_wide = displayed(engine.verify_calibration(wide, correction=np.eye(3)))
        corrected_wide = displayed(engine.verify_calibration(wide))
        corrected_srgb = displayed(engine.verify_calibration(panel_with(SRGB_PRIMARIES)))

        assert bare_wide != corrected_wide
        assert bare_wide != corrected_srgb


class TestTheFigureForTheDisplayNobodyCorrected:
    """What ``predict_accuracy`` reports beside the corrected number."""

    def test_a_covered_target_reports_both_uncorrected_figures(self, swept: dict[str, VerificationResult]) -> None:
        """Both halves, labelled the way every other figure on this path is."""
        result = swept["DCI-P3"]

        average = result.uncorrected_average_delta_e
        maximum = result.uncorrected_maximum_delta_e
        assert average is not None and maximum is not None
        assert (average.unit, maximum.unit) == (DELTA_E_UNIT, DELTA_E_UNIT)
        assert average.evidence is EvidenceKind.ESTIMATED
        assert maximum.evidence is EvidenceKind.ESTIMATED
        assert average.source == MODEL_NAME
        assert maximum.source == MODEL_NAME
        assert uncorrected_maximum_of(result) >= uncorrected_average_of(result)

    def test_an_exact_srgb_panel_scores_zero_before_and_after(self, swept: dict[str, VerificationResult]) -> None:
        """A display that already reproduces the target has nothing to gain.

        Both figures are zero, which is the case the pair exists to tell apart
        from a corrected wide panel that also reports zero after.
        """
        result = swept["sRGB"]

        assert average_of(result) == pytest.approx(0.0, abs=NOISE)
        assert uncorrected_average_of(result) == pytest.approx(0.0, abs=NOISE)
        assert uncorrected_maximum_of(result) == pytest.approx(0.0, abs=NOISE)

    def test_a_wider_gamut_raises_the_uncorrected_figure(self, swept: dict[str, VerificationResult]) -> None:
        """The before figure is a property of the panel, and it has to move.

        Ordering is asserted first because it is the claim: a display further
        from the target reads further from it. The magnitudes follow, with a
        tolerance, so a colour-science change that shifts a digit does not fail
        this while a change that flattens the sweep does.
        """
        srgb = uncorrected_average_of(swept["sRGB"])
        p3 = uncorrected_average_of(swept["DCI-P3"])
        rec2020 = uncorrected_average_of(swept["Rec.2020"])

        assert srgb < p3 < rec2020
        for name, result in swept.items():
            expected = EXPECTED_UNCORRECTED[name]
            assert uncorrected_average_of(result) == pytest.approx(expected, abs=MAGNITUDE_TOLERANCE), name

        assert (
            uncorrected_maximum_of(swept["sRGB"])
            < uncorrected_maximum_of(swept["DCI-P3"])
            < uncorrected_maximum_of(swept["Rec.2020"])
        )

    def test_the_corrected_figure_stays_near_zero_across_every_gamut(
        self, swept: dict[str, VerificationResult]
    ) -> None:
        """The after figure is flat, which is why it cannot be read alone."""
        for name, result in swept.items():
            assert average_of(result) < CORRECTED_CEILING, name

    def test_the_uncorrected_figure_is_not_the_corrected_one_and_not_a_constant(
        self, swept: dict[str, VerificationResult]
    ) -> None:
        """FALSE-SUCCESS CONTROL.

        Catches two stubs at once. One copies the corrected figure into the
        uncorrected field, which would pass every assertion about labels and
        presence while reporting that no display ever needed correcting. The
        other returns a fixed number for every panel, which is the shape the
        old reference-table residual had: three panels that differ visibly
        would report the same before figure and nothing comparing one panel
        against another would notice.
        """
        befores = [uncorrected_average_of(result) for result in swept.values()]
        afters = [average_of(result) for result in swept.values()]

        assert befores[1] - afters[1] > 1.0
        assert befores[2] - afters[2] > 1.0
        assert max(befores) - min(befores) > 1.0
        assert len({round(value, 3) for value in befores}) == len(befores)

    def test_an_uncovered_target_carries_no_uncorrected_figure(self, engine: SensorlessEngine) -> None:
        """A target the model does not simulate reports neither half."""
        result = predict_accuracy(engine, panel_with(P3_PRIMARIES), UNMODELLED)

        assert result.evidence is EvidenceKind.NOT_MEASURED
        assert result.uncorrected_average_delta_e is None
        assert result.uncorrected_maximum_delta_e is None
        assert not result.correction_is_established
        assert correction_note(result) is None

    def test_the_uncovered_result_itself_carries_no_uncorrected_figure(self) -> None:
        result = uncovered_result(UNMODELLED)

        assert result.uncorrected_average_delta_e is None
        assert result.uncorrected_maximum_delta_e is None


class TestWhatAResultMayCarry:
    """The rules a result enforces on itself, so no caller can half-fill it."""

    def test_an_uncorrected_average_without_its_maximum_is_refused(self) -> None:
        with pytest.raises(ValueError, match="carries both its average and its maximum, or neither"):
            built_result(uncorrected_average=metric(2.24))

    def test_an_uncorrected_maximum_without_its_average_is_refused(self) -> None:
        with pytest.raises(ValueError, match="carries both its average and its maximum, or neither"):
            built_result(uncorrected_maximum=metric(4.91))

    def test_a_result_carrying_no_figure_cannot_carry_an_uncorrected_one(self) -> None:
        """A not-measured result with a before figure would claim a comparison
        that was never run."""
        with pytest.raises(ValueError, match="cannot carry an uncorrected one either"):
            built_result(
                evidence=EvidenceKind.NOT_MEASURED,
                average=NOT_MEASURED,
                maximum=NOT_MEASURED,
                uncorrected_average=metric(2.24),
                uncorrected_maximum=metric(4.91),
            )

    def test_a_result_carrying_both_halves_is_accepted(self) -> None:
        result = built_result(uncorrected_average=metric(2.24), uncorrected_maximum=metric(4.91))

        assert uncorrected_average_of(result) == 2.24
        assert uncorrected_maximum_of(result) == 4.91


class TestWhenTheCorrectionCountsAsEstablished:
    """The one place a surface asks whether the correction did anything."""

    def test_an_srgb_panel_shows_no_established_correction(self, swept: dict[str, VerificationResult]) -> None:
        result = swept["sRGB"]

        assert uncorrected_average_of(result) - average_of(result) <= CORRECTION_THRESHOLD_DELTA_E
        assert not result.correction_is_established

    def test_a_p3_panel_shows_an_established_correction(self, swept: dict[str, VerificationResult]) -> None:
        result = swept["DCI-P3"]

        assert uncorrected_average_of(result) - average_of(result) > CORRECTION_THRESHOLD_DELTA_E
        assert result.correction_is_established

    def test_a_result_with_no_uncorrected_figure_is_never_established(self) -> None:
        assert not built_result().correction_is_established

    @pytest.mark.parametrize(
        ("gap", "established"),
        [(-0.01, False), (0.0, False), (0.01, True)],
        ids=["under", "exactly-at", "over"],
    )
    def test_the_threshold_is_the_published_one(self, gap: float, established: bool) -> None:
        """The boundary is read off the constant, not typed again here.

        Raising ``CORRECTION_THRESHOLD_DELTA_E`` without meaning to would move
        what the product calls an established correction. This fails if the
        property stops using the constant, and it keeps holding if the constant
        is deliberately changed.
        """
        before = CORRECTION_THRESHOLD_DELTA_E + gap
        result = built_result(
            average=metric(0.0),
            uncorrected_average=metric(before),
            uncorrected_maximum=metric(before * 2),
        )

        assert result.correction_is_established is established


class TestTheSentenceAnOperatorReads:
    """``correction_note``, which is the pair rendered as one line."""

    def test_no_uncorrected_figure_prints_nothing(self) -> None:
        """A hedge would be a sentence about a comparison nobody ran."""
        assert correction_note(built_result()) is None

    def test_a_display_that_needed_nothing_says_so(self, swept: dict[str, VerificationResult]) -> None:
        note = correction_note(swept["sRGB"])

        assert note is not None
        assert "already reproduces the target to 0.00 dE2000" in note
        assert "the correction has little left to change" in note

    def test_an_established_correction_names_both_numbers(self, swept: dict[str, VerificationResult]) -> None:
        """The drop is the claim, so neither number may be left out."""
        result = swept["DCI-P3"]
        note = correction_note(result)

        assert note is not None
        assert f"Uncorrected, the model puts this display {uncorrected_average_of(result):.2f} dE2000" in note
        assert f"brings it to {average_of(result):.2f} dE2000" in note
        assert "2.2" in note


class TestWhichPanelIsVerified:
    """The regression. Verification reads the record the bundle was built from."""

    @pytest.fixture
    def generator(self) -> AssetGenerator:
        return AssetGenerator(database=get_database())

    def test_a_held_declaration_is_verified_rather_than_the_panel_key(self, generator: AssetGenerator) -> None:
        """The defect, pinned.

        The session accepted a declaration, so the generator built from the
        declared record. Resolving ``selected_panel_key`` here would verify the
        generic sRGB record instead, which is a different display.
        """
        declared = declared_panel(P3_PRIMARIES)
        state = session_on()
        state.record_declaration(declared)

        panel = verification_panel(state, generator)

        assert panel is declared.panel
        assert panel.native_primaries.red == ChromaticityCoord(0.680, 0.320)
        assert panel.native_primaries.green == ChromaticityCoord(0.265, 0.690)
        key_record, _kind = generator.resolve_panel(GENERIC_PANEL_KEY)
        assert panel.native_primaries != key_record.native_primaries

    def test_a_declaration_outranks_a_matched_panel_key_too(self, generator: AssetGenerator) -> None:
        """Not only the generic key. A matched record is replaced as well."""
        declared = declared_panel(P3_PRIMARIES)
        state = session_on(panel_key=MATCHED_KEY)
        state.record_declaration(declared)

        panel = verification_panel(state, generator)

        matched, kind = generator.resolve_panel(MATCHED_KEY)
        assert kind is CharacterizationKind.MATCHED
        assert panel is declared.panel
        assert panel.name != matched.name

    def test_a_measurement_outranks_a_declaration(self, generator: AssetGenerator) -> None:
        """A reading of the unit answers what a descriptor only claims."""
        measured = measured_panel(get_builtin_panels()[MATCHED_KEY])
        state = session_on()
        state.record_declaration(declared_panel(P3_PRIMARIES))
        state.record_measurement(measured)

        panel = verification_panel(state, generator)

        assert panel is measured.panel
        assert panel.name == get_builtin_panels()[MATCHED_KEY].name

    def test_the_panel_key_answers_when_the_session_holds_neither(self, generator: AssetGenerator) -> None:
        """The third build path, which is the one the key was always right for."""
        state = session_on(panel_key=MATCHED_KEY)

        panel = verification_panel(state, generator)

        matched, _kind = generator.resolve_panel(MATCHED_KEY)
        assert panel is matched

    def test_a_session_with_no_panel_key_falls_back_to_the_generic_record(self, generator: AssetGenerator) -> None:
        state = session_on(panel_key=None)

        panel = verification_panel(state, generator)

        fallback, _kind = generator.resolve_panel(GENERIC_PANEL_KEY)
        assert panel is fallback

    def test_a_declaration_by_another_display_is_not_verified(self, generator: AssetGenerator) -> None:
        """The declaration describes one display claim about its own model.

        Selecting a second display drops it from the answer, the way it drops
        out of the build, so verification does not report a panel this session
        would not generate for.
        """
        state = session_on(panel_key=MATCHED_KEY)
        state.record_declaration(declared_panel(P3_PRIMARIES))
        state.selected_display_id = "TEST-DISPLAY-2"

        panel = verification_panel(state, generator)

        matched, _kind = generator.resolve_panel(MATCHED_KEY)
        assert panel is matched

    def test_a_measurement_of_another_display_is_not_verified(self, generator: AssetGenerator) -> None:
        state = session_on(panel_key=MATCHED_KEY)
        state.record_measurement(measured_panel(reference_panel()))
        state.selected_display_id = "TEST-DISPLAY-2"

        panel = verification_panel(state, generator)

        matched, _kind = generator.resolve_panel(MATCHED_KEY)
        assert panel is matched

    def test_verifying_the_panel_key_would_call_every_display_perfect(
        self, engine: SensorlessEngine, generator: AssetGenerator
    ) -> None:
        """FALSE-SUCCESS CONTROL, and the reason this file exists.

        Catches ``verification_panel`` reverting to ``resolve_panel`` on the
        session key. That version reports zero corrected and zero uncorrected
        for a declared wide-gamut display, because the generic record is exact
        sRGB and scores perfectly against an sRGB reference no matter what is
        plugged in. Nothing about the number would look wrong, which is what
        makes it worse than an error.

        The two results are computed side by side so the assertion states the
        difference rather than describing it.
        """
        declared = declared_panel(P3_PRIMARIES)
        state = session_on()
        state.record_declaration(declared)

        key_record, _kind = generator.resolve_panel(state.selected_panel_key or GENERIC_PANEL_KEY)
        by_key = predict_accuracy(engine, key_record, MODELLED)
        by_build = predict_accuracy(engine, verification_panel(state, generator), MODELLED)

        assert average_of(by_key) == pytest.approx(0.0, abs=NOISE)
        assert uncorrected_average_of(by_key) == pytest.approx(0.0, abs=CORRECTION_THRESHOLD_DELTA_E)
        assert not by_key.correction_is_established

        assert uncorrected_average_of(by_build) == pytest.approx(
            EXPECTED_UNCORRECTED["DCI-P3"], abs=MAGNITUDE_TOLERANCE
        )
        assert by_build.correction_is_established
        assert uncorrected_average_of(by_build) - uncorrected_average_of(by_key) > 2.0
