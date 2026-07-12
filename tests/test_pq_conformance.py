"""Cross-surface conformance tests for the audited ST 2084 primitive."""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import numpy as np
import pytest

SURFACES = (
    ("core", "calibrate_pro.core.pq", "pq_oetf", "pq_eotf"),
    ("color_math", "calibrate_pro.core.color_math", "pq_oetf", "pq_eotf"),
    ("color_models", "calibrate_pro.core.color_models", "pq_oetf", "pq_eotf"),
    ("targets", "calibrate_pro.targets.gamma", "pq_oetf", "pq_eotf"),
    ("hdr", "calibrate_pro.hdr.pq_st2084", "pq_oetf", "pq_eotf"),
    pytest.param(
        "dwm",
        "calibrate_pro.lut_system.dwm_lut",
        "pq_oetf",
        "pq_eotf",
        marks=pytest.mark.windows,
    ),
    ("scrgb", "calibrate_pro.display.scrgb_pipeline", "_pq_oetf", "_pq_eotf"),
)

EXPECTED_PARAMETERS = {
    "core": (("luminance", "peak_luminance"), ("signal", "peak_luminance")),
    "color_math": (("v", "peak_luminance"), ("v", "peak_luminance")),
    "color_models": (("Y",), ("E",)),
    "targets": (("L",), ("x",)),
    "hdr": (("luminance", "normalize_input"), ("signal", "normalize")),
    "dwm": (("Y",), ("E",)),
    "scrgb": (("nits", "peak_nits"), ("pq", "peak_nits")),
}

_GOLD_PATH = Path(__file__).parent / "data" / "st2084-gold-vectors.json"
_GOLD = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))
_NITS = np.array([vector["nits"] for vector in _GOLD["vectors"]], dtype=np.float64)
_PQ = np.array([vector["pq"] for vector in _GOLD["vectors"]], dtype=np.float64)

RAW_INPUTS = (
    ("float32", np.array([0.0, 0.5, 1.0], dtype=np.float32)),
    ("integer", np.array([0, 1], dtype=np.int16)),
    ("multidimensional", np.array([[0.0, 0.25], [0.5, 1.0]], dtype=np.float32)),
    ("empty", np.array([], dtype=np.float32)),
    ("python_scalar", 0.5),
    ("zero_dimensional", np.array(0.5, dtype=np.float32)),
)


@pytest.mark.parametrize(("label", "module_name", "encode_name", "decode_name"), SURFACES, ids=lambda value: value)
def test_st2084_gold_vectors_across_every_surface(
    label: str,
    module_name: str,
    encode_name: str,
    decode_name: str,
) -> None:
    module = importlib.import_module(module_name)
    encode = getattr(module, encode_name)
    decode = getattr(module, decode_name)

    encoded = encode(_NITS)
    decoded = decode(_PQ)

    assert isinstance(encoded, np.ndarray), label
    assert isinstance(decoded, np.ndarray), label
    assert encoded.dtype == np.dtype(np.float64), label
    assert decoded.dtype == np.dtype(np.float64), label
    np.testing.assert_allclose(
        encoded,
        _PQ,
        rtol=0.0,
        atol=float(_GOLD["float64_encode_abs_tolerance"]),
        err_msg=f"{label} ST 2084 encode drifted",
    )
    np.testing.assert_allclose(
        decoded,
        _NITS,
        rtol=0.0,
        atol=float(_GOLD["float64_decode_abs_tolerance_nits"]),
        err_msg=f"{label} ST 2084 decode drifted",
    )


@pytest.mark.parametrize(("label", "module_name", "encode_name", "decode_name"), SURFACES, ids=lambda value: value)
@pytest.mark.parametrize(("input_label", "sample"), RAW_INPUTS, ids=[case[0] for case in RAW_INPUTS])
def test_st2084_surfaces_preserve_raw_shape_as_float64_ndarray(
    label: str,
    module_name: str,
    encode_name: str,
    decode_name: str,
    input_label: str,
    sample: object,
) -> None:
    module = importlib.import_module(module_name)
    expected_shape = np.shape(sample)

    for function_name in (encode_name, decode_name):
        result = getattr(module, function_name)(sample)
        assert isinstance(result, np.ndarray), f"{label}/{function_name}/{input_label}"
        assert result.dtype == np.dtype(np.float64), f"{label}/{function_name}/{input_label}"
        assert result.shape == expected_shape, f"{label}/{function_name}/{input_label}"


@pytest.mark.parametrize(("label", "module_name", "encode_name", "decode_name"), SURFACES, ids=lambda value: value)
def test_st2084_compatibility_signatures_are_preserved(
    label: str,
    module_name: str,
    encode_name: str,
    decode_name: str,
) -> None:
    module = importlib.import_module(module_name)
    encode_parameters = tuple(inspect.signature(getattr(module, encode_name)).parameters)
    decode_parameters = tuple(inspect.signature(getattr(module, decode_name)).parameters)

    assert (encode_parameters, decode_parameters) == EXPECTED_PARAMETERS[label]


