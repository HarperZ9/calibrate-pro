"""A tone curve the parser cannot read is not guessed at.

An ICC ``para`` tag names its formula in a function type field, and ``_parse_trc``
read every type as the type 0 pure gamma ``X ** g``. Types 1 through 4 carry a
linear segment near black, so the curve the parser built moved the shadow end of
the tone response.

This one is not a readout. The curve drives the gamma ramp loaded into the
display, so the wrong curve reached the panel rather than being misreported in a
number someone reads. The refusal is the same shape: return nothing and let the
caller fall back.
"""

from __future__ import annotations

import pytest


def _para_tag(function_type: int, gamma: float = 2.2) -> bytes:
    """Build an ICC ``para`` tone curve tag with one s15Fixed16 parameter."""
    import struct

    return (
        b"para"
        + b"\x00" * 4
        + struct.pack(">H", function_type)
        + b"\x00\x00"
        + struct.pack(">I", int(gamma * 65536))
        + b"\x00" * 24
    )


@pytest.mark.windows
@pytest.mark.parametrize("function_type", [1, 2, 3, 4])
def test_a_parametric_curve_with_a_linear_segment_is_not_read_as_pure_gamma(function_type):
    """Types 1 through 4 carry a linear segment near black, so ``X ** g`` is wrong.

    The parser applied the type 0 formula to every type. The curve it produced
    went on to drive the display LUT, so the shadow end of the tone curve was
    moved on the panel rather than misreported in a readout.
    """
    from calibrate_pro.lut_system.color_loader import ColorLoader, LoaderConfig

    loader = ColorLoader(LoaderConfig(persist_across_restart=False))

    assert loader._parse_trc(_para_tag(function_type)) is None


@pytest.mark.windows
def test_a_pure_gamma_parametric_curve_is_still_decoded():
    """Type 0 is ``X ** g`` by definition, so it keeps its curve."""
    from calibrate_pro.lut_system.color_loader import ColorLoader, LoaderConfig

    loader = ColorLoader(LoaderConfig(persist_across_restart=False))

    curve = loader._parse_trc(_para_tag(0, gamma=2.2))

    assert curve is not None
    assert len(curve) == 256
    assert curve[0] == 0
    assert curve[255] == 65535
    assert all(curve[i] <= curve[i + 1] for i in range(255))
