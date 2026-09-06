"""What changes in a bundle when an instrument read the display.

A generated bundle is a file an operator loads into a display pipeline, and the
manifest beside it is the only thing that says where its numbers came from. So
the word "measured" on that manifest has to mean a run happened, has to name the
device that ran, and has to describe artifacts the run actually shaped. A bundle
that carried the label without the reading would be the exact claim this product
must not be able to make.

These tests build both bundles from the same request and compare them. The run
is arithmetic, driven against the synthetic display the measurement suite shares,
so no colorimeter is opened here and nothing below establishes that a real one
reads a display correctly. What it establishes is narrower and is the part a
reader of the manifest depends on: the label cannot be set without the run, the
run's own numbers travel with it, and the artifacts differ from the ones the
panel database would have produced.
"""

from __future__ import annotations

import json

import pytest

from calibrate_pro.application.assets import (
    MANIFEST_SCHEMA,
    AssetFormat,
    AssetGenerator,
    AssetRequest,
    GeneratedAssets,
    build_manifest,
)
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.measurement import (
    MeasuredCharacterization,
    measure_characterization,
)
from calibrate_pro.verification.provenance import EvidenceKind
from tests.measurement_support import SyntheticDisplay, base_panel

DISPLAY_ID = "FAKE-ACCEPTANCE-DISPLAY"
PRESET = "calibration.preset.srgb_web"
GENERIC = "GENERIC_SRGB"
#: A record in the shipped database, used where a test needs a key that is not
#: the fallback and is not the unit the run measured.
CATALOGUED = "AW3423DW"
STEPS = 5


def run_against(display: SyntheticDisplay) -> MeasuredCharacterization:
    """One measurement run, settling instantly because nothing is on screen."""
    return measure_characterization(
        instrument=display,
        patches=display,
        base=base_panel(),
        steps=STEPS,
        settle=lambda: None,
    )


def request_for(panel_key: str = GENERIC, *, preset: str = PRESET) -> AssetRequest:
    return AssetRequest(
        display_id=DISPLAY_ID,
        panel_key=panel_key,
        preset_id=preset,
        formats=(AssetFormat.CUBE,),
        lut_size=17,
    )


@pytest.fixture(scope="module")
def generator() -> AssetGenerator:
    return AssetGenerator()


@pytest.fixture(scope="module")
def measured() -> MeasuredCharacterization:
    return run_against(SyntheticDisplay())


def manifest_of(generated: GeneratedAssets) -> dict:
    return json.loads(build_manifest(generated).decode("utf-8"))


# A bundle nobody measured -------------------------------------------------


def test_a_bundle_built_without_a_run_is_labeled_estimated(generator: AssetGenerator) -> None:
    generated = generator.generate(request_for())

    assert generated.evidence_kind is EvidenceKind.ESTIMATED
    assert generated.characterization_kind is not CharacterizationKind.MEASURED
    assert generated.measurement is None
    assert "measured" not in generated.panel_name.lower()


def test_a_manifest_without_a_run_carries_no_measurement_block(generator: AssetGenerator) -> None:
    """An absent block, not a block of nulls.

    A reader checking whether a bundle was measured checks for the key. A block
    present with empty fields would answer that question wrongly.
    """
    document = manifest_of(generator.generate(request_for()))

    assert "measurement" not in document
    assert document["schema"] == MANIFEST_SCHEMA
    assert document["evidence_kind"] == EvidenceKind.ESTIMATED.value


# A bundle a run produced ---------------------------------------------------


def test_a_bundle_built_from_a_run_is_labeled_measured(
    generator: AssetGenerator, measured: MeasuredCharacterization
) -> None:
    generated = generator.generate(request_for(), measured=measured)

    assert generated.evidence_kind is EvidenceKind.MEASURED
    assert generated.characterization_kind is CharacterizationKind.MEASURED
    assert generated.measurement is measured, "the bundle holds the run, not a copy of its labels"


def test_the_measured_marker_is_on_the_label_and_not_in_the_panel_record(
    generator: AssetGenerator, measured: MeasuredCharacterization
) -> None:
    """The record names which product this is; the label says what happened to it.

    Writing the marker into the record would put the word inside the field a
    later lookup matches a product by.
    """
    generated = generator.generate(request_for(), measured=measured)

    assert generated.panel_name == f"{measured.panel.name} (measured)"
    assert "measured" not in measured.panel.manufacturer.lower()
    assert "measured" not in measured.panel.model_pattern.lower()
    assert "measured" not in measured.panel.display_name.lower()


