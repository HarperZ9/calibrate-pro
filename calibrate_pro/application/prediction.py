"""Predicted sensorless accuracy, and the targets the prediction does not cover.

The module is named for what it produces. Nothing here reads an instrument.
The figures come from simulating the generated correction chain against the
ColorChecker reference using the panel record's own numbers, so they describe
the model rather than the display in front of the operator.

The simulation is fixed to one target. It linearizes with a 2.2 power law,
builds its correction matrix without a target argument, and adapts the
displayed stimulus from a D65 display white. A session aiming somewhere else
gets no number, because a figure computed for the wrong target would read as an
accuracy claim about a calibration nobody produced.
"""

from __future__ import annotations

from typing import Any

from calibrate_pro.application.actions import PRESET_TARGETS
from calibrate_pro.application.results import PredictedPatch, VerificationResult
from calibrate_pro.panels.panel_types import PanelCharacterization
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

#: Named in the evidence source of every predicted figure, so a report says
#: which code produced the number rather than only that it was predicted.
MODEL_NAME = "sensorless.neuralux.verify_calibration"

#: The target the simulation actually models: sRGB primaries, a D65 display
#: white, and a 2.2 power-law tone response.
MODELLED_TARGET = ("sRGB", "D65", "2.2")

#: What this verification examined. It is the plan the session generated, not a
#: display, and the name says so wherever the result is rendered.
VERIFICATION_SOURCE = "generated_plan"

DELTA_E_UNIT = "dE2000"

_UNCOVERED_LIMITATION = (
    "The sensorless accuracy model simulates sRGB primaries, a D65 white point "
    "and a 2.2 power-law tone response. This target differs from that, so no "
    "predicted accuracy is reported for it."
)

_UNCOVERED_METRIC = MetricValue(value=None, unit=DELTA_E_UNIT, evidence=EvidenceKind.NOT_MEASURED)


def target_is_modelled(preset_id: str) -> bool:
    """Report whether the simulation covers the target this preset selects."""
    target = PRESET_TARGETS.get(preset_id)
    if target is None:
        return False
    return (target[0], target[1], target[2]) == MODELLED_TARGET


def _finite_float(report: dict[str, Any], key: str) -> float:
    value = report.get(key)
    if type(value) is not float:
        raise ValueError(f"accuracy model returned no {key}")
    return value


def _colour(patch: dict[str, Any], key: str) -> tuple[float, float, float]:
    """Read one three-component colour, refusing anything else."""
    value = patch.get(key)
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError(f"accuracy model returned no {key} for a patch")
    return (float(value[0]), float(value[1]), float(value[2]))


def _predicted_patch(patch: object) -> PredictedPatch:
    """Restate one simulated patch, refusing a shape a surface cannot render.

    The check is here rather than in the surface because a missing field means
    the model changed, and a grid that quietly drew a placeholder for it would
    show an operator a patch that was never simulated.
    """
    if not isinstance(patch, dict):
        raise ValueError("accuracy model returned an unexpected patch type")
    name = patch.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("accuracy model returned a patch with no name")
    delta_e = patch.get("delta_e")
    if type(delta_e) is not float:
        raise ValueError(f"accuracy model returned no delta_e for {name}")
    return PredictedPatch(
        name=name,
        reference_srgb=_colour(patch, "ref_srgb"),
        displayed_lab=_colour(patch, "displayed_lab"),
        delta_e=MetricValue(
            value=delta_e,
            unit=DELTA_E_UNIT,
            evidence=EvidenceKind.ESTIMATED,
            source=MODEL_NAME,
        ),
    )


def uncovered_result(preset_id: str) -> VerificationResult:
    """Answer for a target the model does not cover, carrying no figure."""
    _ = preset_id
    return VerificationResult(
        source=VERIFICATION_SOURCE,
        evidence=EvidenceKind.NOT_MEASURED,
        average_delta_e=_UNCOVERED_METRIC,
        maximum_delta_e=_UNCOVERED_METRIC,
        patches=(),
        limitation=_UNCOVERED_LIMITATION,
    )


def predict_accuracy(
    engine: SensorlessEngine,
    panel: PanelCharacterization,
    preset_id: str,
) -> VerificationResult:
    """Predict accuracy for a covered target, or report that it is uncovered."""
    if not target_is_modelled(preset_id):
        return uncovered_result(preset_id)
    report = engine.verify_calibration(panel)
    if not isinstance(report, dict):
        raise ValueError("accuracy model returned an unexpected result type")
    average = _finite_float(report, "delta_e_avg")
    maximum = _finite_float(report, "delta_e_max")
    patches = report.get("patches")
    if not isinstance(patches, list) or not patches:
        raise ValueError("accuracy model returned no patches")
    return VerificationResult(
        source=VERIFICATION_SOURCE,
        evidence=EvidenceKind.ESTIMATED,
        average_delta_e=MetricValue(
            value=average,
            unit=DELTA_E_UNIT,
            evidence=EvidenceKind.ESTIMATED,
            source=MODEL_NAME,
        ),
        maximum_delta_e=MetricValue(
            value=maximum,
            unit=DELTA_E_UNIT,
            evidence=EvidenceKind.ESTIMATED,
            source=MODEL_NAME,
        ),
        patches=tuple(_predicted_patch(patch) for patch in patches),
        limitation=None,
    )


__all__ = [
    "DELTA_E_UNIT",
    "MODELLED_TARGET",
    "MODEL_NAME",
    "VERIFICATION_SOURCE",
    "predict_accuracy",
    "target_is_modelled",
    "uncovered_result",
]
