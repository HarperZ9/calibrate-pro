"""What a bundle becomes when the display's own descriptor is what it was built from.

A declaration is the middle case between a panel record and an instrument run.
The numbers came off the display over its own cable, so they describe the model
its manufacturer shipped rather than a nominal sRGB panel, and that is enough to
generate a real gamut clamp for a monitor no record matches. What it is not is a
reading of the unit on the desk, so the evidence label must not move.

These tests hold three things the manifest's reader depends on. The
``EDID_DECLARED`` label cannot be set without the declaration behind it, the
declared numbers travel into the manifest at the precision the digest is taken
over, and the artifacts differ from the ones the panel database would have
produced. The last is the one that separates a correction from a relabel.

Nothing here opens a display. The declarations are built from descriptor fields
handed in as plain data, which is the same seam ``detection`` writes into.
"""

from __future__ import annotations

import json

import pytest

from calibrate_pro.application import generation
from calibrate_pro.application.assets import (
    AssetFormat,
    AssetGenerationError,
    AssetGenerator,
    AssetRequest,
    GeneratedAssets,
    build_manifest,
)
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.contracts import PanelCharacterization as DeclaredContract
from calibrate_pro.application.declaration import DeclaredCharacterization, declared_from
from calibrate_pro.application.detection import characterization_from_edid
from calibrate_pro.application.measurement import (
    MeasuredCharacterization,
    measure_characterization,
)
from calibrate_pro.application.session import SessionState
from calibrate_pro.panels.database import GENERIC_PANEL_KEY, get_database
from calibrate_pro.verification.provenance import EvidenceKind
from calibrate_pro.workflow import CalibrationMethod
from tests.measurement_support import SyntheticDisplay, base_panel

DISPLAY_ID = "FAKE-DECLARED-DISPLAY"
OTHER_DISPLAY_ID = "FAKE-SECOND-DISPLAY"
PRESET = "calibration.preset.srgb_web"

#: A wide-gamut descriptor. The primaries are well outside sRGB, so the sRGB
#: target has something to clamp and the declared cube cannot come out equal to
#: the generic one by coincidence.
WIDE_RED = ("0.68001234", "0.31991234")
WIDE_GREEN = ("0.26501234", "0.69001234")
WIDE_BLUE = ("0.15001234", "0.06001234")
D65 = ("0.31271234", "0.32901234")
DECLARED_GAMMA = "2.20001234"

PROVENANCE = "edid:ACM1234 WideVision 27"

#: Every field ``_manifest_declaration`` is allowed to write. The set is
#: asserted rather than sampled, so a later field carrying a unit identifier
#: fails this module instead of reaching a file an operator may publish.
DECLARATION_FIELDS = frozenset({"provenance", "red_xy", "green_xy", "blue_xy", "white_xy", "gamma"})

#: Serial fields a parsed descriptor carries. They identify one person's
#: hardware, and no path from a descriptor to a manifest may carry them.
SERIAL_NUMBER = 1234567890
SERIAL_STRING = "SN-UNIT-90210"


def contract(
    *,
    provenance: str = PROVENANCE,
    red: tuple[str, str] = WIDE_RED,
    green: tuple[str, str] = WIDE_GREEN,
    blue: tuple[str, str] = WIDE_BLUE,
    white: tuple[str, str] = D65,
    gamma: str = DECLARED_GAMMA,
) -> DeclaredContract:
    """One descriptor as the application contract spells it."""
    return DeclaredContract(
        kind=CharacterizationKind.EDID_DECLARED,
        provenance=provenance,
        red_xy=red,
        green_xy=green,
        blue_xy=blue,
        white_xy=white,
        nominal_gamma=gamma,
    )


def declaration_from(characterization: DeclaredContract) -> DeclaredCharacterization:
    """Build the record one descriptor describes, over the generic base."""
    return declared_from(get_database().get_fallback(), characterization)


def request_for(panel_key: str = GENERIC_PANEL_KEY, *, display_id: str = DISPLAY_ID) -> AssetRequest:
    return AssetRequest(
        display_id=display_id,
        panel_key=panel_key,
        preset_id=PRESET,
        formats=(AssetFormat.CUBE,),
        lut_size=17,
    )


def manifest_of(generated: GeneratedAssets) -> dict:
    return json.loads(build_manifest(generated).decode("utf-8"))


def session_holding(
    declared: DeclaredCharacterization | None,
    *,
    declared_display_id: str | None = DISPLAY_ID,
) -> SessionState:
    """A session that selected one display and may hold a declaration by another."""
    state = SessionState()
    state.selected_display_id = DISPLAY_ID
    state.selected_panel_key = GENERIC_PANEL_KEY
    state.selected_preset_id = PRESET
    state.declared_characterization = declared
    state.declared_display_id = None if declared is None else declared_display_id
    return state


