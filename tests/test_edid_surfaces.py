"""Accepting a display's own declaration, from the gate through to the terminal.

Three surfaces decide what happens when a monitor no panel record matches turns
out to have declared its own primaries, and all three are held down here.

The resolver decides whether the control exists at all. It is offered for a
selected display that declared something and has no characterization yet, and
each of those three conditions is closed on its own so a refusal names one
reason rather than a coincidence of several.

The service decides what accepting means. A session handed an offer records it,
a session with no offer is refused in the session's own words, and a descriptor
the declaration layer cannot build from is refused in that layer's words rather
than in a summary written here.

The command line decides how an operator asks. ``--edid`` drives the declared
path end to end, and ``--generic --edid`` is refused before anything is detected
because the line named two different descriptions of one panel.

Nothing here opens a display. Every observation arrives from an injected
enumerator, the descriptor is a byte string this file builds, and the capability
probe proves nothing, so no LUT is loaded, no DDC value is written and no
colorimeter is opened.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

import pytest

from calibrate_pro.application.actions import (
    SENSORLESS_CHARACTERIZATIONS,
    ActionContext,
    ActionDisposition,
    ActionRegistry,
)
from calibrate_pro.application.composition import _engine_and_generator, _runner
from calibrate_pro.application.contracts import (
    CapabilityState,
    CharacterizationKind,
    DashboardModel,
    DisplayObservation,
    PanelCharacterization,
)
from calibrate_pro.application.detection import (
    DeniedCapabilityProbe,
    DetectionResult,
    DisplayDetector,
)
from calibrate_pro.application.journal import DiagnosticJournal
from calibrate_pro.application.outcomes import ActionError, ActionOutcome
from calibrate_pro.application.refusals import NO_DECLARATION
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import SessionState
from calibrate_pro.commands import session as commands
from calibrate_pro.commands.session import BOTH_CHARACTERIZATIONS, CommandError, target_action
from calibrate_pro.main import main
from calibrate_pro.panels.database import get_database
from calibrate_pro.panels.detection import DisplayInfo
from calibrate_pro.workflow import CalibrationMethod, WorkflowStage
from tests.action_context_support import action_context
from tests.session_support import PRESET, arguments, field

USE_EDID = "display.characterization.use_edid"
USE_GENERIC = "display.characterization.use_generic"
SENSORLESS_METHOD = "calibration.method.sensorless"
MEASURED_METHOD = "calibration.method.measured"

#: The manifest's own sentence for a declaration control that cannot be used.
#: Read from the resource rather than paraphrased, because it is what the
#: operator sees under a disabled control and after attempting the action.
DECLARATION_UNAVAILABLE = (
    "Accepting a display's own declaration requires an uncharacterized selected display that declared one."
)

#: What the session says when the control was pressed against a display that
#: declared nothing this build could read.
NO_DECLARATION_SUMMARY = "The selected display declared no primaries or transfer this build could read."

#: The reason the declaration layer gives for three primaries on a line, which
#: the service passes through instead of summarizing.
COLLAPSED_GAMUT = "the declared primaries enclose 0.0000, too little to be three separate colours"

REGISTRY = ActionRegistry.load_default()

#: Named the way the production enumerator is named, so a journal record says
#: where the display came from rather than leaving it to be inferred.
ENUMERATOR_NAME = "tests.test_edid_surfaces:declared_display"

_PROBE_REASON = "no capability is probed under test"

#: The display these tests observe. No panel database key, no model and no
#: monitor name, so the panel match fails and the session starts uncharacterized,
#: which is the only state the declaration control is offered from.
DECLARED_DISPLAY = DisplayInfo(
    device_name="\\\\.\\DISPLAY1",
    device_string="tests:no adapter was opened",
    monitor_name="",
    device_id="",
    is_primary=True,
    is_active=True,
    width=3840,
    height=2160,
    refresh_rate=60,
    bit_depth=8,
    position_x=0,
    position_y=0,
)

#: What the descriptor this file builds declares. Wider than sRGB on purpose,
#: so a bundle built from the declaration cannot be mistaken for one built from
#: the generic record.
DECLARED_RED = (0.680, 0.320)
DECLARED_GREEN = (0.265, 0.690)
DECLARED_BLUE = (0.150, 0.060)
DECLARED_WHITE = (0.3127, 0.3290)
DECLARED_GAMMA = 2.2

#: The label the descriptor's manufacturer and product codes spell, and the
#: provenance every surface prints for a characterization read off it.
DECLARED_LABEL = "TST002A"
DECLARED_PROVENANCE = f"edid:{DECLARED_LABEL}"

#: The name the panel record built from the declaration carries, which is the
#: vendor code and the product code the descriptor named and nothing else.
DECLARED_PANEL_NAME = "TST 002A"

_EDID_HEADER = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00])

#: Where each ten-bit chromaticity fraction sits: the byte holding its top
#: eight bits, then the byte and shift holding its low two.
_CHROMATICITY_BYTES = (
    (DECLARED_RED[0], 27, 25, 6),
    (DECLARED_RED[1], 28, 25, 4),
    (DECLARED_GREEN[0], 29, 25, 2),
    (DECLARED_GREEN[1], 30, 25, 0),
    (DECLARED_BLUE[0], 31, 26, 6),
    (DECLARED_BLUE[1], 32, 26, 4),
    (DECLARED_WHITE[0], 33, 26, 2),
    (DECLARED_WHITE[1], 34, 26, 0),
)


def ten_bit(value: float) -> float:
    """The fraction a descriptor can actually carry for one coordinate.

    A descriptor stores each coordinate in ten bits, so the value read back is
    the nearest 1024th and not the decimal written here, and detection then
    carries it as a four-decimal string. Expectations are built from that round
    trip rather than from the input, which is what makes a decoder that drops
    the two low bits fail instead of passing within a rounding error.
    """
    return float(f"{round(value * 1024) / 1024.0:.4f}")


def declared_edid(*, gamma: float = DECLARED_GAMMA) -> bytes:
    """One descriptor declaring the primaries and gamma named above.

    This is a byte string, not a device. It is handed to the detector as what a
    display reported when it was attached, which is the same shape the platform
    hands back from its own stored copy.
    """
    raw = bytearray(128)
    raw[0:8] = _EDID_HEADER
    raw[8], raw[9] = 0x52, 0x74
    raw[10], raw[11] = 0x2A, 0x00
    raw[18], raw[19] = 1, 4
    raw[23] = round(gamma * 100) - 100
    # The sRGB-default bit stays clear. A descriptor that sets it declares the
    # sRGB primaries by definition, and detection reads that as no offer.
    raw[24] = 0x00
    for value, high, low, shift in _CHROMATICITY_BYTES:
        packed = round(value * 1024)
        raw[high] = packed >> 2
        raw[low] |= (packed & 0x03) << shift
    return bytes(raw)


def offered_contract(
    *,
    red: tuple[str, str] = ("0.6800", "0.3200"),
    green: tuple[str, str] = ("0.2650", "0.6900"),
    blue: tuple[str, str] = ("0.1500", "0.0600"),
    gamma: str = "2.2000",
) -> PanelCharacterization:
    """One offer assembled directly, for the shapes a descriptor cannot produce.

    Detection refuses a collapsed gamut before it ever becomes an offer, so the
    declaration layer's own refusal is unreachable through a descriptor. It is
    reachable through this seam, which is the one a surface assembling a
    characterization by hand would come through.
    """
    return PanelCharacterization(
        kind=CharacterizationKind.EDID_DECLARED,
        provenance=DECLARED_PROVENANCE,
        red_xy=red,
        green_xy=green,
        blue_xy=blue,
        white_xy=("0.3127", "0.3290"),
        nominal_gamma=gamma,
    )


def denied_capabilities() -> CapabilityState:
    """A probe that proved nothing, which is what these tests need it to be."""
    return CapabilityState(
        sensor_available=False,
        ddc_available=False,
        dwm_lut_available=False,
        dwm_state_capture_available=False,
        profile_write_available=False,
        vcgt_available=False,
    )


class FixedDetector:
    """Hands back one observation carrying whatever offer a test chose.

    Used where the offer cannot come from a descriptor. Everything else in this
    file drives the production detector over injected bytes.
    """

    def __init__(self, offer: PanelCharacterization | None) -> None:
        self._offer = offer

    def detect(self) -> DetectionResult:
        observation = DisplayObservation(
            platform_display_id=DECLARED_DISPLAY.device_name,
            safe_label="Display 1",
            width_px=3840,
            height_px=2160,
            refresh_millihz=60000,
            hdr_enabled=None,
            characterization=PanelCharacterization(
                kind=CharacterizationKind.UNKNOWN,
                provenance="detector:no_panel_match",
                red_xy=None,
                green_xy=None,
                blue_xy=None,
                white_xy=None,
                nominal_gamma=None,
            ),
            capabilities=denied_capabilities(),
            evidence=(f"enumerator:{ENUMERATOR_NAME}", "panel-match:none"),
            edid_characterization=self._offer,
        )
        dashboard = DashboardModel(
            displays=(observation,),
            selected_display_id=observation.platform_display_id,
            refreshed_utc="2026-09-06T00:00:00Z",
        )
        return DetectionResult(dashboard=dashboard, rejected=())


class ForcedContextState(SessionState):
    """A session whose resolver reads a context the session no longer matches.

    Two of the checks under test defend against exactly this: a control that was
    resolved from one reading of the machine and pressed against another. The
    shipped composition builds the context and the offer from the same session,
    so it cannot produce that disagreement, and a service check reachable no
    other way would go untested. This produces it, by replacing the fields the
    gate reads and changing nothing else about the session.
    """

    def __init__(self) -> None:
        super().__init__()
        self.forced: dict[str, object] = {}

    def to_context(self) -> ActionContext:
        context = super().to_context()
        return replace(context, **self.forced) if self.forced else context


def build_session(
    root: Path,
    *,
    detector: object,
    state: SessionState | None = None,
) -> tuple[FunctionalRecoveryService, SessionState]:
    """The session a terminal drives, over an injected detector and no hardware.

    The state is handed back beside the service because the service keeps it
    private, and what these tests read is what the session ended up holding.
    """
    session_state = state if state is not None else SessionState()
    journal = DiagnosticJournal(root / "diagnostics")
    database = get_database()
    engine, generator = _engine_and_generator(database)
    service = FunctionalRecoveryService(
        state=session_state,
        runner=_runner(session_state, journal),
        detector=detector,
        generator=generator,
        engine=engine,
    )
    return service, session_state


def declaring_detector(*, edid: bytes | None = None) -> DisplayDetector:
    """The production detector, reading one descriptor this file wrote."""
    return DisplayDetector(
        enumerator=lambda: (DECLARED_DISPLAY,),
        capability_probe=DeniedCapabilityProbe(_PROBE_REASON),
        edid_reader=None if edid is None else (lambda display: edid),
        database=get_database(),
        enumerator_name=ENUMERATOR_NAME,
    )


def declared_session(root: Path) -> tuple[FunctionalRecoveryService, SessionState]:
    """A detected session over the display that declared its own primaries."""
    service, state = build_session(root, detector=declaring_detector(edid=declared_edid()))
    succeeded(service.detect())
    return service, state


def succeeded(outcome: ActionOutcome[object]) -> object:
    """The value one action returned, or a failure naming why it was refused."""
    if isinstance(outcome, ActionError):
        raise AssertionError(f"{outcome.action_id} was refused: {outcome.code}: {outcome.summary}")
    return outcome.value


def refused(outcome: ActionOutcome[object]) -> ActionError:
    """The refusal one action answered with, or a failure saying it ran."""
    if not isinstance(outcome, ActionError):
        raise AssertionError("the action ran when this test required a refusal")
    return outcome


def run_command_line(
    monkeypatch: pytest.MonkeyPatch,
    service: FunctionalRecoveryService,
    *argv: str,
) -> tuple[int, str]:
    """Drive one command line through `main`, over the session handed here.

    The composition is replaced rather than the command, so the parser, the
    dispatch and the driver are the shipped ones. Only the display behind them
    is this file's, which is what keeps the test off real hardware.
    """
    monkeypatch.setattr(commands, "build_service", lambda command: service)
    monkeypatch.setattr(sys, "argv", ["calibrate-pro", *argv])
    printed = io.StringIO()
    with redirect_stdout(printed):
        code = main()
    return code, printed.getvalue()


# -- the gate ---------------------------------------------------------------


def test_use_edid_is_offered_to_an_uncharacterized_display_that_declared_one() -> None:
    """The one state the control exists in: selected, uncharacterized, declaring."""
    resolved = REGISTRY.resolve(USE_EDID, action_context(characterization_kind=CharacterizationKind.UNKNOWN))

    assert resolved.disposition is ActionDisposition.ENABLED
    assert resolved.reason is None


def test_use_edid_is_refused_with_no_display_selected() -> None:
    """A declaration is one display's, so there is nothing to accept without one."""
    resolved = REGISTRY.resolve(
        USE_EDID,
        action_context(characterization_kind=CharacterizationKind.UNKNOWN, selected_display_id=None),
    )

    assert resolved.disposition is ActionDisposition.DISABLED
    assert resolved.reason == DECLARATION_UNAVAILABLE


