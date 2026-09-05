"""DDC/CI control surface.

Every control here stands for one action the manifest declares, and the session
decides what each one is. The page writes nothing to a monitor and holds no
private notion of what is permitted.
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

from calibrate_pro.application.outcomes import ActionOutcome
from calibrate_pro.application.results import DetectionSummary
from calibrate_pro.gui.action_binding import ActionBinder
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

        row, self._brightness_slider, _ = _make_slider_row(
            "Brightness",
            SLIDER_STYLE,
            initial=50,
        )
        self._stage("ddc.stage.brightness", self._brightness_slider)
        bc_layout.addLayout(row)

        row, self._contrast_slider, _ = _make_slider_row(
            "Contrast",
            SLIDER_STYLE,
            initial=50,
        )
        self._stage("ddc.stage.contrast", self._contrast_slider)
        bc_layout.addLayout(row)

        layout.addWidget(bc_card)

        # --- RGB Gain ---
        gain_card, gain_layout = Card.with_layout(spacing=14)

        gain_heading = QLabel("RGB Gain (highlights)")
        gain_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT};")
        gain_layout.addWidget(gain_heading)

        row, self._red_gain_slider, _ = _make_slider_row(
            "Red",
            RED_SLIDER_STYLE,
            initial=50,
            label_color=C.RED,
        )
        self._stage("ddc.stage.red_gain", self._red_gain_slider)
        gain_layout.addLayout(row)

        row, self._green_gain_slider, _ = _make_slider_row(
            "Green",
            GREEN_SLIDER_STYLE,
            initial=50,
            label_color=C.GREEN,
        )
        self._stage("ddc.stage.green_gain", self._green_gain_slider)
        gain_layout.addLayout(row)

        row, self._blue_gain_slider, _ = _make_slider_row(
            "Blue",
            BLUE_SLIDER_STYLE,
            initial=50,
            label_color=C.CYAN,
        )
        self._stage("ddc.stage.blue_gain", self._blue_gain_slider)
        gain_layout.addLayout(row)

        layout.addWidget(gain_card)

        # --- RGB Offset (Black Level) ---
        offset_card, offset_layout = Card.with_layout(spacing=14)

        offset_heading = QLabel("RGB Offset (shadows)")
        offset_heading.setStyleSheet(f"font-size: 13px; font-weight: 500; color: {C.TEXT};")
        offset_layout.addWidget(offset_heading)

        row, self._red_offset_slider, _ = _make_slider_row(
            "Red",
            RED_SLIDER_STYLE,
            initial=50,
            label_color=C.RED,
        )
        self._stage("ddc.stage.red_black_level", self._red_offset_slider)
        offset_layout.addLayout(row)

        row, self._green_offset_slider, _ = _make_slider_row(
            "Green",
            GREEN_SLIDER_STYLE,
            initial=50,
            label_color=C.GREEN,
        )
        self._stage("ddc.stage.green_black_level", self._green_offset_slider)
        offset_layout.addLayout(row)

        row, self._blue_offset_slider, _ = _make_slider_row(
            "Blue",
            BLUE_SLIDER_STYLE,
            initial=50,
            label_color=C.CYAN,
        )
        self._stage("ddc.stage.blue_black_level", self._blue_offset_slider)
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
        read_btn.setProperty("primary", True)
        read_btn.setStyleSheet(primary_button_style(padding="6px 22px"))
        self._command("ddc.read_current", read_btn)
        btn_row.addWidget(read_btn)

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

        A slider or a combo emits no trigger signal, so nothing is connected
        here. Disabling it now means a page nobody bound offers no control that
        would silently do nothing.
        """
        self._staged_controls[action_id] = control
        control.setEnabled(False)
        control.setToolTip(UNBOUND_REASON)

    def _command(self, action_id: str, button: QPushButton) -> None:
        """Record one button as standing for an action, and disable it."""
        self._command_controls[action_id] = button
        button.setEnabled(False)
        button.setToolTip(UNBOUND_REASON)

    def bind_actions(
        self,
        binder: ActionBinder,
        unhandled: Callable[[str], ActionOutcome[object]],
    ) -> None:
        """Render every control here from the session's answer about its action.

        The page used to write a refusal per control. A slider recorded its
        value into a dictionary nothing read, under a line announcing a staged
        change toward a plan that was never assembled, and the raw VCP buttons
        printed a sentence naming a version number. None of it came from the
        manifest, so this page could disagree with the session about what it
        would do.

        The manifest decides now. Value controls are rendered without a trigger
        because they have none; a button is connected, and using one asks the
        session, which answers with a refusal the window reports.
        """
        for action_id, control in self._staged_controls.items():
            binder.bind(action_id, control, partial(unhandled, action_id), hides=False, connect=False)
        for action_id, button in self._command_controls.items():
            binder.bind(action_id, button, partial(unhandled, action_id), hides=False)
        self._status_label.setText(binder.disposition_of(DDC_TRANSACTION).reason or "")

    # Monitor list

    def render_session(self, summary: DetectionSummary) -> None:
        """List the displays one detection pass observed, and only those.

        The page used to enumerate displays itself while it was being built, so
        its selector could name hardware that no action had looked at. The list
        now comes from the session, which means an entry here stands for an
        observation the session recorded.
        """
        self._display_combo.clear()
        self._monitors = [
            {"name": display.safe_label, "display_id": display.platform_display_id}
            for display in summary.dashboard.displays
        ]
        self._status_dot.set_color(C.YELLOW)
        if not self._monitors:
            self._current_monitor = None
            self._display_combo.addItem("The last detection pass found no usable display")
            return
        for monitor in self._monitors:
            self._display_combo.addItem(str(monitor["name"]))
        self._current_monitor = self._monitors[0]

    def _on_display_changed(self, index: int):
        """Follow the selector, which chooses among observations already made."""
        if 0 <= index < len(self._monitors):
            self._current_monitor = self._monitors[index]
