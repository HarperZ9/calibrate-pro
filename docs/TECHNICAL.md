# Calibrate Pro -- Technical Documentation

## Calibration Pipeline

### Overview

Calibrate Pro prepares and, only after explicit operator confirmation, applies supported
display corrections through a multi-stage pipeline:

```
Detection → Panel Matching → Method/Target → Immutable Preview → Explicit Confirmation → Supported Actuation → Evidence-Labeled Verification
```

The detection, planning, and reporting stages do not write display state. Every supported
actuation requires a fresh plan and explicit confirmation through the interactive workflow.

### Stage 1: Panel Identification

Monitors are identified through three methods in priority order:

1. **EDID model name** -- parsed from the monitor's EDID data block (bytes 54-125, descriptor tag 0xFC)
2. **Fingerprint matching** -- resolution + refresh rate + manufacturer code mapped to known panels
3. **EDID chromaticity extraction** -- raw 10-bit CIE xy coordinates from EDID bytes 25-34, used to construct a dynamic panel characterization for unknown displays

The panel database stores nominal characterization primaries, per-channel gamma, capabilities,
and source notes -- not observations of the connected unit. EDID chromaticities and database
values are inputs to an estimate, not a measurement of the attached unit. Color correction
matrices are computed at runtime from the selected characterization using
`primaries_to_xyz_matrix()`.

### Stage 2: DDC-CI Hardware Plan

When the attached display reports support, a plan may propose these bounded DDC-CI controls:
- RGB gain (VCP codes 0x16, 0x18, 0x1A) for white point correction
- Brightness (VCP 0x10) for target luminance
- Contrast (VCP 0x12) for black level optimization

No control is adjusted during detection or planning. The GUI shows the exact plan and requires
explicit confirmation before the confirmation-bound adapter can attempt a supported write.
When confirmed and supported, hardware correction can reduce the correction left to a software
LUT while preserving more of the signal path's available precision.

### Stage 3: 3D LUT Generation

Three LUT generation modes:

**Native Gamut (default):** Corrects gamma tracking and white point within the panel's native gamut. No gamut compression. Uses per-channel gamma correction with Bradford chromatic adaptation for white point adjustment. This preserves the full color volume of wide-gamut displays.

**sRGB Target:** Compresses the panel's gamut to sRGB using Oklab perceptual gamut mapping (Ottosson, 2020). Binary search in Oklab space finds the maximum achievable chroma at each hue angle, preserving hue while reducing saturation smoothly. This avoids the blue→purple hue shift that Lab-space compression produces.

**HDR (PQ):** Operates in PQ signal space (SMPTE ST.2084). Uses BT.2390 EETF (hermite spline) for luminance mapping from source peak to display peak. Gamut mapping in JzAzBz space (Safdar et al., 2017) which is perceptually uniform across the full HDR luminance range -- unlike Oklab which was designed for SDR.

Generation produces an asset; it does not imply that the asset was installed or applied. Any
supported application is capability-checked, included in the immutable preview, and separately
confirmed. Unsupported or unrecoverable actuation fails closed.

### Stage 4: OLED-Specific Compensation

For OLED panels, the LUT accounts for:

**ABL (Auto Brightness Limiter):** Modeled per-panel family. At 25% APL (typical mixed content), a QD-OLED 2024 panel sustains ~770 cd/m² vs 1000 cd/m² peak. The LUT targets the sustainable luminance, not the peak spec.

**Near-black handling:** QD-OLED exhibits slight raised blacks at <3% signal. WOLED shows green tint in near-black due to the white subpixel turning off at a different threshold than RGB. Both are modeled and corrected in the LUT.

### Stage 5: Verification

Verification uses two perceptual color difference metrics:

**CIEDE2000** (CIE, 2001): The standard metric. Accounts for lightness, chroma, and hue weighting. A model-derived score is labelled estimated and is not an accuracy claim for the attached unit. Instrument-derived values retain their measurement provenance; unavailable observations are reported as Not measured.

