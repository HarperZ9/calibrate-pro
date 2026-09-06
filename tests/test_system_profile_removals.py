"""Taking back what this product put into Windows colour management.

Removal is the half of the lane that can damage a machine it does not own. The
profile directory is shared with whatever the display vendor, the GPU driver,
and every previous calibration tool put there, so the bound is the name: only a
profile whose basename this build derives from a bundle it published may be
detached or unregistered. Each test that touches a vendor profile asserts it
survived, rather than asserting only that the intended one went.

Order is load-bearing. Unregistering a file a display still lists leaves that
display naming something the store cannot open, which an operator meets as
colour management that quietly stopped working. The tests read the recorded call
order rather than the end state, because both orders reach the same end state
when nothing fails.
"""

from __future__ import annotations

import pytest

from calibrate_pro.application.system_profile_transactions import remove_profile, restore_display_profiles
from calibrate_pro.application.system_profiles import SystemProfileError, installed_name_for
from tests.system_profile_support import (
    DISPLAY_ID,
    OTHER_DISPLAY_ID,
    VENDOR_PROFILE,
    FakeProfileStore,
)

NAME = installed_name_for("a" * 64)
OTHER = installed_name_for("b" * 64)


def written(store: FakeProfileStore) -> list[str]:
    """The operations that changed the store, in order, with the reads dropped."""
    return [call[0] for call in store.calls if call[0] != "read"]


# -- what may be removed at all ----------------------------------------------


@pytest.mark.parametrize("name", [VENDOR_PROFILE, "sRGB IEC61966-2.1.icm", NAME.upper(), "Calibrate Pro .icc"])
def test_only_a_profile_this_product_installed_may_be_removed(name: str) -> None:
    store = FakeProfileStore(installed=(name,), associated=(name,), default=name)
    with pytest.raises(SystemProfileError) as caught:
        remove_profile(store, DISPLAY_ID, name)
    assert "was not installed by this product" in str(caught.value)
    assert store.calls == []
    assert store.associated[DISPLAY_ID] == [name]


def test_removing_something_the_machine_never_had_is_refused_rather_than_reported() -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)
    with pytest.raises(SystemProfileError) as caught:
        remove_profile(store, DISPLAY_ID, NAME)
    assert "neither installed on this machine nor listed" in str(caught.value)
    assert written(store) == []


# -- removing ----------------------------------------------------------------


def test_removing_detaches_from_the_display_before_it_unregisters_the_file() -> None:
    store = FakeProfileStore(installed=(NAME,), associated=(NAME,), default=NAME)
    removal = remove_profile(store, DISPLAY_ID, NAME)
    assert removal.accepted
    assert written(store) == ["disassociate", "uninstall"]
    assert store.installed == []
    assert store.default[DISPLAY_ID] is None
    assert "now uses no profile" in removal.summary


def test_a_removal_leaves_the_display_using_whatever_windows_fell_back_to() -> None:
    store = FakeProfileStore(
        installed=(VENDOR_PROFILE, NAME),
        associated=(VENDOR_PROFILE, NAME),
        default=NAME,
    )
    removal = remove_profile(store, DISPLAY_ID, NAME)
    assert removal.accepted
    assert store.associated[DISPLAY_ID] == [VENDOR_PROFILE]
    assert store.installed == [VENDOR_PROFILE]
    assert f"now uses {VENDOR_PROFILE}" in removal.summary


def test_a_profile_registered_but_never_attached_is_unregistered_on_its_own() -> None:
    store = FakeProfileStore(installed=(NAME,))
    removal = remove_profile(store, DISPLAY_ID, NAME)
    assert removal.accepted
    assert written(store) == ["uninstall"]


def test_a_display_naming_a_file_the_machine_lost_can_still_be_cleaned_up() -> None:
    store = FakeProfileStore(associated=(NAME,), default=NAME)
    removal = remove_profile(store, DISPLAY_ID, NAME)
    assert removal.accepted
    assert written(store) == ["disassociate"]
    assert store.associated[DISPLAY_ID] == []


def test_a_detach_the_display_refused_stops_before_the_file_is_unregistered() -> None:
    store = FakeProfileStore(installed=(NAME,), associated=(NAME,), default=NAME)
    store.refuse("disassociate", "access is denied")
    with pytest.raises(SystemProfileError) as caught:
        remove_profile(store, DISPLAY_ID, NAME)
    assert "could not be detached" in str(caught.value)
    assert "access is denied" in str(caught.value)
    assert store.named("uninstall") == []
    assert store.installed == [NAME]