def test_the_manifest_names_the_instrument_and_what_it_read(
    generator: AssetGenerator, measured: MeasuredCharacterization
) -> None:
    """Enough of the run for a reader to repeat it and disagree with the result."""
    block = manifest_of(generator.generate(request_for(), measured=measured))["measurement"]

    assert block["instrument"] == measured.instrument
    assert block["ramp_steps"] == STEPS
    assert block["patch_count"] == measured.patch_count
    assert block["patch_geometry"] == measured.patch_geometry, "an OLED peak depends on the field it was read from"
    assert block["white_luminance_cd_m2"] == pytest.approx(250.05)
    assert block["black_luminance_cd_m2"] == pytest.approx(0.05)
    assert block["contrast_ratio"] == pytest.approx(5001.0)
    assert block["white_xy"] == [pytest.approx(0.3127), pytest.approx(0.329)]
    assert block["gamma"] == [pytest.approx(2.2), pytest.approx(2.24), pytest.approx(2.18)]


def test_the_manifest_rounds_to_the_precision_a_colorimeter_delivers(
    generator: AssetGenerator, measured: MeasuredCharacterization
) -> None:
    """The manifest is compared by digest, so trailing sensor noise is dropped.

    The assertion that the rounding is doing something is the last one: the run
    really does carry a gamma the block does not repeat verbatim.
    """
    block = manifest_of(generator.generate(request_for(), measured=measured))["measurement"]

    assert block["white_luminance_cd_m2"] == round(measured.white_luminance, 4)
    assert block["black_luminance_cd_m2"] == round(measured.black_luminance, 4)
    assert block["contrast_ratio"] == round(measured.contrast_ratio, 1)
    assert block["white_xy"] == [round(value, 6) for value in measured.white_xy]
    assert block["gamma"] == [round(value, 4) for value in measured.gamma]
    assert block["gamma"] != list(measured.gamma), "nothing was rounded, so this module is not watching the rounding"


def test_a_run_that_could_not_tell_black_from_no_light_reports_no_contrast_ratio(
    generator: AssetGenerator,
) -> None:
    """None rather than a number, because the floor was not resolved.

    A zero reading means the instrument did not separate black from no light. A
    ratio computed against it would be infinite, and writing a very large finite
    number in its place would report an unbounded contrast as a measurement.
    """
    dark = run_against(SyntheticDisplay(black_luminance=0.0))
    block = manifest_of(generator.generate(request_for(), measured=dark))["measurement"]

    assert dark.contrast_ratio is None
    assert block["contrast_ratio"] is None
    assert block["black_luminance_cd_m2"] == 0.0


def test_the_manifest_keeps_the_record_key_the_run_refined(
    generator: AssetGenerator, measured: MeasuredCharacterization
) -> None:
    """The measurement corrected a starting point rather than replacing it.

    Rewriting the key to something that says measured would lose which record
    was corrected, which is what a reader needs to judge the correction.
    """
    document = manifest_of(generator.generate(request_for(CATALOGUED), measured=measured))

    assert document["panel_key"] == CATALOGUED
    assert document["display_id"] == DISPLAY_ID
    assert document["characterization_kind"] == CharacterizationKind.MEASURED.value
    assert document["evidence_kind"] == EvidenceKind.MEASURED.value


# The run shaped the artifact, not only the label ---------------------------


def test_a_measured_bundle_is_not_the_sensorless_one_with_a_label_changed(
    generator: AssetGenerator, measured: MeasuredCharacterization
) -> None:
    """The claim under test, at the level of bytes.

    If these matched, the word measured on the manifest would be describing a
    file the run had no part in producing.
    """
    estimated = generator.generate(request_for())
    from_run = generator.generate(request_for(), measured=measured)

    assert from_run.assets[AssetFormat.CUBE] != estimated.assets[AssetFormat.CUBE]
    assert from_run.digest_for(AssetFormat.CUBE) != estimated.digest_for(AssetFormat.CUBE)


def test_the_artifacts_come_from_the_run_rather_than_the_named_record(
    generator: AssetGenerator, measured: MeasuredCharacterization
) -> None:
    """Two different records, one run, identical artifacts.

    The measured build corrects the unit the instrument read. A record the
    request happened to name cannot move the numbers, or a mismatched key would
    quietly change a profile that claims to describe this display.
    """
    generic = generator.generate(request_for(GENERIC), measured=measured)
    catalogued = generator.generate(request_for(CATALOGUED), measured=measured)

    assert generic.assets[AssetFormat.CUBE] == catalogued.assets[AssetFormat.CUBE]
    assert generic.panel_name == catalogued.panel_name
    assert manifest_of(generic)["panel_key"] != manifest_of(catalogued)["panel_key"]


