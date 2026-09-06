"""Answering a previewed plan, which the window had no way to do.

The manifest declares two conditional actions here, ``calibration.confirm_plan``
and ``calibration.decline_plan``, and names their surfaces ``dialog.plan.accept``
and ``dialog.plan.decline``. No window presented either one. The command line
did: ``verify`` and ``generate`` both confirm the plan they printed before they
report a figure or write a bundle.

That gap closed the rest of the window. Sensorless verification requires a
confirmed plan, saving a report requires verified evidence, and every active
export requires the same, so a session driven from the window stopped at the
preview and could reach none of them. The three pages after Calibrate were
reachable and permanently refused.

Accepting writes nothing to a display. In the production composition the
acceptance calls ``acknowledge_without_apply``, and every action classified as a
physical mutation is declared disabled in this build. What acceptance does is
record a decision against one plan digest, which is what verification then reads
and what a saved report cites. The dialog says that where the button is, because
"Accept" beside a list of ICC and LUT files otherwise reads as a promise to load
them.
"""

from __future__ import annotations

from collections.abc import Callable

from calibrate_pro.qt_runtime import configure_qt_api

configure_qt_api()

from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from calibrate_pro.application.outcomes import ActionError, ActionOutcome
from calibrate_pro.application.results import PlanDecision, PlanPreview, reach_text
from calibrate_pro.application.surface import SurfaceActions
from calibrate_pro.gui.action_binding import ActionBinder, Restriction, refusal_message
from calibrate_pro.gui.theme import C, primary_button_style, secondary_button_style
from calibrate_pro.targets.coverage import GamutContainment
from calibrate_pro.workflow import ApplyPlan

#: What accepting does in this build, beside the button that does it. The
#: sentence is deliberately about the display rather than about the session,
#: because that is the thing an operator is worried about when they read
#: "Accept" under a list of profile files.
ACCEPT_NOTE = (
    "Accepting records this exact plan as the one this session confirmed. It sends nothing "
    "to the display and loads no profile. Verification and any saved report read the plan "
    "you accept here, and cite it by the digest above."
)

#: What declining does. Stated because a declined preview is not a no-op: the
#: plan stops being current, so the figures that would have cited it are closed
#: again until another plan is generated and previewed.
DECLINE_NOTE = "Declining drops this plan. Generating again produces a new one with its own digest."

#: Printed where a plan names no asset of that kind. An empty row would read as
#: a file the plan carries and did not name.
NOT_IN_PLAN = "not in this plan"

#: What the DDC row says when a plan proposes no control changes. A plan that
#: proposes some still sends none, which the accept note covers.
NO_DDC_CHANGES = "none proposed"

_DIALOG_STYLE = (
    f"QDialog {{ background: {C.BG}; }}"
    f"QLabel {{ color: {C.TEXT}; }}"
    f"QFrame#planCard {{ background: {C.SURFACE}; border: 1px solid {C.BORDER}; "
    f"  border-radius: 10px; padding: 12px; }}"
)

_DIGEST_STYLE = (
    f"font-family: Consolas, monospace; font-size: 11px; color: {C.TEXT2}; "
    f"padding: 8px; background: {C.SURFACE2}; border: 1px solid {C.BORDER}; border-radius: 8px;"
)


def _asset(path: str | None, digest: str | None) -> str:
    """Name one asset with the digest that seals it, or say the plan has none.

    There is no branch for a path arriving without a digest. ``ApplyPlan``
    refuses that pair when it is constructed, which is what makes every asset
    row a citation rather than a filename, and a branch here rendering the path
    alone would present an unsealed asset as though the plan carried it.
    """
    if not path:
        return NOT_IN_PLAN
    return f"{path}  {digest}"


def plan_rows(plan: ApplyPlan, reach: GamutContainment | None = None) -> tuple[tuple[str, str], ...]:
    """Lay out one plan as the field-and-value pairs the terminal prints.

    The window and the terminal describe a plan from the same object and in the
    same order, so an operator comparing a screenshot against ``calibrate-pro
    verify`` output is reading two renderings of one thing. Every asset row is
    present whether or not the plan carries that asset, because a row that
    appears only when a file exists makes an absent file invisible. The reach
    row is there for the same reason: a target this display covers and a target
    it cannot touch have to be told apart by reading the row, not by noticing
    that one of them printed an extra line.
    """
    return (
        ("display", plan.display_id),
        ("method", plan.method.value),
        ("white point", plan.target_whitepoint),
        ("tone response", plan.target_gamma),
        ("gamut", plan.target_gamut),
        ("gamut reach", reach_text(reach)),
        ("ICC profile", _asset(plan.icc_profile_path, plan.icc_profile_sha256)),
        ("VCGT ramp", _asset(plan.vcgt_path, plan.vcgt_sha256)),
        ("dwm LUT", _asset(plan.dwm_lut_path, plan.dwm_lut_sha256)),
        ("DDC changes", ddc_text(plan)),
        ("files", ", ".join(plan.output_files) if plan.output_files else NOT_IN_PLAN),
    )


