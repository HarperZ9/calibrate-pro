"""What opens the lane that writes into Windows colour management, and what does not.

Six actions in the shipped manifest are gated on the profile-store predicates.
Every one of them changes a machine the operator keeps using after this
application closes, so the interesting question is not whether a qualified
session can run them. It is whether each predicate closes them on its own.

The list of actions is not typed out and trusted here. It is read back out of
the manifest, so an action added to the lane and not to this file fails the
coverage check rather than going untested. The per-predicate checks are read out
of the manifest too, which makes them a drift check as well: the resolver gates
these actions in code, and `required_capabilities` is a declaration beside that
code. A capability declared and not enforced fails here, and so does one
enforced without being declared, because the resolver would then close an action
this file expected to stay open.
"""

from __future__ import annotations

import json
from dataclasses import replace
from importlib import resources

import pytest

from calibrate_pro.application.actions import ActionDisposition, ActionRegistry
from tests.action_context_support import action_context

#: The session predicates that answer for the machine's colour profile store.
#: An action gated on any of these is part of this lane.
SYSTEM_PROFILE_PREDICATES = frozenset(
    {
        "system_profiles_qualified",
        "system_profile_writes_qualified",
        "selected_profile_installed",
        "restorable_system_profiles",
        "switchable_system_profiles",
    }
)

#: What a qualified session may do to this machine's colour management. Written
#: out so the coverage check below has something to hold the manifest against.
SYSTEM_PROFILE_ACTIONS = (
    "profile.system.read",
    "profile.install",
    "profile.activate",
    "profile.delete",
    "tray.switch_profile",
    "display.restore_defaults",
)

#: Everything in the lane except the reading. These change the machine, and none
#: of them is offered to a session that only demonstrates the workflow.
SYSTEM_PROFILE_WRITES = tuple(action_id for action_id in SYSTEM_PROFILE_ACTIONS if action_id != "profile.system.read")


def _declared_capabilities() -> dict[str, tuple[str, ...]]:
    """Each lane action in the shipped manifest, with the capabilities it declares."""
    payload = resources.files("calibrate_pro").joinpath("resources", "action-capabilities.json").read_bytes()
    manifest = json.loads(payload)
    declared = {}
    for action in manifest["actions"]:
        capabilities = tuple(action["required_capabilities"])
        if SYSTEM_PROFILE_PREDICATES.intersection(capabilities):
            declared[action["action_id"]] = capabilities
    return declared


DECLARED = _declared_capabilities()

#: One case per capability an action in this lane declares, so no declared
#: predicate goes unexercised and none of them can be removed quietly.
DECLARED_PAIRS = [(action_id, capability) for action_id, caps in DECLARED.items() for capability in caps]


def test_the_actions_named_here_are_the_ones_the_manifest_gates_on_the_store() -> None:
    registry = ActionRegistry.load_default()

    assert set(DECLARED) == set(SYSTEM_PROFILE_ACTIONS)
    for action_id in SYSTEM_PROFILE_ACTIONS:
        assert action_id in registry.action_ids


def test_a_qualified_session_is_offered_every_action_in_the_lane() -> None:
    """A store that answered, a reading in hand, a sealed bundle, and a journal."""
    registry = ActionRegistry.load_default()
    context = action_context()

    for action_id in SYSTEM_PROFILE_ACTIONS:
        assert registry.resolve(action_id, context).disposition is ActionDisposition.ENABLED


@pytest.mark.parametrize(("action_id", "capability"), DECLARED_PAIRS)
def test_every_declared_capability_closes_its_action_on_its_own(action_id: str, capability: str) -> None:
    registry = ActionRegistry.load_default()
    baseline = action_context()

    assert isinstance(getattr(baseline, capability), bool), f"{capability} is not a predicate this test can close"
    assert registry.resolve(action_id, baseline).disposition is ActionDisposition.ENABLED
    resolved = registry.resolve(action_id, replace(baseline, **{capability: False}))
    assert resolved.disposition is ActionDisposition.DISABLED
    assert resolved.reason


