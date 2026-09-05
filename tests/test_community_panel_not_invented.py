"""A community panel carries what its submitter measured, and nothing else.

A community file is written under a submitter name, a measurement date and a
measurement device. Every number in it reads as an instrument observation to
the next person who imports it, which is the whole point of the format.

The importer filled the gaps. A file with no capabilities block became a panel
reporting 100 cd/m2 SDR peak, 400 cd/m2 HDR peak, a 0.0001 cd/m2 black and
10-bit colour, and a file missing a gamma channel took 2.2 for it. The
submission CLI made the same substitution one step earlier: pressing enter at
the brightness prompts wrote 100 and 400 into the file, and it never asked for
a black level at all, so every hand-written submission carried the importer's
0.0001.

That black level is not inert. It is below the 0.01 cd/m2 threshold the
DDC/CI path reads as an emissive panel, so an IPS monitor submitted by hand
was sent OLED contrast bytes. The SDR peak divides the target luminance to
produce the brightness byte written beside it.

An imported panel is not a curiosity either. ``cmd_import_panel`` writes it
into the panel database profiles directory, and ``PanelDatabase`` globs that
directory at construction, so it comes back out of ``find_panel`` looking like
a measured builtin.

Both ends now leave the field out. Zero is the panel layer's "not known", and
a missing gamma channel raises the way a missing primary already did.

PRODUCT.md: the interface must never convert modeled, simulated, replayed, or
placeholder values into apparent instrument observations.
"""

from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from calibrate_pro.community.database import export_panel, import_panel, submit_panel_cli
from calibrate_pro.panels.database import get_database
from calibrate_pro.sensorless.auto_calibration import AutoCalibrationEngine, CalibrationTarget

MEASURED_PRIMARIES = {
    "red": {"x": 0.6800, "y": 0.3200},
    "green": {"x": 0.2650, "y": 0.6900},
    "blue": {"x": 0.1500, "y": 0.0600},
    "white": {"x": 0.3127, "y": 0.3290},
}

MEASURED_GAMMA = {"red": 2.19, "green": 2.21, "blue": 2.23}


def _write(tmp_path: Path, **overrides) -> Path:
    """Write a community file, defaulting to primaries and gamma only."""
    data = {
        "calibrate_pro_community": True,
        "version": 1,
        "panel_key": "COMMUNITY1",
        "manufacturer": "Contributor",
        "model": "COMMUNITY1",
        "panel_type": "IPS",
        "display_name": "Community IPS",
        "primaries": MEASURED_PRIMARIES,
        "gamma": dict(MEASURED_GAMMA),
        "measured_by": "a contributor",
        "measurement_date": "2026-09-05",
        "measurement_device": "i1Display Pro",
    }
    data.update(overrides)
    path = tmp_path / "panel.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# -------------------------------------------------------------------------
# The importer leaves absent fields unknown
# -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    ["max_luminance_sdr", "max_luminance_hdr", "min_luminance"],
)
def test_absent_photometry_imports_as_unknown(tmp_path, field):
    """No capabilities block means no photometry was submitted."""
    caps = import_panel(_write(tmp_path)).capabilities

    assert getattr(caps, field) == 0.0


def test_an_absent_bit_depth_is_not_reported_as_ten(tmp_path):
    """Ten bits was the importer's guess, not the submitter's measurement."""
    assert import_panel(_write(tmp_path)).capabilities.bit_depth == 0


def test_a_partly_filled_capabilities_block_keeps_what_was_measured(tmp_path):
    """The fix drops substitution, not the values a submitter did supply."""
    path = _write(tmp_path, capabilities={"max_sdr": 412.5, "hdr": True, "wide_gamut": True})

    caps = import_panel(path).capabilities

    assert caps.max_luminance_sdr == pytest.approx(412.5)
    assert caps.hdr_capable is True
    assert caps.wide_gamut is True
    assert caps.max_luminance_hdr == 0.0
    assert caps.min_luminance == 0.0


@pytest.mark.parametrize("channel", ["red", "green", "blue"])
def test_a_missing_gamma_channel_raises_and_names_the_channel(tmp_path, channel):
    """The three curves drive the correction LUT. A default is a tone response nobody read."""
    partial = {k: v for k, v in MEASURED_GAMMA.items() if k != channel}

    with pytest.raises(ValueError, match=channel):
        import_panel(_write(tmp_path, gamma=partial))


def test_a_complete_file_round_trips_unchanged(tmp_path):
    """A panel that was measured end to end survives export and import intact."""
    measured = get_database().get_panel("AW3423DW")
    assert measured is not None

    reimported = import_panel(export_panel(measured, tmp_path / "round_trip.json"))

    assert reimported.capabilities == measured.capabilities
    assert reimported.gamma_red.gamma == measured.gamma_red.gamma
    assert reimported.gamma_green.gamma == measured.gamma_green.gamma
    assert reimported.gamma_blue.gamma == measured.gamma_blue.gamma