@pytest.fixture(scope="module")
def generator() -> AssetGenerator:
    return AssetGenerator()


@pytest.fixture(scope="module")
def declared() -> DeclaredCharacterization:
    return declaration_from(contract())


@pytest.fixture(scope="module")
def measured() -> MeasuredCharacterization:
    """One run against the arithmetic display the measurement suite shares.

    Nothing here reads a colorimeter. The run exists only so the exclusivity
    check has a real measurement to refuse a declaration beside.
    """
    display = SyntheticDisplay()
    return measure_characterization(
        instrument=display,
        patches=display,
        base=base_panel(),
        steps=5,
        settle=lambda: None,
    )


# The label cannot exist without the declaration ---------------------------


def test_a_declared_label_without_the_declaration_behind_it_is_refused(generator: AssetGenerator) -> None:
    """The invariant every test below reaches the label through.

    A caller assembling this value by hand could otherwise set EDID_DECLARED on
    a bundle nothing declared anything about, which is the manifest claiming a
    source it does not carry.
    """
    built = generator.generate(request_for())

    with pytest.raises(ValueError, match="requires the declaration it came from"):
        GeneratedAssets(
            request=built.request,
            assets=built.assets,
            panel_name=f"{built.panel_name} (declared)",
            characterization_kind=CharacterizationKind.EDID_DECLARED,
            evidence_kind=EvidenceKind.ESTIMATED,
            gamut_mode=built.gamut_mode,
            tone_response=built.tone_response,
            applied_gamma_exponent=built.applied_gamma_exponent,
            white_point=built.white_point,
        )


def test_a_declaration_carried_under_another_label_is_refused(
    generator: AssetGenerator, declared: DeclaredCharacterization
) -> None:
    """The guard runs in both directions.

    A bundle holding a declaration but labeled generic would put the declared
    primaries into the manifest of something a reader was told came from the
    shipped record.
    """
    built = generator.generate(request_for())

    with pytest.raises(ValueError, match="requires the declaration it came from"):
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
            declaration=declared,
        )


def test_a_declaration_that_is_not_one_is_refused(generator: AssetGenerator) -> None:
    """A value shaped like a declaration, that no descriptor produced."""
    built = generator.generate(request_for())

    with pytest.raises(TypeError, match="declaration must be a DeclaredCharacterization or None"):
        GeneratedAssets(
            request=built.request,
            assets=built.assets,
            panel_name=built.panel_name,
            characterization_kind=CharacterizationKind.EDID_DECLARED,
            evidence_kind=EvidenceKind.ESTIMATED,
            gamut_mode=built.gamut_mode,
            tone_response=built.tone_response,
            applied_gamma_exponent=built.applied_gamma_exponent,
            white_point=built.white_point,
            declaration="the display said so",
        )


# What generate accepts -----------------------------------------------------


def test_a_measured_build_takes_no_declaration(
    generator: AssetGenerator,
    declared: DeclaredCharacterization,
    measured: MeasuredCharacterization,
) -> None:
    """The two evidence arguments are exclusive, and the refusal says why.

    A run of the unit has already answered the question a descriptor only
    claims to, so handing the generator both would ask it to build from two
    descriptions of one panel.
    """
    with pytest.raises(AssetGenerationError) as refusal:
        generator.generate(request_for(), measured=measured, declared=declared)

    assert str(refusal.value) == "a measured build reads the display itself, so it takes no declaration"


def test_generating_from_something_that_is_not_a_declaration_is_refused(generator: AssetGenerator) -> None:
    with pytest.raises(TypeError, match="declared must be a DeclaredCharacterization or None"):
        generator.generate(request_for(), declared="the display said so")


# A bundle a declaration produced -------------------------------------------


def test_a_declared_bundle_names_the_display_that_declared_it(
    generator: AssetGenerator, declared: DeclaredCharacterization
) -> None:
    """The marker is on the label, not written into the record's own fields."""
    generated = generator.generate(request_for(), declared=declared)

    assert generated.panel_name == f"{declared.panel.name} (declared)"
    assert generated.panel_name.endswith(" (declared)")
    assert generated.characterization_kind is CharacterizationKind.EDID_DECLARED
    assert generated.declaration is declared, "the bundle holds the declaration, not a copy of its labels"
    assert "declared" not in declared.panel.manufacturer.lower()
    assert "declared" not in declared.panel.model_pattern.lower()