def test_a_different_display_produces_a_different_measurement_block(generator: AssetGenerator) -> None:
    """The false-success control on the block.

    A block filled from constants would pass every assertion above. Two runs of
    displays that differ have to disagree in the manifest.
    """
    bright = manifest_of(generator.generate(request_for(), measured=run_against(SyntheticDisplay())))
    dim = manifest_of(
        generator.generate(
            request_for(),
            measured=run_against(SyntheticDisplay(white_luminance=120.0, gamma=(2.4, 2.4, 2.4))),
        )
    )

    assert bright["measurement"] != dim["measurement"]
    assert bright["measurement"]["white_luminance_cd_m2"] != dim["measurement"]["white_luminance_cd_m2"]
    assert bright["measurement"]["gamma"] != dim["measurement"]["gamma"]


# Two builds of one run -----------------------------------------------------


def test_two_bundles_from_the_same_run_are_byte_identical(
    generator: AssetGenerator, measured: MeasuredCharacterization
) -> None:
    """A measured build is as reproducible as a sensorless one.

    The manifest carries no wall clock, so a reader who rebuilds from the same
    run and the same request gets the same digest or has found a real change.
    """
    first = generator.generate(request_for(), measured=measured)
    second = generator.generate(request_for(), measured=measured)

    assert first.assets[AssetFormat.CUBE] == second.assets[AssetFormat.CUBE]
    assert build_manifest(first) == build_manifest(second)


# What the labels cannot be set to ------------------------------------------


def test_a_measured_label_without_the_run_behind_it_is_refused(generator: AssetGenerator) -> None:
    """The false-success control on the whole module.

    Every test above reaches the measured label through `generate`, which sets
    it from the argument carrying the run. This is the assertion that the label
    cannot be reached any other way.
    """
    built = generator.generate(request_for())

    with pytest.raises(ValueError, match="requires the measurement it came from"):
        GeneratedAssets(
            request=built.request,
            assets=built.assets,
            panel_name=f"{built.panel_name} (measured)",
            characterization_kind=CharacterizationKind.MEASURED,
            evidence_kind=EvidenceKind.MEASURED,
            gamut_mode=built.gamut_mode,
            tone_response=built.tone_response,
            applied_gamma_exponent=built.applied_gamma_exponent,
            white_point=built.white_point,
        )


def test_measured_evidence_without_the_run_behind_it_is_refused(generator: AssetGenerator) -> None:
    """The evidence label is guarded separately from the characterization label."""
    built = generator.generate(request_for())

    with pytest.raises(ValueError, match="MEASURED evidence requires"):
        GeneratedAssets(
            request=built.request,
            assets=built.assets,
            panel_name=built.panel_name,
            characterization_kind=built.characterization_kind,
            evidence_kind=EvidenceKind.MEASURED,
            gamut_mode=built.gamut_mode,
            tone_response=built.tone_response,
            applied_gamma_exponent=built.applied_gamma_exponent,
            white_point=built.white_point,
        )


def test_a_run_carried_under_an_estimated_label_is_refused(
    generator: AssetGenerator, measured: MeasuredCharacterization
) -> None:
    """The guard runs in both directions.

    A bundle holding a run but labeled estimated would put the measurement into
    the manifest of something a reader was told to treat as modeled.
    """
    built = generator.generate(request_for())

    with pytest.raises(ValueError):
        GeneratedAssets(
            request=built.request,
            assets=built.assets,
            panel_name=built.panel_name,
            characterization_kind=CharacterizationKind.EXPLICIT_GENERIC,
            evidence_kind=EvidenceKind.ESTIMATED,
            gamut_mode=built.gamut_mode,
            tone_response=built.tone_response,
            applied_gamma_exponent=built.applied_gamma_exponent,
            white_point=built.white_point,
            measurement=measured,
        )


def test_a_measurement_that_is_not_a_run_is_refused(generator: AssetGenerator) -> None:
    """A value shaped like a run, that no measurement produced."""
    built = generator.generate(request_for())

    with pytest.raises(TypeError, match="MeasuredCharacterization"):
        GeneratedAssets(
            request=built.request,
            assets=built.assets,
            panel_name=built.panel_name,
            characterization_kind=CharacterizationKind.MEASURED,
            evidence_kind=EvidenceKind.MEASURED,
            gamut_mode=built.gamut_mode,
            tone_response=built.tone_response,
            applied_gamma_exponent=built.applied_gamma_exponent,
            white_point=built.white_point,
            measurement="a colorimeter said so",
        )


def test_generating_from_something_that_is_not_a_run_is_refused(generator: AssetGenerator) -> None:
    with pytest.raises(TypeError, match="MeasuredCharacterization"):
        generator.generate(request_for(), measured="a colorimeter said so")
