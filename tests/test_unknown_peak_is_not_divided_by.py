"""A luminance argument either changes the result or it does not exist.

Four functions took a peak or a black luminance and told the caller what it
did to the output. Three of them never read it: the MHC2 profile writer, the
colour volume integrator, and the reference-white leg of the HDR LUT, which
computed the BT.2408 fraction of the peak and discarded the expression. Those
arguments are gone. A control that reads like a measurement input and steers
nothing is the same false report as a fabricated number, one level up.

The fourth reads its peak at every grid point and divides by it. That was
harmless while every panel came from the builtin database with a measured
peak. It stopped being harmless once an EDID-built panel and an imported
community panel began reporting zero for photometry nobody measured: a zero
peak turns the whole LUT into inf and nan and writes it out as a calibration,
and the caller in ``SensorlessEngine.create_3d_lut`` passed it straight
through. Both ends now refuse, and the outer one names the panel.

Honest null: no LUT is loaded into a GPU and no ICC profile is installed here.
These tests pin what is computed and what is written to bytes. The repo's
instructions treat DWM LUT loading and profile installation as side-effecting
code that routine test runs do not touch.

PRODUCT.md: the interface must never convert modeled, simulated, replayed, or
placeholder values into apparent instrument observations.
"""

from __future__ import annotations

import inspect
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from calibrate_pro.community.database import import_panel
from calibrate_pro.core.lut_engine import LUTGenerator
from calibrate_pro.display.color_volume import compute_color_volume
from calibrate_pro.panels.database import get_database
from calibrate_pro.profiles.mhc2 import generate_mhc2_profile
from calibrate_pro.sensorless.neuralux import SensorlessEngine

P3_PRIMARIES = ((0.6800, 0.3200), (0.2650, 0.6900), (0.1500, 0.0600))
D65 = (0.3127, 0.3290)


@pytest.fixture
def unmeasured_panel(tmp_path):
    """A community submission carrying primaries and gamma, and no photometry."""
    path = tmp_path / "unmeasured.json"
    path.write_text(
        json.dumps(
            {
                "calibrate_pro_community": True,
                "version": 1,
                "panel_key": "UNMEASURED1",
                "manufacturer": "Contributor",
                "model": "UNMEASURED1",
                "panel_type": "IPS",
                "display_name": "Unmeasured IPS",
                "primaries": {
                    "red": {"x": 0.6800, "y": 0.3200},
                    "green": {"x": 0.2650, "y": 0.6900},
                    "blue": {"x": 0.1500, "y": 0.0600},
                    "white": {"x": 0.3127, "y": 0.3290},
                },
                "gamma": {"red": 2.2, "green": 2.2, "blue": 2.2},
            }
        ),
        encoding="utf-8",
    )
    return import_panel(path)


# -------------------------------------------------------------------------
# The HDR LUT refuses a peak it would divide by
# -------------------------------------------------------------------------


@pytest.mark.parametrize("peak", [0.0, -1.0])
def test_the_hdr_lut_refuses_a_non_positive_peak(peak):
    """Zero marks a panel whose peak was never measured. It used to divide."""
    with pytest.raises(ValueError, match="peak luminance"):
        LUTGenerator(size=9).create_hdr_calibration_lut(
            panel_primaries=P3_PRIMARIES,
            panel_white=D65,
            peak_luminance=peak,
        )


def test_a_measured_peak_still_produces_a_finite_lut():
    """The refusal is the point, so check the working path is untouched.

    Every entry finite is the assertion the old behaviour failed: with a zero
    peak this grid came back filled with nan.
    """
    lut = LUTGenerator(size=9).create_hdr_calibration_lut(
        panel_primaries=P3_PRIMARIES,
        panel_white=D65,
        peak_luminance=400.0,
    )

    assert np.all(np.isfinite(lut.data))
    np.testing.assert_allclose(lut.data[0, 0, 0], [0, 0, 0], atol=1e-10)


def test_the_hdr_lut_takes_no_reference_white_argument():
    """It computed the BT.2408 fraction of the peak and threw the value away."""
    params = inspect.signature(LUTGenerator.create_hdr_calibration_lut).parameters

    assert "target_white_luminance" not in params


# -------------------------------------------------------------------------
# The caller names the panel before the engine raises
# -------------------------------------------------------------------------


def test_an_hdr_lut_for_an_unmeasured_panel_names_the_panel(unmeasured_panel):
    """A stack trace from inside the LUT loop does not tell the user what to fix."""
    with pytest.raises(ValueError, match=unmeasured_panel.name):
        SensorlessEngine().create_3d_lut(panel=unmeasured_panel, size=9, hdr_mode=True)


def test_an_sdr_lut_for_an_unmeasured_panel_is_still_built(unmeasured_panel):
    """Primaries and gamma are measured, and the SDR path needs no peak."""
    lut = SensorlessEngine().create_3d_lut(panel=unmeasured_panel, size=9, hdr_mode=False)

    assert np.all(np.isfinite(lut.data))


def test_an_hdr_lut_for_a_measured_panel_is_still_built():
    """The guard must not disable HDR for a panel that carries a peak."""
    panel = get_database().get_panel("AW3423DW")
    assert panel is not None
    assert panel.capabilities.max_luminance_hdr > 0.0

    lut = SensorlessEngine().create_3d_lut(panel=panel, size=9, hdr_mode=True)

    assert np.all(np.isfinite(lut.data))


# -------------------------------------------------------------------------
# The arguments that steered nothing are gone
# -------------------------------------------------------------------------


def test_the_colour_volume_takes_no_peak_luminance():
    """It was documented as driving rolloff modelling and was never read."""
    assert "peak_luminance" not in inspect.signature(compute_color_volume).parameters


def test_the_colour_volume_rolloff_is_driven_by_the_panel_family():
    """What does steer the number, so the removed argument is not mistaken for it."""
    common = {"panel_primaries": P3_PRIMARIES, "panel_white": D65, "lightness_steps": 7, "hue_steps": 12}

    lcd = compute_color_volume(panel_type="IPS", **common)
    woled = compute_color_volume(panel_type="WOLED", **common)

    assert woled.p3_volume_pct != pytest.approx(lcd.p3_volume_pct)


@pytest.mark.parametrize("argument", ["peak_luminance", "min_luminance"])
def test_the_mhc2_writer_takes_no_luminance(argument):
    """It documented them as the display luminance written into the profile."""
    assert argument not in inspect.signature(generate_mhc2_profile).parameters


def _read_tag(profile: bytes, signature: bytes) -> bytes:
    """Pull one tag out of an ICC profile by its four-byte signature."""
    count = struct.unpack(">I", profile[128:132])[0]
    for i in range(count):
        entry = 132 + i * 12
        sig, offset, size = struct.unpack(">4sII", profile[entry : entry + 12])
        if sig == signature:
            return profile[offset : offset + size]
    raise AssertionError(f"{signature!r} tag not present")


def test_the_mhc2_tag_this_writes_carries_the_matrix_and_nothing_else(tmp_path: Path):
    """The claim the docstring now makes, checked against the bytes.

    Matrix type 1 is a signature, a reserved word, the type, and twelve
    s15Fixed16 values. There is no field for a peak or a black level, which is
    why the two arguments could be removed without changing a single byte of
    the profile.
    """
    profile = generate_mhc2_profile(
        panel_primaries=P3_PRIMARIES,
        panel_white=D65,
        output_path=tmp_path / "hdr.icc",
    )

    tag = _read_tag(profile, b"MHC2")

    assert len(tag) == 60
    assert tag[:4] == b"MHC2"
    assert struct.unpack(">I", tag[8:12])[0] == 1
