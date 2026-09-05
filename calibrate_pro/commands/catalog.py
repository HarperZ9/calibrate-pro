"""The listings a terminal prints without opening a display or a session.

Everything here reads stored data. The panel tables are characterizations of a
model rather than measurements of the unit attached to this machine, and the
target tables are the definitions a plan is generated against, so no command in
this module observes anything.

The target listing leads with the presets a session can actually be set to,
read from the same table the action layer selects them from. What follows it is
a reference catalogue this build does not let an operator ask for, and it says
so, because a list of names that cannot be chosen reads as a list of names that
can.
"""

from __future__ import annotations

import argparse

from calibrate_pro import __version__

#: Under the selectable targets, above the tables nothing consumes.
REFERENCE_HEADING = "Reference catalogue (definitions, not selectable targets)"


def banner() -> str:
    """The one line every listing leads with."""
    return f"Calibrate Pro v{__version__}"


def _print_selectable_targets() -> None:
    """Name every target a session accepts, with what each one asks for."""
    from calibrate_pro.application.actions import PRESET_TARGETS
    from calibrate_pro.commands.session import PRESET_PREFIX

    print("\nTargets a calibration can be set to")
    print(f"  {'name':16s} {'gamut':10s} {'white point':12s} tone response")
    for action_id, (gamut, white_point, tone_response, is_hdr) in sorted(PRESET_TARGETS.items()):
        name = action_id[len(PRESET_PREFIX) :]
        marker = " [HDR]" if is_hdr else ""
        print(f"  {name:16s} {gamut:10s} {white_point:12s} {tone_response}{marker}")


def list_targets(args: argparse.Namespace) -> int:
    """List the selectable targets, then the definitions behind them."""
    from calibrate_pro.targets import (
        get_gamma_presets,
        get_gamut_presets,
        get_luminance_presets,
        get_profile_presets,
        get_whitepoint_presets,
    )

    print(f"\n{banner()}")
    print("=" * 50)
    _print_selectable_targets()
    print(f"\n{REFERENCE_HEADING}")
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


def list_panels(args: argparse.Namespace) -> int:
    """List characterized panel profiles without enumerating attached displays."""
    from calibrate_pro.panels.database import PanelDatabase

    database = PanelDatabase()
    keys = sorted(database.list_panels())
    print(f"\n{banner()}\n" + "=" * 50)
    print("\nCharacterized Panel Profiles\n")
    for key in keys:
        panel = database.get_panel(key)
        if panel is not None:
            print(f"  {key:24s} {panel.name:40s} {panel.panel_type}")
    print(f"\nTotal: {len(keys)} profiles")
    return 0


def panel_info(args: argparse.Namespace) -> int:
    """Show stored characterization facts for one panel key."""
    from calibrate_pro.panels.database import PanelDatabase

    database = PanelDatabase()
    panel = database.get_panel(args.panel) or database.find_panel(args.panel)
    if panel is None:
        print(f"Panel '{args.panel}' was not found. Use 'list-panels' for keys.")
        return 1
    primaries = panel.native_primaries
    print(f"\n{banner()}\n" + "=" * 50)
    print(f"\nPanel: {panel.name}")
    print(f"  Manufacturer: {panel.manufacturer}")
    print(f"  Type: {panel.panel_type}")
    print("  Characterized primaries (estimated for an attached unit):")
    print(f"    Red:   ({primaries.red.x:.4f}, {primaries.red.y:.4f})")
    print(f"    Green: ({primaries.green.x:.4f}, {primaries.green.y:.4f})")
    print(f"    Blue:  ({primaries.blue.x:.4f}, {primaries.blue.y:.4f})")
    print(f"    White: ({primaries.white.x:.4f}, {primaries.white.y:.4f})")
    return 0


__all__ = ["REFERENCE_HEADING", "banner", "list_panels", "list_targets", "panel_info"]
