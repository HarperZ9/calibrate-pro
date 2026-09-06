"""Whether a bundle labelled for a gamut says how much of it the display reaches.

A generic sRGB panel asked for BT.2020 produced a manifest reading
``"gamut_mode": "BT.2020"`` and nothing beside it. That panel encloses 52.9% of
BT.2020 and cannot touch a single corner of it. The label was a value the
operator declared, written where a reader takes it for a property of the
computed artifact, which is the one thing PRODUCT.md forbids.

Refusing the target would be the wrong answer. Clamping a wide gamut onto a
narrower panel is the ordinary workflow, and ArgyllCMS, DisplayCAL and Calman
all profile toward an unreachable target and report the coverage. What none of
them do is let the label travel alone. So the figure travels with it, and these
tests hold that down at each place it passes through: the arithmetic, the
manifest that is hashed, the plan the operator confirms, and both surfaces.

Two of them are controls rather than assertions about the feature. One recovers
the coverage percentage by a method that shares no code with the one under test,
because a clipper checked against itself reports its own bugs as agreement. The
other drives the same gamut label over two different panels and reads two
different answers, which is the property that makes the row worth printing.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pytest

from calibrate_pro.application.assets import MANIFEST_FILENAME
from calibrate_pro.application.results import NO_GAMUT_CLAIM, reach_text
from calibrate_pro.application.target_selection import (
    GAMUT_MODES,
    compose_target_id,
    resolve_target,
    selectable_gamuts,
)
from calibrate_pro.gui.plan_dialog import plan_rows
from calibrate_pro.panels.builtin_panels import get_builtin_panels
from calibrate_pro.targets.coverage import chromaticity_coverage, gamut_containment
from calibrate_pro.targets.gamut import GAMUT_PRIMARIES, ColorPrimaries, GamutPreset, GamutTarget, reach_of_gamut_mode
from calibrate_pro.workflow import ApplyPlan, CalibrationMethod
from tests.session_support import arguments, build_cli_service, field, run

#: A panel that reaches sRGB and nothing wider, and a panel that reaches most of
#: DCI-P3. The pair is the point: one gamut label over both of them is the case
#: the reach row exists to tell apart.
NARROW = "GENERIC_SRGB"
WIDE = "AW3423DW"

#: Barycentric lattice divisions for the independent coverage estimate. At this
#: density the estimate lands within a third of a percentage point of the
#: clipper on every panel and gamut in the database, and the residual is the
#: lattice boundary rather than either method being wrong.
DIVISIONS = 800

#: How far the two coverage methods may disagree, in percentage points. Set
#: above the lattice error and far below anything an operator would act on.
COVERAGE_TOLERANCE = 0.5

_CORNERS = ("red", "green", "blue")


def panel_primaries(key: str) -> object:
    """The primaries record for one panel in the shipped database."""
    return get_builtin_panels()[key].native_primaries


def corners(primaries: object) -> list[tuple[float, float]]:
    """Read R, G, B chromaticities without using the module under test.

    Both primaries types name the same three corners and differ only in whether
    a corner is a tuple or a record. Reading them here rather than calling the
    package helper keeps the independent estimate below independent.
    """
    read = []
    for name in _CORNERS:
        corner = getattr(primaries, name)
        as_tuple = getattr(corner, "as_tuple", None)
        corner = as_tuple() if callable(as_tuple) else corner
        read.append((float(corner[0]), float(corner[1])))
    return read


def coverage_by_counting(display: object, reference: object, divisions: int = DIVISIONS) -> float:
    """Coverage recovered by counting sampled points, sharing no code with it.

    The figure under test is a Sutherland-Hodgman polygon intersection divided
    by a triangle area. This lays a uniform barycentric lattice over the target
    triangle and counts the points that fall inside the display triangle, which
    is the same quantity computed from half-plane tests and nothing else. A
    clipper compared against itself agrees with its own defects.
    """
    r, g, b = corners(reference)
    rows, columns = np.meshgrid(np.arange(divisions + 1), np.arange(divisions + 1), indexing="ij")
    inside_triangle = (rows + columns) <= divisions
    first = rows[inside_triangle] / divisions
    second = columns[inside_triangle] / divisions
    third = 1.0 - first - second
    xs = first * r[0] + second * g[0] + third * b[0]
    ys = first * r[1] + second * g[1] + third * b[1]

    shape = corners(display)
    turn = (shape[1][0] - shape[0][0]) * (shape[2][1] - shape[1][1]) - (shape[1][1] - shape[0][1]) * (
        shape[2][0] - shape[1][0]
    )
    orientation = 1.0 if turn > 0 else -1.0
    covered = np.ones(xs.shape, dtype=bool)
    for index in range(3):
        a_x, a_y = shape[index]
        b_x, b_y = shape[(index + 1) % 3]
        covered &= ((b_x - a_x) * (ys - a_y) - (b_y - a_y) * (xs - a_x)) * orientation >= 0
    return 100.0 * float(covered.sum()) / float(covered.size)


def bundle_at(tmp_path: Path, name: str, **flags: object) -> dict:
    """Publish one bundle through the terminal and hand back its manifest."""
    directory = tmp_path / name
    code, _ = run("generate-profiles", build_cli_service(tmp_path / f"session-{name}"), output=str(directory), **flags)
    assert code == 0, "the publishing run this test depends on was refused"
    return json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))


def printed_plan(tmp_path: Path, name: str, **flags: object) -> tuple[str, object]:
    """Drive one session to a sealed plan and print it, the way `verify` does.

    Handing back the preview beside the text is what lets the terminal and the
    window be compared against one object rather than against each other's
    wording.
    """
    from calibrate_pro.commands import session as commands

    service = build_cli_service(tmp_path / f"session-{name}")
    target, generated, preview = commands._drive_to_preview(service, arguments(**flags))
    text = io.StringIO()
    with redirect_stdout(text):
        commands._print_plan(target, generated, preview)
    return text.getvalue(), preview


def bare_plan(**overrides: object) -> ApplyPlan:
    """The smallest plan the workflow accepts, so a row is read in isolation."""
    fields = {
        "display_id": "DISPLAY-1",
        "method": CalibrationMethod.SENSORLESS,
        "target_whitepoint": "D65",
        "target_gamma": "sRGB",
        "target_gamut": "BT.2020",
    }
    fields.update(overrides)
    return ApplyPlan(**fields)  # type: ignore[arg-type]


def test_a_display_asked_for_its_own_gamut_makes_no_coverage_claim() -> None:
    """Native has no second triangle, so 100% would be 100% of nothing."""
    assert reach_of_gamut_mode(panel_primaries(WIDE), "native") is None
    assert reach_text(None) == NO_GAMUT_CLAIM


def test_a_named_gamut_reports_the_share_this_panel_encloses() -> None:
    """The answer is the containment computed from this panel's own primaries."""
    primaries = panel_primaries(NARROW)

    reach = reach_of_gamut_mode(primaries, "BT.2020")

    assert reach == gamut_containment(primaries, GAMUT_PRIMARIES["BT.2020"])
    assert reach is not None
    assert reach.covers is False
    assert reach.deficits == ("red", "green", "blue")
    assert 0.0 < reach.coverage_percent < 100.0