def test_use_edid_is_refused_when_the_display_declared_nothing() -> None:
    """No offer means no control, rather than a control that refuses when pressed."""
    resolved = REGISTRY.resolve(
        USE_EDID,
        action_context(characterization_kind=CharacterizationKind.UNKNOWN, edid_declaration_available=False),
    )

    assert resolved.disposition is ActionDisposition.DISABLED
    assert resolved.reason == DECLARATION_UNAVAILABLE


def test_use_edid_is_refused_once_the_display_is_already_characterized() -> None:
    """Every sourced characterization closes it, including a declaration already taken.

    A control that stayed open would let a session that measured its display
    replace the reading with the manufacturer's claim about the model.
    """
    for kind in (
        CharacterizationKind.MATCHED,
        CharacterizationKind.EXPLICIT_GENERIC,
        CharacterizationKind.EDID_DECLARED,
        CharacterizationKind.MEASURED,
    ):
        resolved = REGISTRY.resolve(USE_EDID, action_context(characterization_kind=kind))

        assert resolved.disposition is ActionDisposition.DISABLED, kind
        assert resolved.reason == DECLARATION_UNAVAILABLE, kind


def test_sensorless_characterizations_are_the_three_sourced_kinds() -> None:
    """The set is exact, so a fourth kind cannot join it without this failing."""
    assert (
        frozenset(
            {
                CharacterizationKind.MATCHED,
                CharacterizationKind.EXPLICIT_GENERIC,
                CharacterizationKind.EDID_DECLARED,
            }
        )
        == SENSORLESS_CHARACTERIZATIONS
    )


