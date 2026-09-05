"""Fail-closed runtime support checks for the bundled DWM injector."""

from __future__ import annotations

import pytest

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
