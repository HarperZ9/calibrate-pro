"""The Spyder reads white and black off two different patches.

``analyze_display`` took two readings back to back, filed the first as the white
point and the second as the black level, and never put either patch on screen.
Both readings described whatever image was already there, so the contrast ratio
built from them sat near 1.0 for any panel, and the white chromaticity and CCT
beside it belonged to the desktop rather than to a white field.

PRODUCT.md: the interface must never convert modeled, simulated, replayed, or
placeholder values into apparent instrument observations. A reading filed under
a patch that was never shown is that conversion. The sibling module
``test_patch_must_be_displayed.py`` holds the colorimeter and camera paths to
the same rule.
"""

from __future__ import annotations

import pytest

from calibrate_pro.hardware.colorimeter_base import CalibrationPatch, ColorMeasurement
from calibrate_pro.hardware.spyder import SpyderDriver


class _SpyderReads:
    """Hands out a queue of readings and records the patch shown before each."""

    def __init__(self, driver, luminances: list[float]):
        self.driver = driver
        self.luminances = list(luminances)
        self.shown: list[str] = []
        self.read_at: list[str] = []

    def show(self, patch: CalibrationPatch) -> None:
        self.shown.append(patch.name)

    def measure(self) -> ColorMeasurement | None:
        self.read_at.append(self.shown[-1] if self.shown else "nothing")
        luminance = self.luminances.pop(0)
        return ColorMeasurement(
            X=luminance * 0.95, Y=luminance, Z=luminance * 1.09, x=0.3127, y=0.3290, luminance=luminance, cct=6504.0
        )


@pytest.fixture
def spyder():
    """A Spyder reporting itself connected, with no ArgyllCMS behind it."""
    driver = SpyderDriver()
    driver.is_connected = True
    return driver


def test_spyder_analysis_returns_nothing_without_a_display(spyder):
    """No callback means neither read can be attributed, so nothing comes back."""
    reads = _SpyderReads(spyder, [120.0, 0.12])
    spyder.measure_spot = reads.measure

    assert spyder.analyze_display() is None
    assert reads.read_at == []


def test_spyder_analysis_says_why_it_returned_nothing(spyder):
    """The progress channel carries the reason rather than failing silently."""
    messages: list[str] = []
    spyder.set_progress_callback(lambda msg, pct: messages.append(msg))

    spyder.analyze_display()

    assert any("display callback" in m for m in messages)


def test_spyder_shows_white_then_black_before_each_read(spyder):
    """Each read happens with the patch it is filed under already on screen."""
    reads = _SpyderReads(spyder, [120.0, 0.12])
    spyder.measure_spot = reads.measure

    spyder.analyze_display(reads.show)

    assert reads.shown == ["White", "Black"]
    assert reads.read_at == ["White", "Black"]


def test_spyder_contrast_ratio_comes_from_two_different_patches(spyder):
    """White over black, not one unchanged screen divided by itself.

    Without the display step both reads landed on whatever was already showing,
    so the ratio was near 1.0 for any panel and described nothing.
    """
    reads = _SpyderReads(spyder, [120.0, 0.12])
    spyder.measure_spot = reads.measure

    results = spyder.analyze_display(reads.show)

    assert results["white_luminance"] == 120.0
    assert results["black_luminance"] == 0.12
    assert results["contrast_ratio"] == pytest.approx(1000.0)


def test_spyder_analysis_still_refuses_when_disconnected(spyder):
    """The connection guard runs ahead of the callback guard, unchanged."""
    spyder.is_connected = False

    assert spyder.analyze_display(lambda patch: None) is None