def test_sensorless_calibration_accepts_a_declared_characterization() -> None:
    """A declaration qualifies for the sensorless method, and unknown does not."""
    declared = REGISTRY.resolve(
        SENSORLESS_METHOD,
        action_context(stage=WorkflowStage.METHOD, characterization_kind=CharacterizationKind.EDID_DECLARED),
    )
    unknown = REGISTRY.resolve(
        SENSORLESS_METHOD,
        action_context(stage=WorkflowStage.METHOD, characterization_kind=CharacterizationKind.UNKNOWN),
    )

    assert declared.disposition is ActionDisposition.ENABLED
    assert unknown.disposition is ActionDisposition.DISABLED


def test_measured_calibration_admits_one_kind_the_sensorless_method_does_not() -> None:
    """A completed run qualifies the measured method and no longer the sensorless one."""
    context = action_context(stage=WorkflowStage.METHOD, characterization_kind=CharacterizationKind.MEASURED)

    assert REGISTRY.resolve(MEASURED_METHOD, context).disposition is ActionDisposition.ENABLED
    assert REGISTRY.resolve(SENSORLESS_METHOD, context).disposition is ActionDisposition.DISABLED
    declared_context = replace(context, characterization_kind=CharacterizationKind.EDID_DECLARED)
    assert REGISTRY.resolve(MEASURED_METHOD, declared_context).disposition is ActionDisposition.ENABLED


