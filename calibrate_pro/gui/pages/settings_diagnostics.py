"""The session journal, reachable from the page an operator already opens.

Every action a session runs is written to a redacted journal before it is
allowed to report success. Until now the window offered no way to reach any of
it, so those records were kept for a support story nobody could start. This
section is that story: it lists what a bundle would contain, publishes exactly
those bytes where the operator says, and opens the folder the journal is kept
in.

The listing is the contract. What appears here before the write is what the
bundle holds after it, one line per file with the digest of each, so an operator
sending a bundle knows what they sent.

The token a preview issues is held here and nowhere else. It is spent by the
attempt that follows rather than by that attempt succeeding, which is what stops
a refused publish from leaving a control enabled against a grant the manager has
already dropped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from calibrate_pro.gui.app import C
from calibrate_pro.gui.pages.profile_detail import action_button, note_style

if TYPE_CHECKING:
    from calibrate_pro.application.diagnostics import DiagnosticsActions
    from calibrate_pro.application.journal import BundlePreview, DiagnosticBundleReceipt
    from calibrate_pro.application.outcomes import ActionOutcome
    from calibrate_pro.gui.action_binding import ActionBinder

#: Drawn before a preview has been taken, because nothing has been read yet.
NOT_PREVIEWED = "No preview has been taken in this session."

#: Drawn when the session holds no bundle manager. The three actions still
#: resolve, because the manifest answers from policy rather than from wiring,
#: and each one refuses with its own sentence when it is used.
NO_JOURNAL = "This session was built without a journal, so there is nothing here to read."

#: Where the journal being listed is kept. Naming the folder is a plain read of
#: a configured path, so it is shown without an action having to run.
JOURNAL_FOLDER = "Journal folder: {folder}"

#: Under the buttons. Both sentences state a rule the manager enforces, so an
#: operator meets the rule before a refusal rather than only through one.
PUBLISH_NOTE = (
    "Publishing writes exactly the files listed above, to a path that does not exist yet. "
    "A preview goes stale once the session records another action, so take a fresh one if publishing is refused."
)

SAVE_TITLE = "Publish diagnostic bundle"
SAVE_FILTER = "Zip archive (*.zip)"

#: What the save dialog opens with in its name field. A name and no directory
#: leaves the dialog on whatever folder the platform last used, which is closer
#: to where an operator is working than any folder this page could name.
DEFAULT_BUNDLE_NAME = "calibrate-pro-diagnostics.zip"


def preview_text(preview: BundlePreview) -> str:
    """Name every file the bundle would carry, and the digest of each one."""
    lines = [f"{len(preview.members)} file(s), token valid until {preview.expires_utc}"]
    lines.extend(f"  {member.basename}  {member.byte_length} bytes  {member.sha256}" for member in preview.members)
    return "\n".join(lines)


def receipt_text(receipt: DiagnosticBundleReceipt) -> str:
    """Describe what landed on disk, by the digest of the bytes that landed."""
    readback = "verified" if receipt.readback_verified else "NOT VERIFIED"
    lines = [
        f"Published to {receipt.published_path}",
        f"  bundle      {receipt.bundle_sha256}",
        f"  byte length {receipt.byte_length}",
        f"  readback    {readback}",
    ]
    lines.extend(f"  member      {basename}  {digest}" for basename, digest in receipt.member_hashes)
    return "\n".join(lines)


class DiagnosticsSection(QWidget):
    """Preview the journal, publish it, and open the folder it is kept in."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._diagnostics: DiagnosticsActions | None = None
        #: The token the last preview handed back. The empty string is a token
        #: the manager refuses, so publishing without a preview is journalled as
        #: a refusal rather than dropped here in silence.
        self._token = ""
        self._build()

    def bind_actions(self, binder: ActionBinder, diagnostics: DiagnosticsActions) -> None:
        """Hand each of the three controls to the action it stands for.

        Nothing is read while binding. The folder line comes from the path the
        session was configured with, and the listing stays empty until an
        operator asks for one.
        """
        self._diagnostics = diagnostics
        folder = diagnostics.diagnostics_folder
        self._folder.setText(NO_JOURNAL if folder is None else JOURNAL_FOLDER.format(folder=folder))
        binder.bind(
            "diagnostics.bundle.preview",
            self._preview_button,
            diagnostics.preview_diagnostics,
            on_success=self.render_preview,
            hides=False,
        )
        binder.bind(
            "diagnostics.bundle.create",
            self._save_button,
            self._publish_bundle,
            on_success=self.render_receipt,
            hides=False,
        )
        binder.bind(
            "diagnostics.folder.open",
            self._open_button,
            diagnostics.open_diagnostics_folder,
            hides=False,
        )

    def render_preview(self, preview: BundlePreview) -> None:
        """Show the listing, and hold the token that publishes exactly it.

        Any receipt already drawn is cleared. It describes a bundle that is no
        longer the one the listing above now names, and leaving the two together
        would read as a receipt for the new listing.
        """
        self._token = preview.token
        self._listing.setText(preview_text(preview))
        self._receipt.setText("")

    def render_receipt(self, receipt: DiagnosticBundleReceipt) -> None:
        """Show the published bundle beside the listing it was published from."""
        self._receipt.setText(receipt_text(receipt))

    def _publish_bundle(self) -> ActionOutcome[Any] | None:
        """Ask where the bundle goes, then let the session decide about it.

        Closing the dialog reports nothing, so a withdrawn choice never reaches
        the journal. The dialog is told not to confirm an overwrite because the
        manager refuses a destination that already exists, and a prompt offering
        to replace a file would promise something nothing here can do.
        """
        diagnostics = self._diagnostics
        if diagnostics is None:
            return None
        destination, _selected = QFileDialog.getSaveFileName(
            self,
            SAVE_TITLE,
            DEFAULT_BUNDLE_NAME,
            SAVE_FILTER,
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not destination:
            return None
        token, self._token = self._token, ""
        return diagnostics.create_diagnostics_bundle(token, destination)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._folder = QLabel(NO_JOURNAL)
        self._folder.setWordWrap(True)
        self._folder.setStyleSheet(note_style(C.TEXT2))
        layout.addWidget(self._folder)

        self._listing = _readable_note(C.TEXT2)
        self._listing.setText(NOT_PREVIEWED)
        layout.addWidget(self._listing)

        self._receipt = _readable_note(C.GREEN)
        layout.addWidget(self._receipt)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._preview_button = action_button("Preview", 110)
        self._save_button = action_button("Save bundle", 130)
        self._open_button = action_button("Open folder", 130)
        for button in (self._preview_button, self._save_button, self._open_button):
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)

        note = QLabel(PUBLISH_NOTE)
        note.setWordWrap(True)
        note.setStyleSheet(note_style(C.TEXT3))
        layout.addWidget(note)


def _readable_note(color: str) -> QLabel:
    """A monospaced line the operator can select and copy.

    Digests are here to be sent on to somebody. A label nobody can select turns
    a sixty-four character hash into something to be retyped, which is where a
    transcription error would come from.
    """
    label = QLabel("")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setStyleSheet(note_style(color, mono=True))
    return label


__all__ = [
    "DEFAULT_BUNDLE_NAME",
    "JOURNAL_FOLDER",
    "NOT_PREVIEWED",
    "NO_JOURNAL",
    "PUBLISH_NOTE",
    "DiagnosticsSection",
    "preview_text",
    "receipt_text",
]