def test_a_gamut_this_build_cannot_resolve_stops_the_bundle() -> None:
    """A name with no reference primaries is refused rather than described."""
    with pytest.raises(ValueError, match="no reference primaries") as raised:
        reach_of_gamut_mode(panel_primaries(WIDE), "Rec.2100")

    for known in ("native", "sRGB", "BT.2020"):
        assert known in str(raised.value)


def test_every_gamut_an_operator_can_choose_carries_reference_primaries() -> None:
    """The refusal above cannot fire on a target this build lets anyone compose.

    Each selectable gamut is taken the whole way a real request travels, from
    the slug on the command line through the composed id to the mode string the
    engine is handed, because that is the path a mismatch between the catalogue
    and the reference table would appear on.
    """
    for slug, label in selectable_gamuts():
        mode = resolve_target(compose_target_id(slug, "d65", "g2.2")).gamut_mode

        assert mode == GAMUT_MODES[label]
        assert mode == "native" or mode in GAMUT_PRIMARIES
        reach_of_gamut_mode(panel_primaries(WIDE), mode)


def test_a_panel_record_is_read_as_primaries_and_not_only_a_tuple() -> None:
    """The display side of every comparison here is a panel record.

    Both primaries types in this package name the same three corners, and the
    coverage helpers used to read only the tuple form. A panel record raised
    TypeError, which meant the one question this module exists to answer was
    the one it could not be asked.
    """
    record = panel_primaries(WIDE)
    reference = GAMUT_PRIMARIES["sRGB"]

    assert corners(record) != corners(reference)
    assert chromaticity_coverage(record, reference) == pytest.approx(100.0)
    assert gamut_containment(record, reference).covers is True


