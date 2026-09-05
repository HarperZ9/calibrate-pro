"""The settings this build actually has.

The page used to draw eleven controls and mean four of them. The other seven
wrote into the application's configuration store, which nothing read back, so a
checkbox could be ticked, survive a restart, and change nothing. The manifest
had declared those seven hidden the whole time, with the reason that their
product workflow is not specified yet.

What is left is what the session can be asked for: the grid its next LUT is
built on, where its reports are written, and the journal underneath both. HDR is
drawn and closed, because someone looking for it needs to read why rather than
conclude the build never had it.
"""

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro import __version__ as APP_VERSION
from calibrate_pro.gui.app import C, Card, Heading
from calibrate_pro.gui.pages.settings_diagnostics import DiagnosticsSection

# Constants

APP_ORG = "Build Universe"
APP_NAME = "Calibrate Pro"

DEFAULT_OUTPUT_DIR = str(Path.home() / "Documents" / "Calibrate Pro" / "Calibrations")

#: What the output field says before the session has accepted a directory. The
#: field used to open on a default path, which read as a configured folder while
#: the session held none and refused every export.
OUTPUT_UNSET = "No output folder chosen in this session"

OUTPUT_UNSET_NOTE = "Saving a report needs an output folder. Choose one here."

OUTPUT_NOTE = "Saved reports and exports are written here."

OUTPUT_REJECTED = "This location cannot be written to, so report saving stays closed."

#: The grids this build generates, in the order the selector offers them.
LUT_SIZES = (17, 33, 65)

LUT_NOTE = "The next generated bundle is built on this grid. A sealed bundle keeps the grid it was built with."

#: Under the HDR box. The resolver supplies the reason the control is closed;
#: this says what the build does in the meantime, which the reason does not.
HDR_NOTE = "Everything this build generates is SDR."

_FIELD_STYLE = (
    f"QLineEdit {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
    f"border-radius: 8px; padding: 7px 12px; font-size: 12px; }}"
    f"QLineEdit:focus {{ border-color: {C.ACCENT}; }}"
)

_BROWSE_STYLE = (
    f"QPushButton {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
    f"border-radius: 10px; font-size: 11px; padding: 4px 12px; }}"
    f"QPushButton:hover {{ border-color: {C.ACCENT}; background: {C.SURFACE2}; }}"
)


# Helpers


def _make_section_heading(text: str) -> QLabel:
    """Create a styled section heading label."""
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {C.ACCENT_TX}; padding-top: 6px;")
    return label