def test_a_descriptor_is_not_a_reading(generator: AssetGenerator, declared: DeclaredCharacterization) -> None:
    """FALSE-SUCCESS CONTROL.

    This catches an implementation that promotes the evidence label along with
    the characterization label on the declared path, which is the one mistake
    that would let a monitor's own marketing numbers be reported as a
    colorimeter run. The negative assertion is the load-bearing one: a stub
    returning MEASURED for every build would satisfy any test that only checked
    the characterization kind.
    """
    generated = generator.generate(request_for(), declared=declared)

    assert generated.evidence_kind is EvidenceKind.ESTIMATED
    assert generated.evidence_kind is not EvidenceKind.MEASURED
    assert generated.characterization_kind is not CharacterizationKind.MEASURED
    assert generated.measurement is None
    assert manifest_of(generated)["evidence_kind"] == EvidenceKind.ESTIMATED.value
    assert "measurement" not in manifest_of(generated)


# The manifest block --------------------------------------------------------


def test_the_manifest_names_what_the_display_declared(
    generator: AssetGenerator, declared: DeclaredCharacterization
) -> None:
    """Enough of the declaration for a reader to check the correction against it."""
    document = manifest_of(generator.generate(request_for(), declared=declared))
    block = document["declaration"]

    assert block["provenance"] == PROVENANCE
    assert block["red_xy"] == [0.680012, 0.319912]
    assert block["green_xy"] == [0.265012, 0.690012]
    assert block["blue_xy"] == [0.150012, 0.060012]
    assert block["white_xy"] == [0.312712, 0.329012]
    assert block["gamma"] == 2.2
    assert document["characterization_kind"] == CharacterizationKind.EDID_DECLARED.value
    assert document["panel_name"] == f"{declared.panel.name} (declared)"


def test_a_manifest_without_a_declaration_carries_no_declaration_block(generator: AssetGenerator) -> None:
    """An absent key, not a block of nulls.

    A reader asking whether a bundle was built from a descriptor asks whether
    the key is there. A block present with empty fields answers that wrongly.
    """
    document = manifest_of(generator.generate(request_for()))

    assert "declaration" not in document
    assert document["characterization_kind"] == CharacterizationKind.EXPLICIT_GENERIC.value


def test_the_declaration_block_rounds_the_numbers_the_digest_is_taken_over(
    generator: AssetGenerator, declared: DeclaredCharacterization
) -> None:
    """The manifest is compared by digest, so trailing descriptor digits are dropped.

    The assertion that the rounding is doing something is the last one: the
    declaration really does carry numbers the block does not repeat verbatim.
    """
    block = manifest_of(generator.generate(request_for(), declared=declared))["declaration"]

    assert block["red_xy"] == [round(value, 6) for value in declared.red_xy]
    assert block["green_xy"] == [round(value, 6) for value in declared.green_xy]
    assert block["blue_xy"] == [round(value, 6) for value in declared.blue_xy]
    assert block["white_xy"] == [round(value, 6) for value in declared.white_xy]
    assert block["gamma"] == round(declared.gamma, 4)
    assert block["red_xy"] != list(declared.red_xy), "nothing was rounded, so this test is not watching the rounding"
    assert block["gamma"] != declared.gamma


def test_the_declaration_block_names_a_model_and_never_a_unit(generator: AssetGenerator) -> None:
    """Nothing identifying the operator's hardware reaches a file they may publish.

    The descriptor handed in carries both serial fields a parsed EDID holds.
    The manifest is searched as text rather than by key, so a serial reaching
    it through the provenance string fails this too.
    """
    characterization, _note = characterization_from_edid(
        {
            "manufacturer_code": "ACM",
            "product_code": 0x1234,
            "monitor_name": "WideVision 27",
            "serial_number": SERIAL_NUMBER,
            "serial_string": SERIAL_STRING,
            "gamma": 2.2,
            "srgb_default": False,
            "chromaticity": {
                "red": (0.68, 0.32),
                "green": (0.265, 0.69),
                "blue": (0.15, 0.06),
                "white": (0.3127, 0.329),
            },
        }
    )
    assert characterization is not None, "the descriptor under test declared nothing"
    payload = build_manifest(generator.generate(request_for(), declared=declaration_from(characterization)))
    document = json.loads(payload.decode("utf-8"))

    assert set(document["declaration"]) == DECLARATION_FIELDS
    assert document["declaration"]["provenance"] == "edid:ACM1234 WideVision 27"
    assert SERIAL_STRING not in payload.decode("utf-8")
    assert str(SERIAL_NUMBER) not in payload.decode("utf-8")
    assert "serial" not in payload.decode("utf-8").lower()