def test_a_preset_naming_no_primaries_refuses_rather_than_answering_srgb() -> None:
    """Native and Custom have no triangle, and sRGB is not a stand-in for one."""
    for preset in (GamutPreset.NATIVE, GamutPreset.CUSTOM):
        with pytest.raises(ValueError, match="names no primaries of its own"):
            GamutTarget(preset=preset).get_primaries()


def test_a_shortfall_is_named_for_the_corner_it_belongs_to() -> None:
    """The corner names are read by name, not off a list that may be reversed.

    The triangle helper reverses a clockwise input so the clipper and the inside
    test both read a counter-clockwise boundary. Naming the deficits by walking
    that reversed list reported the blue shortfall as a red one, and the name
    travels into a hashed manifest. The reference below is wound clockwise by
    construction: it names its red where sRGB puts its blue.
    """
    reference = ColorPrimaries(
        red=(0.150, 0.060),
        green=(0.300, 0.600),
        blue=(0.680, 0.320),
        white=(0.3127, 0.3290),
    )

    reach = gamut_containment(GAMUT_PRIMARIES["sRGB"], reference)

    assert reach.deficits == ("blue",)
    assert reach.covers is False


@pytest.mark.parametrize("panel", [NARROW, WIDE])
@pytest.mark.parametrize("gamut", ["sRGB", "DCI-P3", "Adobe RGB", "BT.2020", "ProPhoto RGB"])
def test_the_coverage_figure_survives_being_measured_a_second_way(panel: str, gamut: str) -> None:
    """A percentage checked only against the code that computed it proves nothing."""
    primaries = panel_primaries(panel)
    reference = GAMUT_PRIMARIES[gamut]

    reported = chromaticity_coverage(primaries, reference)

    assert reported == pytest.approx(coverage_by_counting(primaries, reference), abs=COVERAGE_TOLERANCE)


def test_one_gamut_label_stands_for_two_different_reaches() -> None:
    """Why the label alone is not a fact about the artifact.

    Both panels take a DCI-P3 bundle and both bundles are correct. Read the
    gamut line on its own and they are the same calibration. They are not: one
    display reaches nearly all of that gamut and the other misses a quarter of
    it, and every corner of it.
    """
    narrow = reach_of_gamut_mode(panel_primaries(NARROW), "DCI-P3")
    wide = reach_of_gamut_mode(panel_primaries(WIDE), "DCI-P3")

    assert narrow is not None and wide is not None
    assert narrow.coverage_percent < wide.coverage_percent - 20.0
    assert narrow.deficits == ("red", "green")
    assert wide.deficits == ("red",)
    assert reach_text(narrow) != reach_text(wide)