**CAM16-UCS** (Li et al., 2017): Euclidean distance in the CAM16 Uniform Color Space. More accurate than CIEDE2000 for wide-gamut displays because it accounts for viewing conditions (adapting luminance, surround, chromatic adaptation degree). The stricter of the two metrics determines the grade.

### Stage 6: Gamut Analysis

**2D Gamut Area:** Exact polygon intersection using Sutherland-Hodgman clipping. No Monte Carlo sampling.

**3D Color Volume:** Computed in CIE LCH space at multiple lightness levels. Integrates gamut area over lightness to capture luminance-dependent gamut changes. For OLED panels, includes a luminance rolloff model: QD-OLED loses ~5% saturation at L*=90, WOLED loses ~15%.

---

## Color Science Foundations

### Perceptual Color Spaces

| Space | Use Case | Reference |
|-------|----------|-----------|
| Oklab | SDR gamut mapping | Ottosson, "A perceptual color space for image processing" (2020) |
| JzAzBz | HDR gamut mapping | Safdar et al., "Perceptually uniform color space for image signals including HDR and WCG" (2017) |
| CAM16 | Verification metrics | Li et al., "Comprehensive color model CIECAM16" (2017) |
| ICtCp | Dolby Vision processing | Dolby, ITU-R BT.2100 |
| CIELAB | Legacy compatibility | CIE 15:2004 |

### Transfer Functions

| Function | Standard | Use |
|----------|----------|-----|
| sRGB EOTF | IEC 61966-2-1 | SDR display encoding |
| PQ (ST.2084) | SMPTE ST.2084 | HDR absolute luminance |
| HLG | ARIB STD-B67 / BT.2100 | HDR relative/broadcast |
| BT.1886 | ITU-R BT.1886 | Broadcast SDR |
| BT.2390 EETF | ITU-R BT.2390 | HDR-to-display tone mapping |

### Chromatic Adaptation

Bradford cone-response model (Lam, 1985; Süsstrunk et al., 2000). Used for:
- Panel white point to D65 adaptation
- ICC PCS adaptation (D65 ↔ D50)
- Cross-illuminant verification (ColorChecker under D50 vs display under D65)

---

## Sensorless Calibration: Honest Limitations

Sensorless calibration uses panel database characteristics to predict corrections. The accuracy depends on:

1. **How close your specific panel is to the database values.** Panel-to-panel variation within the same model can be ±0.003 in chromaticity. Our database stores nominal values -- your unit may differ.

2. **Gamma accuracy.** Per-channel gamma is stored as a single power value. Real panels have complex TRC shapes that deviate from a pure power law, especially in the near-black region.

3. **Temperature and age.** OLED panels shift in color and brightness as they warm up (first 30 minutes) and as they age (over months/years).

**What sensorless calibration CAN do:** Produce an estimated correction plan from nominal panel
characterization or EDID-derived inputs. It can make the assumptions and proposed transforms
inspectable, but its model score does not establish the accuracy of the attached unit.

**What sensorless calibration CANNOT do:** Guarantee measured accuracy. Only a colorimeter measurement on YOUR specific panel tells you the actual result.

**Recommendation:** Use the window to review the assumptions and the exact plan before
generating. With a supported colorimeter attached, measure the display first. The run
replaces the panel record the plan is derived from, and measured verification then reports
the result from a second reading rather than from a model. Generate and explicitly confirm
a fresh plan for every display change; legacy direct-action CLI names are proposal-only and
exit without changing display state.

---

## Output Formats

| Format | Consumer | Purpose |
|--------|----------|---------|
| `.cube` (33³) | DaVinci Resolve, dwm_lut | Standard 3D LUT |
| `.3dlut` | MadVR | Binary LUT for video playback |
| `.icc` (v4) | Windows, macOS, Linux | ICC color profile with TRC curves |
| `_mhc2.icc` | Windows HDR | MHC2 matrix for DWM compositor |
| `_reshade.png` | ReShade | Strip texture LUT |
| `_specialk.png` | SpecialK | Strip texture LUT |
| `_obs.cube` | OBS Studio | LUT with setup instructions |
| `_mpv.conf` | mpv | Player configuration snippet |
| `_report.html` | Browser | Self-contained calibration report |
