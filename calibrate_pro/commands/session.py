"""The commands a terminal drives, through the session a window drives.

A terminal and a window are two renderings of one session. Every command here
builds the same service, calls the same actions, and prints what comes back, so
what a terminal may do is what the manifest allows rather than a second policy
written for the command line. A refusal is printed as the resolver worded it,
which is how the sentence a window shows and the sentence a terminal prints stay
the same sentence.

Two commands write to a path the operator named on the command line: a
calibration bundle into a directory, and a diagnostic bundle at a file path.
Two more speak to the display over its own control bus, five reach the Windows
colour profile store, and one opens a window on the display and waits there
while the operator looks at it. Each of those two groups holds one command that
only reads and the rest that change the machine, and a change is refused unless
the operator passes ``--confirm``. Both groups are built from a composition
holding the port they address, which the read-only one deliberately does not.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from calibrate_pro.application.actions import ActionDisposition
from calibrate_pro.application.outcomes import ActionError, ActionOutcome, refusal_message
from calibrate_pro.commands.session_args import COMPOSE_HINT, TARGET_FLAGS
from calibrate_pro.commands.session_ddc import ddc_calibrate, ddc_info
from calibrate_pro.commands.session_diagnostics import diagnostics
from calibrate_pro.commands.session_patterns import patterns as show_patterns
from calibrate_pro.commands.session_patterns import show_pattern
from calibrate_pro.commands.session_profiles import (
    install_profile,
    remove_profile,
    restore_profiles,
    switch_profile,
    system_profiles,
)

if TYPE_CHECKING:
    from calibrate_pro.application.assets import ExportBundle
    from calibrate_pro.application.results import (
        GenerationResult,
        PlanPreview,
        TargetSelection,
        VerificationResult,
    )
    from calibrate_pro.application.service import FunctionalRecoveryService

#: Every target action id begins with this, and the command line asks for the
#: rest of it. Deriving the names from the targets themselves is what keeps a
#: second list of presets from existing here to drift against the first.
PRESET_PREFIX = "calibration.preset."

REFUSED = 2

#: The commands that speak to a display over its own control bus. Every other
#: command is answered by the read-only composition, which wires no control
#: port and says so. These two are built from the composition this machine can
#: honestly offer, because a port is the thing they exist to use.
DISPLAY_CONTROL_COMMANDS = frozenset({"ddc-calibrate", "ddc-info"})

#: The commands that address the Windows colour profile store. They are routed
#: the same way the control commands are and for the same reason: the store is
#: the thing they exist to read and write, and a composition that wired no
#: profile port answers them by saying so rather than by failing at a call.
SYSTEM_PROFILE_COMMANDS = frozenset(
    {
        "install-profile",
        "remove-profile",
        "restore-profiles",
        "switch-profile",
        "system-profiles",
    }
)

#: The command that opens a window on the operator's own display. It is routed
#: with the hardware commands because it needs the composition that wired a
#: pattern surface, and for no other reason: it reads nothing off the machine
#: and changes nothing on it. Listing the patterns needs no port at all and is
#: deliberately not here.
PATTERN_COMMANDS = frozenset({"show-pattern"})

#: Every command that needs a port into the machine. Built from the three
#: groups rather than typed out again, so a command added to any of them is
#: routed by that alone.
HARDWARE_COMMANDS = DISPLAY_CONTROL_COMMANDS | SYSTEM_PROFILE_COMMANDS | PATTERN_COMMANDS


#: What a command line that aims at nothing is answered with. The parser says
#: the same thing in its own words, and both are built from one hint.
UNAIMED = f"No target was named. Pass --target. {COMPOSE_HINT}"

#: What a command line asking for two descriptions of the same panel is
#: answered with. Choosing between them is the operator's decision, and
#: picking one here would make a run mean something the line did not say.
BOTH_CHARACTERIZATIONS = "--generic and --edid each name a different characterization. Pass one of them."


class CommandError(Exception):
    """One command that cannot go on, carrying the line the operator reads."""


class Refused(CommandError):
    """One action the session declined, carrying the refusal it returned."""

    def __init__(self, error: ActionError) -> None:
        super().__init__(refusal_message(error))
        self.error = error


def preset_names() -> tuple[str, ...]:
    """The target names a terminal may ask for, read off the targets themselves."""
    from calibrate_pro.application.actions import PRESET_TARGETS

    return tuple(sorted(action_id[len(PRESET_PREFIX) :] for action_id in PRESET_TARGETS))


def target_action(name: str) -> str:
    """The action one preset name selects, named for a session to run.

    The check happens here rather than at the session, which would answer that
    no such action is declared. That is true and it is not what the operator
    got wrong, so the names are read off the same targets and printed back.

    The other route is named too. A gamut this build carries is a plausible
    thing to write after ``--target``, and answering with four preset names
    alone would report that the gamut does not exist when what does not exist
    is a preset by that name.
    """
    available = preset_names()
    if name not in available:
        raise CommandError(f"No target named '{name}'. Available targets: {', '.join(available)}. {COMPOSE_HINT}")
    return PRESET_PREFIX + name


def target_name(target_id: str) -> str:
    """What a terminal calls one target, in the words its own flags take.

    A preset is named by the word ``--target`` takes. A composed target has no
    single word, so it is written as the three slugs the axis flags take, which
    is what an operator would pass to ask for it again. An id this build cannot
    read back is printed whole rather than guessed at.
    """
    if target_id.startswith(PRESET_PREFIX):
        return target_id[len(PRESET_PREFIX) :]
    from calibrate_pro.application.target_editing import target_slugs
    from calibrate_pro.application.target_selection import TargetSelectionError

    try:
        return "/".join(target_slugs(target_id))
    except TargetSelectionError:
        return target_id


def value(outcome: ActionOutcome[Any]) -> Any:
    """Unwrap a completed action, or raise the refusal the session returned."""
    if isinstance(outcome, ActionError):
        raise Refused(outcome)
    return outcome.value


def _hdr_text(enabled: bool | None) -> str:
    """Say what was observed, and say so when nothing was."""
    if enabled is None:
        return "HDR not reported"
    return "HDR on" if enabled else "SDR"


def detect(service: FunctionalRecoveryService, args: Any) -> int:
    """List the displays one detection pass observed, and the ones it refused."""
    summary = value(service.detect())
    dashboard = summary.dashboard
    print(f"{len(dashboard.displays)} display(s) observed at {dashboard.refreshed_utc}")
    for display in dashboard.displays:
        marker = "*" if display.platform_display_id == summary.selected_display_id else " "
        geometry = f"{display.width_px}x{display.height_px} at {display.refresh_millihz / 1000:g} Hz"
        print(f" {marker} {display.platform_display_id}  {display.safe_label}")
        print(f"     {geometry}, {_hdr_text(display.hdr_enabled)}")
        print(f"     characterization: {display.characterization.provenance}")
    for display_id, reason in summary.rejected:
        print(f"   refused {display_id}: {reason}")
    return 0


def _action_lines(service: FunctionalRecoveryService, *, closed_only: bool) -> list[str]:
    """One line per declared action, with the disposition this session resolved."""
    lines: list[str] = []
    for action_id in sorted(service.action_ids()):
        resolved = service.resolve(action_id)
        if closed_only and resolved.disposition is ActionDisposition.ENABLED:
            continue
        classification = service.classification(action_id)
        kind = classification.value if classification is not None else "unclassified"
        lines.append(f"  {resolved.disposition.value:8s} {kind:17s} {action_id}")
        if resolved.reason:
            lines.append(f"           {resolved.reason}")
    return lines


def status(service: FunctionalRecoveryService, args: Any) -> int:
    """Report what this build can do on this machine, and why not for the rest."""
    value(service.detect())
    declared = service.action_ids()
    available = sum(1 for action_id in declared if service.resolve(action_id).disposition is ActionDisposition.ENABLED)
    print(f"Stage: {service.stage.value}")
    print(f"Actions: {available} of {len(declared)} available in this session")
    print("")
    for line in _action_lines(service, closed_only=bool(getattr(args, "closed", False))):
        print(line)
    return 0


def _kelvin(text: str) -> int | None:
    """Read a white point written as a temperature, or answer None for a name.

    ``6300``, ``6300K`` and ``cct6300`` are one request written three ways. A
    name from the illuminant table comes back as ``None``. The range check
    belongs to the action rather than to this, so a number outside it is
    refused by the sentence that names the range.
    """
    digits = text.lower().removeprefix("cct").removesuffix("k")
    return int(digits) if digits.isdigit() else None


def _select_white_point(service: FunctionalRecoveryService, text: str) -> ActionOutcome[Any]:
    """Aim the white point at an illuminant or at a colour temperature."""
    kelvin = _kelvin(text)
    if kelvin is None:
        return service.select_target_white_point(text)
    return service.select_custom_white_point(kelvin)


def _preset_action(args: Any) -> str | None:
    """The preset action a command line names, read before a session is driven.

    A name no preset carries is a fact about the command line, and reading it
    off the table costs nothing. Leaving it until the session had been aimed
    would have the operator watch their displays be enumerated and their panel
    be matched before being told they had mistyped one word.
    """
    name = getattr(args, "target", None)
    return target_action(name) if name else None


def _select_target(service: FunctionalRecoveryService, args: Any, preset: str | None) -> TargetSelection:
    """Aim the session at the target the flags name, one action per flag.

    ``--target`` names one of the presets, resolved to its action before this
    is called. An axis flag replaces one part of whatever the session holds, so
    passing both is how an operator asks for a preset with one part changed,
    and passing axis flags alone composes a target from the parts they name and
    the sRGB defaults for the rest. Each edit answers with the whole target, so
    the last answer is what the plan is generated against.
    """
    selected: TargetSelection | None = None
    if preset is not None:
        selected = value(service.set_target(preset))
    if getattr(args, "gamut", None):
        selected = value(service.select_target_gamut(args.gamut))
    if getattr(args, "white_point", None):
        selected = value(_select_white_point(service, args.white_point))
    if getattr(args, "tone_response", None):
        selected = value(service.select_target_tone_response(args.tone_response))
    if selected is None:
        raise CommandError(UNAIMED)
    return selected


def _unaimed(args: Any) -> bool:
    """Whether this line carries nothing that aims a calibration.

    The parser refuses an unaimed command line before a command is dispatched,
    so this is not what an operator meets. It is what a caller that built the
    arguments itself meets, which a test does and an embedder may, and asking
    is cheap next to detecting a display to find the same thing out.
    """
    return not any(getattr(args, flag, None) for flag in TARGET_FLAGS)


def _drive_to_preview(
    service: FunctionalRecoveryService,
    args: Any,
) -> tuple[TargetSelection, GenerationResult, PlanPreview]:
    """Run one session from detection to a sealed plan, writing nothing.

    Every step is the action a window calls for that same step, in the order the
    resolver requires, so a refusal here is the refusal a window would show.

    ``--generic`` and ``--edid`` are performed here rather than defaulted
    anywhere, and each action refuses on a display that already matched a panel
    record. What a plan is generated against stays something the operator
    recorded.
    """
    from calibrate_pro.workflow import CalibrationMethod

    if _unaimed(args):
        raise CommandError(UNAIMED)
    preset = _preset_action(args)
    value(service.detect())
    display_id = getattr(args, "display", None)
    if display_id:
        value(service.select_display(display_id))
    if getattr(args, "generic", False) and getattr(args, "edid", False):
        raise CommandError(BOTH_CHARACTERIZATIONS)
    if getattr(args, "generic", False):
        value(service.use_generic_characterization())
    if getattr(args, "edid", False):
        value(service.use_edid_characterization())
    value(service.select_method(CalibrationMethod.SENSORLESS))
    target = _select_target(service, args, preset)
    generated = value(service.generate())
    preview = value(service.preview())
    return target, generated, preview


def _print_plan(target: TargetSelection, generated: GenerationResult, preview: PlanPreview) -> None:
    """Print the exact proposal, named by the digest that seals it."""
    # Imported here rather than at module scope, the way the verification
    # printer does it. This module keeps the results layer off the import path
    # of a command that never prints a plan.
    from calibrate_pro.application.results import reach_text

    plan = preview.plan
    print(f"Plan {preview.plan_sha256}")
    print(f"  display        {plan.display_id}")
    print(f"  method         {plan.method.value}")
    print(f"  panel          {generated.panel_name} ({generated.characterization_kind.value})")
    print(f"  target         {target_name(target.preset_id)}")
    print(f"  white point    {plan.target_whitepoint}")
    print(f"  tone response  {plan.target_gamma}")
    print(f"  gamut          {plan.target_gamut}")
    # Directly under the gamut, because it qualifies that line and no other. A
    # display reaching 52.9% of BT.2020 still gets a BT.2020 bundle, and the
    # operator confirming this plan reads both facts in one place instead of
    # inferring the second from the panel name.
    print(f"  gamut reach    {reach_text(preview.gamut_reach)}")
    print(f"  evidence       {generated.evidence_kind.value}")
    for filename in generated.filenames:
        print(f"  generated      {filename}")


def _print_verification(result: VerificationResult) -> None:
    """Print the accuracy figures beside the plain statement of their source."""
    from calibrate_pro.application.results import correction_note, verification_note

    print(f"Verification source: {result.source}")
    print(f"  evidence       {result.evidence.value}")
    if result.metric:
        print(f"  measure        {result.metric}")
    # Printed above the corrected pair because it is the number the corrected
    # one is read against. Below it, an operator reads 0.00 first and has
    # already concluded nothing happened.
    if result.uncorrected_average_delta_e is not None:
        print(f"  uncorrected dE {result.uncorrected_average_delta_e.display_text()}")
    print(f"  average dE     {result.average_delta_e.display_text()}")
    print(f"  maximum dE     {result.maximum_delta_e.display_text()}")
    print(f"  patches        {result.patch_count}")
    correction = correction_note(result)
    if correction is not None:
        print(f"  {correction}")
    print(f"  {verification_note(result)}")


def _print_bundle(bundle: ExportBundle) -> None:
    """Print what landed on disk, sealed by the manifest that describes it."""
    print(f"Published to {bundle.directory}")
    for asset in bundle.assets:
        print(f"  {asset.filename}")
    print(f"  {bundle.manifest_filename}  {bundle.manifest_sha256}")


def verify(service: FunctionalRecoveryService, args: Any) -> int:
    """Generate a plan, confirm it without applying it, and report the figures."""
    target, generated, preview = _drive_to_preview(service, args)
    _print_plan(target, generated, preview)
    print("")
    value(service.confirm_plan())
    _print_verification(value(service.verify()))
    return 0


def generate(service: FunctionalRecoveryService, args: Any) -> int:
    """Publish one calibration bundle into a directory named on the command line."""
    target, generated, preview = _drive_to_preview(service, args)
    _print_plan(target, generated, preview)
    print("")
    if getattr(args, "dry_run", False):
        print("Stopped at the plan. Nothing was written.")
        return 0
    value(service.confirm_plan())
    _print_verification(value(service.verify()))
    print("")
    _print_bundle(value(service.export(args.output)))
    return 0


def _print_profile(service: FunctionalRecoveryService, record: Any) -> bool:
    """Read one published bundle back and report whether its files still match."""
    inspection = value(service.inspect_profile(record.directory))
    print(f"{record.name}  {'sealed' if inspection.sealed else 'CHANGED'}")
    print(f"  directory      {record.directory}")
    print(f"  panel          {record.panel_name}")
    print(f"  target         {target_name(record.target.preset_id)}")
    print(f"  white point    {record.target.white_point}")
    print(f"  tone response  {record.target.tone_response}")
    print(f"  evidence       {record.evidence_kind}")
    for check in inspection.broken:
        print(f"  {'changed' if check.present else 'missing'}        {check.filename}")
    return inspection.sealed


def profiles(service: FunctionalRecoveryService, args: Any) -> int:
    """List the bundles published under a directory, checking each one's seal.

    A path with nothing at it is refused rather than tallied. Both fields the
    listing carries for that case arrive here as the same fact, because the
    directory was set from the command line one line earlier: the session either
    would not hold the path at all or held it and found nothing there to read.
    Printing a zero for either would report a folder that had been looked in.
    """
    value(service.detect())
    value(service.set_export_directory(args.directory))
    listing = value(service.list_profiles())
    if not listing.searched or not listing.existed:
        raise CommandError(f"No directory at {args.directory}. Nothing was read.")
    sealed = [_print_profile(service, record) for record in listing.profiles]
    for entry in listing.unreadable:
        print(f"{entry.name}  unreadable")
        print(f"  directory      {entry.directory}")
        print(f"  reason         {entry.reason}")
    print("")
    if not sealed and not listing.unreadable:
        print(f"No published bundle under {listing.directory}.")
        return 0
    print(f"{sum(sealed)} of {len(sealed)} sealed, {len(listing.unreadable)} unreadable")
    return 0 if all(sealed) and not listing.unreadable else 1


COMMANDS = {
    "ddc-calibrate": ddc_calibrate,
    "ddc-info": ddc_info,
    "detect": detect,
    "diagnostics": diagnostics,
    "generate-profiles": generate,
    "install-profile": install_profile,
    "patterns": show_patterns,
    "profiles": profiles,
    "remove-profile": remove_profile,
    "restore-profiles": restore_profiles,
    "show-pattern": show_pattern,
    "status": status,
    "switch-profile": switch_profile,
    "system-profiles": system_profiles,
    "verify": verify,
}


def build_service(command: str) -> FunctionalRecoveryService:
    """Build the composition one command needs, which is not the same for all of them.

    A command that never touches a display is answered by the read-only
    composition, so nothing it does can reach one. The commands that address a
    display's control bus or the machine's colour profile store need a build
    holding those ports, and asking for that build per command is what keeps
    both ports out of the commands that have no use for them.
    """
    from calibrate_pro.application.composition import build_default_service, build_production_service

    if command in HARDWARE_COMMANDS:
        return build_default_service()
    return build_production_service()


def run(command: str, args: Any, service: FunctionalRecoveryService | None = None) -> int:
    """Drive one command, turning a refusal into its own sentence and exit code.

    The service is a parameter for the same reason the window takes one: a test
    drives the fake composition, and no test in this repository reaches a real
    display to find out what a command prints.
    """
    session = service if service is not None else build_service(command)
    try:
        return COMMANDS[command](session, args)
    except CommandError as failure:
        print(f"{command}: {failure}")
        return REFUSED


def run_argv(command: str, argv: Sequence[str]) -> int:
    """Drive one command from a bare argument list, parsing the arguments here.

    The frozen binary chooses the command itself and has no developer parser to
    route through, so it hands the rest of the line to this. The arguments are
    read from the table the developer parser is built from, which is what keeps
    one command meaning the same thing whichever way it was started.
    """
    from calibrate_pro.commands.session_args import parse

    return run(command, parse(command, argv))


__all__ = [
    "COMMANDS",
    "DISPLAY_CONTROL_COMMANDS",
    "HARDWARE_COMMANDS",
    "PRESET_PREFIX",
    "REFUSED",
    "SYSTEM_PROFILE_COMMANDS",
    "UNAIMED",
    "CommandError",
    "Refused",
    "build_service",
    "preset_names",
    "run",
    "run_argv",
    "target_action",
    "target_name",
    "value",
]