def ddc_text(plan: ApplyPlan) -> str:
    """State the control changes a plan proposes, by name and value."""
    if not plan.ddc_changes:
        return NO_DDC_CHANGES
    return ", ".join(f"{name} {value}" for name, value in plan.ddc_changes)


def _field(name: str, value: str) -> QWidget:
    """One row of the plan card, read left to right as name then value."""
    row = QWidget()
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 2, 0, 2)
    box.setSpacing(12)

    label = QLabel(name)
    label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
    label.setFixedWidth(110)
    box.addWidget(label)

    text = QLabel(value)
    text.setStyleSheet(f"font-size: 11px; color: {C.TEXT};")
    text.setWordWrap(True)
    box.addWidget(text, 1)
    return row


def _note(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"font-size: 11px; color: {C.TEXT2};")
    label.setWordWrap(True)
    return label


class PlanConfirmationDialog(QDialog):
    """The plan the session sealed, and the two answers it accepts.

    The dialog holds its own binder for the same reason the add-profile dialog
    does: the window's binder outlives every dialog, so a control registered
    there would still be refreshed after this one was destroyed. The window
    refreshes itself when the dialog closes, which is what carries an acceptance
    out to the Verify page.
    """

    def __init__(
        self,
        service: SurfaceActions,
        preview: PlanPreview,
        *,
        accept: Callable[[], ActionOutcome[PlanDecision]],
        decline: Callable[[], ActionOutcome[PlanDecision]],
        restrict: Restriction | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.preview = preview
        self._accept = accept
        self._decline = decline
        self._decision: PlanDecision | None = None
        self._binder = ActionBinder(service, report=self.show_message, restrict=restrict)
        self.setWindowTitle("Confirm Calibration Plan")
        self.setMinimumSize(560, 480)
        self.setStyleSheet(_DIALOG_STYLE)
        self._build()
        self._bind()

    # -- construction -------------------------------------------------------

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        heading = QLabel("Confirm Calibration Plan")
        heading.setStyleSheet(f"font-size: 18px; font-weight: 500; color: {C.TEXT};")
        layout.addWidget(heading)

        self._digest_label = QLabel(f"plan sha256: {self.preview.plan_sha256}")
        self._digest_label.setStyleSheet(_DIGEST_STYLE)
        self._digest_label.setWordWrap(True)
        layout.addWidget(self._digest_label)

        layout.addWidget(self._build_plan_card())
        layout.addWidget(_note(ACCEPT_NOTE))
        layout.addWidget(_note(DECLINE_NOTE))
        layout.addStretch()

        self._message = QLabel("")
        self._message.setStyleSheet(f"font-size: 11px; color: {C.YELLOW};")
        self._message.setWordWrap(True)
        self._message.hide()
        layout.addWidget(self._message)
        layout.addLayout(self._build_buttons())

    def _build_plan_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("planCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(12, 12, 12, 12)
        box.setSpacing(0)
        for name, value in plan_rows(self.preview.plan, self.preview.gamut_reach):
            box.addWidget(_field(name, value))
        return card

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()

        self._decline_btn = QPushButton("Decline")
        self._decline_btn.setStyleSheet(secondary_button_style())
        self._decline_btn.setFixedHeight(38)
        row.addWidget(self._decline_btn)

        self._accept_btn = QPushButton("Accept Plan")
        self._accept_btn.setStyleSheet(primary_button_style())
        self._accept_btn.setFixedHeight(38)
        row.addWidget(self._accept_btn)
        return row

    def _bind(self) -> None:
        """Hand both buttons to the resolver, which owns whether either opens."""
        self._binder.bind(
            "calibration.decline_plan",
            self._decline_btn,
            self._decline,
            on_success=self._decided,
            on_refusal=self._refused,
            hides=False,
        )
        self._binder.bind(
            "calibration.confirm_plan",
            self._accept_btn,
            self._accept,
            on_success=self._decided,
            on_refusal=self._refused,
            hides=False,
        )

    # -- answering ----------------------------------------------------------

    def _decided(self, decision: PlanDecision) -> None:
        """Close on the session's answer, keeping the decision it returned.

        The decision is kept rather than reported here so the caller renders it.
        A dialog that closes on acceptance and also announces one would put the
        sentence where the operator is no longer looking.
        """
        self._decision = decision
        self.accept()

    def _refused(self, error: ActionError) -> None:
        """Stay open on a refusal, so the plan is still in front of the reason."""
        self.show_message(refusal_message(error), "warning")

    def decision(self) -> PlanDecision | None:
        """What the session answered, or nothing if the operator closed the dialog."""
        return self._decision

    # -- reporting ----------------------------------------------------------

    def show_message(self, message: str, level: str = "info") -> None:
        """Report inside the dialog, where the operator is looking."""
        del level
        self._message.setText(message)
        self._message.setVisible(bool(message))


__all__ = [
    "ACCEPT_NOTE",
    "DECLINE_NOTE",
    "NOT_IN_PLAN",
    "NO_DDC_CHANGES",
    "PlanConfirmationDialog",
    "ddc_text",
    "plan_rows",
]