def test_a_file_the_machine_would_not_unregister_is_reported_as_still_held() -> None:
    store = FakeProfileStore(installed=(NAME,), associated=(NAME,), default=NAME)
    store.refuse("uninstall", "the file is in use")
    removal = remove_profile(store, DISPLAY_ID, NAME)
    assert removal.detached
    assert not removal.unregistered and not removal.accepted
    assert removal.refusal == "the file is in use"
    assert "still holds the file" in removal.summary
    assert "Windows said: the file is in use" in removal.summary


def test_an_unregistration_the_machine_accepted_without_performing_is_not_reported_as_one() -> None:
    """The false-success control on the unregister half.

    ``uninstall`` returns success and leaves the file registered, which is what
    Windows does when another process holds the profile open. Nothing raised,
    so a result taken from the calls would report the profile gone.
    """
    store = FakeProfileStore(installed=(NAME,), associated=(NAME,), default=NAME)
    store.ignore("uninstall")
    removal = remove_profile(store, DISPLAY_ID, NAME)
    assert removal.detached
    assert not removal.unregistered and not removal.accepted
    assert removal.refusal is None
    assert store.installed == [NAME]


def test_a_detach_the_display_accepted_without_performing_is_not_reported_as_one() -> None:
    store = FakeProfileStore(installed=(NAME,), associated=(NAME,), default=NAME)
    store.ignore("disassociate")
    removal = remove_profile(store, DISPLAY_ID, NAME)
    assert not removal.detached and not removal.accepted
    assert f"still lists {NAME}" in removal.summary


# -- restoring ---------------------------------------------------------------


def test_restoring_takes_off_what_this_product_attached_and_nothing_else() -> None:
    store = FakeProfileStore(
        installed=(VENDOR_PROFILE, NAME, OTHER),
        associated=(VENDOR_PROFILE, NAME, OTHER),
        default=NAME,
    )
    restoration = restore_display_profiles(store, DISPLAY_ID)
    assert restoration.accepted
    assert restoration.removed == (NAME, OTHER)
    assert store.associated[DISPLAY_ID] == [VENDOR_PROFILE]
    assert store.default[DISPLAY_ID] == VENDOR_PROFILE
    assert f"no longer lists {NAME}, {OTHER}" in restoration.summary


def test_restoring_leaves_every_file_registered_with_the_machine() -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE, NAME), associated=(VENDOR_PROFILE, NAME), default=NAME)
    restore_display_profiles(store, DISPLAY_ID)
    assert store.installed == [VENDOR_PROFILE, NAME]
    assert store.named("uninstall") == []


def test_restoring_one_display_leaves_another_display_still_using_the_profile() -> None:
    store = FakeProfileStore(installed=(NAME,), associated=(NAME,), default=NAME)
    store.attach(NAME, display_id=OTHER_DISPLAY_ID, default=True)
    restoration = restore_display_profiles(store, DISPLAY_ID)
    assert restoration.accepted
    assert store.associated[OTHER_DISPLAY_ID] == [NAME]
    assert store.default[OTHER_DISPLAY_ID] == NAME
    assert store.installed == [NAME]


def test_a_display_carrying_nothing_from_this_product_is_left_alone() -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)
    restoration = restore_display_profiles(store, DISPLAY_ID)
    assert restoration.accepted and restoration.removed == ()
    assert written(store) == []
    assert "lists no profile from this product" in restoration.summary


def test_a_detach_the_display_refused_stops_the_whole_restore() -> None:
    store = FakeProfileStore(installed=(NAME, OTHER), associated=(NAME, OTHER), default=NAME)
    store.refuse("disassociate", "access is denied")
    with pytest.raises(SystemProfileError) as caught:
        restore_display_profiles(store, DISPLAY_ID)
    assert "could not be detached" in str(caught.value)
    assert store.associated[DISPLAY_ID] == [NAME, OTHER]


def test_a_restore_the_store_accepted_without_performing_is_not_reported_as_done() -> None:
    """The false-success control on the restore.

    Both detaches return success and change nothing. The display still lists
    both profiles, so the restore names them as remaining rather than reporting
    a display returned to its vendor profile.
    """
    store = FakeProfileStore(
        installed=(VENDOR_PROFILE, NAME, OTHER),
        associated=(VENDOR_PROFILE, NAME, OTHER),
        default=NAME,
    )
    store.ignore("disassociate")
    restoration = restore_display_profiles(store, DISPLAY_ID)
    assert not restoration.accepted
    assert restoration.remaining == (NAME, OTHER)
    assert f"still lists {NAME}, {OTHER}" in restoration.summary
