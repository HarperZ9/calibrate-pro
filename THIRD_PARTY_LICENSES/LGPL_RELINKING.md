# Replacing LGPL Qt components

Calibrate Pro ships as a PyInstaller **onedir** application. Qt, PySide6, and shiboken6 remain external dynamic libraries in the application directory; they are not statically linked into either launcher. A recipient may replace those LGPL-covered libraries with a compatible modified build for relinking and debugging.

1. Make a backup copy of the complete installed application directory and close every Calibrate Pro process.
2. Obtain or build ABI-compatible PySide6, shiboken6, and Qt libraries. The exact unmodified 6.11.1 sources used for this release are listed in `QT_SOURCE_OFFER.txt`.
3. In the copied onedir tree, replace the corresponding external files in `_internal/PySide6/`, `_internal/PySide6/Qt/bin/`, `_internal/PySide6/Qt/plugins/`, and the adjacent shiboken6 package paths. Preserve the original relative paths and filenames expected by Python and Qt.
4. Keep a mutually compatible set: the replacement PySide6 and shiboken6 bindings must match the replacement Qt ABI and the packaged CPython 3.12 ABI.
5. Launch `CalibrateProCLI.exe doctor --json`, then exercise the copied application before relying on it. A modified library can be incompatible or unsafe; this diagnostic is not a certification of the modification.

The installer does not require a cryptographic signature on replacement DLLs. Windows security controls may still warn about downloaded or modified binaries, and replacing files invalidates any original signature that covered those files. The distributor does not warrant modified libraries, but Calibrate Pro's terms do not withdraw the LGPL rights needed to perform this replacement or to reverse engineer for debugging a modification to an LGPL component.
