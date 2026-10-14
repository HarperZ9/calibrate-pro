"""The digest printed above a preview plan covers the characterization under it.

Two previews over one injected display and one target differ only in which
record the bundle was built from. The panel line and the characterization kind
are printed under the digest, so the digest has to move when they do. Nothing
here opens a display or reads an instrument.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from calibrate_pro.application.planning import build_apply_plan
from calibrate_pro.workflow import ApplyPlan, CalibrationMethod
from tests.session_support import PRESET
from tests.test_edid_surfaces import build_session, declared_edid, declaring_detector, run_command_line


def _plan_digest(text: str) -> str:
    first = text.splitlines()[0]
    assert first.startswith("Plan "), first
    return first.removeprefix("Plan ")


def _preview_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str) -> str:
    service, _state = build_session(tmp_path / flag.strip("-"), detector=declaring_detector(edid=declared_edid()))
    code, text = run_command_line(monkeypatch, service, "verify", "--target", PRESET, flag)
    assert code == 0
    return _plan_digest(text)


def test_edid_and_generic_previews_over_one_display_seal_different_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edid = _preview_digest(tmp_path, monkeypatch, "--edid")
    generic = _preview_digest(tmp_path, monkeypatch, "--generic")

    assert len(edid) == 64
    assert edid != generic


def test_the_same_preview_run_twice_seals_the_same_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: the digest moved above because of the record, not because it is unstable."""
    first = _preview_digest(tmp_path / "a", monkeypatch, "--edid")
    second = _preview_digest(tmp_path / "b", monkeypatch, "--edid")

    assert first == second


def _plan(characterization: object) -> ApplyPlan:
    return build_apply_plan(
        display_id="D1",
        method=CalibrationMethod.SENSORLESS,
        preset_id="calibration.preset.srgb_web",
        output_files=("a.icc",),
        characterization=characterization,  # type: ignore[arg-type]
    )


def test_the_plan_carries_the_characterization_it_was_built_from() -> None:
    assert _plan("Panel X (declared) (edid_declared)").characterization == "Panel X (declared) (edid_declared)"


@pytest.mark.parametrize("bad", [7, b"x", ["x"], "", "   "])
def test_a_plan_refuses_a_characterization_that_is_not_a_non_empty_string(bad: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        _plan(bad)
