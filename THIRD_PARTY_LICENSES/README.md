# Third-party notices

Calibrate Pro's FSL-1.1-MIT terms apply only to Calibrate Pro material. They do not replace, restrict, or supersede any third-party license in this directory. Each redistributed dependency remains governed by its own notice and license text.

Qt for Python, Shiboken, and the approved Qt libraries are distributed under the LGPL-3.0-only option identified in `Qt-for-Python-NOTICE.txt`. The full license is in `LGPL-3.0-only.txt`; exact source locations and hashes are in `QT_SOURCE_OFFER.txt` and `../packaging/source-provenance.lock.json`; practical replacement instructions are in `LGPL_RELINKING.md`.

Nothing in Calibrate Pro's terms is intended to prohibit replacing or relinking a compatible LGPL library, or reverse engineering solely as necessary to debug a modification to an LGPL-covered component, where the LGPL preserves those rights.

The remaining files reproduce upstream license payloads from the locked Python 3.12 Windows release environment or the exact source revision recorded for the component. This notice collection is a release-engineering control, not legal advice or a substitute for final counsel review.

Additional release-evidence indexes:

- `Packaging-26.2.txt` reproduces packaging's exact dual-license payloads.
- `CPython-3.12.10-Windows-Externals-NOTICE.txt` identifies the external
  libraries present in the official CPython Windows runtime and reproduces
  their upstream license payloads.
- `Microsoft-Visual-Cpp-Runtime-NOTICE.txt` records the versions, hashes, and
  immutable binary origins of proprietary Microsoft redistributable files;
  these are intentionally not represented as open-source components.
- `Qt-6.11.1-THIRD-PARTY-NOTICES.txt` reproduces the official
  `qt_attribution.json` payloads relevant to the retained Qt Base surface.
- `../packaging/binary-provenance.lock.json` records the exact Windows
  installer, wheel, SPDX, release-archive, and build-input receipts used to
  trace binary origins. It complements rather than replaces corresponding
  source in `../packaging/source-provenance.lock.json`.

The Windows package also contains unmodified `dwm_lut` 3.8 binaries and its
`WindowsDisplayAPI` 1.3.0.13 dependency. Their original `LICENSE` (GPL-3.0-only) and
`LICENSE-THIRD-PARTY` (including the WindowsDisplayAPI LGPL-3.0-only notice) remain
beside those binaries. Exact corresponding-source URLs and SHA-256 values for both
immutable tags are recorded in `../packaging/source-provenance.lock.json` and in the
`source-provenance.json` release receipt.