# -- the service ------------------------------------------------------------


def test_accepting_a_declaration_records_the_numbers_the_display_declared(tmp_path: Path) -> None:
    """The session ends holding the descriptor's own primaries, labeled as declared."""
    service, state = declared_session(tmp_path)

    selection = succeeded(service.use_edid_characterization())

    declaration = state.declared_characterization
    assert selection.characterization_kind is CharacterizationKind.EDID_DECLARED
    assert declaration is not None
    assert declaration.provenance == DECLARED_PROVENANCE
    assert declaration.red_xy == (ten_bit(DECLARED_RED[0]), ten_bit(DECLARED_RED[1]))
    assert declaration.green_xy == (ten_bit(DECLARED_GREEN[0]), ten_bit(DECLARED_GREEN[1]))
    assert declaration.blue_xy == (ten_bit(DECLARED_BLUE[0]), ten_bit(DECLARED_BLUE[1]))
    assert declaration.gamma == pytest.approx(DECLARED_GAMMA)
    assert declaration.panel.name == DECLARED_PANEL_NAME
    assert state.declared_display_id == DECLARED_DISPLAY.device_name


def test_accepting_a_declaration_that_is_no_longer_there_is_refused(tmp_path: Path) -> None:
    """A control resolved from a stale reading is refused, not filled in.

    The session holds no offer, so there is nothing to record, and the refusal
    says that rather than substituting the generic record for it.
    """
    service, state = build_session(tmp_path, detector=declaring_detector(), state=ForcedContextState())
    succeeded(service.detect())
    state.forced = {"edid_declaration_available": True}

    error = refused(service.use_edid_characterization())

    assert error.code == NO_DECLARATION
    assert error.summary == NO_DECLARATION_SUMMARY
    assert error.next_action == "Use the generic characterization, or measure the display with an instrument."
    assert error.retryable is False
    assert state.declared_characterization is None


