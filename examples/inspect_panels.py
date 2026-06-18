#!/usr/bin/env python3
"""Best-effort demo — not runtime-verified by author.

Hardware-free Calibrate Pro demo. Exercises only the read-only panel database
and the public package metadata, so it runs without admin rights, a connected
display, or a colorimeter.

Run from the repository root after `pip install -e ".[all]"` (or with the
package on PYTHONPATH):

    python examples/inspect_panels.py

For the calibration commands that DO touch hardware/system state
(`auto`, `calibrate`, `verify`, ...), see USAGE.md.
"""

import calibrate_pro
from calibrate_pro.panels.database import PanelDatabase


def main() -> int:
    print(f"Calibrate Pro v{calibrate_pro.__version__} - panel database demo")
    print("=" * 55)

    db = PanelDatabase()
    keys = sorted(db.list_panels())
    print(f"Supported panels: {len(keys)}\n")

    # Show the first few panels and their type.
    print("Sample of the panel database:")
    for key in keys[:8]:
        panel = db.get_panel(key)
        if panel:
            print(f"  {key:14s}  {panel.name:32s}  {panel.panel_type}")

    # Detailed look at one well-characterised QD-OLED panel.
    example_key = "PG27UCDM"
    panel = db.get_panel(example_key)
    if panel:
        print(f"\nDetail for {example_key}:")
        print(f"  Name:         {panel.name}")
        print(f"  Manufacturer: {panel.manufacturer}")
        print(f"  Type:         {panel.panel_type}")
        gr, gg, gb = panel.gamma_red, panel.gamma_green, panel.gamma_blue
        # gamma_* are GammaCurve objects with a .gamma exponent attribute.
        print(f"  Gamma (R/G/B): {gr.gamma:.3f} / {gg.gamma:.3f} / {gb.gamma:.3f}")
        if panel.notes:
            print(f"  Notes:        {panel.notes}")

    print("\nNext steps (require hardware / admin - see USAGE.md):")
    print("  calibrate-pro detect      # list displays, sensors, DDC/CI monitors")
    print("  calibrate-pro auto        # automatic calibration of all displays")
    print(f"  calibrate-pro info {example_key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
