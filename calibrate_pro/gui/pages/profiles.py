"""The bundles this application published, listed from what it actually wrote.

The page this replaces globbed ``~/Documents/Calibrate Pro/Calibrations`` for
``.cube`` and ``.icc`` files, a folder no part of this application writes to,
and described whatever it found using figures nobody had recorded. Its buttons
copied, renamed, and deleted files directly. No action stood behind any of them,
so a profile could be destroyed by a control the session had never been asked
about, and the page reported the deletion by removing its own card.

What is here now reads the export directory the session recorded, finds bundles
by the manifest each one carries, and hands every control to the action it
stands for.

Activate and delete reach the Windows colour profile store. Both are judged
against a reading of that store rather than against the bundle on disk, so the
page carries a control that takes one and a line saying what it found. Rename
and generate remain bound to actions this build has no handler for, and each of
those buttons carries the manifest's reason instead of doing the work.

Nothing is read until an action reads it. The page opens saying so, and the
first listing is one the operator asked for.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.profiles import ProfileInspection, ProfileListing, ProfileRecord
from calibrate_pro.application.system_profile_session import ProfileOutcome
from calibrate_pro.application.system_profiles import SystemProfileReading
from calibrate_pro.gui.action_binding import ActionBinder, Operation, SurfaceBinding
from calibrate_pro.gui.app import C, Heading
from calibrate_pro.gui.pages.profile_detail import ProfileDetail, action_button, note_style

#: Drawn before the listing action has run, because nothing has been read yet.
NOT_READ = "No profile listing has been read in this session."

#: When the session holds no export directory, so there is nowhere to look. This
#: is a different answer from an empty folder and is worded as one.
NOWHERE_TO_LOOK = "No export directory is set in this session, so there is nowhere to read profiles from."

#: When a directory was named and there was nothing at that path to read. A
#: folder that has been moved or deleted since the export is not an empty one.
NOT_THERE = "Nothing is at {directory}, so no profiles were read."

#: When a directory was read and held no bundle this build can describe.
NONE_FOUND = "No published bundle under {directory}."

#: When a directory was read and held some.
FOUND = "{count} published bundle(s) under {directory}."

#: Above the directories whose manifest this build could not read.
UNREADABLE = "Holds a manifest this build cannot read:"

#: The mutations the manifest still holds closed, each bound so its button
#: explains itself with the resolver's own sentence.
CLOSED_MUTATIONS = ("profile.rename",)

#: Drawn before the system profile store has been read in this session. The
#: page says what it does not know rather than showing an empty list, which
#: would read as a machine holding no profiles.
STORE_NOT_READ = "The Windows colour profile store has not been read in this session."


def _item_text(record: ProfileRecord) -> str:
    """Label one row with what its manifest recorded, and nothing else."""
    return f"{record.name}\n{record.panel_name} · {record.target.preset_id} · {record.evidence_kind}"


def _where_text(listing: ProfileListing) -> str:
    if not listing.searched:
        return NOWHERE_TO_LOOK
    if not listing.existed:
        return NOT_THERE.format(directory=listing.directory)
    if not listing.profiles:
        return NONE_FOUND.format(directory=listing.directory)
    return FOUND.format(count=len(listing.profiles), directory=listing.directory)


def _unreadable_text(listing: ProfileListing) -> str:
    """Name every directory that held a manifest and could not be read.

    A bundle that has become unreadable is something an operator needs to see,
    so it stays in view with its reason attached instead of being dropped from
    the listing and appearing to have never existed.
    """
    if not listing.unreadable:
        return ""
    lines = [f"  {entry.directory}: {entry.reason}" for entry in listing.unreadable]
    return "\n".join([UNREADABLE, *lines])


class ProfilesPage(QWidget):
    """List published bundles, check one, and copy it where it is asked for."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._binder: ActionBinder | None = None
        self._inspect_binding: SurfaceBinding | None = None
        self._inspect_profile: Callable[[str], ActionOutcome[Any]] | None = None
        self._export_profile: Callable[[str], ActionOutcome[Any]] | None = None
        #: Where the last listing looked, offered as the copy dialog's start.
        self._directory: str | None = None
        #: The record the detail pane is drawing, held so a redrawn list can
        #: tell a surviving selection from one that has changed underneath it.
        self._selected: ProfileRecord | None = None
        self._build()

    def bind_actions(
        self,
        binder: ActionBinder,
        *,
        refresh: Operation,
        inspect_profile: Callable[[str], ActionOutcome[Any]],
        export_profile: Callable[[str], ActionOutcome[Any]],
        read_system: Operation,
        activate_profile: Operation,
        delete_profile: Operation,
        unhandled: Callable[[str], ActionOutcome[Any]],
    ) -> None:
        """Hand every control here to the action it stands for.

        The list is bound without a connection. Qt would trigger it on a click,
        which would leave a row reachable by the keyboard and not by the action,
        so the selection signal drives the invocation instead and both routes
        arrive at the same place.

        Copy is the one write this page performs against the filesystem, and it
        is bound to the export action rather than to the no-handler path: the
        manifest enables it once a profile has been checked, and a control bound
        to a refusal would still look ready at that point.

        Activate and delete write to the colour profile store, and both render
        their result into the same line the reading is drawn on. The write has
        already read the store back, so that line is current, and an operator
        does not have to read again to see whether the profile took effect.
        """
        self._binder = binder
        self._inspect_profile = inspect_profile
        self._export_profile = export_profile
        binder.bind(
            "profile.list.refresh",
            self._refresh_button,
            refresh,
            on_success=self.render_listing,
            hides=False,
        )
        binder.bind(
            "profile.system.read",
            self._system_button,
            read_system,
            on_success=self.render_system_reading,
            hides=False,
        )
        binder.bind(
            "profile.activate",
            self._detail.activate_button,
            activate_profile,
            on_success=self._render_store_write,
            hides=False,
        )
        binder.bind(
            "profile.delete",
            self._detail.delete_button,
            delete_profile,
            on_success=self._render_store_write,
            hides=False,
        )
        binder.bind(
            "profile.generate_all",
            self._generate_button,
            partial(unhandled, "profile.generate_all"),
            hides=False,
        )
        self._inspect_binding = binder.bind(
            "profile.inspect",
            self._list,
            self._inspect_selected,
            on_success=self._render_inspection,
            hides=False,
            connect=False,
        )
        binder.bind(
            "profile.export",
            self._detail.export_button,
            self._copy_to_chosen_directory,
            on_success=self._detail.render_export,
            hides=False,
        )
        for action_id, button in zip(CLOSED_MUTATIONS, (self._detail.rename_button,), strict=True):
            binder.bind(action_id, button, partial(unhandled, action_id), hides=False)

    def render_system_reading(self, reading: SystemProfileReading) -> None:
        """Say what the store held for this display when it was read."""
        self._system.setText(reading.summary)

    def _render_store_write(self, outcome: ProfileOutcome) -> None:
        """Say what one write did, in the sentence the result writes itself."""
        self._system.setText(outcome.summary)

    def render_listing(self, listing: ProfileListing) -> None:
        """Redraw the list from one reading, keeping a selection that survived.

        Repopulating moves the current row, so the signal is blocked while it
        happens. Without that, a refresh would inspect whatever landed under the
        cursor and replace a selection the operator had made.

        A selection survives only when its record comes back unchanged. A bundle
        whose manifest has been rewritten is a different record, and the session
        drops it for the same reason, so the pane and the export gate close
        together instead of disagreeing.
        """
        self._directory = listing.directory
        self._where.setText(_where_text(listing))
        self._unreadable.setText(_unreadable_text(listing))
        blocked = self._list.blockSignals(True)
        try:
            self._list.clear()
            for record in listing.profiles:
                item = QListWidgetItem(_item_text(record))
                item.setData(Qt.ItemDataRole.UserRole, record.directory)
                self._list.addItem(item)
            self._restore_selection(listing)
        finally:
            self._list.blockSignals(blocked)

    def _restore_selection(self, listing: ProfileListing) -> None:
        for row, record in enumerate(listing.profiles):
            if record == self._selected:
                self._list.setCurrentRow(row)
                return
        self._selected = None
        self._detail.clear()

    def _render_inspection(self, inspection: ProfileInspection) -> None:
        self._selected = inspection.record
        self._detail.render_inspection(inspection)

    def _on_row_changed(self, _row: int) -> None:
        """Check whatever the operator moved to, by keyboard or by mouse."""
        binder = self._binder
        binding = self._inspect_binding
        if binder is not None and binding is not None:
            binder.invoke(binding)

    def _inspect_selected(self) -> ActionOutcome[Any] | None:
        """Check the bundle the list is on, if it is on one."""
        inspect = self._inspect_profile
        item = self._list.currentItem()
        if inspect is None or item is None:
            return None
        return inspect(item.data(Qt.ItemDataRole.UserRole))

    def _copy_to_chosen_directory(self) -> ActionOutcome[Any] | None:
        """Ask where the copy should go, then let the session decide about it.

        Closing the dialog reports nothing, so a withdrawn choice never reaches
        the journal and never changes what the pane says.
        """
        export = self._export_profile
        if export is None:
            return None
        directory = QFileDialog.getExistingDirectory(self, "Copy profile into", self._directory or "")
        if not directory:
            return None
        return export(directory)

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)
        layout.addLayout(self._header())

        self._where = QLabel(NOT_READ)
        self._where.setWordWrap(True)
        self._where.setStyleSheet(note_style(C.TEXT2))
        layout.addWidget(self._where)

        self._list = QListWidget()
        self._list.setMinimumHeight(220)
        self._list.setStyleSheet(
            f"QListWidget {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 12px; color: {C.TEXT}; font-size: 12px; padding: 6px; }}"
            f"QListWidget::item {{ padding: 8px; border-radius: 8px; }}"
            f"QListWidget::item:selected {{ background: {C.SURFACE2}; color: {C.TEXT}; }}"
        )
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        self._unreadable = QLabel("")
        self._unreadable.setWordWrap(True)
        self._unreadable.setStyleSheet(note_style(C.YELLOW, mono=True))
        layout.addWidget(self._unreadable)

        self._system = QLabel(STORE_NOT_READ)
        self._system.setWordWrap(True)
        self._system.setStyleSheet(note_style(C.TEXT2))
        layout.addWidget(self._system)

        self._detail = ProfileDetail()
        layout.addWidget(self._detail)
        layout.addStretch()
        scroll.setWidget(content)

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(Heading("Profiles"))
        row.addStretch()
        self._generate_button = action_button("Generate All", 140)
        self._system_button = action_button("Read System", 140)
        self._refresh_button = action_button("Refresh", 110, primary=True)
        row.addWidget(self._generate_button)
        row.addWidget(self._system_button)
        row.addWidget(self._refresh_button)
        return row


__all__ = [
    "FOUND",
    "NONE_FOUND",
    "NOT_READ",
    "NOT_THERE",
    "NOWHERE_TO_LOOK",
    "STORE_NOT_READ",
    "UNREADABLE",
    "ProfilesPage",
]