def _make_note(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 10px; color: {C.TEXT3};")
    label.setWordWrap(True)
    return label


# Settings Page


class SettingsPage(QWidget):
    """Application settings page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings(APP_ORG, APP_NAME)
        self._binder = None
        self._lut_binding = None
        self._lut_size = None
        self._build()

    def _build_output_row(self) -> QWidget:
        """Build the output-directory row the session owns.

        The field is not typed into and the button opens no dialog on its own.
        Both stand for one declared action, so what the field shows is the
        directory the session recorded and checked rather than a path this page
        remembered. Neither is offered until the binder has resolved the action.
        """
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self._output_field = QLineEdit(OUTPUT_UNSET)
        self._output_field.setReadOnly(True)
        self._output_field.setStyleSheet(_FIELD_STYLE)
        row.addWidget(self._output_field, stretch=1)

        self._output_browse = QPushButton("Browse")
        self._output_browse.setFixedHeight(32)
        self._output_browse.setFixedWidth(80)
        self._output_browse.setStyleSheet(_BROWSE_STYLE)
        self._output_browse.setEnabled(False)
        row.addWidget(self._output_browse)
        return container

    def bind_actions(
        self,
        binder,
        *,
        set_output_directory,
        set_lut_size,
        lut_size,
        unhandled,
        diagnostics,
    ) -> None:
        """Hand every control on this page to the action it stands for.

        The selector opens on the grid the session already holds, read before
        anything is bound, so the page never shows a size the session did not
        choose. The diagnostics section binds its own three controls, because
        the token a preview issues has to be held next to the button that spends
        it.
        """
        self._binder = binder
        self._set_output_directory = set_output_directory
        self._set_lut_size = set_lut_size
        self.render_lut_size(lut_size)
        self._lut_binding = binder.bind(
            "settings.lut_size",
            self._lut_combo,
            self._choose_lut_size,
            on_success=self.render_lut_size,
            hides=False,
            connect=False,
        )
        binder.bind("settings.hdr", self._hdr_cb, lambda: unhandled("settings.hdr"), hides=False)
        binder.bind(
            "settings.output_directory",
            self._output_browse,
            self._choose_output_directory,
            on_success=self.render_output_directory,
            hides=False,
        )
        self._diagnostics_section.bind_actions(binder, diagnostics)

    def _on_lut_size_changed(self) -> None:
        """Ask the session for the grid the operator's edit names.

        The selector is put back afterwards. A refusal would otherwise leave it
        showing a grid the session does not hold, and a success has already
        moved it, which makes the restore a redraw of what the session reported.
        """
        binder, binding = self._binder, self._lut_binding
        if binder is not None and binding is not None:
            binder.invoke(binding)
        self.render_lut_size(self._lut_size)

    def _choose_lut_size(self):
        """Offer the session the grid the selector now shows."""
        return self._set_lut_size(int(self._lut_combo.currentText()))

    def render_lut_size(self, size) -> None:
        """Move the selector onto the grid the session holds.

        The signal is blocked while it moves. Without that, redrawing this page
        would re-offer the size through the binding, and the session would
        answer a choice nobody made.
        """
        self._lut_size = size
        combo = self._lut_combo
        blocked = combo.blockSignals(True)
        try:
            index = combo.findText(str(size))
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(blocked)

    def _choose_output_directory(self):
        """Ask for a directory, then let the session decide about it.

        Closing the dialog reports nothing, so a withdrawn choice never reaches
        the journal and never changes what the field says.
        """
        start = self._settings.value("paths/output_dir", "") or DEFAULT_OUTPUT_DIR
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory", start)
        if not directory:
            return None
        return self._set_output_directory(directory)

    def render_output_directory(self, chosen) -> None:
        """Show the directory as the session recorded it, valid or not.

        A rejected directory is still displayed. Clearing the field would hide
        which path was turned down, and the operator would be left with a
        refusal naming a folder they could no longer see.
        """
        self._output_field.setText(chosen.directory)
        if not chosen.valid:
            self._output_note.setText(OUTPUT_REJECTED)
            return
        self._output_note.setText(OUTPUT_NOTE)
        self._settings.setValue("paths/output_dir", chosen.directory)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(20)

        # --- Page heading ---
        layout.addWidget(Heading("Settings"))

        # Calibration section
        layout.addWidget(_make_section_heading("Calibration"))

        cal_card, cal_layout = Card.with_layout(spacing=14)

        form_cal = QFormLayout()
        form_cal.setSpacing(14)
        form_cal.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_cal.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # LUT size
        lut_label = QLabel("LUT size")
        lut_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT};")
        self._lut_combo = QComboBox()
        self._lut_combo.addItems([str(size) for size in LUT_SIZES])
        self._lut_combo.setEnabled(False)
        self._lut_combo.currentTextChanged.connect(lambda _text: self._on_lut_size_changed())
        form_cal.addRow(lut_label, self._lut_combo)
        form_cal.addRow("", _make_note(LUT_NOTE))

        # HDR mode
        self._hdr_cb = QCheckBox("HDR mode")
        self._hdr_cb.setEnabled(False)
        form_cal.addRow("", self._hdr_cb)
        form_cal.addRow("", _make_note(HDR_NOTE))

        cal_layout.addLayout(form_cal)
        layout.addWidget(cal_card)

        # Paths section
        layout.addWidget(_make_section_heading("Paths"))

        paths_card, paths_layout = Card.with_layout(spacing=14)

        form_paths = QFormLayout()
        form_paths.setSpacing(14)
        form_paths.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_paths.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # Output directory
        out_label = QLabel("Output directory")
        out_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT};")
        form_paths.addRow(out_label, self._build_output_row())
        self._output_note = _make_note(OUTPUT_UNSET_NOTE)
        form_paths.addRow("", self._output_note)

        paths_layout.addLayout(form_paths)
        layout.addWidget(paths_card)

        # Diagnostics section
        layout.addWidget(_make_section_heading("Diagnostics"))

        diagnostics_card, diagnostics_layout = Card.with_layout(spacing=10)
        self._diagnostics_section = DiagnosticsSection()
        diagnostics_layout.addWidget(self._diagnostics_section)
        layout.addWidget(diagnostics_card)

        # About section
        layout.addWidget(_make_section_heading("About"))

        about_card, about_layout = Card.with_layout(spacing=10)

        version_label = QLabel(f"{APP_NAME}  v{APP_VERSION}")
        version_label.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {C.TEXT};")
        about_layout.addWidget(version_label)

        subtitle = QLabel("Professional display calibration for Windows")
        subtitle.setStyleSheet(f"font-size: 12px; color: {C.ACCENT_TX}; font-style: italic;")
        about_layout.addWidget(subtitle)

        # Separator
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {C.BORDER};")
        about_layout.addWidget(sep)

        details = [
            ("Color Science", "Oklab, JzAzBz, CAM16-UCS, PQ/HLG, ACES"),
            ("Gamut Mapping", "Oklab perceptual (SDR), JzCzhz (HDR)"),
            ("Native Sensor", "i1Display3 family via USB HID"),
            ("Spectral Correction", "CCMX for QD-OLED / WOLED"),
            ("Panel Database", "58 characterized displays"),
        ]
        for label, value in details:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(label)
            lbl.setStyleSheet(f"font-size: 11px; color: {C.TEXT3}; min-width: 120px;")
            row.addWidget(lbl)
            val = QLabel(value)
            val.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
            row.addWidget(val, stretch=1)
            about_layout.addLayout(row)

        # Separator
        sep2 = QFrame()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(f"background: {C.BORDER};")
        about_layout.addWidget(sep2)

        author_label = QLabel("Zain Dana Harper")
        author_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT};")
        about_layout.addWidget(author_label)

        copyright_label = QLabel("Copyright 2022-2026 Build Universe. All rights reserved.")
        copyright_label.setStyleSheet(f"font-size: 10px; color: {C.TEXT3};")
        about_layout.addWidget(copyright_label)

        layout.addWidget(about_card)

        # Bottom spacer
        layout.addStretch()
        scroll.setWidget(content)
