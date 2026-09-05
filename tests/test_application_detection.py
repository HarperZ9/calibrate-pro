"""Contract tests for read-only display detection.

These pin the properties the detector exists to guarantee: it never claims a
capability nothing proved, it never substitutes a generic panel for a display
it failed to recognize, it never puts a serial number in a label, and one
malformed platform report never blanks the rest of the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from calibrate_pro.application import detection as detection_module
from calibrate_pro.application.contracts import CharacterizationKind, DashboardModel, DisplayObservation
from calibrate_pro.application.detection import (
    UNKNOWN_PROVENANCE,
    CapabilityFinding,
    CapabilityReport,
    CapabilityUnavailable,
    DeniedCapabilityProbe,
    DetectionError,
    DisplayDetector,
    ReadOnlyCapabilityProbe,
    characterization_from_panel,
    dwm_lut_path_usable,
    unknown_characterization,
)
from calibrate_pro.panels.database import PanelDatabase
from calibrate_pro.panels.detection import DisplayInfo

DISPLAY_ONE = "\\\\.\\DISPLAY1"
DISPLAY_TWO = "\\\\.\\DISPLAY2"
KNOWN_PANEL_KEY = "AW3423DW"
PRIVATE_SERIAL = "SN-PRIVATE-0001"
FIXED_MOMENT = datetime(2026, 9, 4, 17, 30, 5, tzinfo=timezone.utc)

CAPABILITY_NAMES = (
    "sensor_available",
    "ddc_available",
    "dwm_lut_available",
    "dwm_state_capture_available",
    "profile_write_available",
    "vcgt_available",
)


def make_display(
    *,
    device_name: str = DISPLAY_ONE,
    monitor_name: str = "Generic PnP Monitor",
    model: str = KNOWN_PANEL_KEY,
    serial: str = PRIVATE_SERIAL,
    is_primary: bool = True,
    width: int = 3440,
    height: int = 1440,
    refresh_rate: int = 175,
    panel_database_key: str = "",
) -> DisplayInfo:
    display = DisplayInfo(
        device_name=device_name,
        device_string="Test Adapter",
        monitor_name=monitor_name,
        device_id="MONITOR\\TEST0001\\{4d36e96e}\\0000",
        is_primary=is_primary,
        is_active=True,
        width=width,
        height=height,
        refresh_rate=refresh_rate,
        bit_depth=10,
        position_x=0,
        position_y=0,
        manufacturer="Test",
        model=model,
        serial=serial,
    )
    display.panel_database_key = panel_database_key
    return display


def fixed_clock() -> datetime:
    return FIXED_MOMENT


def build_detector(displays, **kwargs) -> DisplayDetector:
    kwargs.setdefault("clock", fixed_clock)
    kwargs.setdefault("database", PanelDatabase())
    return DisplayDetector(enumerator=lambda: list(displays), **kwargs)


class TestCapabilityReporting:
    def test_default_probe_reports_every_capability_unavailable(self):
        report = DeniedCapabilityProbe().probe(make_display())
        for name in CAPABILITY_NAMES:
            assert getattr(report.state, name) is False

    def test_every_denial_carries_a_reason(self):
        report = DeniedCapabilityProbe().probe(make_display())
        assert len(report.findings) == len(CAPABILITY_NAMES)
        for finding in report.findings:
            assert finding.reason.strip()
            assert finding.evidence_line().startswith(f"capability:{finding.name}=unavailable")

    def test_unwired_check_is_denied_not_assumed(self):
        report = ReadOnlyCapabilityProbe().probe(make_display())
        assert report.state.sensor_available is False
        reasons = {finding.name: finding.reason for finding in report.findings}
        assert "not probed" in reasons["sensor_available"]

    def test_raising_check_denies_the_capability_and_records_the_failure(self):
        def explode(_display):
            raise OSError("device handle refused")

        report = ReadOnlyCapabilityProbe(ddc=explode).probe(make_display())
        assert report.state.ddc_available is False
        reason = next(f.reason for f in report.findings if f.name == "ddc_available")
        assert "check raised OSError" in reason
        assert "device handle refused" in reason

    def test_non_boolean_check_result_denies_the_capability(self):
        report = ReadOnlyCapabilityProbe(vcgt=lambda _display: 1).probe(make_display())
        assert report.state.vcgt_available is False

    def test_passing_check_grants_the_capability(self):
        report = ReadOnlyCapabilityProbe(profile_write=lambda _display: True).probe(make_display())
        assert report.state.profile_write_available is True

    def test_incomplete_finding_set_is_rejected(self):
        with pytest.raises(ValueError, match="missing capability findings"):
            CapabilityReport.from_findings(
                [CapabilityFinding(name="sensor_available", available=False, reason="untested")]
            )

    def test_duplicate_finding_is_rejected(self):
        findings = [CapabilityFinding(name=name, available=False, reason="untested") for name in CAPABILITY_NAMES]
        findings.append(CapabilityFinding(name="sensor_available", available=True, reason="untested"))
        with pytest.raises(ValueError, match="reported once"):
            CapabilityReport.from_findings(findings)


class TestCharacterization:
    def test_known_model_matches_the_database(self):
        result = build_detector([make_display()]).detect()
        observation = result.dashboard.displays[0]
        assert observation.characterization.kind is CharacterizationKind.MATCHED
        assert observation.characterization.provenance.startswith("panel-database:")
        assert observation.characterization.red_xy is not None

    def test_unknown_model_is_unknown_not_generic(self):
        display = make_display(model="NoSuchPanel9000", monitor_name="NoSuchPanel9000")
        observation = build_detector([display]).detect().dashboard.displays[0]
        assert observation.characterization.kind is CharacterizationKind.UNKNOWN
        assert observation.characterization.provenance == UNKNOWN_PROVENANCE
        assert observation.characterization.red_xy is None
        assert observation.characterization.nominal_gamma is None

    def test_unknown_characterization_carries_no_numbers(self):
        characterization = unknown_characterization()
        assert characterization.white_xy is None
        assert characterization.nominal_gamma is None

    def test_panel_database_key_is_preferred_over_model_text(self):
        display = make_display(model="NoSuchPanel9000", panel_database_key=KNOWN_PANEL_KEY)
        observation = build_detector([display]).detect().dashboard.displays[0]
        assert observation.characterization.kind is CharacterizationKind.MATCHED
        assert observation.characterization.provenance == f"panel-database:{KNOWN_PANEL_KEY}"

    def test_conversion_rejects_a_blank_provenance(self):
        database = PanelDatabase()
        panel = database.get_panel(KNOWN_PANEL_KEY)
        assert panel is not None
        with pytest.raises(DetectionError):
            characterization_from_panel(panel, "   ")

    def test_every_database_panel_converts(self):
        database = PanelDatabase()
        for key in database.list_panels():
            panel = database.get_panel(key)
            assert panel is not None
            characterization = characterization_from_panel(panel, f"panel-database:{key}")
            assert characterization.kind is CharacterizationKind.MATCHED


class TestSafeLabel:
    def test_label_never_contains_the_serial(self):
        observation = build_detector([make_display()]).detect().dashboard.displays[0]
        assert PRIVATE_SERIAL not in observation.safe_label

    def test_label_never_contains_the_device_path(self):
        observation = build_detector([make_display()]).detect().dashboard.displays[0]
        assert "MONITOR" not in observation.safe_label
        assert "DISPLAY1" not in observation.safe_label

    def test_label_names_the_product_when_one_is_reported(self):
        observation = build_detector([make_display()]).detect().dashboard.displays[0]
        assert observation.safe_label == f"Display 1 - {KNOWN_PANEL_KEY}"

    def test_generic_product_text_is_dropped_from_the_label(self):
        display = make_display(model="", monitor_name="Generic PnP Monitor")
        observation = build_detector([display]).detect().dashboard.displays[0]
        assert observation.safe_label == "Display 1"


class TestDetectionPass:
    def test_dashboard_is_one_immutable_unit(self):
        result = build_detector([make_display()]).detect()
        assert type(result.dashboard) is DashboardModel
        assert type(result.dashboard.displays[0]) is DisplayObservation
        assert result.dashboard.refreshed_utc == "2026-09-04T17:30:05Z"

    def test_refresh_rate_is_reported_in_millihertz(self):
        observation = build_detector([make_display(refresh_rate=175)]).detect().dashboard.displays[0]
        assert observation.refresh_millihz == 175000

    def test_primary_display_is_selected(self):
        displays = [
            make_display(device_name=DISPLAY_TWO, is_primary=False),
            make_display(device_name=DISPLAY_ONE, is_primary=True),
        ]
        result = build_detector(displays).detect()
        assert result.dashboard.selected_display_id == DISPLAY_ONE

    def test_first_display_is_selected_when_none_is_primary(self):
        displays = [
            make_display(device_name=DISPLAY_TWO, is_primary=False),
            make_display(device_name=DISPLAY_ONE, is_primary=False),
        ]
        result = build_detector(displays).detect()
        assert result.dashboard.selected_display_id == DISPLAY_TWO

    def test_empty_enumeration_produces_an_empty_dashboard(self):
        result = build_detector([]).detect()
        assert result.dashboard.displays == ()
        assert result.dashboard.selected_display_id is None
        assert result.rejected == ()

    def test_one_bad_report_does_not_blank_the_others(self):
        displays = [
            make_display(device_name=DISPLAY_ONE, refresh_rate=0),
            make_display(device_name=DISPLAY_TWO, is_primary=False),
        ]
        result = build_detector(displays).detect()
        assert [d.platform_display_id for d in result.dashboard.displays] == [DISPLAY_TWO]
        assert len(result.rejected) == 1
        assert result.rejected[0].platform_display_id == DISPLAY_ONE
        assert "refresh rate" in result.rejected[0].reason

    def test_duplicate_device_name_is_rejected_once(self):
        displays = [make_display(), make_display()]
        result = build_detector(displays).detect()
        assert len(result.dashboard.displays) == 1
        assert len(result.rejected) == 1
        assert "twice" in result.rejected[0].reason

    def test_non_positive_resolution_is_rejected(self):
        result = build_detector([make_display(width=0)]).detect()
        assert result.dashboard.displays == ()
        assert "resolution" in result.rejected[0].reason

    def test_evidence_names_the_enumerator_and_the_mode(self):
        observation = build_detector([make_display()]).detect().dashboard.displays[0]
        assert "enumerator:panels.detection.enumerate_displays" in observation.evidence
        assert "mode:3440x1440@175Hz" in observation.evidence

    def test_evidence_carries_one_line_per_capability(self):
        observation = build_detector([make_display()]).detect().dashboard.displays[0]
        capability_lines = [line for line in observation.evidence if line.startswith("capability:")]
        assert len(capability_lines) == len(CAPABILITY_NAMES)


class TestHdrReporting:
    def test_hdr_is_none_when_not_queried(self):
        observation = build_detector([make_display()]).detect().dashboard.displays[0]
        assert observation.hdr_enabled is None
        assert "hdr:not-queried" in observation.evidence

    def test_hdr_state_is_carried_per_display(self):
        detector = build_detector([make_display()], hdr_reader=lambda: {DISPLAY_ONE: True})
        observation = detector.detect().dashboard.displays[0]
        assert observation.hdr_enabled is True
        assert "hdr:queried" in observation.evidence

    def test_failed_hdr_query_reports_unknown_not_false(self):
        def explode():
            raise OSError("HDR query refused")

        observation = build_detector([make_display()], hdr_reader=explode).detect().dashboard.displays[0]
        assert observation.hdr_enabled is None
        assert any(line.startswith("hdr:query-failed") for line in observation.evidence)

    def test_hdr_state_for_another_display_is_not_borrowed(self):
        detector = build_detector([make_display()], hdr_reader=lambda: {DISPLAY_TWO: True})
        observation = detector.detect().dashboard.displays[0]
        assert observation.hdr_enabled is None


class TestClockContract:
    def test_naive_clock_is_rejected(self):
        detector = build_detector([make_display()], clock=lambda: datetime(2026, 9, 4, 17, 30, 5))
        with pytest.raises(DetectionError, match="aware datetime"):
            detector.detect()

    def test_non_utc_clock_is_normalized_to_utc(self):
        offset = timezone(timedelta(hours=-4))
        detector = build_detector([make_display()], clock=lambda: FIXED_MOMENT.astimezone(offset))
        assert detector.detect().dashboard.refreshed_utc == "2026-09-04T17:30:05Z"


class TestNoWriterIsOpened:
    def test_detection_never_touches_an_actuation_surface(self, monkeypatch):
        import calibrate_pro.panels.detection as platform_detection

        def forbidden(*args, **kwargs):
            raise AssertionError("detection opened a writer")

        for name in (
            "set_display_profile",
            "install_profile",
            "set_gamma_ramp",
            "reset_gamma_ramp",
        ):
            monkeypatch.setattr(platform_detection, name, forbidden)
        result = build_detector([make_display()]).detect()
        assert len(result.dashboard.displays) == 1


class TestDwmLutUsability:
    """The DWM control is offered only when the hook could actually run.

    A measured run on 2026-07-30 found the bundled 3.8 hook installed on
    Windows build 26220, where it refuses to inject. Reporting that install as
    an available capability would put a permanently failing control in front of
    the operator.
    """

    def _patch_lookup(self, monkeypatch, *, found, version, build):
        import calibrate_pro.lut_system.dwm_lut as dwm_lut

        monkeypatch.setattr(dwm_lut, "find_dwm_lut_directory", lambda: found)
        monkeypatch.setattr(dwm_lut, "bundled_dwm_lut_version_at", lambda path: version)
        if build is not None:
            monkeypatch.setattr(detection_module.sys, "platform", "win32")
            monkeypatch.setattr(
                detection_module.sys,
                "getwindowsversion",
                lambda: SimpleNamespace(build=build),
                raising=False,
            )

    def test_absent_tooling_is_unavailable_with_its_own_reason(self, monkeypatch):
        self._patch_lookup(monkeypatch, found=None, version=None, build=None)
        probe = ReadOnlyCapabilityProbe(dwm_lut=dwm_lut_path_usable)
        finding = self._dwm_finding(probe)
        assert finding.available is False
        assert finding.reason == "no dwm_lut installation was found on this machine"

    def test_bundled_hook_on_an_unsupported_build_is_unavailable(self, monkeypatch):
        self._patch_lookup(monkeypatch, found=Path("dwm_lut"), version="3.8", build=26220)
        probe = ReadOnlyCapabilityProbe(dwm_lut=dwm_lut_path_usable)
        finding = self._dwm_finding(probe)
        assert finding.available is False
        assert "26220" in finding.reason
        assert "Refusing DWM injection" in finding.reason

    def test_bundled_hook_on_a_supported_build_is_available(self, monkeypatch):
        self._patch_lookup(monkeypatch, found=Path("dwm_lut"), version="3.8", build=22000)
        probe = ReadOnlyCapabilityProbe(dwm_lut=dwm_lut_path_usable)
        finding = self._dwm_finding(probe)
        assert finding.available is True

    def test_operator_installed_hook_is_not_gated_on_the_bundled_version(self, monkeypatch):
        self._patch_lookup(monkeypatch, found=Path("elsewhere"), version=None, build=26220)
        probe = ReadOnlyCapabilityProbe(dwm_lut=dwm_lut_path_usable)
        finding = self._dwm_finding(probe)
        assert finding.available is True

    def test_a_stated_reason_reaches_the_report_verbatim(self):
        def refuse(_display):
            raise CapabilityUnavailable("the monitor is asleep")

        probe = ReadOnlyCapabilityProbe(ddc=refuse)
        report = probe.probe(make_display())
        finding = next(item for item in report.findings if item.name == "ddc_available")
        assert finding.available is False
        assert finding.reason == "the monitor is asleep"

    def test_a_blank_stated_reason_falls_back_to_a_named_denial(self):
        def refuse(_display):
            raise CapabilityUnavailable("   ")

        probe = ReadOnlyCapabilityProbe(ddc=refuse)
        report = probe.probe(make_display())
        finding = next(item for item in report.findings if item.name == "ddc_available")
        assert finding.reason == "check reported the capability unavailable"

    def test_a_defect_in_a_check_is_still_reported_as_a_defect(self):
        def broken(_display):
            raise RuntimeError("bad wiring")

        probe = ReadOnlyCapabilityProbe(ddc=broken)
        report = probe.probe(make_display())
        finding = next(item for item in report.findings if item.name == "ddc_available")
        assert finding.available is False
        assert finding.reason == "check raised RuntimeError: bad wiring"

    def test_the_usability_check_creates_nothing(self, monkeypatch, tmp_path):
        import calibrate_pro.lut_system.dwm_lut as dwm_lut

        def forbidden(*args, **kwargs):
            raise AssertionError("the usability check created a directory")

        monkeypatch.setattr(Path, "mkdir", forbidden)
        monkeypatch.setattr(dwm_lut, "find_dwm_lut_directory", lambda: tmp_path)
        monkeypatch.setattr(dwm_lut, "bundled_dwm_lut_version_at", lambda path: None)
        assert dwm_lut_path_usable(make_display()) is True

    @staticmethod
    def _dwm_finding(probe):
        report = probe.probe(make_display())
        return next(item for item in report.findings if item.name == "dwm_lut_available")