# -------------------------------------------------------------------------
# What the unknown means downstream
# -------------------------------------------------------------------------


def test_an_imported_ips_panel_is_not_sent_oled_contrast(tmp_path):
    """0.0001 read as a perfect black; zero reads as no black level submitted."""
    panel = import_panel(_write(tmp_path))

    corrections = AutoCalibrationEngine()._calculate_corrections(panel, CalibrationTarget())

    assert corrections["panel_min_luminance"] == 0.0
    assert corrections["ddc_contrast"] == 75


def test_no_brightness_byte_is_computed_from_an_unsubmitted_peak(tmp_path):
    """The brightness byte is a fraction of the panel peak. Without one, none."""
    panel = import_panel(_write(tmp_path))

    corrections = AutoCalibrationEngine()._calculate_corrections(panel, CalibrationTarget())

    assert corrections["ddc_brightness"] is None


def test_a_fully_measured_submission_still_drives_ddc(tmp_path):
    """The guard must not disable the path for a submitter who measured the panel."""
    path = _write(
        tmp_path,
        capabilities={"max_sdr": 250.0, "min_luminance": 0.0005, "hdr": True, "bit_depth": 10},
    )

    corrections = AutoCalibrationEngine()._calculate_corrections(import_panel(path), CalibrationTarget())

    assert isinstance(corrections["ddc_brightness"], int)
    assert corrections["ddc_contrast"] == 85


# -------------------------------------------------------------------------
# The submission CLI
# -------------------------------------------------------------------------

# Prompt order in submit_panel_cli: key, manufacturer, model, panel type,
# four chromaticity pairs, three gammas, SDR peak, HDR peak, black level,
# three yes/no flags, bit depth, name, device, notes.
IDENTITY = ["COMMUNITY1", "Contributor", "COMMUNITY1", "IPS"]
CHROMATICITY = ["0.68 0.32", "0.265 0.69", "0.15 0.06", "0.3127 0.3290"]
GAMMA = ["2.19", "2.21", "2.23"]
FLAGS = ["n", "y", "n"]
PROVENANCE = ["a contributor", "i1Display Pro", ""]


def _run_cli(monkeypatch, tmp_path, photometry: list[str], bit_depth: str):
    """Drive the interactive submission with a scripted set of answers."""
    answers = iter(IDENTITY + CHROMATICITY + GAMMA + photometry + FLAGS + [bit_depth] + PROVENANCE)
    monkeypatch.setattr(builtins, "input", lambda *_: next(answers))
    monkeypatch.chdir(tmp_path)

    submit_panel_cli()

    return json.loads((tmp_path / "COMMUNITY1_community.json").read_text(encoding="utf-8"))


def test_a_blank_answer_writes_no_capability_key(monkeypatch, tmp_path):
    """Pressing enter used to write 100, 400 and 10 bits into the record."""
    caps = _run_cli(monkeypatch, tmp_path, ["", "", ""], "")["capabilities"]

    assert "max_sdr" not in caps
    assert "max_hdr" not in caps
    assert "min_luminance" not in caps
    assert "bit_depth" not in caps


def test_measured_answers_are_written(monkeypatch, tmp_path):
    """The prompts still record what the submitter read off the instrument."""
    caps = _run_cli(monkeypatch, tmp_path, ["412.5", "0", "0.18"], "10")["capabilities"]

    assert caps["max_sdr"] == pytest.approx(412.5)
    assert caps["max_hdr"] == pytest.approx(0.0)
    assert caps["min_luminance"] == pytest.approx(0.18)
    assert caps["bit_depth"] == 10


def test_the_cli_asks_for_a_black_level(monkeypatch, tmp_path):
    """It never did, so the importer's 0.0001 stood in on every submission."""
    prompts: list[str] = []
    answers = iter(IDENTITY + CHROMATICITY + GAMMA + ["", "", "0.18"] + FLAGS + [""] + PROVENANCE)

    def record(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(answers)

    monkeypatch.setattr(builtins, "input", record)
    monkeypatch.chdir(tmp_path)
    submit_panel_cli()

    assert any("black level" in prompt.lower() for prompt in prompts)


def test_a_blank_submission_imports_without_inventing(monkeypatch, tmp_path):
    """The two ends agree: what the CLI leaves out, the importer leaves unknown."""
    _run_cli(monkeypatch, tmp_path, ["", "", ""], "")

    caps = import_panel(tmp_path / "COMMUNITY1_community.json").capabilities

    assert caps.max_luminance_sdr == 0.0
    assert caps.max_luminance_hdr == 0.0
    assert caps.min_luminance == 0.0
    assert caps.bit_depth == 0