def test_hdr_normalization_flags_preserve_the_absolute_contract() -> None:
    module = importlib.import_module("calibrate_pro.hdr.pq_st2084")

    encoded = module.pq_oetf(_NITS / 10000.0, normalize_input=True)
    decoded = module.pq_eotf(_PQ, normalize=True)

    np.testing.assert_allclose(
        encoded,
        _PQ,
        rtol=0.0,
        atol=float(_GOLD["float64_encode_abs_tolerance"]),
    )
    np.testing.assert_allclose(
        decoded,
        _NITS / 10000.0,
        rtol=0.0,
        atol=float(_GOLD["float64_decode_abs_tolerance_nits"]) / 10000.0,
    )


@pytest.mark.parametrize("sample", (0.5, np.array(0.5, dtype=np.float32)))
def test_hdr_normalization_flags_return_zero_dimensional_float64_arrays(sample: object) -> None:
    module = importlib.import_module("calibrate_pro.hdr.pq_st2084")

    encoded = module.pq_oetf(sample, normalize_input=True)
    decoded = module.pq_eotf(sample, normalize=True)

    for result in (encoded, decoded):
        assert isinstance(result, np.ndarray)
        assert result.dtype == np.dtype(np.float64)
        assert result.shape == ()


def test_core_package_fixed_10000_wrappers_preserve_one_argument_api() -> None:
    import calibrate_pro.core as core
    from calibrate_pro.core.pq import pq_eotf as canonical_eotf
    from calibrate_pro.core.pq import pq_oetf as canonical_oetf

    encode_signature = inspect.signature(core.pq_oetf_10000)
    decode_signature = inspect.signature(core.pq_eotf_10000)
    assert tuple(encode_signature.parameters) == ("Y",)
    assert tuple(decode_signature.parameters) == ("E",)
    assert encode_signature.parameters["Y"].default is inspect.Parameter.empty
    assert decode_signature.parameters["E"].default is inspect.Parameter.empty
    assert core.pq_oetf_10000 is not canonical_oetf
    assert core.pq_eotf_10000 is not canonical_eotf

    encoded = core.pq_oetf_10000(_NITS)
    decoded = core.pq_eotf_10000(_PQ)
    np.testing.assert_array_equal(encoded, canonical_oetf(_NITS, peak_luminance=10000.0))
    np.testing.assert_array_equal(decoded, canonical_eotf(_PQ, peak_luminance=10000.0))

    with pytest.raises(TypeError):
        core.pq_oetf_10000(_NITS, 1000.0)
    with pytest.raises(TypeError):
        core.pq_eotf_10000(_PQ, 1000.0)


@pytest.mark.parametrize("function_name", ("pq_oetf", "pq_eotf"))
@pytest.mark.parametrize("peak_luminance", (0.0, -1.0))
def test_canonical_st2084_rejects_non_positive_peak(function_name: str, peak_luminance: float) -> None:
    module = importlib.import_module("calibrate_pro.core.pq")

    with pytest.raises(ValueError, match="peak_luminance must be finite and positive"):
        getattr(module, function_name)(np.array([0.5], dtype=np.float64), peak_luminance=peak_luminance)


@pytest.mark.parametrize("function_name", ("pq_oetf", "pq_eotf"))
@pytest.mark.parametrize(
    "peak_luminance",
    (pytest.param(np.nan, id="nan"), pytest.param(np.inf, id="positive_inf"), pytest.param(-np.inf, id="negative_inf")),
)
def test_canonical_st2084_rejects_non_finite_peak(function_name: str, peak_luminance: float) -> None:
    module = importlib.import_module("calibrate_pro.core.pq")

    with pytest.raises(ValueError, match="peak_luminance must be finite and positive"):
        getattr(module, function_name)(np.array([0.5], dtype=np.float64), peak_luminance=peak_luminance)


@pytest.mark.parametrize("function_name", ("pq_oetf", "pq_eotf"))
@pytest.mark.parametrize(
    "sample",
    (pytest.param(np.nan, id="nan"), pytest.param(np.inf, id="positive_inf"), pytest.param(-np.inf, id="negative_inf")),
)
def test_canonical_st2084_rejects_non_finite_samples(function_name: str, sample: float) -> None:
    module = importlib.import_module("calibrate_pro.core.pq")
    values = np.array([0.0, sample], dtype=np.float64)

    with pytest.raises(ValueError, match="ST 2084 samples must be finite"):
        getattr(module, function_name)(values)


def test_st2084_m2_is_exact() -> None:
    from calibrate_pro.core.pq import ST2084_M2

    assert ST2084_M2 == 78.84375