def test_the_proof_session_may_read_the_store_and_may_not_change_it() -> None:
    """A session built to demonstrate the workflow against files gets no write.

    Reading is left open because it performs nothing and answers about the
    machine rather than about the session. Every write is closed, because a
    profile registered by a demonstration would outlive it.
    """
    registry = ActionRegistry.load_default()
    proof = action_context(fake_acceptance=True)

    assert registry.resolve("profile.system.read", proof).disposition is ActionDisposition.ENABLED
    for action_id in SYSTEM_PROFILE_WRITES:
        assert registry.resolve(action_id, proof).disposition is ActionDisposition.DISABLED


def test_nothing_in_the_lane_is_offered_without_a_display_to_answer_for() -> None:
    """A session with no display selected closes the lane, reading included.

    Every one of these is asked of a display: which profiles it lists, which it
    hands out, and which of them this product put there. The session derives
    each store predicate from a reading it takes per display, so none of them
    can be open while no display is selected. The whole state is set here rather
    than one field, because a context holding a reading for a display that was
    never selected is not a session this product can be in.
    """
    registry = ActionRegistry.load_default()
    unselected = action_context(
        selected_display_id=None,
        system_profiles_qualified=False,
        system_profile_writes_qualified=False,
        selected_profile_installed=False,
        restorable_system_profiles=False,
        switchable_system_profiles=False,
    )

    for action_id in SYSTEM_PROFILE_ACTIONS:
        assert registry.resolve(action_id, unselected).disposition is ActionDisposition.DISABLED


def test_a_session_that_has_not_read_the_store_may_read_it_and_change_nothing() -> None:
    """Every write is reported by comparing two readings, and the first is missing."""
    registry = ActionRegistry.load_default()
    unread = action_context(system_profile_writes_qualified=False)

    assert registry.resolve("profile.system.read", unread).disposition is ActionDisposition.ENABLED
    for action_id in SYSTEM_PROFILE_WRITES:
        assert registry.resolve(action_id, unread).disposition is ActionDisposition.DISABLED


def test_a_display_carrying_nothing_of_ours_can_still_be_switched_to_another_profile() -> None:
    """Restoring and switching are separate questions about the same display.

    A restore takes off what this product attached, so a display carrying none
    of it has nothing to restore. Switching chooses among the profiles the
    machine holds, the display vendor's own included, which stays available.
    """
    registry = ActionRegistry.load_default()
    nothing_of_ours = action_context(restorable_system_profiles=False)

    assert registry.resolve("display.restore_defaults", nothing_of_ours).disposition is ActionDisposition.DISABLED
    assert registry.resolve("tray.switch_profile", nothing_of_ours).disposition is ActionDisposition.ENABLED


def test_installing_a_bundle_and_acting_on_the_machine_copy_are_gated_apart() -> None:
    """Installing asks about the bundle. Activating and removing ask about the store.

    A bundle whose files no longer match its manifest may not be registered,
    and a bundle the machine never registered may not be activated or removed.
    Neither answer implies the other, so a session can be offered one and
    refused the other.
    """
    registry = ActionRegistry.load_default()
    drifted = action_context(selected_profile_reparsed=False)
    absent = action_context(selected_profile_installed=False)

    assert registry.resolve("profile.install", drifted).disposition is ActionDisposition.DISABLED
    assert registry.resolve("profile.install", absent).disposition is ActionDisposition.ENABLED
    for action_id in ("profile.activate", "profile.delete"):
        assert registry.resolve(action_id, drifted).disposition is ActionDisposition.ENABLED
        assert registry.resolve(action_id, absent).disposition is ActionDisposition.DISABLED


def test_no_write_in_the_lane_is_offered_without_a_journal_to_record_it() -> None:
    registry = ActionRegistry.load_default()
    unjournalled = action_context(journal_ready=False)

    for action_id in SYSTEM_PROFILE_WRITES:
        assert registry.resolve(action_id, unjournalled).disposition is ActionDisposition.DISABLED
