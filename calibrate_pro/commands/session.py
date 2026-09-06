"""The commands a terminal drives, through the session a window drives.

A terminal and a window are two renderings of one session. Every command here
builds the same service, calls the same actions, and prints what comes back, so
what a terminal may do is what the manifest allows rather than a second policy
written for the command line. A refusal is printed as the resolver worded it,
which is how the sentence a window shows and the sentence a terminal prints stay
the same sentence.

Two commands write to a path the operator named on the command line: a
calibration bundle into a directory, and a diagnostic bundle at a file path.
Two more speak to the display over its own control bus, and one of those is the
only command here that changes hardware. It is refused unless the operator
passes ``--confirm``, and it is built from a composition that holds a control
port, which the read-only one deliberately does not.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from calibrate_pro.application.actions import ActionDisposition
from calibrate_pro.application.outcomes import ActionError, ActionOutcome, refusal_message
from calibrate_pro.commands.session_ddc import ddc_calibrate, ddc_info
from calibrate_pro.commands.session_diagnostics import diagnostics

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
    """The action one target name selects, named for a session to run.

    The check happens here rather than at the session, which would answer that
    no such action is declared. That is true and it is not what the operator
    got wrong, so the names are read off the same targets and printed back.
    """
    available = preset_names()
    if name not in available:
        raise CommandError(f"No target named '{name}'. Available targets: {', '.join(available)}.")
    return PRESET_PREFIX + name


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


def _drive_to_preview(
    service: FunctionalRecoveryService,
    args: Any,
) -> tuple[TargetSelection, GenerationResult, PlanPreview]:
    """Run one session from detection to a sealed plan, writing nothing.

    Every step is the action a window calls for that same step, in the order the
    resolver requires, so a refusal here is the refusal a window would show.
    """
    from calibrate_pro.workflow import CalibrationMethod

    value(service.detect())
    display_id = getattr(args, "display", None)
    if display_id:
        value(service.select_display(display_id))
    value(service.select_method(CalibrationMethod.SENSORLESS))
    target = value(service.set_target(target_action(args.target)))
    generated = value(service.generate())
    preview = value(service.preview())
    return target, generated, preview


def _print_plan(target: TargetSelection, generated: GenerationResult, preview: PlanPreview) -> None:
    """Print the exact proposal, named by the digest that seals it."""
    plan = preview.plan
    print(f"Plan {preview.plan_sha256}")
    print(f"  display        {plan.display_id}")
    print(f"  method         {plan.method.value}")
    print(f"  panel          {generated.panel_name} ({generated.characterization_kind.value})")
    print(f"  target         {target.preset_id[len(PRESET_PREFIX) :]}")
    print(f"  white point    {plan.target_whitepoint}")
    print(f"  tone response  {plan.target_gamma}")
    print(f"  gamut          {plan.target_gamut}")
    print(f"  evidence       {generated.evidence_kind.value}")
    for filename in generated.filenames:
        print(f"  generated      {filename}")


def _print_verification(result: VerificationResult) -> None:
    """Print the accuracy figures beside the plain statement of their source."""
    from calibrate_pro.application.results import verification_note

    print(f"Verification source: {result.source}")
    print(f"  evidence       {result.evidence.value}")
    print(f"  average dE     {result.average_delta_e.display_text()}")
    print(f"  maximum dE     {result.maximum_delta_e.display_text()}")
    print(f"  patches        {result.patch_count}")
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
    print(f"  target         {record.target.preset_id[len(PRESET_PREFIX) :]}")
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
    "profiles": profiles,
    "status": status,
    "verify": verify,
}


def build_service(command: str) -> FunctionalRecoveryService:
    """Build the composition one command needs, which is not the same for all of them.

    A command that never touches a display is answered by the read-only
    composition, so nothing it does can reach one. The two that address a
    display need a build with a control port in it, and asking for that build
    per command is what keeps the port out of the six that have no use for it.
    """
    from calibrate_pro.application.composition import build_default_service, build_production_service

    if command in DISPLAY_CONTROL_COMMANDS:
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
    "PRESET_PREFIX",
    "REFUSED",
    "CommandError",
    "Refused",
    "build_service",
    "preset_names",
    "run",
    "run_argv",
    "target_action",
    "value",
]
