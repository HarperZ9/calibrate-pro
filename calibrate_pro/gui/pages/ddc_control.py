"""DDC/CI control surface.

Every control here stands for one action the manifest declares, and the session
decides what each one is. The page opens no display and holds no private notion
of what is permitted.

A slider is a request, not a state. Its range and its position come from what
the display answered when the session read it, and moving one asks the session
to stage a value, which changes nothing on the panel. The write happens once,
for the whole staged set, when the operator applies it.

Nothing here fills a control from a value this page invented. Before a reading
the sliders are disabled with the resolver's own reason on them, because a
slider showing 50 for a display nobody has read would be a number the product
made up and presented as the display's.
"""

from collections.abc import Callable
from functools import partial
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.application.control_results import ControlRestore, ControlTransaction, StagedControl
from calibrate_pro.application.monitor_controls import (
    CONTROL_ACTIONS,
    STAGE_ACTION_CODES,
    MonitorControl,
    MonitorReading,
)
from calibrate_pro.application.outcomes import ActionError, ActionOutcome
from calibrate_pro.application.results import DetectionSummary, DisplaySelection
from calibrate_pro.gui.action_binding import ActionBinder, SurfaceBinding
from calibrate_pro.gui.app import C, Card, Heading, StatusDot
from calibrate_pro.gui.theme import primary_button_style, secondary_button_style

# Slider Stylesheet

SLIDER_STYLE = f"""
    QSlider::groove:horizontal {{
        background: {C.BORDER}; height: 6px; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {C.ACCENT}; width: 16px; height: 16px;
        margin: -5px 0; border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {C.ACCENT}; border-radius: 3px;
    }}
"""

RED_SLIDER_STYLE = f"""
    QSlider::groove:horizontal {{
        background: {C.BORDER}; height: 6px; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {C.RED}; width: 16px; height: 16px;
        margin: -5px 0; border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {C.RED}; border-radius: 3px;
    }}
"""

GREEN_SLIDER_STYLE = f"""
    QSlider::groove:horizontal {{
        background: {C.BORDER}; height: 6px; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {C.GREEN}; width: 16px; height: 16px;
        margin: -5px 0; border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {C.GREEN}; border-radius: 3px;
    }}
"""

BLUE_SLIDER_STYLE = f"""
    QSlider::groove:horizontal {{
        background: {C.BORDER}; height: 6px; border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
        background: {C.CYAN}; width: 16px; height: 16px;
        margin: -5px 0; border-radius: 8px;
    }}
    QSlider::sub-page:horizontal {{
        background: {C.CYAN}; border-radius: 3px;
    }}
"""


# Helper: labeled slider row


def _make_slider_row(
    label_text: str,
    style: str,
    min_val: int = 0,
    max_val: int = 100,
    initial: int = 50,
    label_color: str = C.TEXT,
):
    """Create a horizontal row: label -- slider -- value label."""
    row = QHBoxLayout()
    row.setSpacing(12)

    label = QLabel(label_text)
    label.setFixedWidth(80)
    label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {label_color};")
    row.addWidget(label)

    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setMinimum(min_val)
    slider.setMaximum(max_val)
    slider.setValue(initial)
    slider.setStyleSheet(style)
    slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    row.addWidget(slider, stretch=1)

    value_label = QLabel(str(initial))
    value_label.setFixedWidth(36)
    value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    value_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2};")
    row.addWidget(value_label)

    # Wire up the value display
    slider.valueChanged.connect(lambda v: value_label.setText(str(v)))

    return row, slider, value_label


# DDC Control Page


#: What the selector shows before any detection pass has been handed to it.
NO_SESSION_ITEM = "No detection pass has run in this session"

#: The transaction every control on this page depends on. Its resolved reason
#: is what the status line reports, so one sentence from the manifest covers
#: the page rather than a second one written here.
DDC_TRANSACTION = "ddc.apply"

