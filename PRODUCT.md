# Product

## Register

product

## Users

Calibrate Pro serves display-calibration practitioners working on Windows in
controlled lighting: colorists, photographers, video editors, technical artists,
display reviewers, and engineers who need profiles, LUTs, display controls, and
verification evidence without moving between disconnected tools.

The primary task is to understand the selected display’s current state, choose a
sensorless or instrument-assisted method, review the exact proposed change,
apply only supported operations with explicit consent, verify the result, and
save a profile, LUT, or report. Expert users should see the technical facts they
need without navigating a settings labyrinth. Users without optional hardware
must still have a useful, truthful sensorless workflow.

## Product Purpose

Calibrate Pro makes Windows display calibration inspectable and reversible. It
unifies display discovery, characterized panel data, calibration targets,
DDC/CI, ICC/VCGT and 3D LUT output, instrument measurement, and evidence-labelled
reports behind one native desktop workflow:

Detect → Method → Preview → Apply → Verify → Save/Report.

Success means the operator can see what is known, what is estimated, what is not
measured, what will change, and what artifacts were produced. The interface must
never convert modeled, simulated, replayed, or placeholder values into apparent
instrument observations.

## Brand Personality

**Precise, restrained, trustworthy.**

The product should feel like calibrated lab equipment adapted for a creative
workstation: quiet in a dark room, dense where expertise benefits from density,
and explicit about capability and evidence. Copy is direct and technical without
performing expertise or hiding unavailable operations behind vague errors.

## Anti-references

- Not a generic neon developer dashboard or a glassmorphic AI control panel.
- Not a color-grading tool with creative wheels, curves, or look-design controls.
- Not a monitor-review suite for response time, input lag, or uniformity maps.
- Not a settings labyrinth that makes the operator configure sensible defaults.
- Not a marketing mockup populated with fabricated Delta E, gamut, luminance,
  calibration age, or sensor readings.
- Not a bright white productivity app that disrupts controlled viewing conditions.

## Design Principles

1. **Evidence before decoration.** Every visible metric carries its evidence kind;
   unavailable observations render as “Not measured.”
2. **The next safe action is obvious.** The selected display, method, target,
   preview state, consent boundary, and recovery path remain legible at every step.
3. **Expert density, calm hierarchy.** Preserve useful technical detail while
   organizing it into scan-friendly groups with one primary action per state.
4. **Capability-aware by default.** Missing instruments, DDC/CI, privileges, LUT
   support, or platform features disable only the affected operation and explain
   the available alternative.
5. **Native, not theatrical.** Use familiar Windows and Qt interaction patterns,
   keyboard navigation, compact components, and state-driven motion.

## Accessibility & Inclusion

Target WCAG 2.2 AA contrast and interaction semantics within Qt’s capabilities.
The dark-room palette must retain at least 4.5:1 contrast for body text and clear
visible focus. Color is never the only status signal; evidence kinds and
pass/warn/fail states use text and shape as well as hue. Support keyboard
navigation, screen-reader names for custom widgets, 100–200% Windows scaling,
reduced or disabled nonessential motion, and layouts that remain usable without
a colorimeter or mutation-capable hardware.
