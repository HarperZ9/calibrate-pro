"""An EDID that states no gamma must not report one.

EDID byte 23 holds gamma as (gamma * 100) - 100, and the value 0xFF is the
EDID saying its gamma sits in an extension block. ``parse_edid`` honours that
by leaving ``gamma`` at 0.0, and ``update_from_edid`` in the same module only
copies the field when it is above zero.

``_match_panel`` did not honour it. It read ``edid_info.get("gamma", 2.2) or
2.2``, so a display that stated no gamma got 2.2, and the log line beneath
printed that 2.2 in a message whose other numbers are chromaticities the EDID
really carried. ``create_from_edid`` then wrote "Gamma assumed 2.2" into the
panel notes whatever the caller passed, so a gamma read off byte 23 and a
gamma nobody read looked the same in the profile.

None of these tests opens a display, reads a registry, talks to a colorimeter
or writes a profile. Display enumeration and the EDID registry read are
replaced with fakes.
"""

import logging

import pytest

from calibrate_pro.panels.database import create_from_edid
from calibrate_pro.panels.detection import parse_edid
from calibrate_pro.sensorless.auto_calibration import AutoCalibrationEngine

P3_EDID = {
    "red": (0.6800, 0.3200),
    "green": (0.2650, 0.6900),
    "blue": (0.1500, 0.0600),
    "white": (0.3127, 0.3290),
}

# A base EDID block. Byte 23 is the gamma byte and every test sets it.
BASE_EDID = bytes([0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00]) + bytes(120)


def _edid_with_gamma_byte(value: int) -> bytes:
    raw = bytearray(BASE_EDID)
    raw[23] = value
    return bytes(raw)


class TestTheParserLeavesAnUnstatedGammaAtZero:
    """The sentinel the rest of the fix depends on."""

    def test_byte_23_of_0xff_leaves_gamma_at_zero(self):
        assert parse_edid(_edid_with_gamma_byte(0xFF))["gamma"] == 0.0

    def test_a_stated_gamma_decodes(self):
        # 120 -> (120 + 100) / 100 = 2.2
        assert parse_edid(_edid_with_gamma_byte(120))["gamma"] == pytest.approx(2.2)

    def test_a_stated_gamma_of_2_4_decodes(self):
        # 140 -> (140 + 100) / 100 = 2.4
        assert parse_edid(_edid_with_gamma_byte(140))["gamma"] == pytest.approx(2.4)


class TestThePanelNoteSaysWhichGammaItHas:
    def test_no_gamma_gives_a_note_that_says_assumed(self):
        notes = create_from_edid(P3_EDID).notes.lower()

        assert "gamma assumed 2.2" in notes
        assert "carried none" in notes

    def test_a_read_gamma_gives_a_note_that_says_read(self):
        notes = create_from_edid(P3_EDID, gamma=2.4).notes.lower()

        assert "read from edid" in notes
        assert "assumed" not in notes

    def test_a_read_2_2_is_not_the_assumed_2_2(self):
        """The discriminating case. Both produce curves of 2.2."""
        assumed = create_from_edid(P3_EDID).notes.lower()
        measured = create_from_edid(P3_EDID, gamma=2.2).notes.lower()

        assert assumed != measured
        assert "assumed" in assumed
        assert "read from edid" in measured

    def test_the_curves_still_carry_a_usable_number_when_none_was_read(self):
        """The model needs a gamma even when the EDID gave none."""
        panel = create_from_edid(P3_EDID)

        assert panel.gamma_red.gamma == pytest.approx(2.2)
        assert panel.gamma_green.gamma == pytest.approx(2.2)
        assert panel.gamma_blue.gamma == pytest.approx(2.2)

    def test_a_read_gamma_reaches_the_curves(self):
        """Control. The fix must not stop a real reading getting through."""
        panel = create_from_edid(P3_EDID, gamma=2.4)

        assert panel.gamma_red.gamma == pytest.approx(2.4)
        assert panel.gamma_blue.gamma == pytest.approx(2.4)


class TestTheProfilingLogNamesTheSource:
    """The operator-facing surface. The log line lists EDID chromaticities."""

    @pytest.fixture
    def engine(self, monkeypatch):
        from calibrate_pro.panels import detection

        # No display enumeration and no registry read. Method 3 must fall
        # through so method 4 is the one under test.
        monkeypatch.setattr(detection, "enumerate_displays", lambda: [])
        monkeypatch.setattr(detection, "get_edid_from_registry", lambda device_id: b"fake-edid")
        monkeypatch.setattr(
            AutoCalibrationEngine,
            "_extract_edid_chromaticity",
            lambda self, data: dict(P3_EDID),
        )
        return AutoCalibrationEngine()

    def _run(self, engine, monkeypatch, caplog, gamma):
        from calibrate_pro.panels import detection

        monkeypatch.setattr(detection, "parse_edid", lambda data: {"gamma": gamma})
        with caplog.at_level(logging.INFO):
            panel = engine._match_panel({"name": "No Such Panel 9000", "device_id": "FAKE"})
        return panel, caplog.text

    def test_an_unstated_gamma_is_named_in_the_line(self, engine, monkeypatch, caplog):
        panel, text = self._run(engine, monkeypatch, caplog, 0.0)

        assert panel is not None
        assert "Gamma=not in EDID, model assumes 2.2" in text
        assert "Gamma=2.20." not in text

    def test_a_stated_gamma_prints_as_a_number(self, engine, monkeypatch, caplog):
        """Control. A gamma the EDID carried is still reported as one."""
        panel, text = self._run(engine, monkeypatch, caplog, 2.4)

        assert panel is not None
        assert "Gamma=2.40" in text
        assert "assumes" not in text

    def test_a_stated_2_2_prints_as_a_number_not_as_an_assumption(self, engine, monkeypatch, caplog):
        """The discriminating case again, on the log line this time."""
        _, text = self._run(engine, monkeypatch, caplog, 2.2)

        assert "Gamma=2.20" in text
        assert "not in EDID" not in text

    def test_the_primaries_beside_it_are_still_the_ones_that_were_read(self, engine, monkeypatch, caplog):
        """Control. The line is only wrong about gamma, so the rest must hold."""
        _, text = self._run(engine, monkeypatch, caplog, 0.0)

        assert "R(0.6800,0.3200)" in text
        assert "White(0.3127,0.3290)" in text

    def test_the_line_claims_no_advantage_nobody_measured(self, engine, monkeypatch, caplog):
        """The line used to end 'significantly better calibration than generic
        sRGB fallback'. Nothing in this repo measures EDID-derived primaries
        against the sRGB fallback, so the line stated a result it did not have.
        """
        _, text = self._run(engine, monkeypatch, caplog, 2.4)

        lowered = text.lower()
        for phrase in ("significantly better", "much better", "far better", "better calibration"):
            assert phrase not in lowered, f"the profiling log claims {phrase!r} with no measurement behind it"

    def test_the_line_states_what_edid_does_not_carry(self, engine, monkeypatch, caplog):
        """What replaced the claim has to be worth the space it took."""
        _, text = self._run(engine, monkeypatch, caplog, 2.4)

        assert "carries no photometry" in text
