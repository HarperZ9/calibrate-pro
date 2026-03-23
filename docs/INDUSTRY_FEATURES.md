# Industry-Driven Feature Priorities

Based on research across DisplayCAL forums, AVS Forum, LiftGammaGain, REDUSER, Doom9, ResetEra, DPReview, Reddit r/colorists, and Hacker News.

## Tier 1: Address Immediate Pain Points (Build Now)

### 1. Windows Calibration Protection
Windows 24H2 actively sabotages calibration by resetting VCGT data and unloading ICC profiles. Build a watchdog service that:
- Monitors VCGT state every 10 seconds, reapplies if Windows resets it
- Re-registers ICC profile association after Settings panel visits
- Detects Windows "Auto Color Management" and warns the user
- Survives sleep/wake, display topology changes, and Settings panel interactions

### 2. Unified ICC + 3D LUT Workflow
No tool handles both ecosystems. In the GUI:
- Single calibration run generates BOTH an ICC profile (for Photoshop/Lightroom) AND a 3D LUT (for Resolve/video)
- Show which applications use which profile
- Explain clearly: "ICC profile corrects Photoshop, 3D LUT corrects Resolve, both are needed"

### 3. Beautiful Customer-Facing Reports
CalMAN's main advantage over free tools is "beautiful reports for customers." Our HTML report exists but needs:
- PDF export button
- Professional layout suitable for sending to clients
- Before/after comparison with measured data
- Company logo customization

### 4. sRGB System-Wide Gamut Clamp
Wide-gamut displays show oversaturated colors in non-color-managed apps (games, browsers, desktop). Users desperately need:
- A system-wide sRGB clamp that works for ALL applications (via dwm_lut)
- Toggle in the tray: "sRGB Clamp ON/OFF"
- Option to exclude specific apps (Resolve, Photoshop — they manage their own color)

### 5. DaVinci Resolve Integration Guide
The #1 question on every color forum: "How do I use my calibration in Resolve?" Build:
- One-click "Install to Resolve" that copies the LUT to Resolve's LUT folder
- Clear instructions: use Color Viewer LUT (not Video Monitor LUT) for single-monitor
- Warn about ACES incompatibility with monitor LUTs

## Tier 2: Serve Professional Workflows (Build Next)

### 6. Colorimeter Correction Data (CCSS/CCMX)
Different backlight technologies need spectral corrections. Support:
- Loading custom CCSS/CCMX files (X-Rite correction data)
- Auto-detect backlight type from panel database (WLED, QD-OLED, PFS, etc.)
- Apply appropriate correction for the sensor+display combination

### 7. Verification Reports That Match CalMAN Quality
Professionals need reports they can show clients. Include:
- CIE diagram with measured points
- Grayscale tracking chart
- Gamma curve comparison
- Delta E table with pass/fail
- Monitor info, sensor info, date, conditions
- Export as PDF and PNG

### 8. OLED-Aware Measurement Workflow
OLED calibration has unique requirements:
- Configurable patch dwell time (OLED needs 2-3 seconds for ABL to settle)
- Black frame insertion between patches
- Auto-detect and warn about ASBL
- Skip full-field white patches (trigger aggressive ABL)

### 9. SDR/HDR Auto-Switching
Users manually toggle HDR in Windows settings per-game. Build:
- Detect HDR mode change via registry monitoring
- Auto-apply SDR or HDR profile when mode switches
- Per-app HDR rules (always HDR for Game X, always SDR for Photoshop)

### 10. Monitor Hardware LUT Loading
Professional monitors (EIZO, BenQ, NEC) have internal 3D LUTs:
- Document which monitors support hardware LUT loading
- Implement EIZO ColorNavigator protocol
- Implement BenQ Palette Master protocol
- These bypass Windows color management entirely

## Tier 3: Community & Ecosystem (Build Later)

### 11. Sensor Cross-Calibration
No two meters measure the same. Build:
- Cross-calibration wizard: measure with two sensors, compute correction matrix
- Community-shared correction data for sensor+display combinations

### 12. macOS Gamma Fix
macOS uses gamma 2.2 compound curve for P3-D65, causing gamma mismatch with Rec.709 content. Build:
- Export Cullen Kelly-style macOS Viewing Transform LUT
- Document the macOS gamma problem for users

### 13. Wayland/Linux Color Management
Linux is getting proper color management via xx-color-management-v1 protocol. Build:
- Early Wayland color management integration
- colord/xrandr fallback for X11

## Anti-Features (What NOT to Build)

- Don't build a color grading tool (Resolve does this)
- Don't build a pattern generator (ArgyllCMS/DisplayCAL do this)
- Don't build a TV service menu editor (too specialized)
- Don't build monitor review/comparison features (Rtings does this)