def test_a_declaration_that_cannot_be_built_from_is_refused_in_its_own_words(tmp_path: Path) -> None:
    """The declaration layer's reason reaches the operator, not a summary of it.

    Three primaries on a line and a gamma outside the band a display responds in
    are different faults, and an operator acts on which one it was.
    """
    collapsed = offered_contract(red=("0.3000", "0.3000"), green=("0.3000", "0.3000"), blue=("0.3000", "0.3000"))
    service, state = build_session(tmp_path, detector=FixedDetector(collapsed))
    succeeded(service.detect())

    error = refused(service.use_edid_characterization())

    assert error.code == NO_DECLARATION
    assert error.summary == COLLAPSED_GAMUT
    assert state.declared_characterization is None


def test_a_declared_gamma_outside_the_band_is_refused_by_its_number(tmp_path: Path) -> None:
    """The refusal quotes the gamma that was rejected, so the fault is readable."""
    service, _state = build_session(tmp_path, detector=FixedDetector(offered_contract(gamma="9.0000")))
    succeeded(service.detect())

    error = refused(service.use_edid_characterization())

    assert error.code == NO_DECLARATION
    assert error.summary == "the declared gamma is 9.0000, outside the band a display responds in"


def test_asking_for_the_generic_record_discards_a_held_declaration(tmp_path: Path) -> None:
    """FALSE-SUCCESS CONTROL.

    Catches a `_use_generic` that sets the panel key and the kind without
    discarding the declaration the session already accepted. The label would
    read EXPLICIT_GENERIC and the bundle would still be built from the declared
    primaries, because generation prefers a held declaration over the key. The
    session would report the generic record while correcting for a wide gamut,
    which is the one outcome asking for the generic record has to rule out.

    The generic control is closed once a declaration is held, so the resolver is
    handed the reading it would have been offered from. What is under test is
    what the action does, not when it appears.
    """
    service, state = build_session(
        tmp_path,
        detector=declaring_detector(edid=declared_edid()),
        state=ForcedContextState(),
    )
    succeeded(service.detect())
    succeeded(service.use_edid_characterization())
    assert state.declared_characterization is not None

    state.forced = {"characterization_kind": CharacterizationKind.UNKNOWN}
    selection = succeeded(service.use_generic_characterization())
    state.forced = {}

    assert selection.characterization_kind is CharacterizationKind.EXPLICIT_GENERIC
    assert state.declared_characterization is None
    assert state.declared_display_id is None
    assert state.declaration_matches_selection is False

    succeeded(service.select_method(CalibrationMethod.SENSORLESS))
    succeeded(service.set_target(target_action(PRESET)))
    generated = succeeded(service.generate())
    assert generated.characterization_kind is CharacterizationKind.EXPLICIT_GENERIC
    assert generated.panel_name != DECLARED_PANEL_NAME


