"""Fail-closed runtime support checks for the bundled DWM injector."""

from __future__ import annotations

import sys

import pytest

# Importing the injector reaches calibrate_pro.lut_system, whose package body
# binds user32 through ctypes.windll. A windows marker would not help: pytest
# imports a module to read its markers, so the deselection happens after the
# import that fails. The skip has to run before the import below.
if sys.platform != "win32":
    pytest.skip("the DWM injector guard reads a Windows-only import chain", allow_module_level=True)

from calibrate_pro.lut_system.dwm_lut import (
    DwmLutError,
    assert_dwm_lut_runtime_supported,
)


@pytest.mark.parametrize("build", [19042, 19043, 22000])
def test_bundled_v38_accepts_only_its_documented_windows_builds(build: int) -> None:
    assert_dwm_lut_runtime_supported("3.8", build)


@pytest.mark.parametrize("build", [22621, 26100, 26220])
def test_bundled_v38_rejects_newer_dwm_builds_before_injection(build: int) -> None:
    with pytest.raises(DwmLutError, match="unsupported.*build"):
        assert_dwm_lut_runtime_supported("3.8", build)