def test_two_different_declarations_do_not_produce_one_block(generator: AssetGenerator) -> None:
    """FALSE-SUCCESS CONTROL.

    A block filled from constants, or one that echoed the generic record
    instead of the declaration, would satisfy every field assertion above on a
    single fixture. Two descriptors that disagree have to disagree here.
    """
    wide = manifest_of(generator.generate(request_for(), declared=declaration_from(contract())))
    narrow = manifest_of(
        generator.generate(
            request_for(),
            declared=declaration_from(
                contract(
                    provenance="edid:BNQ5678 NarrowVision 24",
                    red=("0.6400", "0.3300"),
                    green=("0.3000", "0.6000"),
                    gamma="2.4000",
                )
            ),
        )
    )

    assert wide["declaration"] != narrow["declaration"]
    assert wide["declaration"]["red_xy"] != narrow["declaration"]["red_xy"]
    assert wide["declaration"]["gamma"] != narrow["declaration"]["gamma"]
    assert wide["declaration"]["provenance"] != narrow["declaration"]["provenance"]


# Which build path reads a declaration --------------------------------------


def test_the_measured_method_reads_no_declaration(declared: DeclaredCharacterization) -> None:
    """A reading of the unit outranks a claim about the model.

    The session holds a declaration that matches the selected display, and the
    measured path still passes None, so the generator is never handed two
    descriptions of one panel.
    """
    state = session_holding(declared)

    assert state.declaration_matches_selection is True
    assert generation._declaration_for(state, CalibrationMethod.MEASURED) is None


def test_a_declaration_by_another_display_is_not_read(declared: DeclaredCharacterization) -> None:
    """Absence is not a refusal, but a mismatch is not a match either.

    A declaration recorded against one monitor must not build a bundle for the
    one selected now, or the manifest would carry primaries the selected
    display never claimed.
    """
    state = session_holding(declared, declared_display_id=OTHER_DISPLAY_ID)

    assert state.declaration_matches_selection is False
    assert generation._declaration_for(state, CalibrationMethod.SENSORLESS) is None


def test_the_sensorless_method_reads_a_matching_declaration(declared: DeclaredCharacterization) -> None:
    state = session_holding(declared)

    assert generation._declaration_for(state, CalibrationMethod.SENSORLESS) is declared


def test_a_sensorless_session_with_no_declaration_builds_from_the_record(generator: AssetGenerator) -> None:
    """The path a matched display and an accepted generic record both take."""
    state = session_holding(None)

    assert generation._declaration_for(state, CalibrationMethod.SENSORLESS) is None
    assert generator.generate(request_for()).declaration is None


# The declaration shaped the artifact, not only the label -------------------


def test_a_declared_bundle_is_not_the_generic_one_with_a_label_changed(
    generator: AssetGenerator, declared: DeclaredCharacterization
) -> None:
    """FALSE-SUCCESS CONTROL, and the claim the whole feature rests on.

    A generator that took the declaration, set the label from it and then built
    the cube from the panel record would pass every label and manifest test in
    this module. It fails here: the declared primaries sit well outside sRGB, so
    clamping to the sRGB target has to move output codes the generic record
    leaves alone.
    """
    generic = generator.generate(request_for())
    from_descriptor = generator.generate(request_for(), declared=declared)

    assert from_descriptor.assets[AssetFormat.CUBE] != generic.assets[AssetFormat.CUBE]
    assert from_descriptor.digest_for(AssetFormat.CUBE) != generic.digest_for(AssetFormat.CUBE)
    assert from_descriptor.cube_changes_output is True
    assert generic.cube_changes_output is False, "the generic record on its own target is the identity cube"


def test_two_bundles_from_the_same_declaration_are_byte_identical(
    generator: AssetGenerator, declared: DeclaredCharacterization
) -> None:
    """A declared build is as reproducible as a generic one, manifest included."""
    first = generator.generate(request_for(), declared=declared)
    second = generator.generate(request_for(), declared=declared)

    assert first.assets[AssetFormat.CUBE] == second.assets[AssetFormat.CUBE]
    assert build_manifest(first) == build_manifest(second)


def test_the_manifest_keeps_the_record_key_the_declaration_refined(
    generator: AssetGenerator, declared: DeclaredCharacterization
) -> None:
    """The descriptor corrected a starting point rather than replacing it.

    Rewriting the key would lose which record was corrected, which is what a
    reader needs in order to judge the correction.
    """
    document = manifest_of(generator.generate(request_for("AW3423DW"), declared=declared))

    assert document["panel_key"] == "AW3423DW"
    assert document["display_id"] == DISPLAY_ID
    assert document["declaration"]["provenance"] == PROVENANCE
