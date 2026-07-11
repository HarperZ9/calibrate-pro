"""
HDR Calibration Workflow

End-to-end HDR10 and HLG display calibration:
1. Target selection (HDR10 PQ, HLG BT.2100)
2. EOTF verification (PQ/HLG curves)
3. HDR tone mapping (BT.2390 EETF, BT.2446)
4. MaxCLL/MaxFALL measurement estimation
5. HDR metadata generation
6. HDR-aware ICC/LUT export
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np

from calibrate_pro.core.color_math import (
    bt2390_eetf,
    hlg_eotf,
    pq_eotf,
    pq_oetf,
)
from calibrate_pro.verification.provenance import EvidenceKind, MetricValue

# =========================================================================
# HDR Standards & Targets
# =========================================================================


class HDRStandard(Enum):
    HDR10 = "hdr10"  # PQ/ST.2084, Rec.2020, 10-bit
    HLG = "hlg"  # HLG/BT.2100, Rec.2020
    DOLBY_VISION = "dv"  # Future


# BT.2020 CIE 1931 xy primaries
_BT2020_RED = (0.708, 0.292)
_BT2020_GREEN = (0.170, 0.797)
_BT2020_BLUE = (0.131, 0.046)
_BT2020_WHITE = (0.3127, 0.3290)

# BT.2020 luminance coefficients
_BT2020_LUM = np.array([0.2627, 0.6780, 0.0593])


@dataclass
class HDRTarget:
    """HDR calibration target specification."""

    standard: HDRStandard
    peak_luminance: float = 1000.0  # cd/m2 (nits)
    min_luminance: float = 0.005  # cd/m2
    max_cll: float = 1000.0  # Maximum Content Light Level
    max_fall: float = 400.0  # Max Frame Average Light Level
    gamut: str = "bt2020"  # Target color gamut

    @classmethod
    def hdr10_1000(cls) -> "HDRTarget":
        """HDR10 at 1000 nits peak."""
        return cls(standard=HDRStandard.HDR10, peak_luminance=1000.0)

    @classmethod
    def hdr10_600(cls) -> "HDRTarget":
        """HDR10 at 600 nits (common for OLED)."""
        return cls(
            standard=HDRStandard.HDR10,
            peak_luminance=600.0,
            max_cll=600.0,
            max_fall=250.0,
        )

    @classmethod
    def hlg_1000(cls) -> "HDRTarget":
        """HLG at 1000 nits system gamma."""
        return cls(standard=HDRStandard.HLG, peak_luminance=1000.0)


# =========================================================================
# Result Container
# =========================================================================


@dataclass
class HDRCalibrationResult:
    """Results from an HDR calibration pass."""

    target: HDRTarget
    eotf_error: MetricValue
    peak_luminance: MetricValue
    gamut_coverage_bt2020: MetricValue
    tone_map_curve: np.ndarray
    lut_data: np.ndarray | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target.standard.value,
            "eotf_error": self.eotf_error.to_dict(),
            "peak_luminance": self.peak_luminance.to_dict(),
            "gamut_coverage_bt2020": self.gamut_coverage_bt2020.to_dict(),
        }


# =========================================================================
# HDR Workflow
# =========================================================================


class HDRWorkflow:
    """
    Complete HDR calibration workflow.

    Orchestrates EOTF patch generation, measurement verification,
    tone-map creation, 3-D LUT generation, metadata output, and
    .cube export for both HDR10 (PQ) and HLG targets.
    """

    # HLG system gamma (nominal BT.2100 reference viewing)
    _HLG_SYSTEM_GAMMA = 1.2

    def __init__(self, target: HDRTarget):
        self.target = target
        self._result: HDRCalibrationResult | None = None

    # -----------------------------------------------------------------
    # Step 1 -- EOTF Verification Patches
    # -----------------------------------------------------------------

    def generate_eotf_patches(self, steps: int = 21) -> np.ndarray:
        """
        Generate PQ or HLG EOTF verification patches.

        Returns an (steps, 2) array where column 0 is the signal
        value [0, 1] and column 1 is the expected luminance (cd/m2).
        """
        if steps < 2:
            raise ValueError("steps must be >= 2")

        if self.target.standard == HDRStandard.HDR10:
            max_signal = float(pq_oetf(np.array([self.target.peak_luminance], dtype=np.float64))[0])
            signals = np.linspace(0.0, max_signal, steps)
            luminances = pq_eotf(signals)
        else:
            signals = np.linspace(0.0, 1.0, steps)
            # HLG: inverse OETF gives scene-linear, then OOTF
            scene = hlg_eotf(signals)
            luminances = scene * self.target.peak_luminance

        return np.column_stack([signals, luminances])

    # -----------------------------------------------------------------
    # Step 2 -- EOTF Verification
    # -----------------------------------------------------------------

    def verify_eotf(
        self,
        measured: np.ndarray,
        expected: np.ndarray,
    ) -> float:
        """
        Compare measured vs expected EOTF luminance values.

        Args:
            measured: Measured luminance array (cd/m2).
            expected: Target luminance array (cd/m2).

        Returns:
            Average percentage error across all steps.
        """
        measured = np.asarray(measured, dtype=np.float64)
        expected = np.asarray(expected, dtype=np.float64)

        if measured.shape != expected.shape:
            raise ValueError(f"Shape mismatch: measured {measured.shape} vs expected {expected.shape}")

        # Avoid division by zero for the black-level patch
        safe_expected = np.where(expected > 0, expected, 1.0)
        errors = np.abs(measured - expected) / safe_expected * 100.0
        # Zero-luminance patches get 0 % error
        errors = np.where(expected > 0, errors, 0.0)

        return float(np.mean(errors))

    # -----------------------------------------------------------------
    # Step 3 -- Tone Map Generation
    # -----------------------------------------------------------------

    def generate_tone_map(self, steps: int = 1024) -> np.ndarray:
        """
        Generate a BT.2390 EETF curve adapted to the display peak.

        Returns an (steps, 2) array: col 0 = input PQ signal,
        col 1 = output PQ signal after tone mapping.
        """
        if steps < 2:
            raise ValueError("steps must be >= 2")

        pq_in = np.linspace(0.0, 1.0, steps)

        pq_out = bt2390_eetf(
            pq_in,
            source_peak_nits=10000.0,
            target_peak_nits=self.target.peak_luminance,
            target_black_nits=self.target.min_luminance,
        )

        return np.column_stack([pq_in, pq_out])

    # -----------------------------------------------------------------
    # Step 4 -- 3-D LUT Generation
    # -----------------------------------------------------------------

    def generate_hdr_lut(self, size: int = 33) -> np.ndarray:
        """
        Generate a 3-D LUT that tone-maps source HDR (BT.2020 PQ)
        to the display capability defined by self.target.

        Returns an (size, size, size, 3) float64 array in [0, 1].
        """
        if size < 2:
            raise ValueError("LUT size must be >= 2")

        coords = np.linspace(0.0, 1.0, size)
        r, g, b = np.meshgrid(coords, coords, coords, indexing="ij")
        rgb = np.stack([r, g, b], axis=-1)  # (S, S, S, 3)

        flat = rgb.reshape(-1, 3)

        # 1.  Apply BT.2390 EETF per channel (PQ domain)
        mapped = bt2390_eetf(
            flat,
            source_peak_nits=10000.0,
            target_peak_nits=self.target.peak_luminance,
            target_black_nits=self.target.min_luminance,
        )

        # 2.  Decode to linear luminance
        linear = pq_eotf(mapped)

        # 3.  Normalise back to [0, 1] relative to display peak
        linear_norm = linear / max(self.target.peak_luminance, 1.0)

        # 4.  Re-encode to PQ for the LUT output
        out = pq_oetf(linear_norm * self.target.peak_luminance)

        return np.clip(out.reshape(size, size, size, 3), 0.0, 1.0)

    # -----------------------------------------------------------------
    # Step 5 -- HDR Metadata
    # -----------------------------------------------------------------

    def generate_hdr_metadata(self) -> dict:
        """
        Generate HDR10 static metadata (ST.2086 + CEA-861.3).

        Returns a dict suitable for JSON serialisation or embedding
        in a .cube file header.
        """
        return {
            "standard": self.target.standard.value,
            "primaries": {
                "red": _BT2020_RED,
                "green": _BT2020_GREEN,
                "blue": _BT2020_BLUE,
                "white_point": _BT2020_WHITE,
            },
            "luminance": {
                "max_nits": self.target.peak_luminance,
                "min_nits": self.target.min_luminance,
            },
            "content_light_level": {
                "max_cll": self.target.max_cll,
                "max_fall": self.target.max_fall,
            },
        }

    # -----------------------------------------------------------------
    # Step 6 -- .cube Export
    # -----------------------------------------------------------------

    def export_cube(self, path: str, lut: np.ndarray) -> None:
        """
        Export a 3-D LUT as a .cube file with HDR metadata comments.

        Args:
            path: Output file path (should end in .cube).
            lut: (size, size, size, 3) LUT data in [0, 1].
        """
        if lut.ndim != 4 or lut.shape[-1] != 3:
            raise ValueError(f"LUT must be shape (size, size, size, 3), got {lut.shape}")

        size = lut.shape[0]
        meta = self.generate_hdr_metadata()

        lines: list[str] = []
        lines.append(f'TITLE "Calibrate Pro HDR {self.target.standard.value}"')
        lines.append(f"# HDR Standard: {meta['standard']}")
        lines.append(f"# Peak luminance: {meta['luminance']['max_nits']} nits")
        lines.append(f"# Min luminance: {meta['luminance']['min_nits']} nits")
        lines.append(f"# MaxCLL: {meta['content_light_level']['max_cll']} nits")
        lines.append(f"# MaxFALL: {meta['content_light_level']['max_fall']} nits")
        lines.append(f"LUT_3D_SIZE {size}")
        lines.append("DOMAIN_MIN 0.0 0.0 0.0")
        lines.append("DOMAIN_MAX 1.0 1.0 1.0")
        lines.append("")

        # .cube ordering: B fastest, then G, then R
        for ri in range(size):
            for gi in range(size):
                for bi in range(size):
                    rv, gv, bv = lut[ri, gi, bi]
                    lines.append(f"{rv:.6f} {gv:.6f} {bv:.6f}")

        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
            fh.write("\n")

    # -----------------------------------------------------------------
    # run() -- Full Orchestration
    # -----------------------------------------------------------------

    def run(
        self,
        measured_luminances: np.ndarray | None = None,
        lut_size: int = 17,
        *,
        evidence: EvidenceKind = EvidenceKind.NOT_MEASURED,
        evidence_source: str | None = None,
    ) -> HDRCalibrationResult:
        """
        Execute the full HDR calibration workflow.

        Args:
            measured_luminances: Optional measured or replayed luminance
                readings in cd/m2. Missing readings remain not measured unless
                an explicit simulation is requested.
            lut_size: Resolution of the generated 3-D LUT.
            evidence: Evidence label for the supplied or simulated readings.
            evidence_source: Instrument receipt, fixture, or simulation source.

        Returns:
            HDRCalibrationResult with all artefacts.
        """
        if not isinstance(evidence, EvidenceKind):
            raise TypeError("evidence must be an EvidenceKind")

        # 1. EOTF patches
        patches = self.generate_eotf_patches(steps=21)
        expected = patches[:, 1]

        # 2. Construct evidence-bearing luminance metrics.
        if measured_luminances is None and evidence is EvidenceKind.NOT_MEASURED:
            eotf_error = MetricValue(None, "percent", EvidenceKind.NOT_MEASURED)
            peak_luminance = MetricValue(None, "nits", EvidenceKind.NOT_MEASURED)
        elif measured_luminances is None and evidence is EvidenceKind.SIMULATED:
            if not evidence_source or not evidence_source.strip():
                raise ValueError("SIMULATED HDR runs require evidence_source")
            measured = expected.copy()
            eotf_error = MetricValue(
                self.verify_eotf(measured, expected),
                "percent",
                evidence,
                evidence_source,
            )
            peak_luminance = MetricValue(float(np.max(measured)), "nits", evidence, evidence_source)
        elif measured_luminances is None:
            raise ValueError(f"{evidence.value} evidence requires measured_luminances")
        else:
            if evidence not in {EvidenceKind.MEASURED, EvidenceKind.REPLAYED}:
                raise ValueError("measured_luminances require MEASURED or REPLAYED evidence")
            if not evidence_source or not evidence_source.strip():
                raise ValueError(f"{evidence.value} HDR runs require evidence_source")
            measured = np.asarray(measured_luminances, dtype=np.float64)
            if not np.all(np.isfinite(measured)):
                raise ValueError("measured_luminances must contain only finite readings")
            eotf_error = MetricValue(
                self.verify_eotf(measured, expected),
                "percent",
                evidence,
                evidence_source,
            )
            peak_luminance = MetricValue(float(np.max(measured)), "nits", evidence, evidence_source)

        # 3. Tone map
        tm_curve = self.generate_tone_map()

        # 4. 3-D LUT
        lut = self.generate_hdr_lut(size=lut_size)

        # 5. Luminance-only inputs cannot establish color-volume coverage.
        self._result = HDRCalibrationResult(
            target=self.target,
            eotf_error=eotf_error,
            peak_luminance=peak_luminance,
            gamut_coverage_bt2020=MetricValue(None, "percent", EvidenceKind.NOT_MEASURED),
            tone_map_curve=tm_curve[:, 1],
            lut_data=lut,
        )

        return self._result
