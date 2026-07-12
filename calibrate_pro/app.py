"""Compatibility entry point for the least-privilege Calibrate Pro CLI."""

from __future__ import annotations

from collections.abc import Sequence

from calibrate_pro import __version__

__app_name__ = "Calibrate Pro"


def get_banner() -> str:
    """Return the compatibility banner without importing runtime surfaces."""
    return f"{__app_name__} v{__version__}"


def main(argv: Sequence[str] | None = None) -> int:
    """Delegate to the audited developer entry point."""
    from calibrate_pro.main import main as run

    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
