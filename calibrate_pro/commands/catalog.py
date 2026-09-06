"""The panel listings a terminal prints without opening a display or a session.

Both read stored data. A panel table is a characterization of a model rather
than a measurement of the unit attached to this machine, so neither command
here observes anything.

Both are developer-wheel commands. The packaged binary refuses them by name, so
nothing in this module is reachable from the frozen dispatcher, and the target
listing it does ship lives in :mod:`calibrate_pro.commands.list_targets`.
"""

from __future__ import annotations

import argparse

from calibrate_pro.commands import banner


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


__all__ = ["list_panels", "panel_info"]