# -- the command line -------------------------------------------------------


def test_the_edid_flag_drives_the_declared_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One line asks for the declaration, and the plan says what it was built from."""
    service, state = build_session(tmp_path, detector=declaring_detector(edid=declared_edid()))

    code, text = run_command_line(monkeypatch, service, "verify", "--target", PRESET, "--edid")

    assert code == 0
    assert field(text, "panel") == f"{DECLARED_PANEL_NAME} (declared) (edid_declared)"
    assert state.declared_characterization is not None
    assert state.declared_characterization.provenance == DECLARED_PROVENANCE


def test_the_declared_plan_is_not_the_plan_the_generic_record_produces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FALSE-SUCCESS CONTROL.

    Catches a `use_edid_characterization` that records the label without the
    numbers behind it: a stub that sets EDID_DECLARED, or one that hands the
    generator the generic record anyway. Either passes every test that reads a
    kind, and both produce the same correction the `--generic` line produces.
    The two runs are compared where the numbers actually reach the operator: the
    panel the plan names, and the distance the model puts this display from the
    target before correction. The declared primaries are wider than sRGB, so an
    `--edid` run that quietly used the generic record would report the generic
    run's zero.

    The plan digest is not compared. It covers the display, the method, the
    target labels and the output filenames, and no preview asset digests exist
    yet, so both runs seal the same digest with different corrections behind it.
    """
    declared_service, _declared_state = build_session(
        tmp_path / "declared",
        detector=declaring_detector(edid=declared_edid()),
    )
    generic_service, _generic_state = build_session(
        tmp_path / "generic",
        detector=declaring_detector(edid=declared_edid()),
    )

    declared_code, declared_text = run_command_line(
        monkeypatch, declared_service, "verify", "--target", PRESET, "--edid"
    )
    generic_code, generic_text = run_command_line(
        monkeypatch, generic_service, "verify", "--target", PRESET, "--generic"
    )

    assert declared_code == 0
    assert generic_code == 0
    assert field(declared_text, "panel") == f"{DECLARED_PANEL_NAME} (declared) (edid_declared)"
    assert field(generic_text, "panel").endswith("(explicit_generic)")
    assert field(declared_text, "panel") != field(generic_text, "panel")
    declared_uncorrected = float(field(declared_text, "uncorrected dE").split()[0])
    generic_uncorrected = float(field(generic_text, "uncorrected dE").split()[0])
    assert generic_uncorrected == 0.0
    assert declared_uncorrected > 1.0


def test_naming_both_characterizations_is_refused_at_the_command_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The line named two descriptions of one panel, so nothing chooses between them."""
    service, state = build_session(tmp_path, detector=declaring_detector(edid=declared_edid()))

    code, text = run_command_line(monkeypatch, service, "verify", "--target", PRESET, "--generic", "--edid")

    assert code == commands.REFUSED
    assert text.splitlines()[-1] == f"verify: {BOTH_CHARACTERIZATIONS}"
    assert state.declared_characterization is None
    assert state.selected_panel_key is None


def test_naming_both_characterizations_raises_the_command_error(tmp_path: Path) -> None:
    """The driver converts it to an exit code, so the type is asserted underneath."""
    service, _state = build_session(tmp_path, detector=declaring_detector(edid=declared_edid()))

    with pytest.raises(CommandError) as raised:
        commands.COMMANDS["verify"](service, arguments(generic=True, edid=True))

    assert str(raised.value) == BOTH_CHARACTERIZATIONS
    assert BOTH_CHARACTERIZATIONS == "--generic and --edid each name a different characterization. Pass one of them."
