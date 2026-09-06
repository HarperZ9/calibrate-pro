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
resolver a terminal quotes. The three target selectors list the whole
catalogue, and choosing a value replaces that one part of the target the
session holds while the other two stay where they are. The preset buttons are
still here, because four of these combinations are what most operators want and
they should not have to assemble one.

A custom correlated colour temperature had a slider and no target behind it,
and the slider was removed rather than left moving over nothing. It is a spin
box now with a target behind it. The number reaches the session, which puts the
white point on the daylight locus at that temperature and answers with the
whole target it went on to hold.

Choosing a display drops the method, the target and the seal. Choosing a method
drops the target and the seal, and choosing a target drops the seal. The page
clears what each of those invalidated at the moment it happens, so a figure on
screen is never one the session stopped holding.
"""

from __future__ import annotations

from collections.abc import Callable
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.application.actions import PRESET_TARGETS
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.results import (
    AppliedPlanResult,
    DetectionSummary,
    DisplaySelection,
    GenerationResult,
    MeasurementSummary,
    MethodSelection,
    PlanDecision,
    PlanPreview,
    TargetSelection,
)
from calibrate_pro.application.target_editing import target_slugs
from calibrate_pro.application.target_selection import (
    CUSTOM_CCT_MAX_K,
    CUSTOM_CCT_MIN_K,
    selectable_gamuts,
    selectable_tone_responses,
    selectable_white_points,
)
from calibrate_pro.gui.action_binding import ActionBinder, Operation, SurfaceBinding
from calibrate_pro.gui.app import C, Card, Heading, Stat
from calibrate_pro.verification.provenance import EvidenceKind

#: What the page says once a receipt reports the display was written. The
#: routes, the phases the adapter reached and the recovery guarantee follow
#: it on the line below, so the claim and its detail are read together.
APPLIED_NOTE = "Calibration applied to the display."

#: What the page says when an apply returned a receipt that never reached the
#: write. The phases below it name how far the adapter got.
NOT_APPLIED_NOTE = "Apply did not change the display."

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

#: What the target line calls a target no preset names. The three parts follow
#: it in the same sentence, so the word carries no information the operator
#: needs and is not asked to.
COMPOSED_TARGET_LABEL = "Custom"

#: Where the temperature spin box starts. It is the one temperature that also
#: names an illuminant this build carries, so an operator who opens the control
#: and presses the button lands on a white the catalogue can be checked against
#: rather than on the low end of the range.
DEFAULT_CUSTOM_CCT_K = 6500

#: How far one press of the spin box moves. Fifty kelvin is under the smallest
#: step that changes the composed white by a visible amount, so the control can
#: be driven to a specific number rather than stepped past it.
CUSTOM_CCT_STEP_K = 50

#: Under the workflow before an action has produced anything.
NOT_GENERATED_NOTE = "No calibration bundle has been generated in this session."

#: What the page says about the target until the session holds one.
NO_TARGET_NOTE = "No target selected in this session."

#: What the page says about the method until the session holds one.
NO_METHOD_NOTE = "No profiling method selected in this session."

#: Beside the generated bundle. Generation seals files and changes no display.
GENERATED_NOTE = "Generated and sealed in memory. No display state was changed."

#: Beside a finished instrument run. The sentence names what the run replaced,
#: because the record it wrote is what every later figure in the session is
#: derived from, and an operator who does not know that reads the next bundle
#: as though the panel database had still produced it.
MEASURED_NOTE = "Display measured. This session now generates from the reading rather than from a panel record."

#: After the operator accepts a previewed plan. The sentence stays about the
#: display, because a workflow step called "confirm" beside a list of profile
#: files otherwise reads as one that loaded them.
CONFIRMED_NOTE = "Plan confirmed. Nothing was sent to the display. Verification reads this plan."

#: After the operator declines one. The seal is gone with it, so the page says
#: what is needed to get back to a plan rather than leaving a stale digest up.
DECLINED_NOTE = "Plan declined. Generate again to seal a new one."


#: What each selector offers, as (slug, label) in catalogue order. The page
#: shows the label and sends the slug, so a control never has to be read back
#: through its own text to find out what it stands for.
SELECTABLE = {
    GAMUT: selectable_gamuts,
    WHITE_POINT: selectable_white_points,
    TONE_RESPONSE: selectable_tone_responses,
}


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
        self._set_axis: dict[int, Callable[[str], ActionOutcome[Any]]] = {}
        self._set_custom_cct: Callable[[int], ActionOutcome[Any]] | None = None
        self._display_binding: SurfaceBinding | None = None
        self._target_bindings: dict[int, SurfaceBinding] = {}
        self._displays: list[tuple[str, str]] = []
        self._display_id: str | None = None
        self._target: TargetSelection | None = None
        self._confirm_plan: Callable[[PlanPreview], None] | None = None
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
        #: How many items each selector was built with. Anything past it is a
        #: value the session holds that the catalogue does not list, which is
        #: how a colour temperature comes to be shown on the white selector.
        self._catalogue_items: dict[int, int] = {}
        rows = ((GAMUT, "Target Gamut"), (WHITE_POINT, "White Point"), (TONE_RESPONSE, "Tone Response"))
        for row, (field, caption) in enumerate(rows):
            text = QLabel(caption)
            text.setStyleSheet(label_style)
            layout.addWidget(text, row, 0)
            combo = QComboBox()
            combo.addItem(UNSET_TARGET_ITEM, None)
            for slug, label in SELECTABLE[field]():
                combo.addItem(label, slug)
            combo.setStyleSheet(self._combo_style())
            combo.currentIndexChanged.connect(lambda _index, key=field: self._on_target_changed(key))
            layout.addWidget(combo, row, 1)
            self._target_combos[field] = combo
            self._catalogue_items[field] = combo.count()

        cct_caption = QLabel("Colour Temperature")
        cct_caption.setStyleSheet(label_style)
        layout.addWidget(cct_caption, 3, 0)
        layout.addLayout(self._build_custom_cct_row(), 3, 1)

        hdr_caption = QLabel("HDR Mode")
        hdr_caption.setStyleSheet(label_style)
        layout.addWidget(hdr_caption, 4, 0)
        self._btn_hdr = QPushButton("Enable HDR calibration")
        self._btn_hdr.setStyleSheet(self._pill_style())
        self._btn_hdr.setFixedHeight(28)
        layout.addWidget(self._btn_hdr, 4, 1)

        self._target_label = QLabel(NO_TARGET_NOTE)
        self._target_label.setWordWrap(True)
        self._target_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
        layout.addWidget(self._target_label, 5, 0, 1, 2)

        self._layout.addWidget(card)

    def _build_custom_cct_row(self) -> QHBoxLayout:
        """A number and the button that sends it, both standing for one action.

        The spin box does not perform on its own. An operator scrolling through
        temperatures would otherwise set a target on every intermediate value,
        journalling a run of targets nobody asked for and invalidating the seal
        each time. The button is when the number is meant.
        """
        row = QHBoxLayout()
        row.setSpacing(8)
        self._cct_spin = QSpinBox()
        self._cct_spin.setRange(CUSTOM_CCT_MIN_K, CUSTOM_CCT_MAX_K)
        self._cct_spin.setSingleStep(CUSTOM_CCT_STEP_K)
        self._cct_spin.setValue(DEFAULT_CUSTOM_CCT_K)
        self._cct_spin.setSuffix(" K")
        self._cct_spin.setStyleSheet(self._combo_style())
        row.addWidget(self._cct_spin)
        self._btn_cct = QPushButton("Use temperature")
        self._btn_cct.setStyleSheet(self._pill_style())
        self._btn_cct.setFixedHeight(28)
        row.addWidget(self._btn_cct)
        row.addStretch()
        return row

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
        # Measuring comes before generating because that is the order the two
        # happen in: a run writes the record, and generation reads it.
        self._btn_measure = QPushButton("Measure Display")
        self._btn_measure.setStyleSheet(self._secondary_style())
        self._btn_measure.setFixedHeight(44)
        self._btn_measure.setFixedWidth(180)
        row.addWidget(self._btn_measure)

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
        self._btn_apply = QPushButton("Apply to Display")
        self._btn_apply.setStyleSheet(self._secondary_style())
        self._btn_apply.setFixedHeight(44)
        self._btn_apply.setFixedWidth(180)
        row.addWidget(self._btn_apply)
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
        self._progress_bar.setRange(0, 4)
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
        select_measured: Operation,
        set_target: Callable[[str], ActionOutcome[Any]],
        set_gamut: Callable[[str], ActionOutcome[Any]],
        set_white_point: Callable[[str], ActionOutcome[Any]],
        set_tone_response: Callable[[str], ActionOutcome[Any]],
        set_custom_cct: Callable[[int], ActionOutcome[Any]],
        unhandled: Callable[[str], ActionOutcome[Any]],
        measure: Operation,
        generate: Operation,
        preview: Operation,
        apply_plan: Operation,
        confirm_plan: Callable[[PlanPreview], None],
    ) -> None:
        """Hand every control here to the action it stands for.

        The hybrid card is bound to an action this build has no handler for, so
        what appears on it is the manifest's reason for holding hybrid
        calibration closed. The measured card and the measure button perform,
        and what decides whether either is offered is the resolver rather than
        the page. The page used to decide it, by asking the USB bus what was
        attached and enabling both cards on the answer, which is how it came to
        offer a method the manifest was holding shut.

        A target selector renders the action it stands for and performs that
        same action, which is editing one axis of the target. What comes back
        is the whole target the session went on to hold, and all three
        selectors are redrawn from it, so the controls and the line under them
        cannot end up describing two different targets.

        The temperature is two controls for one action. Both are bound, so a
        session that would refuse it closes the number and the button together
        and puts the resolver's sentence on each.
        """
        self._binder = binder
        self._select_display = select_display
        self._set_target = set_target
        self._set_axis = {GAMUT: set_gamut, WHITE_POINT: set_white_point, TONE_RESPONSE: set_tone_response}
        self._set_custom_cct = set_custom_cct
        self._confirm_plan = confirm_plan

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
        binder.bind(
            "calibration.method.measured",
            self._mode_measured,
            select_measured,
            on_success=self.render_method,
            hides=False,
        )
        binder.bind(
            "calibration.method.hybrid",
            self._mode_hybrid,
            _closed(unhandled, "calibration.method.hybrid"),
            hides=False,
        )

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
            "calibration.target.custom_cct",
            self._btn_cct,
            self._custom_cct_operation(),
            on_success=self.render_target,
            hides=False,
        )
        binder.bind(
            "calibration.target.custom_cct",
            self._cct_spin,
            self._custom_cct_operation(),
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
            "calibration.measure",
            self._btn_measure,
            measure,
            on_success=self.render_measurement,
            hides=False,
        )
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
        binder.bind(
            "calibration.apply",
            self._btn_apply,
            apply_plan,
            on_success=self.render_apply,
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
        """Edit this one axis of the target, leaving the other two held.

        The unset item carries no slug, so landing on it asks for nothing. It
        is what the selectors are put back to when the target is dropped, and
        an operator choosing it is saying no more than that.
        """

        def run() -> ActionOutcome[Any] | None:
            edit = self._set_axis.get(field)
            slug = self._target_combos[field].currentData()
            if edit is None or slug is None:
                return None
            return edit(str(slug))

        return run

    def _custom_cct_operation(self) -> Operation:
        """Aim the white point at the daylight locus at the number shown."""

        def run() -> ActionOutcome[Any] | None:
            edit = self._set_custom_cct
            if edit is None:
                return None
            return edit(self._cct_spin.value())

        return run

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
        labels = (selection.gamut, selection.white_point, selection.tone_response)
        for field, slug in enumerate(target_slugs(selection.preset_id)):
            self._show_target_value(field, slug, labels[field])
        label = PRESET_LABELS.get(selection.preset_id, COMPOSED_TARGET_LABEL)
        self._target_label.setText(
            f"Target: {label}. {selection.gamut} primaries, {selection.white_point} white point, "
            f"{selection.tone_response} tone response."
        )
        self._progress_bar.setValue(2)

    def render_measurement(self, summary: MeasurementSummary) -> None:
        """Report the run the instrument took, in the terms the session recorded.

        The result card is cleared first. A run replaces the record the next
        generation builds from, so a bundle sealed against the record it
        replaced no longer describes this session, and its digest would sit on
        screen naming a plan nothing downstream can still cite.

        The target survives a run, so the workflow returns to the step it was
        on rather than to the start. What the display was loading when the run
        was taken goes on the line under the reading, because a measurement is
        only reproducible next to that state.
        """
        self._clear_result()
        self._result_heading.setText(MEASURED_NOTE)
        self._result_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.GREEN_HI};")
        self._stat_panel.set_value(summary.characterization.panel.name)
        self._stat_characterization.set_value(CharacterizationKind.MEASURED.value)
        self._stat_evidence.set_value(EvidenceKind.MEASURED.value)
        self._digest_label.setText(summary.summary)
        self._files_label.setText(summary.correction_state)
        self._progress_bar.setValue(2)

    def render_generation(self, result: GenerationResult) -> None:
        """Report the bundle the session sealed, in the terms it reported it."""
        self._result_heading.setText(GENERATED_NOTE)
        self._result_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.GREEN_HI};")
        self._stat_panel.set_value(result.panel_name)
        self._stat_characterization.set_value(result.characterization_kind.value)
        self._stat_evidence.set_value(result.evidence_kind.value)
        self._digest_label.setText(f"plan sha256: {result.plan_sha256}")
        files = "Files: " + ", ".join(result.filenames)
        note = result.apply_note
        self._files_label.setText(files if note is None else f"{files}. {note}")
        self._progress_bar.setValue(3)

    def render_preview(self, preview: PlanPreview) -> None:
        """Report the proposal, then hand it on to be answered.

        A previewed plan is the last thing this page can produce on its own.
        Verification, saving a report and every active export read a plan the
        session confirmed, and confirming one is an action with its own surface,
        so the preview is passed out to whoever wired that surface up rather
        than left on screen with no way to answer it.
        """
        applied = preview.physical_apply_performed
        self._result_heading.setText(
            "Plan applied to the display." if applied else "Plan previewed. No display state was changed."
        )
        self._result_heading.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {C.ACCENT_TX if applied else C.GREEN_HI};"
        )
        self._digest_label.setText(f"plan sha256: {preview.plan_sha256}")
        self._progress_bar.setValue(3)
        if self._confirm_plan is not None:
            self._confirm_plan(preview)

    def render_apply(self, result: AppliedPlanResult) -> None:
        """Report what the display did, reading the receipt and not the intent.

        The heading answers one question: was this display changed. It comes
        from the receipt, so a session built to drive a display still reports
        an apply that stopped before the write as one that changed nothing.

        The phases follow it in the order the adapter takes them, which is
        what lets an operator see where a partial apply stopped instead of
        reading a single word that flattens capture, write, verify and
        restore into one.
        """
        applied = result.physical_apply_performed
        self._result_heading.setText(APPLIED_NOTE if applied else NOT_APPLIED_NOTE)
        self._result_heading.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {C.GREEN_HI if applied else C.TEXT2};"
        )
        routes = ", ".join(result.routes) or "none"
        phases = ", ".join(f"{name}={'yes' if done else 'no'}" for name, done in result.apply_phase_flags)
        self._files_label.setText(f"Routes: {routes}. Phases: {phases}. Recovery: {result.recovery_guarantee}.")
        self._digest_label.setText(f"plan sha256: {result.plan_sha256}")
        self._progress_bar.setValue(4)

    def render_decision(self, decision: PlanDecision) -> None:
        """Report which way the plan went, naming the plan it went for.

        A declined plan clears the result rather than greying it, because the
        session dropped the preview and returned to the preview stage. Leaving
        the digest up would leave a seal on screen that nothing downstream can
        still cite.
        """
        if not decision.accepted:
            self._clear_result()
            self._result_heading.setText(DECLINED_NOTE)
            return
        self._result_heading.setText(CONFIRMED_NOTE)
        self._result_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.GREEN_HI};")
        self._digest_label.setText(f"plan sha256: {decision.plan_sha256}")
        self._progress_bar.setValue(4)

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
            self._show_target_value(field, None, UNSET_TARGET_ITEM)
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
        if target is None:
            for field in self._target_combos:
                self._show_target_value(field, None, UNSET_TARGET_ITEM)
            return
        labels = (target.gamut, target.white_point, target.tone_response)
        for field, slug in enumerate(target_slugs(target.preset_id)):
            self._show_target_value(field, slug, labels[field])

    def _show_target_value(self, field: int, slug: str | None, label: str) -> None:
        """Put one selector on a value without asking the session for it.

        A white point the catalogue does not list is added rather than dropped.
        Every colour temperature is one of those, and a selector that quietly
        stayed on D65 while the session held 5400 K would be the page telling
        the operator a white the bundle is not aimed at. One trailing item is
        kept at most, so the list does not grow a row per temperature tried.
        """
        combo = self._target_combos[field]
        blocked = combo.blockSignals(True)
        try:
            while combo.count() > self._catalogue_items[field]:
                combo.removeItem(combo.count() - 1)
            index = 0 if slug is None else combo.findData(slug)
            if index < 0:
                combo.addItem(label, slug)
                index = combo.count() - 1
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
    "APPLIED_NOTE",
    "COMPOSED_TARGET_LABEL",
    "CONFIRMED_NOTE",
    "CUSTOM_CCT_STEP_K",
    "DECLINED_NOTE",
    "DEFAULT_CUSTOM_CCT_K",
    "GENERATED_NOTE",
    "HDR_PRESET_ACTION",
    "NOT_APPLIED_NOTE",
    "NOT_GENERATED_NOTE",
    "NO_DISPLAY_ITEM",
    "NO_METHOD_NOTE",
    "NO_TARGET_NOTE",
    "PRESET_LABELS",
    "SELECTABLE",
    "UNSET_TARGET_ITEM",
    "CalibratePage",
    "ModeCard",
]
