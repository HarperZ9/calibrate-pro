"""
Calibrate Pro - Cross-Platform Display Backend (Phase 6)

Provides a unified API for display enumeration, gamma ramp manipulation,
and ICC profile management across Windows, macOS, and Linux.

Usage::

    from calibrate_pro.platform import get_platform_backend

    backend = get_platform_backend()
    displays = backend.enumerate_displays()
    backend.apply_gamma_ramp(0, red, green, blue)

All three platform backends (Windows, macOS, Linux) are fully implemented:
- Windows: Win32 / GDI / MSCMS via calibrate_pro.panels.detection
- macOS: CoreGraphics / IOKit / ColorSync via pyobjc
- Linux: xrandr / python-xlib / colord / DRM sysfs
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from calibrate_pro.platform.base import PlatformBackend


def get_platform_backend() -> PlatformBackend:
    """
    Get the appropriate platform backend for the current OS.

    Returns
    -------
    PlatformBackend
        A concrete backend for the running operating system.

    Raises
    ------
    RuntimeError
        If the current platform is not recognized.
    """
    if sys.platform == "win32":
        from calibrate_pro.platform.windows import WindowsBackend

        return WindowsBackend()
    elif sys.platform == "darwin":
        from calibrate_pro.platform.macos import MacOSBackend

        return MacOSBackend()
    elif sys.platform.startswith("linux"):
        from calibrate_pro.platform.linux import LinuxBackend

        return LinuxBackend()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}. Calibrate Pro supports win32, darwin, and linux.")


__all__ = ["get_platform_backend"]
