"""One real published bundle, for the tests that read published bundles back.

Nothing here stands in for the product. Generation reads a panel table and a
preset, publication writes the manifest that seals exactly what it placed, and
both are the paths a sensorless export takes, so a bundle built here is the
bundle the application writes. No display is opened and nothing is measured.

The manifest helpers rewrite a bundle the way a hand edit would leave it, which
is what the reader has to survive: a field removed, a schema it does not know,
or a file that no longer hashes to the digest recorded for it.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

from calibrate_pro.application.assets import (
    MANIFEST_FILENAME,
    AssetFormat,
    AssetGenerator,
    AssetRequest,
    publish_bundle,
)

DISPLAY_ID = r"\\.\DISPLAY1"
PANEL_KEY = "AW3423DW"
PRESET_ID = "calibration.preset.srgb_web"
BASENAME = "Bundle"
CUBE = f"{BASENAME}.cube"
ICC = f"{BASENAME}.icc"


@cache
def _generator() -> AssetGenerator:
    """Build the generator once. It reads a panel table and holds no state."""
    return AssetGenerator()


def publish(directory: Path) -> Path:
    """Write one real bundle, manifest included, at the given path."""
    request = AssetRequest(
        display_id=DISPLAY_ID,
        panel_key=PANEL_KEY,
        preset_id=PRESET_ID,
        formats=(AssetFormat.CUBE, AssetFormat.ICC),
        lut_size=17,
        basename=BASENAME,
    )
    directory.mkdir(parents=True, exist_ok=True)
    publish_bundle(_generator().generate(request), directory, overwrite=True)
    return directory


def manifest_of(directory: Path) -> dict:
    """Read one bundle's manifest as the document the generator serialized."""
    return json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))


def rewrite_manifest(directory: Path, document: object) -> None:
    """Put a manifest back exactly as given, the way a hand edit would leave it."""
    (directory / MANIFEST_FILENAME).write_text(json.dumps(document), encoding="utf-8")


__all__ = [
    "BASENAME",
    "CUBE",
    "DISPLAY_ID",
    "ICC",
    "PANEL_KEY",
    "PRESET_ID",
    "manifest_of",
    "publish",
    "rewrite_manifest",
]