def test_the_manifest_records_the_reach_beside_the_gamut_it_qualifies(tmp_path: Path) -> None:
    """The figure is recomputed from the panel record the manifest names.

    Reading it back out of the same document would only prove the file round
    trips. The manifest names the panel it was built from, so the check is that
    the reach it carries is the reach that panel actually has.
    """
    manifest = bundle_at(tmp_path, "p3", target="dci_p3")
    expected = reach_of_gamut_mode(panel_primaries(manifest["panel_key"]), manifest["target"]["gamut_mode"])
    recorded = manifest["target"]["gamut_reach"]

    assert expected is not None
    assert manifest["target"]["gamut_mode"] == "DCI-P3"
    assert recorded["covers"] == expected.covers
    assert recorded["unreachable_corners"] == list(expected.deficits)
    assert recorded["coverage_percent"] == pytest.approx(expected.coverage_percent, abs=0.05)
    assert recorded["worst_deficit_uv"] == pytest.approx(expected.worst_deficit_uv, abs=0.00005)


def test_a_native_bundle_records_no_coverage_claim(tmp_path: Path) -> None:
    """Null rather than 100, because the question was never asked of it."""
    manifest = bundle_at(tmp_path, "native", target=None, gamut="native")

    assert manifest["target"]["gamut_mode"] == "native"
    assert manifest["target"]["gamut_reach"] is None


def test_a_composed_target_reaches_generation(tmp_path: Path) -> None:
    """A target built from the axis controls has to reach the arithmetic.

    Session state read the preset table alone to decide whether it held a valid
    target, so each axis selection reported success and then generation reported
    that no valid target had been chosen. Every gamut, white point and tone
    response outside the four presets published nothing.
    """
    manifest = bundle_at(tmp_path, "composed", target=None, gamut="bt2020", white_point="d50", tone_response="g2.4")

    assert manifest["preset_id"] == compose_target_id("bt2020", "d50", "g2.4")
    assert manifest["target"]["gamut_mode"] == "BT.2020"
    assert manifest["target"]["white_point"] == "D50"
    assert manifest["target"]["gamut_reach"]["covers"] is False


def test_the_window_prints_a_reach_row_under_the_gamut_it_qualifies() -> None:
    """The row is directly beneath the gamut, and it is always there.

    A row that appeared only where a display fell short would leave a covered
    target and an unreachable one to be told apart by counting lines.
    """
    names = [name for name, _ in plan_rows(bare_plan())]

    assert names[names.index("gamut") + 1] == "gamut reach"
    assert dict(plan_rows(bare_plan()))["gamut reach"] == NO_GAMUT_CLAIM


def test_the_window_states_the_shortfall_it_was_handed() -> None:
    """The row carries the containment's own sentence, not one the page wrote."""
    reach = reach_of_gamut_mode(panel_primaries(NARROW), "BT.2020")

    value = dict(plan_rows(bare_plan(), reach))["gamut reach"]

    assert reach is not None
    assert value == reach.describe()
    assert "52" in value
    assert "red, green, blue" in value


def test_the_terminal_and_the_window_print_one_reach(tmp_path: Path) -> None:
    """Both surfaces read the preview, so neither can describe the other's plan."""
    text, preview = printed_plan(tmp_path, "p3", target="dci_p3")

    assert preview.gamut_reach is not None
    assert field(text, "gamut reach") == dict(plan_rows(preview.plan, preview.gamut_reach))["gamut reach"]
    assert field(text, "gamut reach") == preview.gamut_reach.describe()
    assert field(text, "gamut") == "DCI-P3"


def test_the_terminal_says_no_coverage_claim_for_a_native_target(tmp_path: Path) -> None:
    """The one row an operator reads on every plan, including the one with no figure."""
    text, preview = printed_plan(tmp_path, "native", target=None, gamut="native")

    assert preview.gamut_reach is None
    assert field(text, "gamut reach") == NO_GAMUT_CLAIM