#: What a control says before a session has answered for it. A page built
#: without a binder disables its controls rather than offering one whose
#: trigger goes nowhere.
UNBOUND_REASON = "No session has answered for this control."

#: What a row shows for a control no reading has reported. A number here would
#: be one this page chose, presented where the display's own value goes.
NO_VALUE = "--"

#: The buttons this page performs through a named session method. Everything
#: else it holds is rendered from the manifest and reports its own refusal.
HANDLED_COMMANDS = frozenset({"ddc.read_current", DDC_TRANSACTION, "ddc.restore_defaults", "ddc.raw_read"})


class DDCControlPage(QWidget):
    """DDC/CI staging surface, listing the displays the session observed.

    Nothing on this page reaches a monitor. Brightness and the other allowlisted
    controls are staged for a plan that a confirmed transaction applies, and
    every other control reports that it sent no command. The display list is
    handed in by the window rather than read here, so the page never opens a
    display of its own.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._monitors: list[dict[str, Any]] = []
        self._current_monitor: dict[str, Any] | None = None
        # Filled while the page is built and read when it is bound. A value
        # control emits no trigger signal, so it is kept apart from the buttons,
        # which are connected to the action they stand for.
        self._staged_controls: dict[str, QWidget] = {}
        self._command_controls: dict[str, QPushButton] = {}
        # The eight controls a value can be staged for, and the number shown
        # beside each. Kept apart from the combos and spin boxes above because
        # only these are filled from a reading.
        self._control_sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}
        self._binder: ActionBinder | None = None
        self._stage_bindings: dict[str, SurfaceBinding] = {}
        # The selector goes through the session, so the display this page acts
        # on is the one the rest of the application holds.
        self._select_display: Callable[[str], ActionOutcome[Any]] | None = None
        self._display_binding: SurfaceBinding | None = None
        self._display_id: str | None = None
        # What the session last read off the selected display. Held so a value
        # a stage refused can be put back to the number the display reported,
        # rather than left showing a position that was never accepted.
        self._reading: MonitorReading | None = None
        # Raised while a reading is written into the sliders, so filling the
        # page from what a display said does not ask to stage it back.
        self._syncing = False
        self._build()

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

        # --- Header ---
        layout.addWidget(Heading("DDC/CI Control"))

        # --- Display selector ---
        selector_card, selector_layout = Card.with_layout(
            QHBoxLayout,
            margins=(16, 12, 16, 12),
            spacing=12,
        )

        sel_label = QLabel("Display")
        sel_label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {C.TEXT};")
        selector_layout.addWidget(sel_label)

        self._display_combo = QComboBox()
        self._display_combo.setMinimumWidth(300)
        self._display_combo.addItem(NO_SESSION_ITEM)
        self._display_combo.currentIndexChanged.connect(self._on_display_changed)
        selector_layout.addWidget(self._display_combo, stretch=1)

        self._status_dot = StatusDot(C.TEXT3, 10)
        selector_layout.addWidget(self._status_dot)

        layout.addWidget(selector_card)

        # --- Brightness & Contrast ---
        bc_card, bc_layout = Card.with_layout(spacing=14)

        bc_heading = QLabel("Brightness & Contrast")
        bc_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT};")
        bc_layout.addWidget(bc_heading)

        row, self._brightness_slider, brightness_value = _make_slider_row(
            "Brightness",
            SLIDER_STYLE,
            initial=50,
        )
        self._slider("ddc.stage.brightness", self._brightness_slider, brightness_value)
        bc_layout.addLayout(row)

        row, self._contrast_slider, contrast_value = _make_slider_row(
            "Contrast",
            SLIDER_STYLE,
            initial=50,
        )
        self._slider("ddc.stage.contrast", self._contrast_slider, contrast_value)
        bc_layout.addLayout(row)

        layout.addWidget(bc_card)

        # --- RGB Gain ---
        gain_card, gain_layout = Card.with_layout(spacing=14)

        gain_heading = QLabel("RGB Gain (highlights)")
        gain_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT};")
        gain_layout.addWidget(gain_heading)

        row, self._red_gain_slider, red_gain_value = _make_slider_row(
            "Red",
            RED_SLIDER_STYLE,
            initial=50,
            label_color=C.RED,
        )
        self._slider("ddc.stage.red_gain", self._red_gain_slider, red_gain_value)
        gain_layout.addLayout(row)

        row, self._green_gain_slider, green_gain_value = _make_slider_row(
            "Green",
            GREEN_SLIDER_STYLE,
            initial=50,
            label_color=C.GREEN,
        )
        self._slider("ddc.stage.green_gain", self._green_gain_slider, green_gain_value)
        gain_layout.addLayout(row)

        row, self._blue_gain_slider, blue_gain_value = _make_slider_row(
            "Blue",
            BLUE_SLIDER_STYLE,
            initial=50,
            label_color=C.CYAN,
        )
        self._slider("ddc.stage.blue_gain", self._blue_gain_slider, blue_gain_value)
        gain_layout.addLayout(row)

        layout.addWidget(gain_card)

        # --- RGB Offset (Black Level) ---
        offset_card, offset_layout = Card.with_layout(spacing=14)

        offset_heading = QLabel("RGB Offset (shadows)")
        offset_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT};")
        offset_layout.addWidget(offset_heading)

        row, self._red_offset_slider, red_offset_value = _make_slider_row(
            "Red",
            RED_SLIDER_STYLE,
            initial=50,
            label_color=C.RED,
        )
        self._slider("ddc.stage.red_black_level", self._red_offset_slider, red_offset_value)
        offset_layout.addLayout(row)

        row, self._green_offset_slider, green_offset_value = _make_slider_row(
            "Green",
            GREEN_SLIDER_STYLE,
            initial=50,
            label_color=C.GREEN,
        )
        self._slider("ddc.stage.green_black_level", self._green_offset_slider, green_offset_value)
        offset_layout.addLayout(row)

        row, self._blue_offset_slider, blue_offset_value = _make_slider_row(
            "Blue",
            BLUE_SLIDER_STYLE,
            initial=50,
            label_color=C.CYAN,
        )
        self._slider("ddc.stage.blue_black_level", self._blue_offset_slider, blue_offset_value)
        offset_layout.addLayout(row)

        layout.addWidget(offset_card)

        # --- Display Mode & Gamma ---
        mode_card, mode_layout = Card.with_layout(spacing=14)

        mode_heading = QLabel("Display Mode")
        mode_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT};")
        mode_layout.addWidget(mode_heading)

        combo_style = (
            f"QComboBox {{ background: {C.SURFACE2}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 6px 12px; color: {C.TEXT}; min-width: 160px; }}"
            f"QComboBox::drop-down {{ border: none; width: 24px; }}"
            f"QComboBox QAbstractItemView {{ background: {C.SURFACE}; "
            f"border: 1px solid {C.BORDER}; color: {C.TEXT}; "
            f"selection-background-color: {C.ACCENT}; }}"
        )

        # Picture mode combo
        pic_row = QHBoxLayout()
        pic_row.setSpacing(8)
        pic_label = QLabel("Picture Mode")
        pic_label.setFixedWidth(100)
        pic_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2};")
        pic_row.addWidget(pic_label)
        self._picture_mode_combo = QComboBox()
        self._picture_mode_combo.addItems(
            [
                "Standard",
                "Custom 1",
                "Custom 2",
                "Custom 3",
                "sRGB",
                "Cinema",
                "Game",
                "FPS",
                "RTS",
                "Vivid",
                "Eco",
                "User",
                "Filmmaker",
            ]
        )
        self._picture_mode_combo.setStyleSheet(combo_style)
        self._stage("ddc.unsupported.image_mode", self._picture_mode_combo)
        pic_row.addWidget(self._picture_mode_combo, stretch=1)
        mode_layout.addLayout(pic_row)

        # Color preset combo
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        color_label = QLabel("Color Preset")
        color_label.setFixedWidth(100)
        color_label.setStyleSheet(f"font-size: 12px; color: {C.TEXT2};")
        color_row.addWidget(color_label)
        self._color_preset_combo = QComboBox()
        self._color_preset_combo.addItems(
            [
                "Native",
                "sRGB",
                "4000K",
                "5000K",
                "5500K",
                "6500K",
                "7500K",
                "8200K",
                "9300K",
                "11500K",
                "User 1",
                "User 2",
                "User 3",
            ]
        )
        self._color_preset_combo.setStyleSheet(combo_style)
        self._stage("ddc.unsupported.color_preset", self._color_preset_combo)
        color_row.addWidget(self._color_preset_combo, stretch=1)
        mode_layout.addLayout(color_row)

        # Gamma slider
        gamma_row, self._gamma_slider, _ = _make_slider_row(
            "Gamma",
            SLIDER_STYLE,
            initial=22,
            label_color=C.TEXT,
        )
        self._gamma_slider.setRange(10, 30)
        self._gamma_slider.setValue(22)
        self._stage("ddc.unsupported.gamma", self._gamma_slider)
        mode_layout.addLayout(gamma_row)

        # Factory reset button (specific resets)
        reset_color_btn = QPushButton("Reset Factory Color")
        reset_color_btn.setFixedHeight(30)
        reset_color_btn.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 4px 16px; "
            f"background: {C.SURFACE}; border: 1px solid {C.BORDER}; border-radius: 8px; "
            f"color: {C.TEXT2}; }}"
            f"QPushButton:hover {{ border-color: {C.ACCENT}; }}"
        )
        self._command("ddc.unsupported.factory_color_reset", reset_color_btn)
        mode_layout.addWidget(reset_color_btn)

        layout.addWidget(mode_card)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        btn_row.addStretch()

        read_btn = QPushButton("Read Current")
        read_btn.setFixedHeight(36)
        read_btn.setStyleSheet(secondary_button_style(padding="6px 22px"))
        self._command("ddc.read_current", read_btn)
        btn_row.addWidget(read_btn)

        # The only control on this page that changes a display. Everything
        # above it stages a request, and one press sends the whole staged set.
        apply_btn = QPushButton("Apply Staged")
        apply_btn.setFixedHeight(36)
        apply_btn.setProperty("primary", True)
        apply_btn.setStyleSheet(primary_button_style(padding="6px 22px"))
        self._command(DDC_TRANSACTION, apply_btn)
        btn_row.addWidget(apply_btn)

        reset_btn = QPushButton("Reset to Default")
        reset_btn.setFixedHeight(36)
        reset_btn.setStyleSheet(secondary_button_style(padding="6px 22px", text=C.RED, edge=C.RED))
        self._command("ddc.restore_defaults", reset_btn)
        btn_row.addWidget(reset_btn)

        layout.addLayout(btn_row)

        # Status label for DDC feedback
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"font-size: 11px; color: {C.TEXT3};")
        layout.addWidget(self._status_label)

        # --- Advanced: Raw VCP Read/Write ---
        adv_card, adv_layout = Card.with_layout(spacing=14)

        adv_heading = QLabel("Advanced: raw VCP read and write")
        adv_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT};")
        adv_layout.addWidget(adv_heading)

        adv_desc = QLabel(
            "Read or write one VCP code. The session decides whether either is "
            "available and refuses the request when it is not."
        )
        adv_desc.setStyleSheet(f"font-size: 11px; color: {C.TEXT3};")
        adv_desc.setWordWrap(True)
        adv_layout.addWidget(adv_desc)

        # VCP Code input row
        code_row = QHBoxLayout()
        code_row.setSpacing(10)

        code_label = QLabel("VCP Code")
        code_label.setFixedWidth(80)
        code_label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {C.TEXT};")
        code_row.addWidget(code_label)

        self._vcp_code_spin = QSpinBox()
        self._vcp_code_spin.setRange(0x00, 0xFF)
        self._vcp_code_spin.setPrefix("0x")
        self._vcp_code_spin.setDisplayIntegerBase(16)
        self._vcp_code_spin.setValue(0x10)  # Default to brightness
        self._vcp_code_spin.setFixedWidth(100)
        self._vcp_code_spin.setFixedHeight(32)
        self._vcp_code_spin.setStyleSheet(
            f"QSpinBox {{ background: {C.SURFACE2}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 4px 8px; color: {C.TEXT}; font-size: 12px; "
            f"font-family: 'Cascadia Code', 'Consolas', monospace; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}"
        )
        self._stage("ddc.raw_read", self._vcp_code_spin)
        code_row.addWidget(self._vcp_code_spin)

        self._vcp_read_btn = QPushButton("Read")
        self._vcp_read_btn.setFixedHeight(32)
        self._vcp_read_btn.setFixedWidth(70)
        self._vcp_read_btn.setProperty("primary", True)
        self._vcp_read_btn.setStyleSheet(primary_button_style(padding="4px 14px", font_size=11))
        self._command("ddc.raw_read", self._vcp_read_btn)
        code_row.addWidget(self._vcp_read_btn)

        code_row.addStretch()
        adv_layout.addLayout(code_row)

        # Write row: value spinbox + write button
        write_row = QHBoxLayout()
        write_row.setSpacing(10)

        write_label = QLabel("Value")
        write_label.setFixedWidth(80)
        write_label.setStyleSheet(f"font-size: 12px; font-weight: 500; color: {C.TEXT};")
        write_row.addWidget(write_label)

        self._vcp_value_spin = QSpinBox()
        self._vcp_value_spin.setRange(0, 65535)
        self._vcp_value_spin.setValue(0)
        self._vcp_value_spin.setFixedWidth(100)
        self._vcp_value_spin.setFixedHeight(32)
        self._vcp_value_spin.setStyleSheet(
            f"QSpinBox {{ background: {C.SURFACE2}; border: 1px solid {C.BORDER}; "
            f"border-radius: 6px; padding: 4px 8px; color: {C.TEXT}; font-size: 12px; "
            f"font-family: 'Cascadia Code', 'Consolas', monospace; }}"
            f"QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; }}"
        )
        self._stage("ddc.raw_write", self._vcp_value_spin)
        write_row.addWidget(self._vcp_value_spin)

        self._vcp_write_btn = QPushButton("Write")
        self._vcp_write_btn.setFixedHeight(32)
        self._vcp_write_btn.setFixedWidth(70)
        self._vcp_write_btn.setStyleSheet(
            secondary_button_style(padding="4px 14px", font_size=11, text=C.RED, edge=C.RED, weight=600)
        )
        self._command("ddc.raw_write", self._vcp_write_btn)
        write_row.addWidget(self._vcp_write_btn)

        write_row.addStretch()
        adv_layout.addLayout(write_row)

        layout.addWidget(adv_card)

        layout.addStretch()
        scroll.setWidget(content)

    # Action binding

    def _stage(self, action_id: str, control: QWidget) -> None:
        """Record one value control as standing for an action, and disable it.

        A combo or a spin box emits no trigger signal, so nothing is connected
        here. Disabling it now means a page nobody bound offers no control that
        would silently do nothing.
        """
        self._staged_controls[action_id] = control
        control.setEnabled(False)
        control.setToolTip(UNBOUND_REASON)

    def _slider(self, action_id: str, slider: QSlider, value_label: QLabel) -> None:
        """Record one slider as staging a control, and leave it showing nothing.

        A slider parked at a position is a number this page picked. Until the
        display has been read there is no number to show, so the row says so
        rather than offering a plausible looking 50 that came from nowhere.
        """
        self._stage(action_id, slider)
        self._control_sliders[action_id] = slider
        self._value_labels[action_id] = value_label
        slider.setValue(slider.minimum())
        value_label.setText(NO_VALUE)

    def _command(self, action_id: str, button: QPushButton) -> None:
        """Record one button as standing for an action, and disable it."""
        self._command_controls[action_id] = button
        button.setEnabled(False)
        button.setToolTip(UNBOUND_REASON)

    def bind_actions(
        self,
        binder: ActionBinder,
        *,
        select_display: Callable[[str], ActionOutcome[Any]],
        read_current: Callable[[], ActionOutcome[MonitorReading]],
        read_raw: Callable[[int], ActionOutcome[MonitorReading]],
        stage: Callable[[str, int], ActionOutcome[StagedControl]],
        apply_controls: Callable[[], ActionOutcome[ControlTransaction]],
        restore_defaults: Callable[[], ActionOutcome[ControlRestore]],
        unhandled: Callable[[str], ActionOutcome[object]],
    ) -> None:
        """Wire every control here to the session method that performs it.

        The page decides nothing about what is offered. Each control is
        rendered from the resolver's answer for its action, and the four that
        reach a display do so through the session, which resolves the action a
        second time and refuses if the state moved underneath the operator.

        The display selector goes through the session too. It used to set a
        field on this page, which meant the operator could pick one monitor
        here and have a write land on whichever display the session held. One
        selection now serves the whole application.
        """
        self._binder = binder
        self._select_display = select_display
        self._display_binding = binder.bind(
            "workflow.select_display",
            self._display_combo,
            self._selected_display,
            on_success=self.render_display,
            hides=False,
            connect=False,
        )
        binder.bind(
            "ddc.read_current",
            self._command_controls["ddc.read_current"],
            read_current,
            on_success=self.render_reading,
            hides=False,
        )
        binder.bind(
            DDC_TRANSACTION,
            self._command_controls[DDC_TRANSACTION],
            apply_controls,
            on_success=self.render_transaction,
            hides=False,
        )
        binder.bind(
            "ddc.restore_defaults",
            self._command_controls["ddc.restore_defaults"],
            restore_defaults,
            on_success=self.render_restore,
            hides=False,
        )
        binder.bind(
            "ddc.raw_read",
            self._command_controls["ddc.raw_read"],
            lambda: read_raw(self._vcp_code_spin.value()),
            on_success=self.render_raw,
            hides=False,
        )
        self._bind_stagers(binder, stage)
        self._bind_remaining(binder, unhandled)
        self.render_status()

    def _bind_stagers(self, binder: ActionBinder, stage: Callable[[str, int], ActionOutcome[StagedControl]]) -> None:
        """Wire the eight sliders that hold a value for a later write.

        A slider has no trigger signal, so the binder renders it and this
        connects it. Both ways a slider settles are covered: a drag stages once
        on release rather than once per pixel, and a wheel or an arrow key
        stages as soon as the value moves.
        """
        for action_id, slider in self._control_sliders.items():
            self._stage_bindings[action_id] = binder.bind(
                action_id,
                slider,
                partial(self._stage_value, stage, action_id),
                on_success=self.render_staged,
                hides=False,
                connect=False,
            )
            slider.sliderReleased.connect(partial(self._settled, action_id))
            slider.valueChanged.connect(partial(self._changed, action_id))

    def _bind_remaining(self, binder: ActionBinder, unhandled: Callable[[str], ActionOutcome[object]]) -> None:
        """Render every control this build does not perform, with its own reason.

        The raw write and the four display mode controls stay refused, and the
        sentence on each comes from the manifest rather than from a line
        written here. The raw read's spin box is rendered from its action too,
        so the number a read would use is enabled exactly when the read is.
        """
        for action_id, control in self._staged_controls.items():
            if action_id in self._control_sliders:
                continue
            binder.bind(action_id, control, partial(unhandled, action_id), hides=False, connect=False)
        for action_id, button in self._command_controls.items():
            if action_id in HANDLED_COMMANDS:
                continue
            binder.bind(action_id, button, partial(unhandled, action_id), hides=False)

    # Staging

    def _stage_value(
        self,
        stage: Callable[[str, int], ActionOutcome[StagedControl]],
        action_id: str,
    ) -> ActionOutcome[StagedControl]:
        """Ask the session to hold whatever value the slider now shows."""
        return stage(action_id, self._control_sliders[action_id].value())

    def _changed(self, action_id: str, value: int) -> None:
        """Stage a value the operator set without dragging the handle."""
        del value
        if self._control_sliders[action_id].isSliderDown():
            return
        self._settled(action_id)

    def _settled(self, action_id: str) -> None:
        """Stage one control, putting the slider back if the session refused it.

        A refused value leaves the handle where the operator dropped it, which
        would show a number the session is not holding. The reading is what the
        display last said, so that is where the handle goes back to.
        """
        if self._syncing:
            return
        binder = self._binder
        binding = self._stage_bindings.get(action_id)
        if binder is None or binding is None:
            return
        if isinstance(binder.invoke(binding), ActionError):
            self._restore_slider(action_id)

    def _restore_slider(self, action_id: str) -> None:
        """Move one slider back to what the display reported for its control."""
        code = STAGE_ACTION_CODES.get(action_id)
        reading = self._reading
        control = reading.control(code) if reading is not None and code is not None else None
        self._show_control(action_id, control)

    def _show_control(self, action_id: str, control: MonitorControl | None) -> None:
        """Put one row on the display's own number and range, or on nothing at all.

        Writing a value into a slider must not ask to stage it back, so the
        guard is raised around the move. Blocking the widget's signals would
        also stop the number beside it from following.
        """
        slider = self._control_sliders[action_id]
        self._syncing = True
        try:
            if control is None:
                slider.setValue(slider.minimum())
                self._value_labels[action_id].setText(NO_VALUE)
                return
            slider.setRange(0, control.maximum)
            slider.setValue(control.current)
            self._value_labels[action_id].setText(str(control.current))
        finally:
            self._syncing = False

    def _show_value(self, action_id: str, value: int) -> None:
        """Move one row onto a number the display reported, leaving its range alone.

        The range came from a reading. A write reports what a control now reads
        at and says nothing about what it can take, so nothing here claims to
        know a new ceiling.
        """
        slider = self._control_sliders[action_id]
        self._syncing = True
        try:
            slider.setValue(value)
            self._value_labels[action_id].setText(str(value))
        finally:
            self._syncing = False

    def _selected_display(self) -> ActionOutcome[Any] | None:
        """Adopt whichever display the selector is on, if it is on one."""
        select = self._select_display
        index = self._display_combo.currentIndex()
        if select is None or not (0 <= index < len(self._monitors)):
            return None
        return select(str(self._monitors[index]["display_id"]))

    def _invoke(self, binding: SurfaceBinding | None) -> None:
        binder = self._binder
        if binder is not None and binding is not None:
            binder.invoke(binding)

    # Rendering

    def render_status(self) -> None:
        """Report the transaction every control here depends on.

        One sentence from the manifest covers the page. A control that is off
        carries the resolver's reason for itself, and this says what the write
        those controls lead to is waiting for.
        """
        binder = self._binder
        if binder is None:
            return
        self._status_label.setText(binder.disposition_of(DDC_TRANSACTION).reason or "")

    def render_session(self, summary: DetectionSummary) -> None:
        """List the displays one detection pass observed, and only those.

        The page used to enumerate displays itself while it was being built, so
        its selector could name hardware that no action had looked at. The list
        now comes from the session, which means an entry here stands for an
        observation the session recorded.

        The signal is blocked while the list is refilled. Without that, drawing
        this page would ask the session to adopt a display nobody picked. A
        detection pass drops whatever was read from the display it re-adopts,
        so every row is cleared to match.
        """
        combo = self._display_combo
        blocked = combo.blockSignals(True)
        try:
            combo.clear()
            self._monitors = [
                {"name": display.safe_label, "display_id": display.platform_display_id}
                for display in summary.dashboard.displays
            ]
            self._status_dot.set_color(C.YELLOW)
            if not self._monitors:
                self._current_monitor = None
                combo.addItem("The last detection pass found no usable display")
            else:
                for monitor in self._monitors:
                    combo.addItem(str(monitor["name"]))
                self._current_monitor = self._monitors[0]
            self._show_display(summary.selected_display_id)
        finally:
            combo.blockSignals(blocked)
        self.clear_reading()

    def render_display(self, selection: DisplaySelection) -> None:
        """Take the session's word for the display, and drop the reading with it.

        Every number on this page was read off the display the operator just
        left, and the ranges under them were reported by that unit. Carrying
        either across would stage a write against a panel that never answered
        for it.
        """
        self._display_id = selection.display_id
        self.clear_reading()

    def render_selection(self, selection: DisplaySelection | None) -> None:
        """Follow the session's own display, whichever page adopted it.

        Reading the session back is the only way to be right here. Another page
        can adopt a display while the operator is looking at it, and the session
        drops what it read off the display it left, so a number still on screen
        would describe a panel these controls no longer address.
        """
        display_id = selection.display_id if selection is not None else None
        if display_id == self._display_id:
            return
        self._display_id = display_id
        combo = self._display_combo
        blocked = combo.blockSignals(True)
        try:
            self._show_display(display_id)
        finally:
            combo.blockSignals(blocked)
        self.clear_reading()

    def render_reading(self, reading: MonitorReading) -> None:
        """Fill every row from what the display answered, and say what it said.

        The range comes from the display too. A panel that drives red gain
        across 0 to 255 gets a slider that goes that far, rather than a 0 to
        100 track this page would then have to scale a write out of.
        """
        self._reading = reading
        for code, action_id in CONTROL_ACTIONS.items():
            if action_id in self._control_sliders:
                self._show_control(action_id, reading.control(code))
        self._status_label.setText(reading.summary)

    def render_raw(self, reading: MonitorReading) -> None:
        """Report one arbitrary code, touching none of the staged rows.

        A raw read asks about a single control and is not the session's
        reading, so nothing above it moves.
        """
        self._status_label.setText(reading.summary)

    def render_staged(self, staged: StagedControl) -> None:
        """Report the value the session is holding for one control."""
        self._status_label.setText(staged.line)

    def render_transaction(self, transaction: ControlTransaction) -> None:
        """Show what each control reads at now, and report the whole write.

        The values are the read-back, not the request. A display that clamped
        brightness to its own ceiling leaves the handle where the panel put it,
        and the summary names both numbers.

        The session dropped its reading when it recorded this, so the rows go
        dead until the display is read again. What they show meanwhile is the
        last thing the display said about itself.
        """
        self._reading = None
        for write in transaction.writes:
            action_id = CONTROL_ACTIONS.get(write.code)
            if action_id is None or action_id not in self._control_sliders:
                continue
            self._show_value(action_id, write.after)
        self._status_label.setText(transaction.summary)

    def render_restore(self, restore: ControlRestore) -> None:
        """Fill the rows from the reading taken after the restore was asked for."""
        self.render_reading(restore.after)
        self._status_label.setText(restore.summary)

    def clear_reading(self) -> None:
        """Forget the display's numbers, because they describe a display or a state this page no longer holds."""
        self._reading = None
        for action_id in self._control_sliders:
            self._show_control(action_id, None)
        self.render_status()

    def _on_display_changed(self, index: int) -> None:
        """Ask the session to adopt the display the operator picked.

        The selector is put back afterwards. A withdrawal or a refusal leaves
        the session on the display it already held, and the control that asked
        would otherwise keep naming the one it was refused.
        """
        if 0 <= index < len(self._monitors):
            self._current_monitor = self._monitors[index]
        self._invoke(self._display_binding)
        self._restore_display()

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
        for index, monitor in enumerate(self._monitors):
            if monitor["display_id"] == display_id:
                self._display_combo.setCurrentIndex(index)
                self._current_monitor = monitor
                return
