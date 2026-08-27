"""Calibrate Pro's least-privilege developer command entry point.

Display changes are never performed directly by this module. Commands that
can change ICC associations, gamma ramps, DDC/CI values, or compositor LUTs
route the operator to the interactive preview/confirmation workflow.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from calibrate_pro import __version__

_CONFIRMATION_COMMANDS = frozenset(
    {
        "auto",
        "calibrate",
        "ddc-calibrate",
        "ddc-info",
        "detect",
        "disable-startup",
        "enable-startup",
        "export-panel",
        "generate-profiles",
        "import-panel",
        "match",
        "native-calibrate",
        "refine",
        "restore",
        "status",
        "uniformity",
        "verify",
    }
)


def _banner() -> str:
    return f"Calibrate Pro v{__version__}"


def _requires_confirmation(command: str) -> int:
    """Refuse legacy direct actuation and point to the confirmed workflow."""
    print(_banner())
    print(f"\n'{command}' is proposal-only in Calibrate Pro 1.1.")
    print("Open the GUI to Detect, choose a Method, Preview the exact plan,")
    print("and explicitly confirm Apply. No display state was changed.")
    return 2


def cmd_detect(args: argparse.Namespace) -> int:
    """Keep device probing out of the non-interactive command surface."""
    return _requires_confirmation("detect")


def cmd_calibrate(args: argparse.Namespace) -> int:
    """Require the interactive preview and one-use confirmation workflow."""
    return _requires_confirmation("calibrate")


def cmd_verify(args: argparse.Namespace) -> int:
    """Require an explicit measured or characterized evidence workflow."""
    return _requires_confirmation("verify")


def cmd_enable_startup(args: argparse.Namespace) -> int:
    """Refuse direct registry mutation from the developer CLI."""
    return _requires_confirmation("enable-startup")


def cmd_disable_startup(args: argparse.Namespace) -> int:
    """Refuse direct registry mutation from the developer CLI."""
    return _requires_confirmation("disable-startup")


def cmd_generate_profiles(args: argparse.Namespace) -> int:
    """Require a selected display and confirmed Save/Report stage."""
    return _requires_confirmation("generate-profiles")


def cmd_restore(args: argparse.Namespace) -> int:
    """Require a captured restoration plan and explicit confirmation."""
    return _requires_confirmation("restore")


def cmd_native_calibrate(args: argparse.Namespace) -> int:
    """Require the interactive measured-calibration workflow."""
    return _requires_confirmation("native-calibrate")


def cmd_ddc_info(args: argparse.Namespace) -> int:
    """Keep DDC handles out of the application command surface."""
    return _requires_confirmation("ddc-info")


def cmd_ddc_calibrate(args: argparse.Namespace) -> int:
    """Require a bounded ApplyPlan and one-use confirmation."""
    return _requires_confirmation("ddc-calibrate")


def cmd_match(args: argparse.Namespace) -> int:
    """Require displays selected through the read-only GUI detection stage."""
    return _requires_confirmation("match")


def cmd_refine(args: argparse.Namespace) -> int:
    """Require the interactive measured-calibration workflow."""
    return _requires_confirmation("refine")


def cmd_auto(args: argparse.Namespace) -> int:
    """Refuse unattended calibration or startup persistence."""
    return _requires_confirmation("auto")


def cmd_status(args: argparse.Namespace) -> int:
    """Require the read-only GUI monitor rather than low-level imports."""
    return _requires_confirmation("status")


def cmd_list_targets(args: argparse.Namespace) -> int:
    """List pure calibration target presets without probing hardware."""
    from calibrate_pro.targets import (
        get_gamma_presets,
        get_gamut_presets,
        get_luminance_presets,
        get_profile_presets,
        get_whitepoint_presets,
    )

    print(f"\n{_banner()}")
    print("=" * 50)
    print("\nCalibration Profiles")
    for profile in get_profile_presets():
        label = " [HDR]" if profile.is_hdr() else ""
        print(f"  {profile.name:25s} - {profile.description}{label}")
    print("\nWhite Points")
    for whitepoint in get_whitepoint_presets():
        print(f"  {whitepoint.preset.value:15s} ({whitepoint.get_cct():.0f}K)")
    print("\nLuminance")
    for luminance in get_luminance_presets():
        label = " [HDR]" if luminance.is_hdr() else " [SDR]"
        print(f"  {luminance.standard.value:20s} - {luminance.get_peak_luminance():.0f} cd/m2{label}")
    print("\nGamma / EOTF")
    for gamma in get_gamma_presets():
        label = " [HDR]" if gamma.is_hdr() else ""
        print(f"  {gamma.preset.value:15s}{label}")
    print("\nGamuts")
    for gamut in get_gamut_presets():
        label = " [Wide Gamut]" if gamut.is_wide_gamut() else ""
        print(f"  {gamut.preset.value:15s}{label}")
    return 0


def cmd_list_panels(args: argparse.Namespace) -> int:
    """List characterized panels without enumerating attached displays."""
    from calibrate_pro.panels.database import PanelDatabase

    database = PanelDatabase()
    keys = sorted(database.list_panels())
    print(f"\n{_banner()}\n" + "=" * 50)
    print("\nCharacterized Panel Profiles\n")
    for key in keys:
        panel = database.get_panel(key)
        if panel is not None:
            print(f"  {key:24s} {panel.name:40s} {panel.panel_type}")
    print(f"\nTotal: {len(keys)} profiles")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """Show stored characterization facts for one panel key."""
    from calibrate_pro.panels.database import PanelDatabase

    database = PanelDatabase()
    panel = database.get_panel(args.panel) or database.find_panel(args.panel)
    if panel is None:
        print(f"Panel '{args.panel}' was not found. Use 'list-panels' for keys.")
        return 1
    primaries = panel.native_primaries
    print(f"\n{_banner()}\n" + "=" * 50)
    print(f"\nPanel: {panel.name}")
    print(f"  Manufacturer: {panel.manufacturer}")
    print(f"  Type: {panel.panel_type}")
    print("  Characterized primaries (estimated for an attached unit):")
    print(f"    Red:   ({primaries.red.x:.4f}, {primaries.red.y:.4f})")
    print(f"    Green: ({primaries.green.x:.4f}, {primaries.green.y:.4f})")
    print(f"    Blue:  ({primaries.blue.x:.4f}, {primaries.blue.y:.4f})")
    print(f"    White: ({primaries.white.x:.4f}, {primaries.white.y:.4f})")
    return 0


def cmd_hdr_status(args: argparse.Namespace) -> int:
    """Report OS HDR state through the read-only HDR query surface."""
    from calibrate_pro.display.hdr_detect import print_hdr_status

    print(f"\n{_banner()} - HDR Status\n" + "=" * 50)
    print_hdr_status()
    return 0


def cmd_plugins(args: argparse.Namespace) -> int:
    """List plugin metadata without loading display actuator modules."""
    from calibrate_pro.plugins.manager import print_discovered_plugins

    directories = [args.plugin_dir] if args.plugin_dir else None
    print_discovered_plugins(plugin_dirs=directories)
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    """Launch the unelevated six-stage GUI."""
    from calibrate_pro.commands.gui import run

    return run([])


def cmd_hdr(args: argparse.Namespace) -> int:
    """Launch the unelevated HDR target/proposal GUI."""
    from calibrate_pro.commands.hdr import run

    return run([])


def cmd_tray(args: argparse.Namespace) -> int:
    """Launch the read-only tray monitor."""
    from calibrate_pro.tray.tray_app import run_tray_app

    result = run_tray_app()
    return int(result or 0)


def cmd_patterns(args: argparse.Namespace) -> int:
    """Show visual test patterns; this does not mutate calibration state."""
    from calibrate_pro.patterns.display import show_patterns

    display = max(0, (args.display or 1) - 1)
    show_patterns(display=display)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run read-only installation and capability diagnostics."""
    from calibrate_pro.commands.doctor import run

    return run(args)


