"""Read-only display detection that produces immutable observations.

Nothing in this module opens a writer, loads a LUT, changes an ICC
association, or writes a DDC/CI value. It reads what the platform already
reports and turns it into `DisplayObservation` values whose every claim is
traceable to a named source.

Two rules shape the design.

A capability is False until something read-only proves it. `CapabilityState`
gates the workflow, so a capability reported True with no evidence would offer
the operator an action the machine cannot perform. Probes that would need a
device handle or a USB session are not run here; they are injected by a caller
that has decided to pay that cost, and their absence is recorded as an
explicit reason rather than an optimistic default.

A characterization is MATCHED or UNKNOWN. Detection never silently substitutes
the generic sRGB panel for a display it failed to recognize. Choosing the
generic profile is an operator decision, and the contract layer records that
choice as EXPLICIT_GENERIC where the operator can see it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from calibrate_pro.application.contracts import (
    CharacterizationKind,
    DashboardModel,
    DisplayObservation,
    PanelCharacterization,
)
from calibrate_pro.panels.database import GENERIC_PANEL_KEY, PanelDatabase, get_database
from calibrate_pro.panels.database import PanelCharacterization as PanelRecord
from calibrate_pro.panels.detection import DisplayInfo
from calibrate_pro.workflow import CapabilityState

UNKNOWN_PROVENANCE = "detector:no_panel_match"
#: Prefix a matched characterization carries so the panel key that produced it
#: can be read back. Written and parsed in this module and nowhere else.
PANEL_DATABASE_PROVENANCE_PREFIX = "panel-database:"

_CHROMATICITY_DECIMALS = 4
_GAMMA_DECIMALS = 4

_CAPABILITY_NAMES = (
    "sensor_available",
    "ddc_available",
    "dwm_lut_available",
    "dwm_state_capture_available",
    "profile_write_available",
    "vcgt_available",
)

_GENERIC_PRODUCT_LABELS = frozenset({"generic pnp monitor", "default monitor", "unknown"})


class DetectionError(Exception):
    """A detection input was malformed in a way no observation can describe."""


@dataclass(frozen=True)
class CapabilityFinding:
    """One capability answer and the read-only check that produced it."""

    name: str
    available: bool
    reason: str

    def __post_init__(self) -> None:
        if self.name not in _CAPABILITY_NAMES:
            raise ValueError(f"unknown capability: {self.name!r}")
        if type(self.available) is not bool:
            raise TypeError("available must be an exact boolean")
        if type(self.reason) is not str or not self.reason.strip():
            raise TypeError("reason must be a nonblank exact string")

    def evidence_line(self) -> str:
        verdict = "available" if self.available else "unavailable"
        return f"capability:{self.name}={verdict} ({self.reason})"


@dataclass(frozen=True)
class CapabilityReport:
    """A complete capability answer set with one reason per capability."""

    state: CapabilityState
    findings: tuple[CapabilityFinding, ...]

    @classmethod
    def from_findings(cls, findings: Sequence[CapabilityFinding]) -> CapabilityReport:
        by_name = {finding.name: finding for finding in findings}
        if len(by_name) != len(findings):
            raise ValueError("each capability may be reported once")
        missing = [name for name in _CAPABILITY_NAMES if name not in by_name]
        if missing:
            raise ValueError("missing capability findings: " + ", ".join(missing))
        state = CapabilityState(**{name: by_name[name].available for name in _CAPABILITY_NAMES})
        ordered = tuple(by_name[name] for name in _CAPABILITY_NAMES)
        return cls(state=state, findings=ordered)

    def evidence_lines(self) -> tuple[str, ...]:
        return tuple(finding.evidence_line() for finding in self.findings)


class CapabilityUnavailable(DetectionError):
    """Raised by a check to answer False with its own reason.

    A check that knows why a capability is unusable raises this instead of
    returning False, so the operator reads the specific refusal rather than a
    generic one. Any other exception is a defect in the check and is reported
    as such.
    """


class CapabilityProbe(Protocol):
    """Answers the six capability questions for one display, read-only."""

    def probe(self, display: DisplayInfo) -> CapabilityReport: ...


class DeniedCapabilityProbe:
    """Reports every capability unavailable with an explicit reason.

    This is the default. A caller that has not wired a probe has not proved
    anything about the machine, and reporting an unproven capability as
    available would put a dead control in front of the operator.
    """

    def __init__(self, reason: str = "no capability probe was wired for this session") -> None:
        if type(reason) is not str or not reason.strip():
            raise TypeError("reason must be a nonblank exact string")
        self._reason = reason

    def probe(self, display: DisplayInfo) -> CapabilityReport:
        return CapabilityReport.from_findings(
            [CapabilityFinding(name=name, available=False, reason=self._reason) for name in _CAPABILITY_NAMES]
        )


CapabilityCheck = Callable[[DisplayInfo], bool]


class ReadOnlyCapabilityProbe:
    """Answers each capability from an injected read-only check.

    A check that is absent answers False, naming its absence. A check that
    raises answers False, naming the failure. Neither case becomes an
    optimistic default, and neither aborts detection.
    """

    def __init__(
        self,
        *,
        sensor: CapabilityCheck | None = None,
        ddc: CapabilityCheck | None = None,
        dwm_lut: CapabilityCheck | None = None,
        dwm_state_capture: CapabilityCheck | None = None,
        profile_write: CapabilityCheck | None = None,
        vcgt: CapabilityCheck | None = None,
        absent_reason: str = "not probed; this check needs a device session the read-only path does not open",
    ) -> None:
        self._checks: dict[str, CapabilityCheck | None] = {
            "sensor_available": sensor,
            "ddc_available": ddc,
            "dwm_lut_available": dwm_lut,
            "dwm_state_capture_available": dwm_state_capture,
            "profile_write_available": profile_write,
            "vcgt_available": vcgt,
        }
        if type(absent_reason) is not str or not absent_reason.strip():
            raise TypeError("absent_reason must be a nonblank exact string")
        self._absent_reason = absent_reason

    def probe(self, display: DisplayInfo) -> CapabilityReport:
        findings = [self._run(name, self._checks[name], display) for name in _CAPABILITY_NAMES]
        return CapabilityReport.from_findings(findings)

    def _run(self, name: str, check: CapabilityCheck | None, display: DisplayInfo) -> CapabilityFinding:
        if check is None:
            return CapabilityFinding(name=name, available=False, reason=self._absent_reason)
        try:
            answer = check(display)
        except CapabilityUnavailable as exc:
            stated = str(exc).strip()
            return CapabilityFinding(
                name=name,
                available=False,
                reason=stated or "check reported the capability unavailable",
            )
        except Exception as exc:
            summary = f"{type(exc).__name__}: {exc}".strip()
            return CapabilityFinding(name=name, available=False, reason=f"check raised {summary}")
        if type(answer) is not bool:
            return CapabilityFinding(name=name, available=False, reason="check did not return an exact boolean")
        detail = "read-only check passed" if answer else "read-only check did not pass"
        return CapabilityFinding(name=name, available=answer, reason=detail)


def color_directory_present(_display: DisplayInfo) -> bool:
    """Report whether the platform ICC directory exists, without writing."""
    from calibrate_pro.panels.detection import get_color_directory

    return get_color_directory().is_dir()


def gamma_ramp_api_present(_display: DisplayInfo) -> bool:
    """Report whether the gamma ramp API exists on this platform."""
    return sys.platform == "win32"


def dwm_lut_path_usable(_display: DisplayInfo) -> bool:
    """Report whether the DWM LUT path could run here, without loading a LUT.

    Presence of the tool is not enough to enable the control. The bundled hook
    patches DWM at fixed offsets and refuses to run on a Windows build it was
    not built against, so a present-but-refused install answers unavailable and
    carries the refusal text. A measured run on 2026-07-30 found exactly that
    case: the bundled 3.8 hook installed, and refused on Windows build 26220.

    This stats the tool's install locations and reads the OS build number. It
    does not construct the LUT controller, which creates its LUT directory and
    enumerates monitors on construction.
    """
    from calibrate_pro.lut_system.dwm_lut import (
        DwmLutError,
        assert_dwm_lut_runtime_supported,
        bundled_dwm_lut_version_at,
        find_dwm_lut_directory,
    )

    found = find_dwm_lut_directory()
    if found is None:
        raise CapabilityUnavailable("no dwm_lut installation was found on this machine")
    version = bundled_dwm_lut_version_at(found)
    if version is None:
        return True
    if sys.platform != "win32":
        return True
    try:
        assert_dwm_lut_runtime_supported(version, sys.getwindowsversion().build)
    except DwmLutError as exc:
        raise CapabilityUnavailable(str(exc)) from exc
    return True


def windows_read_only_probe(*, sensor: CapabilityCheck | None = None) -> ReadOnlyCapabilityProbe:
    """Wire the checks that answer without opening a device session.

    DDC/CI and authoritative DWM state capture stay unwired. Each needs a
    monitor handle or a device session, and this module opens neither. A
    caller that wants those answers passes its own check and accepts that
    cost explicitly.

    The sensor check is a parameter for the same reason. USB enumeration is
    cheap and reads descriptors only, so a composition may wire it, and this
    module still does not decide that a colorimeter should be searched for.
    """
    return ReadOnlyCapabilityProbe(
        sensor=sensor,
        dwm_lut=dwm_lut_path_usable,
        profile_write=color_directory_present,
        vcgt=gamma_ramp_api_present,
    )


def _format_decimal(value: object, places: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DetectionError("chromaticity and gamma values must be real numbers")
    text = f"{float(value):.{places}f}"
    if text.startswith("-") and float(text) == 0.0:
        return text[1:]
    return text


def _mean_gamma(panel: PanelRecord) -> float:
    channels = (panel.gamma_red.gamma, panel.gamma_green.gamma, panel.gamma_blue.gamma)
    return sum(float(channel) for channel in channels) / len(channels)


def characterization_from_panel(panel: PanelRecord, provenance: str) -> PanelCharacterization:
    """Convert a database panel record into the contract characterization.

    `nominal_gamma` is the mean of the three channel gammas. The database
    models gamma per channel and the contract carries one number, so the
    summary is stated here rather than hidden behind a channel choice.
    """
    if type(provenance) is not str or not provenance.strip():
        raise DetectionError("provenance must be a nonblank exact string")
    primaries = panel.native_primaries
    return PanelCharacterization(
        kind=CharacterizationKind.MATCHED,
        provenance=provenance,
        red_xy=(
            _format_decimal(primaries.red.x, _CHROMATICITY_DECIMALS),
            _format_decimal(primaries.red.y, _CHROMATICITY_DECIMALS),
        ),
        green_xy=(
            _format_decimal(primaries.green.x, _CHROMATICITY_DECIMALS),
            _format_decimal(primaries.green.y, _CHROMATICITY_DECIMALS),
        ),
        blue_xy=(
            _format_decimal(primaries.blue.x, _CHROMATICITY_DECIMALS),
            _format_decimal(primaries.blue.y, _CHROMATICITY_DECIMALS),
        ),
        white_xy=(
            _format_decimal(primaries.white.x, _CHROMATICITY_DECIMALS),
            _format_decimal(primaries.white.y, _CHROMATICITY_DECIMALS),
        ),
        nominal_gamma=_format_decimal(_mean_gamma(panel), _GAMMA_DECIMALS),
    )


def unknown_characterization() -> PanelCharacterization:
    """Return the only characterization a failed panel match may produce."""
    return PanelCharacterization(
        kind=CharacterizationKind.UNKNOWN,
        provenance=UNKNOWN_PROVENANCE,
        red_xy=None,
        green_xy=None,
        blue_xy=None,
        white_xy=None,
        nominal_gamma=None,
    )


def panel_key_from_provenance(characterization: PanelCharacterization) -> str | None:
    """Recover the panel key behind a matched characterization, or None.

    Generation needs the key, not the numbers, because the generator resolves
    its own record from the database. Parsing lives beside the code that writes
    the provenance string so one edit changes both. A characterization that was
    not produced by a database match answers None, and the caller falls back to
    the explicit generic panel rather than guessing a key.
    """
    if not isinstance(characterization, PanelCharacterization):
        raise DetectionError("characterization must be a PanelCharacterization")
    if characterization.kind is not CharacterizationKind.MATCHED:
        return None
    provenance = characterization.provenance
    if not provenance.startswith(PANEL_DATABASE_PROVENANCE_PREFIX):
        return None
    key = provenance[len(PANEL_DATABASE_PROVENANCE_PREFIX) :].strip()
    return key or None


@dataclass(frozen=True)
class RejectedDisplay:
    """A display the platform reported that no observation can describe."""

    platform_display_id: str
    reason: str


@dataclass(frozen=True)
class DetectionResult:
    """Everything one detection pass observed, including what it could not use."""

    dashboard: DashboardModel
    rejected: tuple[RejectedDisplay, ...]


def _safe_label(display: DisplayInfo) -> str:
    """Build a label that identifies the display without identifying the unit.

    Model and manufacturer name a product. Serial numbers and PnP device
    paths name one person's hardware, so they never reach this string.
    """
    number = display.get_display_number()
    stem = f"Display {number}" if number > 0 else "Display"
    product = (display.model or display.monitor_name or "").strip()
    if product and product.casefold() not in _GENERIC_PRODUCT_LABELS:
        return f"{stem} - {product}"
    return stem


def _resolve_panel_key(database: PanelDatabase, record: PanelRecord) -> str:
    for name, value in database.panels.items():
        if value is record:
            return name
    return record.model_pattern.split("|")[0]


def _match_panel(display: DisplayInfo, database: PanelDatabase) -> tuple[PanelCharacterization, str]:
    key = (getattr(display, "panel_database_key", "") or "").strip()
    if key and key != GENERIC_PANEL_KEY:
        record = database.get_panel(key)
        if record is not None:
            provenance = f"{PANEL_DATABASE_PROVENANCE_PREFIX}{key}"
            return characterization_from_panel(record, provenance), f"panel-match:key={key}"
    for candidate in (display.model, display.monitor_name):
        text = (candidate or "").strip()
        if not text:
            continue
        record = database.find_panel(text)
        if record is None:
            continue
        matched_key = _resolve_panel_key(database, record)
        provenance = f"{PANEL_DATABASE_PROVENANCE_PREFIX}{matched_key}"
        return characterization_from_panel(record, provenance), f"panel-match:model={text!r} key={matched_key}"
    return unknown_characterization(), "panel-match:none"


def _utc_stamp(clock: Callable[[], datetime]) -> str:
    moment = clock()
    if type(moment) is not datetime:
        raise DetectionError("clock must return an exact datetime")
    if moment.tzinfo is None:
        raise DetectionError("clock must return an aware datetime")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_enumerator() -> Sequence[DisplayInfo]:
    from calibrate_pro.panels.detection import enumerate_displays

    return enumerate_displays()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DisplayDetector:
    """Turns platform display reports into immutable observations."""

    def __init__(
        self,
        *,
        enumerator: Callable[[], Sequence[DisplayInfo]] | None = None,
        capability_probe: CapabilityProbe | None = None,
        hdr_reader: Callable[[], dict[str, bool]] | None = None,
        database: PanelDatabase | None = None,
        clock: Callable[[], datetime] | None = None,
        enumerator_name: str = "panels.detection.enumerate_displays",
    ) -> None:
        self._enumerator = enumerator if enumerator is not None else _default_enumerator
        self._probe = capability_probe if capability_probe is not None else DeniedCapabilityProbe()
        self._hdr_reader = hdr_reader
        self._database = database if database is not None else get_database()
        self._clock = clock if clock is not None else _utc_now
        if type(enumerator_name) is not str or not enumerator_name.strip():
            raise TypeError("enumerator_name must be a nonblank exact string")
        self._enumerator_name = enumerator_name

    def detect(self) -> DetectionResult:
        """Observe every display once. One bad report never blanks the rest."""
        displays = self._enumerator()
        if not isinstance(displays, (list, tuple)):
            raise DetectionError("enumerator must return a list or tuple of DisplayInfo")
        hdr_states, hdr_evidence = self._read_hdr()

        observations: list[DisplayObservation] = []
        rejected: list[RejectedDisplay] = []
        seen: set[str] = set()
        primary_id: str | None = None

        for display in displays:
            display_id = getattr(display, "device_name", "")
            if type(display_id) is not str or not display_id.strip():
                rejected.append(
                    RejectedDisplay(
                        platform_display_id="(unnamed)",
                        reason="platform reported no device name",
                    )
                )
                continue
            if display_id in seen:
                rejected.append(
                    RejectedDisplay(
                        platform_display_id=display_id,
                        reason="platform reported this device name twice",
                    )
                )
                continue
            try:
                observation = self._observe(display, hdr_states, hdr_evidence)
            except Exception as exc:
                rejected.append(
                    RejectedDisplay(
                        platform_display_id=display_id,
                        reason=f"{type(exc).__name__}: {exc}".strip(),
                    )
                )
                continue
            seen.add(display_id)
            observations.append(observation)
            if primary_id is None and bool(getattr(display, "is_primary", False)):
                primary_id = display_id

        selected = primary_id
        if selected is None and observations:
            selected = observations[0].platform_display_id
        dashboard = DashboardModel(
            displays=tuple(observations),
            selected_display_id=selected,
            refreshed_utc=_utc_stamp(self._clock),
        )
        return DetectionResult(dashboard=dashboard, rejected=tuple(rejected))

    def _read_hdr(self) -> tuple[dict[str, bool], str]:
        if self._hdr_reader is None:
            return {}, "hdr:not-queried"
        try:
            states = self._hdr_reader()
        except Exception as exc:
            return {}, f"hdr:query-failed ({type(exc).__name__}: {exc})".strip()
        if not isinstance(states, dict):
            return {}, "hdr:query-returned-unexpected-type"
        cleaned = {key: value for key, value in states.items() if type(key) is str and type(value) is bool}
        return cleaned, "hdr:queried"

    def _observe(
        self,
        display: DisplayInfo,
        hdr_states: dict[str, bool],
        hdr_evidence: str,
    ) -> DisplayObservation:
        width = int(display.width)
        height = int(display.height)
        refresh_hz = int(display.refresh_rate)
        if width <= 0 or height <= 0:
            raise DetectionError("platform reported a non-positive resolution")
        if refresh_hz <= 0:
            raise DetectionError("platform reported no refresh rate for this display")

        characterization, panel_evidence = _match_panel(display, self._database)
        report = self._probe.probe(display)
        if type(report) is not CapabilityReport:
            raise DetectionError("capability probe must return a CapabilityReport")

        evidence = [
            f"enumerator:{self._enumerator_name}",
            f"mode:{width}x{height}@{refresh_hz}Hz",
            panel_evidence,
            hdr_evidence,
        ]
        evidence.extend(report.evidence_lines())

        return DisplayObservation(
            platform_display_id=display.device_name,
            safe_label=_safe_label(display),
            width_px=width,
            height_px=height,
            refresh_millihz=refresh_hz * 1000,
            hdr_enabled=hdr_states.get(display.device_name),
            characterization=characterization,
            capabilities=report.state,
            evidence=tuple(evidence),
        )


def read_hdr_states() -> dict[str, bool]:
    """Read OS HDR state per display through the read-only HDR query."""
    from calibrate_pro.display.hdr_detect import detect_hdr_state

    states: dict[str, bool] = {}
    for state in detect_hdr_state():
        name = getattr(state, "device_path", None)
        enabled = getattr(state, "hdr_enabled", None)
        if type(name) is str and type(enabled) is bool:
            states[name] = enabled
    return states


__all__ = [
    "GENERIC_PANEL_KEY",
    "PANEL_DATABASE_PROVENANCE_PREFIX",
    "UNKNOWN_PROVENANCE",
    "CapabilityFinding",
    "CapabilityProbe",
    "CapabilityReport",
    "CapabilityUnavailable",
    "DeniedCapabilityProbe",
    "DetectionError",
    "DetectionResult",
    "DisplayDetector",
    "ReadOnlyCapabilityProbe",
    "RejectedDisplay",
    "characterization_from_panel",
    "color_directory_present",
    "dwm_lut_path_usable",
    "gamma_ramp_api_present",
    "panel_key_from_provenance",
    "read_hdr_states",
    "unknown_characterization",
    "windows_read_only_probe",
]
