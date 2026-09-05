"""The refusals a session raises, written once so they read the same everywhere.

A refusal is not an error in the program. It is the session declining to do
something the current state does not allow, and it carries a code a surface can
branch on, a summary the operator reads, and the next action that would make the
attempt succeed. Keeping them in one module stops the same refusal from being
worded three different ways in three call sites.
"""

from __future__ import annotations

from calibrate_pro.application.outcomes import ActionFailure

NO_DETECTION = "NO_DETECTION"
UNKNOWN_DISPLAY = "UNKNOWN_DISPLAY"
SESSION_TRANSITION_REJECTED = "SESSION_TRANSITION_REJECTED"
NO_SEALED_PLAN = "NO_SEALED_PLAN"
NO_EXPORT_DIRECTORY = "NO_EXPORT_DIRECTORY"
EXPORT_FAILED = "EXPORT_FAILED"

_COMPLETE_EARLIER_STEPS = "Complete the earlier steps this action depends on."
_GENERATE_FIRST = "Generate a calibration bundle before continuing."


def policy_refusal(code: str, summary: str, next_action: str) -> ActionFailure:
    """Build a refusal that describes a rule, not a fault."""
    return ActionFailure(
        code=code,
        summary=summary,
        retryable=False,
        next_action=next_action,
        category="policy",
    )


def no_display_selected() -> ActionFailure:
    return policy_refusal(
        NO_DETECTION,
        "No display is selected in this session.",
        "Detect displays and select one before continuing.",
    )


def unknown_display() -> ActionFailure:
    return policy_refusal(
        UNKNOWN_DISPLAY,
        "That display is not in the current detection result.",
        "Detect displays again and choose one of the displays it reports.",
    )


def incomplete_setup() -> ActionFailure:
    return policy_refusal(
        NO_DETECTION,
        "Generation needs a selected display, a method, and a target.",
        "Choose a display, a calibration method, and a target preset.",
    )


def no_sealed_plan() -> ActionFailure:
    return policy_refusal(NO_SEALED_PLAN, "This session holds no sealed plan.", _GENERATE_FIRST)


def no_such_asset() -> ActionFailure:
    return policy_refusal(
        NO_SEALED_PLAN,
        "This session holds no generated asset in that format.",
        "Generate a calibration bundle before exporting a single format.",
    )


def no_export_directory() -> ActionFailure:
    return policy_refusal(
        NO_EXPORT_DIRECTORY,
        "No writable export directory has been chosen.",
        "Choose an export directory, then export again.",
    )


def transition_rejected(reason: str) -> ActionFailure:
    """Report an illegal workflow transition using the rule's own wording."""
    return policy_refusal(SESSION_TRANSITION_REJECTED, reason, _COMPLETE_EARLIER_STEPS)


def export_failed() -> ActionFailure:
    """Report a publish the filesystem refused, which a retry might fix."""
    return ActionFailure(
        code=EXPORT_FAILED,
        summary="The export could not be written to the chosen directory.",
        retryable=True,
        next_action="Choose a directory this account can write to, then export again.",
        category="filesystem",
    )


__all__ = [
    "EXPORT_FAILED",
    "NO_DETECTION",
    "NO_EXPORT_DIRECTORY",
    "NO_SEALED_PLAN",
    "SESSION_TRANSITION_REJECTED",
    "UNKNOWN_DISPLAY",
    "export_failed",
    "incomplete_setup",
    "no_display_selected",
    "no_export_directory",
    "no_sealed_plan",
    "no_such_asset",
    "policy_refusal",
    "transition_rejected",
    "unknown_display",
]
