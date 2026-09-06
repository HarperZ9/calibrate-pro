"""Calibration engines for Calibrate Pro.

The names below are re-exported lazily. Importing this package used to run
``from .native_loop import ...`` eagerly, and ``native_loop`` imports SciPy, so
reading a chromaticity constant out of :mod:`calibrate_pro.calibration.targets`
cost 763 modules on Python 3.12 before the first line of a headless command
ran, against the 8 this package costs now. Nothing in this package or its tests imports these names from the
package itself. Every caller reaches the submodule, so the eager import bought
an interface with no callers and charged the whole CLI for it.

``from calibrate_pro.calibration import native_loop`` still works and is
unaffected: the import machinery falls back to loading the submodule when this
module reports no such attribute, which is what it does for a name it does not
carry.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

#: Re-exported name to the submodule that defines it. Written out rather than
#: discovered, so an import of this package resolves a name without importing
#: any submodule to look for it.
_LAZY_EXPORTS = {
    "HybridCalibrationEngine": "hybrid",
    "HybridCalibrationResult": "hybrid",
    "COLORCHECKER_REF_LAB": "native_loop",
    "COLORCHECKER_SRGB": "native_loop",
    "CalibrationResult": "native_loop",
    "DisplayProfile": "native_loop",
    "build_correction_lut": "native_loop",
    "compute_de": "native_loop",
    "profile_display": "native_loop",
}


def __getattr__(name: str) -> Any:
    """Resolve a re-exported name by importing only the submodule that has it."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f".{module_name}", __name__), name)


def __dir__() -> list[str]:
    return sorted({*globals(), *_LAZY_EXPORTS})
