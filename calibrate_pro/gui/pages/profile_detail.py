"""One published bundle, described by the manifest that was written with it.

The pane this replaces stated a white point of D65, a gamma of 2.2, and a gamut
taken from a substring of the filename. Nothing recorded any of those. Every
figure here is read out of the bundle's own manifest, so the pane shows what the
generator wrote at publish time, and shows nothing at all before an inspection
has produced something to show.

The seal line is written in the past tense because that is what it reports: the
answer from the check that ran when the profile was selected. Files can change
after a check, so the copy path re-hashes each one as it reads it and refuses a
bundle that has moved, rather than trusting what this pane last drew.

The button factory lives here because the panes on this page share it, and one
description of what an action button looks like is easier to keep honest than
two.
"""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from calibrate_pro.application.assets import ExportBundle
from calibrate_pro.application.profiles import AssetCheck, ProfileInspection, ProfileRecord
from calibrate_pro.gui.app import C, Card, Heading

#: Drawn in place of a name before any profile has been inspected.
NO_SELECTION = "No profile has been inspected in this session."

#: The two seal verdicts. Both say when the check ran, because both are answers
#: about a moment that has passed rather than claims about the files right now.
SEALED = "Checked on selection: every file the manifest names was present and matched its digest."
BROKEN = "Checked on selection: {count} of {total} files did not match the digests the manifest records."


def action_button(text: str, width: int, *, primary: bool = False) -> QPushButton:
    """Build one action button, disabled until the binder renders it.

    Every button here waits for the resolver. Starting enabled would offer an
    action for the moment between construction and the first render, which is
    long enough for a click.
    """
    button = QPushButton(text)
    button.setProperty("primary", primary)
    button.setFixedHeight(36)
    button.setFixedWidth(width)
    background = C.GREEN if primary else C.SURFACE
    border = C.GREEN_HI if primary else C.BORDER
    hover = f"background: {C.GREEN_HI};" if primary else f"border-color: {C.ACCENT}; background: {C.SURFACE2};"
    button.setStyleSheet(f"""
        QPushButton {{
            background: {background};
            border: 1px solid {border};
            border-radius: 8px;
            color: {C.TEXT};
            font-size: 13px;
            font-weight: {"600" if primary else "500"};
        }}
        QPushButton:hover {{ {hover} }}
        QPushButton:disabled {{
            background: {C.SURFACE2};
            border-color: {C.BORDER};
            color: {C.TEXT3};
        }}
    """)
    button.setEnabled(False)
    return button


def note_style(color: str, *, mono: bool = False) -> str:
    family = "font-family: Consolas, 'Courier New', monospace; " if mono else ""
    return f"{family}font-size: 11px; color: {color};"


def _note(color: str, *, mono: bool = False) -> QLabel:
    label = QLabel("")
    label.setWordWrap(True)
    label.setStyleSheet(note_style(color, mono=mono))
    return label


def _field(text: str, color: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"font-size: 12px; color: {color};")
    return label


def _fields(record: ProfileRecord) -> tuple[tuple[str, str], ...]:
    """Name every figure this pane shows, and where each one was read from."""
    target = record.target
    return (
        ("Display", record.display_id),
        ("Panel", f"{record.panel_name} ({record.panel_key})"),
        ("Target preset", target.preset_id),
        ("Gamut mode", target.gamut_mode),
        ("White point", target.white_point),
        ("Tone response", target.tone_response),
        ("Applied gamma", f"{target.applied_gamma_exponent:g}"),
        ("LUT size", f"{record.lut_size}³"),
        ("Characterization", record.characterization_kind),
        ("Evidence", record.evidence_kind),
        ("Files", f"{len(record.assets)} totalling {record.byte_count} bytes"),
        ("Directory", record.directory),
        ("Manifest digest", record.manifest_sha256),
    )


def _check_line(check: AssetCheck) -> str:
    """Report one file's re-hash, saying which of the three answers it gave."""
    if check.matched:
        return f"  matched   {check.filename}  {check.expected_sha256[:16]}"
    if not check.present:
        return f"  missing   {check.filename}"
    actual = check.actual_sha256 or ""
    return f"  changed   {check.filename}  recorded {check.expected_sha256[:16]}, read {actual[:16]}"


class ProfileDetail(Card):
    """What one published bundle records, and how its files checked out."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self._name = Heading(NO_SELECTION, level=2)
        self._name.setWordWrap(True)
        layout.addWidget(self._name)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(18)
        self._grid.setVerticalSpacing(5)
        self._grid.setColumnStretch(1, 1)
        layout.addLayout(self._grid)
        self._seal = _note(C.TEXT2)
        layout.addWidget(self._seal)
        self._checks = _note(C.TEXT3, mono=True)
        layout.addWidget(self._checks)
        layout.addLayout(self._button_row())
        self._copied = _note(C.TEXT2)
        layout.addWidget(self._copied)

    def _button_row(self) -> QHBoxLayout:
        """Lay out the four controls, one per action this pane offers.

        Copy is the only one this build performs. The other three are bound to
        actions it has no handler for, so each carries the manifest's reason for
        holding profile mutation closed instead of doing the work unasked.
        """
        row = QHBoxLayout()
        row.setSpacing(10)
        self.export_button = action_button("Copy to folder", 150, primary=True)
        self.activate_button = action_button("Activate", 110)
        self.rename_button = action_button("Rename", 110)
        self.delete_button = action_button("Delete", 110)
        for button in (self.export_button, self.activate_button, self.rename_button, self.delete_button):
            row.addWidget(button)
        row.addStretch()
        return row

    def render_inspection(self, inspection: ProfileInspection) -> None:
        """Draw one bundle's manifest and the answer its files just gave."""
        record = inspection.record
        self._name.setText(record.name)
        self._draw_fields(_fields(record))
        broken = inspection.broken
        if broken:
            self._seal.setText(BROKEN.format(count=len(broken), total=len(inspection.checks)))
            self._seal.setStyleSheet(note_style(C.RED))
        else:
            self._seal.setText(SEALED)
            self._seal.setStyleSheet(note_style(C.GREEN_HI))
        self._checks.setText("\n".join(_check_line(check) for check in inspection.checks))
        self._copied.setText("")

    def render_export(self, bundle: ExportBundle) -> None:
        """Name what the copy wrote, taken from the manifest sealing it."""
        self._copied.setText(
            f"Copied {len(bundle.assets)} file(s) to {bundle.directory}, sealed by {bundle.manifest_filename}."
        )

    def clear(self) -> None:
        """Go back to showing nothing, for when the selection is gone.

        Leaving the last drawing in place would describe a bundle this session
        no longer holds, and the copy button beside it would be disabled with a
        reason that read as though it were about the profile on screen.
        """
        self._name.setText(NO_SELECTION)
        self._draw_fields(())
        self._seal.setText("")
        self._seal.setStyleSheet(note_style(C.TEXT2))
        self._checks.setText("")
        self._copied.setText("")

    def _draw_fields(self, fields: tuple[tuple[str, str], ...]) -> None:
        """Replace the figures with a new set, or with none.

        The labels are rebuilt and the buttons are not. Nothing in this grid is
        bound to an action, so destroying it leaves every binding pointing at a
        control that still exists.
        """
        grid = self._grid
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for row, (name, value) in enumerate(fields):
            grid.addWidget(_field(name, C.TEXT3), row, 0)
            grid.addWidget(_field(value, C.TEXT2), row, 1)


__all__ = ["BROKEN", "NO_SELECTION", "SEALED", "ProfileDetail", "action_button", "note_style"]
