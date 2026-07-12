"""Source and frozen-application resource resolution."""

from __future__ import annotations

import sys
from pathlib import Path


def application_root() -> Path:
    """Return the immutable application/resource root for this process."""
    if getattr(sys, "frozen", False):
        return Path(vars(sys)["_MEIPASS"]).resolve()
    return Path(__file__).resolve().parents[1]


def resource_path(*parts: str) -> Path:
    """Resolve a bundled resource without touching the filesystem."""
    return application_root().joinpath(*parts)
