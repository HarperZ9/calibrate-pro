"""Calibrate Pro's developer command line.

Three kinds of command are dispatched here. The catalogue commands read stored
data, the session commands drive the same actions a window drives, and the rest
are names from an earlier release that this build does not perform.

A refused name is refused in the resolver's own words rather than in a sentence
written here, so a terminal and a window give one answer about what this build
does and there is one place for that answer to change. Nothing in this module
changes display state. The session it builds holds no display adapter, and
confirming a plan acknowledges it rather than writing one.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from types import MappingProxyType

from calibrate_pro import __version__
from calibrate_pro.commands import session_args
from calibrate_pro.commands.catalog import banner, list_panels, list_targets, panel_info

#: What a declined command exits with, matching the session driver.
REFUSED = 2

#: Names whose work is one declared action this build has not qualified. Pairing
#: them is what lets a refusal cite the resolver rather than restate a policy,
#: which would give the same decision two places to drift from.
#:
#: 'patterns' is here for that reason rather than as a name from an earlier
#: release. The window routes patterns.open through the resolver and the frozen
#: binary does not ship the name at all, so a terminal that opened the viewer
#: anyway was a second answer to one question about what this build performs.
_DECLARED_REFUSALS = MappingProxyType(
    {
        "calibrate": "calibration.all",
        "ddc-calibrate": "ddc.apply",
        "ddc-info": "ddc.read_current",
        "disable-startup": "settings.startup",
        "enable-startup": "settings.startup",
        "export-panel": "panel_profile.edid.create",
        "import-panel": "panel_profile.import",
        "native-calibrate": "calibration.method.measured",
        "patterns": "patterns.open",
        "refine": "calibration.method.measured",
        "restore": "display.restore_defaults",
    }
)

#: Legacy names with no declared action behind them anywhere in this build.
_UNBUILT_COMMANDS = frozenset({"auto", "match", "uniformity"})

#: Every name this build declines, which is what the MCP boundary gate
#: walks to prove none of them is reachable as a tool.
_CONFIRMATION_COMMANDS = frozenset(_DECLARED_REFUSALS) | _UNBUILT_COMMANDS

#: The names handed to the session driver, read from the table the frozen binary
#: builds its parser from as well. Reaching it costs argparse, which the parser
#: needs anyway, so a `--help` and a rejected flag still load no action layer.
_SESSION_COMMANDS = session_args.COMMANDS

_UNTOUCHED = "Nothing was read and no display state was changed."


def _declared_refusal(command: str, action_id: str) -> int:
    """Decline a legacy name, quoting the resolver on the action behind it."""
    from calibrate_pro.application.composition import build_production_service

    resolved = build_production_service().resolve(action_id)
    print(banner())
    print(f"\n'{command}' depends on {action_id}, which this build does not perform.")
    print(f"  {resolved.disposition.value}: {resolved.reason}")
    print(f"\n{_UNTOUCHED}")
    return REFUSED


def _unbuilt(command: str) -> int:
    """Decline a legacy name that this build declares no capability for."""
    print(banner())
    print(f"\n'{command}' is a name from an earlier release. This build declares no")
    print("capability behind it, so there is nothing to run and nothing to qualify.")
    print(f"\n{_UNTOUCHED}")
    return REFUSED


def _session(command: str, args: argparse.Namespace) -> int:
    """Hand one command to the driver a terminal and a window share."""
    from calibrate_pro.commands import session

    return session.run(command, args)


def cmd_hdr_status(args: argparse.Namespace) -> int:
    """Report OS HDR state through the read-only HDR query surface."""
    from calibrate_pro.display.hdr_detect import print_hdr_status

    print(f"\n{banner()} - HDR Status\n" + "=" * 50)
    print_hdr_status()
    return 0


def cmd_plugins(args: argparse.Namespace) -> int:
    """List plugin metadata without loading display actuator modules."""
    from calibrate_pro.plugins.manager import print_discovered_plugins

    directories = [args.plugin_dir] if args.plugin_dir else None
    print_discovered_plugins(plugin_dirs=directories)
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    """Launch the unelevated calibration window."""
    from calibrate_pro.commands.gui import run

    return run([])


def cmd_hdr(args: argparse.Namespace) -> int:
    """Launch the unelevated HDR target and proposal window."""
    from calibrate_pro.commands.hdr import run

    return run([])


def cmd_tray(args: argparse.Namespace) -> int:
    """Launch the read-only tray monitor."""
    from calibrate_pro.tray.tray_app import run_tray_app

    result = run_tray_app()
    return int(result or 0)


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run read-only installation and capability diagnostics."""
    from calibrate_pro.commands.doctor import run

    return run(args)


def cmd_mcp(args: argparse.Namespace) -> int:
    """Serve the read-only catalog and doctor tools over MCP stdio."""
    from calibrate_pro.mcp import serve

    return serve()


def _build_parser() -> argparse.ArgumentParser:
    """Every command this build answers, built without importing the engine."""
    parser = argparse.ArgumentParser(
        description="Calibrate Pro - least-privilege display calibration",
        epilog="A display change requires the window's preview and an explicit confirmation.",
    )
    parser.add_argument("--version", "-V", action="version", version=f"Calibrate Pro v{__version__}")
    subparsers = parser.add_subparsers(dest="command")

    doctor = subparsers.add_parser("doctor", help="Run read-only installation diagnostics")
    doctor.add_argument("--json", action="store_true", help="Emit schema-1 JSON")
    subparsers.add_parser("list-targets", help="List calibration targets and the reference catalogue")
    subparsers.add_parser("list-panels", help="List characterized panel profiles")
    info = subparsers.add_parser("info", help="Show stored panel characterization")
    info.add_argument("panel")
    subparsers.add_parser("hdr-status", help="Query OS HDR state")
    subparsers.add_parser("gui", help="Launch the unelevated calibration GUI")
    subparsers.add_parser("hdr", help="Launch the unelevated HDR target GUI")
    subparsers.add_parser("tray", help="Launch the read-only tray monitor")
    plugins = subparsers.add_parser("plugins", help="List discovered plugins")
    plugins.add_argument("--plugin-dir")
    subparsers.add_parser("mcp", help="Serve read-only catalog + doctor over MCP stdio")
    session_args.add_parsers(subparsers)

    for command in sorted(_CONFIRMATION_COMMANDS):
        subparsers.add_parser(command, help="Declined; this build does not perform it")
    return parser


_HANDLERS = {
    "doctor": cmd_doctor,
    "gui": cmd_gui,
    "hdr": cmd_hdr,
    "hdr-status": cmd_hdr_status,
    "info": panel_info,
    "list-panels": list_panels,
    "list-targets": list_targets,
    "mcp": cmd_mcp,
    "plugins": cmd_plugins,
    "tray": cmd_tray,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one command, or print the help when none was named.

    Unrecognized arguments are rejected before anything is dispatched. Checking
    afterwards let a declined command accept flags it never read, which reads as
    though the flag had been understood and then refused.
    """
    parser = _build_parser()
    args, unknown = parser.parse_known_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if unknown:
        parser.error("unrecognized arguments: " + " ".join(unknown))
    if args.command in _SESSION_COMMANDS:
        return _session(args.command, args)
    action_id = _DECLARED_REFUSALS.get(args.command)
    if action_id is not None:
        return _declared_refusal(args.command, action_id)
    if args.command in _UNBUILT_COMMANDS:
        return _unbuilt(args.command)
    return _HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
