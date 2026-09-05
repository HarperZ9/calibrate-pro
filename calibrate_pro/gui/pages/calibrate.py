"""The calibration workflow, drawn from what the session answered.

The page reads no display, opens no sensor, runs no thread of its own and
writes no file. Each of those was here. It enumerated screens on a timer 300ms
after it was built, opened an i1Display3 over raw HID with a vendor unlock key,
drove a seventeen step patch measurement behind a fullscreen window, built a
33-cube correction LUT and wrote it under the operator's Documents folder,
outside the session's journal and outside its export directory.

It reached that state by asking the USB bus what was attached. Finding a
colorimeter enabled the measured and hybrid cards and selected measured, while
the manifest held both actions disabled pending a qualified measurement
contract. The page was the only one in the shipped stack with no resolver in
front of it, so it was the only surface that could disagree with the manifest,
and the way it disagreed was by acting.

Every control here is now bound to the action it stands for. A card that is
closed says why in the manifest's words, and the reason arrives from the same
resolver a terminal quotes. The target fields select among the targets this
build has rather than composing one it does not: the session's target vocabulary
is the preset table, so editing a field picks the preset carrying that value.

A custom correlated colour temperature had a slider and no target behind it. No
preset in this build names one, so the control is gone rather than disabled,
because a slider that moves is a claim that something reads it.

Choosing a display drops the method, the target and the seal. Choosing a method
drops the target and the seal, and choosing a target drops the seal. The page
clears what each of those invalidated at the moment it happens, so a figure on
screen is never one the session stopped holding.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.application.actions import PRESET_TARGETS
from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.results import (
    DetectionSummary,
    DisplaySelection,
    GenerationResult,
    MethodSelection,
    PlanPreview,
    TargetSelection,
)
from calibrate_pro.gui.action_binding import ActionBinder, Operation, SurfaceBinding
from calibrate_pro.gui.app import C, Card, Heading, Stat

#: Offered in the selector when the last detection pass observed no display.
NO_DISPLAY_ITEM = "No display in this session"

#: The preset this build declares and does not perform. It is listed with the
#: rest so an operator sees the whole target vocabulary and reads, on the one
#: that is closed, the manifest's own sentence about why.
HDR_PRESET_ACTION = "calibration.preset.hdr10"

#: What each preset is called on its button. The action layer owns which
#: targets exist and what they resolve to; this owns what they are called. The
#: two are held level by a gate rather than by one importing a label from the
#: other, so a preset added to the table without a name here is a test failure
#: instead of a button reading 'calibration.preset.rec2020'.
PRESET_LABELS = {
    "calibration.preset.srgb_web": "sRGB Web",
    "calibration.preset.rec709": "Rec.709",
    "calibration.preset.dci_p3": "DCI-P3",
    "calibration.preset.photography": "Photography",
    HDR_PRESET_ACTION: "HDR10",
}

#: Which position of a preset's target tuple each selector edits.
GAMUT, WHITE_POINT, TONE_RESPONSE = 0, 1, 2

#: What a target selector shows while the session holds no target. Without it
#: the three selectors sit on the first value of each list, which reads as a
#: target the session was never asked for and never generated against.
UNSET_TARGET_ITEM = "Not selected"

#: Under the workflow before an action has produced anything.
NOT_GENERATED_NOTE = "No calibration bundle has been generated in this session."

#: What the page says about the target until the session holds one.
NO_TARGET_NOTE = "No target selected in this session."

#: What the page says about the method until the session holds one.
NO_METHOD_NOTE = "No profiling method selected in this session."

#: Beside the generated bundle. Generation seals files and changes no display.
GENERATED_NOTE = "Generated and sealed in memory. No display state was changed."


def _preset_values(field: int) -> list[str]:
    """Every value the preset table gives one target field, in table order."""
    seen: dict[str, None] = {}
    for target in PRESET_TARGETS.values():
        seen.setdefault(target[field], None)
    return list(seen)


def _presets_with(field: int, value: str) -> Iterator[str]:
    """Preset ids whose target carries ``value`` in ``field``, in table order."""
    for preset_id, target in PRESET_TARGETS.items():
        if target[field] == value:
            yield preset_id


class ModeCard(Card):
    """Selectable mode card with icon area, title, and subtitle.

    The card follows ``isEnabled`` rather than holding a second opinion about
    it. It used to keep its own flag, which the binder had no way to reach, so
    a card the resolver closed stopped responding to a click and went on
    looking available. Qt withholds mouse events from a disabled widget, which
    made that failure silent: the operator clicked and nothing at all happened.
    """

    clicked = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str,
        icon_text: str,
        parent=None,
    ):
        super().__init__(parent)
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        self._icon_label = QLabel(icon_text)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        self._title_label = QLabel(title)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title_label)

        self._sub_label = QLabel(subtitle)
        self._sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_label.setWordWrap(True)
        layout.addWidget(self._sub_label)

        self._apply_style()

    # --- selection ---

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()

    def is_selected(self) -> bool:
        return self._selected

    def changeEvent(self, event) -> None:
        """Redraw when Qt enables or disables the card, including via a binder."""
        if event.type() == QEvent.Type.EnabledChange:
            self.setCursor(Qt.CursorShape.PointingHandCursor if self.isEnabled() else Qt.CursorShape.ForbiddenCursor)
            self._apply_style()
        super().changeEvent(event)

    def _apply_style(self) -> None:
        enabled = self.isEnabled()
        self._icon_label.setStyleSheet(f"font-size: 24px; color: {C.ACCENT_TX if enabled else C.TEXT3};")
        self._title_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {C.TEXT if enabled else C.TEXT3};")
        self._sub_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2 if enabled else C.TEXT3};")
        if not enabled:
            self.setStyleSheet(
                f"ModeCard {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; border-radius: 10px; }}"
            )
        elif self._selected:
            self.setStyleSheet(
                f"ModeCard {{ background: {C.SURFACE2}; border: 2px solid {C.ACCENT_HI}; border-radius: 10px; }}"
            )
        else:
            self.setStyleSheet(
                f"ModeCard {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; border-radius: 10px; }}"
                f"ModeCard:hover {{ border-color: {C.ACCENT}; }}"
            )

    def mousePressEvent(self, event) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class CalibratePage(QWidget):
    """The calibration workflow: a display, a method, a target, a bundle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._binder: ActionBinder | None = None
        self._select_display: Callable[[str], ActionOutcome[Any]] | None = None
        self._set_target: Callable[[str], ActionOutcome[Any]] | None = None
        self._display_binding: SurfaceBinding | None = None
        self._target_bindings: dict[int, SurfaceBinding] = {}
        self._displays: list[tuple[str, str]] = []
        self._display_id: str | None = None
        self._target: TargetSelection | None = None
        self._build()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(32, 28, 32, 28)
        self._layout.setSpacing(20)

        self._layout.addWidget(Heading("Calibrate Display"))
        self._build_display_row()
        self._build_mode_row()
        self._build_target_card()
        self._build_preset_row()
        self._build_actions_row()
        self._build_result_card()

        self._layout.addStretch()
        scroll.setWidget(content)

    def _build_display_row(self) -> None:
        card, layout = Card.with_layout(QHBoxLayout, margins=(16, 12, 16, 12))
        label = QLabel("Display")
        label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2}; font-weight: 500;")
        layout.addWidget(label)

        self._display_combo = QComboBox()
        self._display_combo.setMinimumWidth(280)
        self._display_combo.setStyleSheet(self._combo_style(min_width=0))
        self._display_combo.addItem(NO_DISPLAY_ITEM)
        self._display_combo.currentIndexChanged.connect(self._on_display_changed)
        layout.addWidget(self._display_combo, stretch=1)
        self._layout.addWidget(card)

    def _build_mode_row(self) -> None:
        self._layout.addWidget(Heading("Profiling Mode", level=2))
        row = QHBoxLayout()
        row.setSpacing(12)

        self._mode_sensorless = ModeCard("Sensorless", "Panel database, instant", "██")
        self._mode_measured = ModeCard("Measured", "Colorimeter profiling", "◉")
        self._mode_hybrid = ModeCard("Hybrid", "Database + refinement", "█◉")
        self._mode_cards = (self._mode_sensorless, self._mode_measured, self._mode_hybrid)
        for card in self._mode_cards:
            row.addWidget(card)

        self._method_label = QLabel(NO_METHOD_NOTE)
        self._method_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")

        self._layout.addLayout(row)
        self._layout.addWidget(self._method_label)

    def _build_target_card(self) -> None:
        self._layout.addWidget(Heading("Target Settings", level=2))
        card, layout = Card.with_layout(QGridLayout, margins=(20, 16, 20, 16), spacing=12)
        label_style = f"font-size: 12px; color: {C.TEXT2};"

        self._target_combos: dict[int, QComboBox] = {}
        rows = ((GAMUT, "Target Gamut"), (WHITE_POINT, "White Point"), (TONE_RESPONSE, "Tone Response"))
        for row, (field, caption) in enumerate(rows):
            text = QLabel(caption)
            text.setStyleSheet(label_style)
            layout.addWidget(text, row, 0)
            combo = QComboBox()
            combo.addItem(UNSET_TARGET_ITEM)
            combo.addItems(_preset_values(field))
            combo.setStyleSheet(self._combo_style())
            combo.currentIndexChanged.connect(lambda _index, key=field: self._on_target_changed(key))
            layout.addWidget(combo, row, 1)
            self._target_combos[field] = combo

        hdr_caption = QLabel("HDR Mode")
        hdr_caption.setStyleSheet(label_style)
        layout.addWidget(hdr_caption, 3, 0)
        self._btn_hdr = QPushButton("Enable HDR calibration")
        self._btn_hdr.setStyleSheet(self._pill_style())
        self._btn_hdr.setFixedHeight(28)
        layout.addWidget(self._btn_hdr, 3, 1)

        self._target_label = QLabel(NO_TARGET_NOTE)
        self._target_label.setWordWrap(True)
        self._target_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
        layout.addWidget(self._target_label, 4, 0, 1, 2)

        self._layout.addWidget(card)

    def _build_preset_row(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(8)
        caption = QLabel("Presets")
        caption.setStyleSheet(f"font-size: 12px; color: {C.TEXT2}; font-weight: 500;")
        row.addWidget(caption)

        self._preset_buttons: dict[str, QPushButton] = {}
        for preset_id, label in PRESET_LABELS.items():
            button = QPushButton(label)
            button.setStyleSheet(self._pill_style())
            button.setFixedHeight(28)
            row.addWidget(button)
            self._preset_buttons[preset_id] = button

        row.addStretch()
        self._layout.addLayout(row)

    def _build_actions_row(self) -> None:
        row = QHBoxLayout()
        row.addStretch()
        self._btn_generate = QPushButton("Generate Calibration")
        self._btn_generate.setStyleSheet(self._primary_style())
        self._btn_generate.setFixedHeight(44)
        self._btn_generate.setFixedWidth(220)
        row.addWidget(self._btn_generate)

        self._btn_preview = QPushButton("Preview Plan")
        self._btn_preview.setStyleSheet(self._secondary_style())
        self._btn_preview.setFixedHeight(44)
        self._btn_preview.setFixedWidth(180)
        row.addWidget(self._btn_preview)
        row.addStretch()
        self._layout.addLayout(row)

    def _build_result_card(self) -> None:
        self._result_card, layout = Card.with_layout(QVBoxLayout, margins=(20, 16, 20, 16), spacing=10)

        self._result_heading = QLabel(NOT_GENERATED_NOTE)
        self._result_heading.setWordWrap(True)
        self._result_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT2};")
        layout.addWidget(self._result_heading)

        stats = QHBoxLayout()
        stats.setSpacing(24)
        self._stat_panel = Stat("Panel", "--", C.TEXT)
        self._stat_characterization = Stat("Characterization", "--", C.TEXT)
        self._stat_evidence = Stat("Evidence", "--", C.TEXT)
        for stat in (self._stat_panel, self._stat_characterization, self._stat_evidence):
            stats.addWidget(stat)
        stats.addStretch()
        layout.addLayout(stats)

        self._digest_label = QLabel("")
        self._digest_label.setWordWrap(True)
        self._digest_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._digest_label.setStyleSheet(
            f'font-family: "Cascadia Code", "Consolas", monospace; font-size: 11px; color: {C.TEXT2};'
        )
        layout.addWidget(self._digest_label)

        self._files_label = QLabel("")
        self._files_label.setWordWrap(True)
        self._files_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
        layout.addWidget(self._files_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 3)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(8)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {C.SURFACE2}; border: none; border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {C.GREEN}; border-radius: 4px; }}"
        )
        layout.addWidget(self._progress_bar)

        self._layout.addWidget(self._result_card)

    # -- styles -------------------------------------------------------------

    def _combo_style(self, *, min_width: int = 140) -> str:
        width = f"min-width: {min_width}px;" if min_width else ""
        return f"""
            QComboBox {{
                background: {C.SURFACE2};
                border: 1px solid {C.BORDER};
                border-radius: 6px;
                padding: 6px 12px;
                color: {C.TEXT};
                font-size: 13px;
                {width}
            }}
            QComboBox:disabled {{ color: {C.TEXT3}; }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background: {C.SURFACE};
                border: 1px solid {C.BORDER};
                color: {C.TEXT};
                selection-background-color: {C.ACCENT};
            }}
        """

    def _pill_style(self) -> str:
        return (
            f"QPushButton {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
            f"border-radius: 14px; padding: 5px 14px; font-size: 11px; color: {C.TEXT}; }}"
            f"QPushButton:hover {{ border-color: {C.ACCENT}; background: {C.SURFACE2}; }}"
            f"QPushButton:disabled {{ color: {C.TEXT3}; border-color: {C.BORDER}; }}"
        )

    def _primary_style(self) -> str:
        return f"""
            QPushButton {{
                background: {C.GREEN};
                border: 1px solid {C.GREEN_HI};
                border-radius: 8px;
                color: {C.TEXT};
                font-size: 15px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {C.GREEN_HI}; }}
            QPushButton:disabled {{
                background: {C.SURFACE2};
                border-color: {C.BORDER};
                color: {C.TEXT3};
            }}
        """

    def _secondary_style(self) -> str:
        return f"""
            QPushButton {{
                background: {C.SURFACE};
                border: 1px solid {C.BORDER};
                border-radius: 8px;
                color: {C.TEXT};
                font-size: 14px;
            }}
            QPushButton:hover {{ border-color: {C.ACCENT}; background: {C.SURFACE2}; }}
            QPushButton:disabled {{ color: {C.TEXT3}; }}
        """

    # -- binding ------------------------------------------------------------

    def bind_actions(
        self,
        binder: ActionBinder,
        *,
        select_display: Callable[[str], ActionOutcome[Any]],
        select_sensorless: Operation,
        set_target: Callable[[str], ActionOutcome[Any]],
        unhandled: Callable[[str], ActionOutcome[Any]],
        generate: Operation,
        preview: Operation,
    ) -> None:
        """Hand every control here to the action it stands for.

        The measured and hybrid cards are bound to actions this build has no
        handler for, so what appears on them is the manifest's reason for
        holding measured calibration closed. That reason used to be contradicted
        by the page, which enabled both after finding a colorimeter on the bus
        and then performed one.

        A target selector renders one action and performs another, which the
        binding keeps as two separate fields for exactly this case. The control
        stands for editing that field of the target; what editing it does in
        this build is select the preset carrying the chosen value, because the
        preset table is the whole target vocabulary. Both actions carry the same
        condition, so the sentence on a closed selector is the same either way.
        """
        self._binder = binder
        self._select_display = select_display
        self._set_target = set_target

        self._display_binding = binder.bind(
            "workflow.select_display",
            self._display_combo,
            self._selected_display,
            on_success=self.render_display,
            hides=False,
            connect=False,
        )
        binder.bind(
            "calibration.method.sensorless",
            self._mode_sensorless,
            select_sensorless,
            on_success=self.render_method,
            hides=False,
        )
        for card, method in ((self._mode_measured, "measured"), (self._mode_hybrid, "hybrid")):
            action_id = f"calibration.method.{method}"
            binder.bind(action_id, card, _closed(unhandled, action_id), hides=False)

        for field, combo in self._target_combos.items():
            action_id = f"calibration.target.{('gamut', 'whitepoint', 'gamma')[field]}"
            self._target_bindings[field] = binder.bind(
                action_id,
                combo,
                self._target_operation(field),
                on_success=self.render_target,
                hides=False,
                connect=False,
            )
        binder.bind(
            "calibration.target.hdr",
            self._btn_hdr,
            _closed(unhandled, "calibration.target.hdr"),
            hides=False,
        )

        for preset_id, button in self._preset_buttons.items():
            operation = (
                _closed(unhandled, preset_id) if preset_id not in PRESET_TARGETS else _select(set_target, preset_id)
            )
            binder.bind(preset_id, button, operation, on_success=self.render_target, hides=False)

        binder.bind(
            "calibration.generate",
            self._btn_generate,
            generate,
            on_success=self.render_generation,
            hides=False,
        )
        binder.bind(
            "calibration.preview",
            self._btn_preview,
            preview,
            on_success=self.render_preview,
            hides=False,
        )

    def _selected_display(self) -> ActionOutcome[Any] | None:
        """Adopt whichever display the selector is on, if it is on one."""
        select = self._select_display
        index = self._display_combo.currentIndex()
        if select is None or not (0 <= index < len(self._displays)):
            return None
        return select(self._displays[index][1])

    def _on_display_changed(self, index: int) -> None:
        """Ask the session to adopt the display the operator picked.

        The selector is put back afterwards. A withdrawal or a refusal leaves
        the session on the display it already held, and the control that asked
        would otherwise keep naming the one it was refused.
        """
        _ = index
        self._invoke(self._display_binding)
        self._restore_display()

    def select_display_index(self, index: int) -> None:
        """Move the selector to one listed display, as though it were clicked.

        A caller that set the index behind the signal would leave the page
        naming a display the session never adopted, which is the reading this
        page exists to stop making.
        """
        if 0 <= index < len(self._displays):
            self._display_combo.setCurrentIndex(index)

    def _target_operation(self, field: int) -> Operation:
        """Select the preset carrying whatever value this selector now shows."""

        def run() -> ActionOutcome[Any] | None:
            set_target, combo = self._set_target, self._target_combos[field]
            if set_target is None:
                return None
            preset_id = self._preset_for(field, combo.currentText())
            if preset_id is None:
                return None
            return set_target(preset_id)

        return run

    def _preset_for(self, field: int, value: str) -> str | None:
        """Which preset the operator asked for by putting ``value`` in ``field``.

        A preset matching every selector at once is the one they meant. Where
        the three selectors do not name a preset together, the changed field
        decides and the others follow it, so a selector always reaches a target
        rather than composing one this build cannot generate.
        """
        chosen = tuple(self._target_combos[key].currentText() for key in (GAMUT, WHITE_POINT, TONE_RESPONSE))
        for preset_id, target in PRESET_TARGETS.items():
            if target[:3] == chosen:
                return preset_id
        return next(_presets_with(field, value), None)

    def _on_target_changed(self, field: int) -> None:
        """Ask the session for the target the operator's edit names.

        Every selector is put back afterwards. Selecting the unset item names
        no preset, so nothing is attempted, and a field left on it would read as
        a target with one component missing while the line below names a whole
        preset. A refusal leaves the same disagreement, and a success has
        already moved all three, which makes the restore a redraw of what the
        session just reported.
        """
        self._invoke(self._target_bindings.get(field))
        self._restore_target()

    def _invoke(self, binding: SurfaceBinding | None) -> None:
        binder = self._binder
        if binder is not None and binding is not None:
            binder.invoke(binding)

    # -- rendering ----------------------------------------------------------

    def render_session(self, summary: DetectionSummary) -> None:
        """List the displays one detection pass observed, and only those.

        Repopulating moves the current index, so the signal is blocked while it
        happens. Without that, redrawing this page would re-select a display
        through the binding, and the session would answer a selection nobody
        made. A detection pass re-adopts a display on its own, which drops the
        method and everything under it, so the rest of the page is cleared to
        match rather than left showing what the pass invalidated.
        """
        combo = self._display_combo
        blocked = combo.blockSignals(True)
        try:
            combo.clear()
            self._displays = [
                (display.safe_label, display.platform_display_id) for display in summary.dashboard.displays
            ]
            for label, _display_id in self._displays or [(NO_DISPLAY_ITEM, "")]:
                combo.addItem(label)
            self._display_id = summary.selected_display_id
            self._show_display(self._display_id)
        finally:
            combo.blockSignals(blocked)
        self._clear_method()

    def render_display(self, selection: DisplaySelection) -> None:
        """Take the session's word for the display, and drop what it invalidated.

        Adopting a display resets the method, the target and the seal. What was
        on screen for those described the display the operator just left.
        """
        self._display_id = selection.display_id
        self._clear_method()

    def render_method(self, selection: MethodSelection) -> None:
        """Show the method the session committed to, and mark its card."""
        self._clear_target()
        for card, method in zip(self._mode_cards, ("sensorless", "measured", "hybrid"), strict=True):
            card.set_selected(method == selection.method.value)
        self._method_label.setText(f"Method: {selection.method.value}. Stage: {selection.stage.value}.")
        self._progress_bar.setValue(1)

    def render_target(self, selection: TargetSelection) -> None:
        """Move every selector onto the target the session actually holds.

        Setting a target breaks the seal, so the bundle described below it is
        no longer the one this target would produce and is cleared.
        """
        self._clear_result()
        self._target = selection
        values = {
            GAMUT: selection.gamut,
            WHITE_POINT: selection.white_point,
            TONE_RESPONSE: selection.tone_response,
        }
        for field, value in values.items():
            self._show_target_value(field, value)
        label = PRESET_LABELS.get(selection.preset_id, selection.preset_id)
        self._target_label.setText(
            f"Target: {label}. {selection.gamut} primaries, {selection.white_point} white point, "
            f"{selection.tone_response} tone response."
        )
        self._progress_bar.setValue(2)

    def render_generation(self, result: GenerationResult) -> None:
        """Report the bundle the session sealed, in the terms it reported it."""
        self._result_heading.setText(GENERATED_NOTE)
        self._result_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.GREEN_HI};")
        self._stat_panel.set_value(result.panel_name)
        self._stat_characterization.set_value(result.characterization_kind.value)
        self._stat_evidence.set_value(result.evidence_kind.value)
        self._digest_label.setText(f"plan sha256: {result.plan_sha256}")
        self._files_label.setText("Files: " + ", ".join(result.filenames))
        self._progress_bar.setValue(3)

    def render_preview(self, preview: PlanPreview) -> None:
        """Report the proposal, including whether anything reached the display."""
        applied = preview.physical_apply_performed
        self._result_heading.setText(
            "Plan applied to the display." if applied else "Plan previewed. No display state was changed."
        )
        self._result_heading.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {C.ACCENT_TX if applied else C.GREEN_HI};"
        )
        self._digest_label.setText(f"plan sha256: {preview.plan_sha256}")
        self._progress_bar.setValue(3)

    # -- clearing what the session dropped -----------------------------------

    def _clear_method(self) -> None:
        """Forget the method on screen, and everything that depended on it."""
        for card in self._mode_cards:
            card.set_selected(False)
        self._method_label.setText(NO_METHOD_NOTE)
        self._clear_target()

    def _clear_target(self) -> None:
        """Forget the target on screen, and the bundle generated against it."""
        self._target = None
        for field in self._target_combos:
            self._show_target_value(field, UNSET_TARGET_ITEM)
        self._target_label.setText(NO_TARGET_NOTE)
        self._clear_result()

    def _clear_result(self) -> None:
        """Forget the sealed bundle, which no longer describes this session."""
        self._result_heading.setText(NOT_GENERATED_NOTE)
        self._result_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT2};")
        for stat in (self._stat_panel, self._stat_characterization, self._stat_evidence):
            stat.set_value("--")
        self._digest_label.setText("")
        self._files_label.setText("")
        self._progress_bar.setValue(0)

    def _restore_display(self) -> None:
        """Put the selector back on the display the session says it holds."""
        combo = self._display_combo
        blocked = combo.blockSignals(True)
        try:
            self._show_display(self._display_id)
        finally:
            combo.blockSignals(blocked)

    def _show_display(self, display_id: str | None) -> None:
        """Move the display selector, leaving it where it is if nothing matches.

        The caller blocks the signal. Moving it here would ask the session to
        adopt the display it just reported, and the reply would move it again.
        """
        for index, (_label, listed_id) in enumerate(self._displays):
            if listed_id == display_id:
                self._display_combo.setCurrentIndex(index)
                return

    def _restore_target(self) -> None:
        """Put every selector back on the target the session says it holds."""
        target = self._target
        values = (
            (GAMUT, target.gamut if target else UNSET_TARGET_ITEM),
            (WHITE_POINT, target.white_point if target else UNSET_TARGET_ITEM),
            (TONE_RESPONSE, target.tone_response if target else UNSET_TARGET_ITEM),
        )
        for field, value in values:
            self._show_target_value(field, value)

    def _show_target_value(self, field: int, value: str) -> None:
        """Put one selector on a value without asking the session for it."""
        combo = self._target_combos[field]
        blocked = combo.blockSignals(True)
        try:
            index = combo.findText(value)
            if index >= 0:
                combo.setCurrentIndex(index)
        finally:
            combo.blockSignals(blocked)


def _closed(unhandled: Callable[[str], ActionOutcome[Any]], action_id: str) -> Operation:
    """An action this build declares and has no handler for."""
    return lambda: unhandled(action_id)


def _select(set_target: Callable[[str], ActionOutcome[Any]], preset_id: str) -> Operation:
    """Set the session's target to one named preset."""
    return lambda: set_target(preset_id)


__all__ = [
    "GENERATED_NOTE",
    "HDR_PRESET_ACTION",
    "NOT_GENERATED_NOTE",
    "NO_DISPLAY_ITEM",
    "NO_METHOD_NOTE",
    "NO_TARGET_NOTE",
    "PRESET_LABELS",
    "UNSET_TARGET_ITEM",
    "CalibratePage",
    "ModeCard",
]