def cmd_mcp(args: argparse.Namespace) -> int:
    """Serve the read-only catalog and doctor tools over MCP stdio."""
    from calibrate_pro.mcp import serve

    return serve()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calibrate Pro - least-privilege display calibration",
        epilog="Display changes require GUI preview and explicit confirmation.",
    )
    parser.add_argument("--version", "-V", action="version", version=f"Calibrate Pro v{__version__}")
    subparsers = parser.add_subparsers(dest="command")

    doctor = subparsers.add_parser("doctor", help="Run read-only installation diagnostics")
    doctor.add_argument("--json", action="store_true", help="Emit schema-1 JSON")
    subparsers.add_parser("list-targets", help="List calibration target presets")
    subparsers.add_parser("list-panels", help="List characterized panel profiles")
    info = subparsers.add_parser("info", help="Show stored panel characterization")
    info.add_argument("panel")
    subparsers.add_parser("hdr-status", help="Query OS HDR state")
    subparsers.add_parser("gui", help="Launch the unelevated calibration GUI")
    subparsers.add_parser("hdr", help="Launch the unelevated HDR target GUI")
    subparsers.add_parser("tray", help="Launch the read-only tray monitor")
    patterns = subparsers.add_parser("patterns", help="Display visual test patterns")
    patterns.add_argument("--display", "-d", type=int)
    plugins = subparsers.add_parser("plugins", help="List discovered plugins")
    plugins.add_argument("--plugin-dir")
    subparsers.add_parser("mcp", help="Serve read-only catalog + doctor over MCP stdio")

    for command in sorted(_CONFIRMATION_COMMANDS):
        command_parser = subparsers.add_parser(command, help="Requires GUI preview and confirmation")
        command_parser.set_defaults(confirmation_command=command)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a read-only command or an explicit interactive GUI."""
    parser = _build_parser()
    args, unknown = parser.parse_known_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if getattr(args, "confirmation_command", None):
        return _requires_confirmation(args.confirmation_command)
    if unknown:
        parser.error("unrecognized arguments: " + " ".join(unknown))
    handlers = {
        "doctor": cmd_doctor,
        "gui": cmd_gui,
        "hdr": cmd_hdr,
        "hdr-status": cmd_hdr_status,
        "info": cmd_info,
        "list-panels": cmd_list_panels,
        "list-targets": cmd_list_targets,
        "mcp": cmd_mcp,
        "patterns": cmd_patterns,
        "plugins": cmd_plugins,
        "tray": cmd_tray,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
