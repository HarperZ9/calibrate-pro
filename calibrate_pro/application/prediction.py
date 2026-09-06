"""What a sensorless run establishes about a display, and what it leaves open.

Nothing here reads an instrument. The figures come from simulating the
generated correction chain against the ColorChecker reference using the panel
record's own numbers, so they describe the model rather than the display in
front of the operator.

The figure reported is the part of that simulation the panel record actually
determines: how far this panel's corrected output falls from a display with
exact sRGB primaries driven through the same chain. That is gamut reproduction.
It rises when a reference colour sits outside what the panel can reach and when
the native white has to be adapted onto the target. It is zero when the
correction matrix maps the panel's primaries onto sRGB exactly, which is the
true answer for every panel in the shipped database.

The same measure is reported for the display with no correction applied, and
that is the figure showing the correction did anything. The corrected number is
near zero for every panel this build handles correctly, so printed on its own it
reads the same on a display that needed clamping and on one that was already
sRGB. Reading the pair, an operator sees which of the two they have.

Tone response is not in it and cannot be. The chain encodes for the gamma the
panel record claims and the panel decodes with the same number, so the two
cancel and nothing about grey tracking survives into the result. A record
carrying 2.6 on red and 1.9 on green scores identically to a perfect one. That
is the largest error a sensorless calibration leaves behind, so it is named as
unestablished beside the figure rather than folded into it.

Comparing against the ColorChecker Lab column instead, which is what this
module did before, carries the reference table's own round-trip into the
number. That residual is near 0.65 dE, it lands within 0.001 of the same value
on all fifty-nine panels in the database, and printing it told an operator
their display scores 0.65 when the figure described the chart.

The simulation is fixed to one target. It linearizes with a 2.2 power law,
builds its correction matrix without a target argument, and adapts the
displayed stimulus from a D65 display white. A session aiming somewhere else
gets no number, because a figure computed for the wrong target would read as an
accuracy claim about a calibration nobody produced.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from calibrate_pro.application.results import (
    CORRECTION_THRESHOLD_DELTA_E,
    VerificationResult,
    VerifiedPatch,
)
from calibrate_pro.application.target_selection import TargetSelectionError, resolve_target
from calibrate_pro.core.color_math import delta_e_2000
from calibrate_pro.panels.panel_types import (
    ChromaticityCoord,
    GammaCurve,
    PanelCharacterization,
    PanelPrimaries,
)
from calibrate_pro.sensorless.neuralux import SensorlessEngine
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

#: Named in the evidence source of every predicted figure, so a report says
#: which code produced the number rather than only that it was predicted.
MODEL_NAME = "sensorless.neuralux.verify_calibration"

#: What the figure is, in the words a surface labels it with.
METRIC_NAME = "gamut reproduction, modelled"

#: The correction simulated to get the before figure. An identity matrix leaves
#: the chain's encode and decode steps cancelling as they already do, so the run
#: differs from the corrected one in the matrix and nothing else.
_NO_CORRECTION = np.eye(3)

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

#: Printed beside every predicted figure. It has to carry both halves: what the
#: number is, and the error it is blind to. A reader who takes it for accuracy
#: would be reading a claim about grey that this path never makes.
PREDICTED_LIMITATION = (
    f"Predicted by {MODEL_NAME} from the plan this session generated. No display was "
    "measured and no sensor was read. The figure is gamut reproduction: how far this "
    "panel's corrected output falls from a display with exact sRGB primaries. Tone "
    "response is outside it. The correction encodes for the gamma the panel record "
    "claims and the panel decodes with the same number, so a display whose grey tracks "
    "nothing like its record scores the same here. Measure to establish grey."
)

_UNCOVERED_METRIC = MetricValue(value=None, unit=DELTA_E_UNIT, evidence=EvidenceKind.NOT_MEASURED)

#: The baseline run, kept per engine class. The chain reads nothing but the
#: panel it is handed and the reference table, so one run answers for every
#: session in the process, and the run costs about a fifth of a second.
_BASELINE: dict[type, tuple[np.ndarray, ...]] = {}


def reference_panel() -> PanelCharacterization:
    """The display every predicted figure is expressed against.

    Built here rather than read from the panel database. A record edited in the
    database would otherwise move the baseline that every panel's figure is
    measured from, and no test comparing two panels would notice.
    """
    return PanelCharacterization(
        manufacturer="",
        model_pattern="reference-srgb",
        panel_type="reference",
        native_primaries=PanelPrimaries(
            red=ChromaticityCoord(0.6400, 0.3300),
            green=ChromaticityCoord(0.3000, 0.6000),
            blue=ChromaticityCoord(0.1500, 0.0600),
            white=ChromaticityCoord(0.3127, 0.3290),
        ),
        gamma_red=GammaCurve(gamma=2.2),
        gamma_green=GammaCurve(gamma=2.2),
        gamma_blue=GammaCurve(gamma=2.2),
    )


def target_is_modelled(preset_id: str) -> bool:
    """Report whether the simulation covers the target this selection names.

    A target the simulation does not model answers False rather than raising,
    including one that names no target at all. The caller is asking whether a
    modelled figure may be reported, and the answer to that is no either way.
    """
    try:
        target = resolve_target(preset_id)
    except TargetSelectionError:
        return False
    return (target.gamut_label, target.white_label, target.tone_label) == MODELLED_TARGET


def _colour(patch: dict[str, Any], key: str) -> tuple[float, float, float]:
    """Read one three-component colour, refusing anything else."""
    value = patch.get(key)
    if not isinstance(value, (tuple, list)) or len(value) != 3:
        raise ValueError(f"accuracy model returned no {key} for a patch")
    return (float(value[0]), float(value[1]), float(value[2]))


def _patches(report: object) -> list[dict[str, Any]]:
    """Read the simulated patches, refusing a shape a surface cannot render.

    The check is here rather than in the surface because a missing field means
    the model changed, and a grid that quietly drew a placeholder for it would
    show an operator a patch that was never simulated.
    """
    if not isinstance(report, dict):
        raise ValueError("accuracy model returned an unexpected result type")
    patches = report.get("patches")
    if not isinstance(patches, list) or not patches:
        raise ValueError("accuracy model returned no patches")
    for patch in patches:
        if not isinstance(patch, dict):
            raise ValueError("accuracy model returned an unexpected patch type")
        name = patch.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("accuracy model returned a patch with no name")
    return patches


def _baseline(engine: SensorlessEngine) -> tuple[np.ndarray, ...]:
    """The Lab a reference display shows for each patch, run once per process.

    Held per engine class so a subclass that simulates differently gets its own
    baseline rather than one taken from the class it replaced. The simulation
    reads the panel it is handed and the reference chart, and nothing off the
    engine, so one run answers for every session in the process.

    The call is made on the caller's engine to keep the baseline on the same
    code path as the figure it is subtracted from. That records the reference
    panel in the engine's own last-result field, which the real panel's run
    overwrites on the next line, and which nothing outside the engine reads.
    """
    kind = type(engine)
    held = _BASELINE.get(kind)
    if held is None:
        patches = _patches(engine.verify_calibration(reference_panel()))
        held = tuple(np.array(_colour(patch, "displayed_lab")) for patch in patches)
        _BASELINE[kind] = held
    return held


def _verified(patch: dict[str, Any], delta_e: float) -> VerifiedPatch:
    return VerifiedPatch(
        name=str(patch["name"]),
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
    """Report gamut reproduction for a covered target, or say it is uncovered."""
    if not target_is_modelled(preset_id):
        return uncovered_result(preset_id)
    baseline = _baseline(engine)
    patches = _patches(engine.verify_calibration(panel))
    if len(patches) != len(baseline):
        raise ValueError("accuracy model returned a different patch count than the reference run")
    deltas = _deltas(patches, baseline)
    bare = _patches(engine.verify_calibration(panel, correction=_NO_CORRECTION))
    if len(bare) != len(baseline):
        raise ValueError("accuracy model returned a different patch count than the reference run")
    uncorrected = _deltas(bare, baseline)
    return VerificationResult(
        source=VERIFICATION_SOURCE,
        evidence=EvidenceKind.ESTIMATED,
        average_delta_e=_metric(float(np.mean(deltas))),
        maximum_delta_e=_metric(float(np.max(deltas))),
        patches=tuple(_verified(patch, delta) for patch, delta in zip(patches, deltas, strict=True)),
        limitation=PREDICTED_LIMITATION,
        metric=METRIC_NAME,
        uncorrected_average_delta_e=_metric(float(np.mean(uncorrected))),
        uncorrected_maximum_delta_e=_metric(float(np.max(uncorrected))),
    )


def _deltas(patches: list[dict[str, Any]], baseline: tuple[np.ndarray, ...]) -> list[float]:
    """How far each simulated patch falls from the reference display's own."""
    return [
        float(delta_e_2000(np.array(_colour(patch, "displayed_lab")), reference))
        for patch, reference in zip(patches, baseline, strict=True)
    ]


def _metric(value: float) -> MetricValue:
    return MetricValue(
        value=value,
        unit=DELTA_E_UNIT,
        evidence=EvidenceKind.ESTIMATED,
        source=MODEL_NAME,
    )


__all__ = [
    "CORRECTION_THRESHOLD_DELTA_E",
    "DELTA_E_UNIT",
    "METRIC_NAME",
    "MODELLED_TARGET",
    "MODEL_NAME",
    "PREDICTED_LIMITATION",
    "VERIFICATION_SOURCE",
    "predict_accuracy",
    "reference_panel",
    "target_is_modelled",
    "uncovered_result",
]
