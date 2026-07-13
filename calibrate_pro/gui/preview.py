"""Deterministic, hardware-free data for the native GUI preview."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

if TYPE_CHECKING:
    from calibrate_pro.gui.app import QtDisplaySnapshot


PREVIEW_SOURCE = "bundled public preview fixture"


@dataclass(frozen=True)
class PreviewDisplay:
    """One generic preview display and its explicitly labelled evidence."""

    snapshot: QtDisplaySnapshot
    panel_type: str
    gamut_srgb: MetricValue
    gamut_p3: MetricValue
    gamut_bt2020: MetricValue
    peak_luminance: MetricValue
    delta_e: MetricValue

    @property
    def resolution(self) -> str:
        return f"{self.snapshot.width} × {self.snapshot.height} @ {self.snapshot.refresh_rate} Hz"

    @property
    def metrics(self) -> tuple[MetricValue, ...]:
        return (
            self.gamut_srgb,
            self.gamut_p3,
            self.gamut_bt2020,
            self.peak_luminance,
            self.delta_e,
        )


class PreviewSnapshotProvider:
    """Provide a stable public fixture without consulting local machine state."""

    def snapshots(self) -> tuple[PreviewDisplay, ...]:
        from calibrate_pro.gui.app import QtDisplaySnapshot

        snapshot = QtDisplaySnapshot(
            index=0,
            name="Reference Display",
            device_name="",
            device_id="",
            monitor_name="Reference Display",
            manufacturer="",
            model="",
            serial="",
            width=3840,
            height=2160,
            refresh_rate=120,
            bit_depth=10,
            is_primary=True,
        )
        return (
            PreviewDisplay(
                snapshot=snapshot,
                panel_type="QD-OLED",
                gamut_srgb=MetricValue(100.0, "%", EvidenceKind.SIMULATED, PREVIEW_SOURCE),
                gamut_p3=MetricValue(98.0, "%", EvidenceKind.SIMULATED, PREVIEW_SOURCE),
                gamut_bt2020=MetricValue(None, "%", EvidenceKind.NOT_MEASURED),
                peak_luminance=MetricValue(1000.0, "nits", EvidenceKind.SIMULATED, PREVIEW_SOURCE),
                delta_e=MetricValue(None, "dE2000", EvidenceKind.NOT_MEASURED),
            ),
        )
