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
NO_HANDLER = "NO_HANDLER"
NOT_A_UI_ACTION = "NOT_A_UI_ACTION"
NO_SELECTED_PROFILE = "NO_SELECTED_PROFILE"
PROFILE_SEAL_BROKEN = "PROFILE_SEAL_BROKEN"
PROFILE_UNREADABLE = "PROFILE_UNREADABLE"
NO_MEASUREMENT = "NO_MEASUREMENT"
MEASUREMENT_REFUSED = "MEASUREMENT_REFUSED"

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


def no_such_profile() -> ActionFailure:
    return policy_refusal(
        NO_SELECTED_PROFILE,
        "That profile is not in the current listing.",
        "Refresh the profile list, then choose one of the profiles it reports.",
    )


def no_verified_profile() -> ActionFailure:
    return policy_refusal(
        NO_SELECTED_PROFILE,
        "No inspected profile is selected in this session.",
        "Select a published profile so its files can be checked, then export it.",
    )


def profile_seal_broken() -> ActionFailure:
    """Refuse to copy a bundle whose files no longer match its own manifest.

    The manifest is what makes a copy checkable somewhere else. Copying files
    that have drifted away from it would produce a second bundle carrying a
    manifest that describes something other than what sits beside it.
    """
    return policy_refusal(
        PROFILE_SEAL_BROKEN,
        "The files in this profile no longer match the digests its manifest records.",
        "Inspect the profile to see which files changed, then generate it again.",
    )


def profile_unreadable(reason: str) -> ActionFailure:
    """Report a chosen panel profile this build could not read.

    The reason is the filesystem's or the parser's own, so the operator is told
    what stopped the read rather than that the file was rejected. A different
    file may well work, which is what makes this retryable.
    """
    return ActionFailure(
        code=PROFILE_UNREADABLE,
        summary=f"That panel profile could not be read: {reason}",
        retryable=True,
        next_action="Choose a .json panel profile this account can read.",
        category="filesystem",
    )


def no_handler(action_id: str) -> ActionFailure:
    """Report an action this composition offers no way to perform.

    Every action in this state is hidden or disabled by the manifest, so the
    runner refuses it before the operation runs. Raising here is what makes that
    a checked guarantee: if a policy change ever enabled one of these, the
    surface reports a refusal instead of appearing to work.
    """
    return policy_refusal(
        NO_HANDLER,
        f"This build has no way to perform {action_id}.",
        "Use a build where this action is qualified.",
    )


def not_a_ui_action(action_id: str) -> ActionFailure:
    """Refuse to run a side-effecting action through the interface-only path."""
    return policy_refusal(
        NOT_A_UI_ACTION,
        f"{action_id} changes something outside the interface.",
        "Perform this action through the session method that owns its effect.",
    )


def transition_rejected(reason: str) -> ActionFailure:
    """Report an illegal workflow transition using the rule's own wording."""
    return policy_refusal(SESSION_TRANSITION_REJECTED, reason, _COMPLETE_EARLIER_STEPS)


def no_measurement() -> ActionFailure:
    """Refuse measured artifacts to a session that holds no run for its display.

    This covers two states with one answer, because the operator's next move is
    the same for both: no measurement has been taken, or one was taken on a
    display that is no longer selected and was dropped with it.
    """
    return policy_refusal(
        NO_MEASUREMENT,
        "This session holds no instrument measurement of the selected display.",
        "Run a measurement on this display, or choose the sensorless method.",
    )


def measurement_refused(reason: str) -> ActionFailure:
    """Report a run the instrument or the operator stopped.

    Retryable, unlike most refusals here. A run ends early for reasons that
    pass: an unplugged sensor, a patch window the operator closed, a reading
    the arithmetic could not turn into a display. The reason comes from the
    measurement core and is passed through rather than summarized, because a
    generic message would hide which of those it was.
    """
    return ActionFailure(
        code=MEASUREMENT_REFUSED,
        summary=reason,
        retryable=True,
        next_action="Check the instrument and the patch window, then measure again.",
        category="measurement",
    )


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
    "MEASUREMENT_REFUSED",
    "NO_DETECTION",
    "NOT_A_UI_ACTION",
    "NO_EXPORT_DIRECTORY",
    "NO_HANDLER",
    "NO_MEASUREMENT",
    "NO_SEALED_PLAN",
    "NO_SELECTED_PROFILE",
    "PROFILE_SEAL_BROKEN",
    "PROFILE_UNREADABLE",
    "SESSION_TRANSITION_REJECTED",
    "UNKNOWN_DISPLAY",
    "export_failed",
    "incomplete_setup",
    "measurement_refused",
    "no_display_selected",
    "no_export_directory",
    "no_handler",
    "no_measurement",
    "no_sealed_plan",
    "no_such_asset",
    "no_such_profile",
    "no_verified_profile",
    "not_a_ui_action",
    "policy_refusal",
    "profile_seal_broken",
    "profile_unreadable",
    "transition_rejected",
    "unknown_display",
]
