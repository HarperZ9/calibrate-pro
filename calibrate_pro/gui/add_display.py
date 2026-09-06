"""Adding a panel profile, and what this build will do about one.

The dialog used to write. Creating a profile called into the panel database and
saved a file beside the ones the calibration engine reads; importing copied a
chosen JSON into that same directory and registered whatever it held. The
manifest declares both of those actions disabled pending their Phase 2
contracts, and the command line declines both by name, so this window was
performing work the rest of the build refuses.

Both write paths are gone. What remains reads. The display list is the
detection pass the session already ran rather than a second enumeration of its
own, and choosing a file reads it where it sits. The read itself is the
session's, not this dialog's: the parse lives in the application layer where it
is resolved and journalled, and what is here draws the answer. The two
committing controls stay on the dialog, bound and disabled, carrying the
resolver's own sentence, so an operator reads why this build will not write yet
instead of finding a button that quietly does nothing.

The tab this replaces was titled "Auto-detect from EDID" and promised
chromaticity read from each display's own EDID block. Qt exposes no EDID bytes,
so the tab's own scan left that field empty on every display, its Create button
could never enable, and its info line offered a generic profile it had no way to
build. What the session holds is a matched panel characterization, which
describes a product rather than the unit on the desk, and the tab now says that.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from calibrate_pro.qt_runtime import configure_qt_api

configure_qt_api()

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.application.contracts import (
    CharacterizationKind,
    DisplayObservation,
    PanelCharacterization,
)
from calibrate_pro.application.outcomes import ActionError, ActionOutcome
from calibrate_pro.application.panel_profiles import NOT_STATED, PanelProfilePreview
from calibrate_pro.application.results import DetectionSummary
from calibrate_pro.application.surface import SurfaceActions
from calibrate_pro.gui.action_binding import ActionBinder, Restriction, refusal_message
from calibrate_pro.gui.theme import C, primary_button_style, secondary_button_style

#: What the observed tab says before a detection pass has answered.
NOTHING_OBSERVED = "No detection pass has run in this session."

#: What the card says when the session declined to answer for a display. The
#: previous display's numbers are cleared rather than left in place, because a
#: card that keeps them describes something other than the selected row.
SELECTION_UNANSWERED = "The session did not answer for this display."

OBSERVED_NOTE = (
    "These are the displays the last detection pass observed, each with the panel "
    "characterization it matched. A match describes a product. It is not a reading "
    "of the unit in front of you."
)

IMPORT_NOTE = (
    "A panel profile carries chromaticity, gamma, and capability data. Choosing a "
    "file reads it where it sits and shows what it holds. Nothing is copied."
)

NO_FILE_CHOSEN = "No file chosen"

#: What a file holding nothing this build recognises as a panel says. It is
#: distinct from a refusal: the file was read, and what it held was no panel.
NOTHING_IN_FILE = "This file holds no panel profile."

#: How many panels a multi-panel file lists before the rest are counted. The
#: remainder is stated rather than dropped, so a long file is never shown as a
#: list that looks complete and is not.
PREVIEW_LIMIT = 5

#: How each characterization kind is described. The three are worded apart
#: because they support different claims: a matched product, a fallback the
#: session was told to use, and an explicit absence of colorimetric data.
_SOURCE_SENTENCES = {
    CharacterizationKind.MATCHED: "Matched panel characterization.",
    CharacterizationKind.EXPLICIT_GENERIC: "Generic characterization, chosen for this display.",
    CharacterizationKind.UNKNOWN: "No panel matched, so nothing colorimetric is claimed here.",
    CharacterizationKind.MEASURED: "Measured on this display by an instrument in this session.",
}

_DIALOG_STYLE = (
    f"QDialog {{ background: {C.BG}; }}"
    f"QTabWidget::pane {{ border: 1px solid {C.BORDER}; border-radius: 10px; "
    f"  background: {C.SURFACE}; padding: 12px; }}"
    f"QTabBar::tab {{ background: {C.SURFACE2}; border: 1px solid {C.BORDER}; "
    f"  border-top-left-radius: 8px; border-top-right-radius: 8px; "
    f"  padding: 8px 20px; margin-right: 2px; font-size: 12px; color: {C.TEXT}; }}"
    f"QTabBar::tab:selected {{ background: {C.SURFACE}; border-bottom-color: {C.SURFACE}; "
    f"  font-weight: 600; color: {C.ACCENT_TX}; }}"
    f"QTabBar::tab:hover {{ background: {C.SURFACE}; }}"
    f"QLabel {{ color: {C.TEXT}; }}"
    f"QComboBox {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
    f"  border-radius: 8px; padding: 6px 12px; font-size: 12px; }}"
    f"QComboBox:hover {{ border-color: {C.ACCENT}; }}"
    f"QComboBox::drop-down {{ border: none; width: 24px; }}"
    f"QComboBox:disabled {{ color: {C.TEXT3}; }}"
)

_CARD_STYLE = (
    f"QFrame {{ background: {C.SURFACE2}; border: 1px solid {C.BORDER}; border-radius: 10px; padding: 12px; }}"
)

_BOXED_STYLE = (
    f"font-size: 11px; padding: 8px; background: {C.SURFACE2}; border: 1px solid {C.BORDER}; border-radius: 8px;"
)


def display_entry(observation: DisplayObservation) -> str:
    """Name one observed display the way the dashboard card names it."""
    return f"{observation.safe_label}  ({observation.width_px}x{observation.height_px})"


def source_sentence(characterization: PanelCharacterization) -> str:
    """Say where a characterization came from, in its own recorded terms."""
    return f"{_SOURCE_SENTENCES[characterization.kind]}\nProvenance: {characterization.provenance}"


def primaries_text(characterization: PanelCharacterization) -> str:
    """Print the primaries exactly as the characterization records them.

    The strings are shown unchanged rather than reformatted to a fixed number of
    places. Rounding them here would print a number that appears to have been
    measured to that precision by something in this process.
    """
    red, green, blue = characterization.red_xy, characterization.green_xy, characterization.blue_xy
    white, gamma = characterization.white_xy, characterization.nominal_gamma
    if red is None or green is None or blue is None or white is None or gamma is None:
        return ""
    return (
        f"R({red[0]}, {red[1]})  G({green[0]}, {green[1]})  B({blue[0]}, {blue[1]})\n"
        f"White({white[0]}, {white[1]})   Gamma {gamma}"
    )


def preview_text(preview: PanelProfilePreview) -> str:
    """Print what one chosen file stated about the panels it describes.

    A file describing one panel is shown field by field, and a file describing
    several is shown as a list of what they call themselves. The branch is on
    how many panels were stated rather than on how the JSON was shaped, so a
    one-entry list and a bare object read the same way to an operator who
    cannot see which shape the file used.
    """
    if not preview.entries:
        return NOTHING_IN_FILE
    if len(preview.entries) == 1:
        entry = preview.entries[0]
        return (
            f"Manufacturer: {entry.manufacturer or NOT_STATED}\n"
            f"Display: {entry.stated_name}\n"
            f"Panel type: {entry.panel_type or NOT_STATED}"
        )
    lines = [f"{len(preview.entries)} panel profile(s):"]
    lines += [f"  - {entry.stated_name}" for entry in preview.entries[:PREVIEW_LIMIT]]
    if len(preview.entries) > PREVIEW_LIMIT:
        lines.append(f"  ... and {len(preview.entries) - PREVIEW_LIMIT} more")
    return "\n".join(lines)


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
    label.setWordWrap(True)
    return label


class AddDisplayDialog(QDialog):
    """Two ways to add a panel profile, both waiting on a Phase 2 contract.

    The dialog holds its own binder rather than borrowing the window's. The
    window's lives as long as the process and refreshes every control it holds
    after each action, so a control registered from here would still be in that
    list once this dialog was destroyed.
    """

    def __init__(
        self,
        service: SurfaceActions,
        *,
        inspect_profile: Callable[[Path], ActionOutcome[PanelProfilePreview]],
        observed: DetectionSummary | None = None,
        restrict: Restriction | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        #: The session's own read of a chosen file. It is handed in rather than
        #: reached for through ``service``, because the interface actions this
        #: dialog shares with every other surface and the reading of a panel
        #: profile are different parts of the session, and only one of them is
        #: what a dialog is entitled to assume it was given.
        self._inspect_profile = inspect_profile
        self._displays: tuple[DisplayObservation, ...] = (
            tuple(observed.dashboard.displays) if observed is not None else ()
        )
        self._binder = ActionBinder(service, report=self.show_message, restrict=restrict)
        self.setWindowTitle("Add Display Profile")
        self.setMinimumSize(520, 460)
        self.setStyleSheet(_DIALOG_STYLE)
        self._build()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        heading = QLabel("Add Display Profile")
        heading.setStyleSheet(f"font-size: 18px; font-weight: 500; color: {C.TEXT};")
        layout.addWidget(heading)

        tabs = QTabWidget()
        tabs.addTab(self._build_observed_tab(), "From a detected display")
        tabs.addTab(self._build_import_tab(), "Import from file")
        layout.addWidget(tabs)

        self._message = QLabel("")
        self._message.setStyleSheet(f"font-size: 11px; color: {C.YELLOW};")
        self._message.setWordWrap(True)
        self._message.hide()
        layout.addWidget(self._message)

    def _build_observed_tab(self) -> QWidget:
        tab = QWidget()
        vbox = QVBoxLayout(tab)
        vbox.setContentsMargins(8, 12, 8, 8)
        vbox.setSpacing(12)
        vbox.addWidget(_note(OBSERVED_NOTE))

        self._display_combo = QComboBox()
        self._display_combo.setFixedHeight(34)
        for observation in self._displays:
            self._display_combo.addItem(display_entry(observation))
        vbox.addWidget(self._display_combo)

        card = QFrame()
        card.setStyleSheet(_CARD_STYLE)
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(6)
        self._source_label = QLabel("")
        self._source_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
        self._source_label.setWordWrap(True)
        card_layout.addWidget(self._source_label)
        self._primaries_label = QLabel("")
        self._primaries_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT}; font-family: 'Consolas', monospace;")
        self._primaries_label.setWordWrap(True)
        card_layout.addWidget(self._primaries_label)
        vbox.addWidget(card)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch()
        self._create_btn = QPushButton("Create Profile")
        self._create_btn.setFixedHeight(34)
        self._create_btn.setStyleSheet(primary_button_style(padding="6px 22px"))
        row.addWidget(self._create_btn)
        vbox.addLayout(row)
        vbox.addStretch()

        # Drawn before anything is bound, so opening the dialog on the first row
        # shows that row without asking the session about a choice nobody made.
        self.render_selection()
        self._display_binding = self._binder.bind(
            "panel_profile.edid.select_display",
            self._display_combo,
            self._select_display,
            on_refusal=self._selection_refused,
            hides=False,
            connect=False,
        )
        self._display_combo.currentIndexChanged.connect(lambda _index: self._on_display_changed())
        self._binder.bind(
            "panel_profile.edid.create",
            self._create_btn,
            lambda: self.service.unhandled("panel_profile.edid.create"),
            hides=False,
        )
        return tab

    def _build_import_tab(self) -> QWidget:
        tab = QWidget()
        vbox = QVBoxLayout(tab)
        vbox.setContentsMargins(8, 12, 8, 8)
        vbox.setSpacing(12)
        vbox.addWidget(_note(IMPORT_NOTE))

        self._path_label = QLabel(NO_FILE_CHOSEN)
        self._path_label.setStyleSheet(f"{_BOXED_STYLE} color: {C.TEXT3};")
        self._path_label.setWordWrap(True)
        vbox.addWidget(self._path_label)

        self._preview_label = QLabel("")
        self._preview_label.setStyleSheet(f"{_BOXED_STYLE} color: {C.TEXT}; font-family: 'Consolas', monospace;")
        self._preview_label.setWordWrap(True)
        self._preview_label.setMinimumHeight(80)
        vbox.addWidget(self._preview_label)

        row = QHBoxLayout()
        row.setSpacing(10)
        self._browse_btn = QPushButton("Browse...")
        self._browse_btn.setFixedHeight(34)
        self._browse_btn.setStyleSheet(secondary_button_style(padding="6px 18px"))
        row.addWidget(self._browse_btn)
        row.addStretch()
        self._import_btn = QPushButton("Import Profile")
        self._import_btn.setFixedHeight(34)
        self._import_btn.setStyleSheet(primary_button_style(padding="6px 22px"))
        row.addWidget(self._import_btn)
        vbox.addLayout(row)
        vbox.addStretch()

        self._binder.bind(
            "panel_profile.import.choose",
            self._browse_btn,
            self._choose_import_file,
            on_success=self._show_preview,
            on_refusal=self._import_refused,
            hides=False,
        )
        self._binder.bind(
            "panel_profile.import",
            self._import_btn,
            lambda: self.service.unhandled("panel_profile.import"),
            hides=False,
        )
        return tab

    # -- the observed display -----------------------------------------------

    def _on_display_changed(self) -> None:
        """Ask the session about the display the operator moved to."""
        self._binder.invoke(self._display_binding)

    def _select_display(self) -> ActionOutcome[None]:
        """Show what the session observed about the display now selected."""
        return self.service.perform_ui("panel_profile.edid.select_display", self.render_selection)

    def render_selection(self) -> None:
        """Describe the selected display using the pass that observed it."""
        index = self._display_combo.currentIndex()
        if not self._displays or index < 0:
            self._source_label.setText(NOTHING_OBSERVED)
            self._primaries_label.setText("")
            return
        characterization = self._displays[index].characterization
        self._source_label.setText(source_sentence(characterization))
        self._primaries_label.setText(primaries_text(characterization))

    def _selection_refused(self, error: ActionError) -> None:
        """Clear the card rather than leave it describing a different display."""
        self._source_label.setText(SELECTION_UNANSWERED)
        self._primaries_label.setText("")
        self.show_message(refusal_message(error), "warning")

    # -- the chosen file ----------------------------------------------------

    def _choose_import_file(self) -> ActionOutcome[PanelProfilePreview] | None:
        """Offer a chooser and hand what the operator picked to the session.

        Closing the chooser reports nothing, so a withdrawn choice never reaches
        the journal. Nothing here reads the file. The session does, which is
        what makes the read an action rather than something a dialog did on its
        own, and copying it into the panel profiles directory is the disabled
        action next to this one.
        """
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, "Select Panel Profile", "", "JSON Panel Profiles (*.json);;All Files (*)"
        )
        if not path:
            return None
        return self._inspect_profile(Path(path))

    def _show_preview(self, preview: PanelProfilePreview) -> None:
        """Name the file the session read and print what it stated."""
        self._path_label.setText(preview.path)
        self._path_label.setStyleSheet(f"{_BOXED_STYLE} color: {C.TEXT};")
        self._preview_label.setText(preview_text(preview))

    def _import_refused(self, error: ActionError) -> None:
        """Put the field back, so it never names a file that was turned down."""
        self._path_label.setText(NO_FILE_CHOSEN)
        self._path_label.setStyleSheet(f"{_BOXED_STYLE} color: {C.TEXT3};")
        self._preview_label.setText("")
        self.show_message(refusal_message(error), "warning")

    # -- reporting ----------------------------------------------------------

    def show_message(self, message: str, level: str = "info") -> None:
        """Report inside the dialog, where the operator is looking.

        The window's toasts appear in its own corner, which this dialog covers.
        A refusal shown there would be a refusal the operator never reads.
        """
        del level
        self._message.setText(message)
        self._message.setVisible(bool(message))


__all__ = [
    "IMPORT_NOTE",
    "NOTHING_IN_FILE",
    "NOTHING_OBSERVED",
    "NO_FILE_CHOSEN",
    "OBSERVED_NOTE",
    "PREVIEW_LIMIT",
    "SELECTION_UNANSWERED",
    "AddDisplayDialog",
    "display_entry",
    "preview_text",
    "primaries_text",
    "source_sentence",
]
