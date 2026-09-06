"""Registering a published bundle with the machine, and putting it in effect.

Two of the three native calls in this lane report success for work they did not
do. Windows registers a profile and leaves the display default where it was, and
it accepts an association naming a file it does not hold. Every test here that
ends in an assertion about what was accepted is arranged so a result built out of
return values would pass and a result built out of a second reading of the store
fails, which is the only way to tell those two apart.

The bounds are tested from the outside as well. A name this build cannot derive
from a bundle it published never reaches the store, and neither does a payload
that is not exact nonempty bytes.
"""

from __future__ import annotations

import pytest

from calibrate_pro.application.system_profile_transactions import (
    activate_profile,
    install_bundle_profile,
    read_profiles,
)
from calibrate_pro.application.system_profiles import SystemProfileError, installed_name_for
from tests.system_profile_support import DISPLAY_ID, VENDOR_PROFILE, FakeProfileStore

DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
NAME = installed_name_for(DIGEST)
OTHER = installed_name_for(OTHER_DIGEST)
PAYLOAD = b"the bytes a manifest sealed"


def written(store: FakeProfileStore) -> list[str]:
    """The operations that changed the store, in order, with the reads dropped."""
    return [call[0] for call in store.calls if call[0] != "read"]


# -- reading -----------------------------------------------------------------


def test_a_store_that_did_not_answer_is_named_as_a_store_failure() -> None:
    store = FakeProfileStore()
    store.refuse("read", "the colour management API is unavailable")
    with pytest.raises(SystemProfileError) as caught:
        read_profiles(store, DISPLAY_ID)
    assert "The colour profile store did not answer" in str(caught.value)
    assert "the colour management API is unavailable" in str(caught.value)


# -- what may be installed at all --------------------------------------------


@pytest.mark.parametrize(
    "name",
    [VENDOR_PROFILE, "Calibrate Pro.icc", NAME.upper(), NAME.replace(".icc", ".icm"), f"{NAME} copy.icc"],
)
def test_only_a_name_derived_from_a_published_bundle_reaches_the_store(name: str) -> None:
    store = FakeProfileStore()
    with pytest.raises(SystemProfileError) as caught:
        install_bundle_profile(store, DISPLAY_ID, name, PAYLOAD)
    assert "was not installed by this product" in str(caught.value)
    assert store.calls == []


@pytest.mark.parametrize("payload", [b"", "the bytes a manifest sealed", bytearray(PAYLOAD), None, 0])
def test_a_profile_is_written_from_exact_nonempty_bytes_or_not_at_all(payload: object) -> None:
    store = FakeProfileStore()
    with pytest.raises(SystemProfileError) as caught:
        install_bundle_profile(store, DISPLAY_ID, NAME, payload)  # type: ignore[arg-type]
    assert "nonempty exact bytes" in str(caught.value)
    assert store.calls == []


# -- installing --------------------------------------------------------------


def test_installing_registers_the_file_and_attaches_it_to_the_display() -> None:
    store = FakeProfileStore()
    installation = install_bundle_profile(store, DISPLAY_ID, NAME, PAYLOAD)
    assert installation.accepted
    assert installation.registered and installation.associated
    assert not installation.replaced
    assert store.payloads[NAME] == PAYLOAD
    assert written(store) == ["install", "associate"]


def test_installing_does_not_make_the_profile_the_display_default() -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)
    installation = install_bundle_profile(store, DISPLAY_ID, NAME, PAYLOAD)
    assert installation.accepted
    assert store.default[DISPLAY_ID] == VENDOR_PROFILE
    assert written(store) == ["install", "associate"]


def test_a_name_the_machine_already_holds_is_left_as_it_stands() -> None:
    store = FakeProfileStore(installed=(NAME,))
    installation = install_bundle_profile(store, DISPLAY_ID, NAME, PAYLOAD)
    assert installation.accepted and installation.replaced
    assert written(store) == ["associate"]
    assert NAME not in store.payloads
    assert "left as it stood" in installation.summary


def test_a_profile_the_display_already_lists_is_not_attached_a_second_time() -> None:
    store = FakeProfileStore(installed=(NAME,), associated=(NAME,))
    installation = install_bundle_profile(store, DISPLAY_ID, NAME, PAYLOAD)
    assert installation.accepted
    assert written(store) == []


def test_a_registration_the_machine_refused_stops_before_the_display_is_touched() -> None:
    store = FakeProfileStore()
    store.refuse("install", "the colour directory is not writable")
    with pytest.raises(SystemProfileError) as caught:
        install_bundle_profile(store, DISPLAY_ID, NAME, PAYLOAD)
    assert "the colour directory is not writable" in str(caught.value)
    assert written(store) == ["install"]


def test_a_registration_that_could_not_be_attached_keeps_the_file_it_wrote() -> None:
    store = FakeProfileStore()
    store.refuse("associate", "access is denied")
    installation = install_bundle_profile(store, DISPLAY_ID, NAME, PAYLOAD)
    assert installation.registered
    assert not installation.associated and not installation.accepted
    assert installation.refusal == "access is denied"
    assert store.named("uninstall") == []
    assert NAME in store.installed
    assert "still there to associate" in installation.summary
    assert "Windows said: access is denied" in installation.summary


def test_a_registration_windows_accepted_without_performing_is_not_reported_as_one() -> None:
    """The false-success control on the install half.

    Here ``install`` returns success and writes nothing, which is what a
    profile directory rejecting the copy without raising looks like. The
    association then succeeds, because Windows will attach a name the machine
    does not hold. A result taken from the calls reads as fully accepted.
    """
    store = FakeProfileStore()
    store.ignore("install")
    installation = install_bundle_profile(store, DISPLAY_ID, NAME, PAYLOAD)
    assert installation.associated
    assert not installation.registered and not installation.accepted
    assert installation.refusal is None
    assert "the machine holds no file under that name" in installation.summary


def test_an_association_windows_accepted_without_performing_is_not_reported_as_one() -> None:
    store = FakeProfileStore()
    store.ignore("associate")
    installation = install_bundle_profile(store, DISPLAY_ID, NAME, PAYLOAD)
    assert installation.registered
    assert not installation.associated and not installation.accepted
    assert installation.refusal is None
    assert "does not list it" in installation.summary


# -- activating --------------------------------------------------------------


def test_a_profile_the_machine_does_not_hold_cannot_be_made_the_default() -> None:
    store = FakeProfileStore(associated=(NAME,))
    with pytest.raises(SystemProfileError) as caught:
        activate_profile(store, DISPLAY_ID, NAME)
    assert "is not installed on this machine" in str(caught.value)
    assert written(store) == []


def test_activating_attaches_the_profile_before_it_names_it_the_default() -> None:
    store = FakeProfileStore(installed=(NAME,))
    activation = activate_profile(store, DISPLAY_ID, NAME)
    assert activation.accepted and activation.moved
    assert written(store) == ["associate", "make_default"]
    assert "It was using no profile" in activation.summary


def test_a_profile_the_display_already_lists_is_made_default_without_reattaching() -> None:
    store = FakeProfileStore(installed=(NAME,), associated=(NAME,))
    activation = activate_profile(store, DISPLAY_ID, NAME)
    assert activation.accepted
    assert written(store) == ["make_default"]


def test_the_display_vendor_own_profile_may_be_chosen_as_the_default() -> None:
    store = FakeProfileStore(
        installed=(VENDOR_PROFILE, NAME),
        associated=(VENDOR_PROFILE, NAME),
        default=NAME,
    )
    activation = activate_profile(store, DISPLAY_ID, VENDOR_PROFILE)
    assert activation.accepted and activation.moved
    assert store.default[DISPLAY_ID] == VENDOR_PROFILE
    assert f"It was using {NAME}" in activation.summary


def test_a_display_already_using_the_profile_is_reported_as_unmoved() -> None:
    store = FakeProfileStore(installed=(NAME,), associated=(NAME,), default=NAME)
    activation = activate_profile(store, DISPLAY_ID, NAME)
    assert activation.accepted and not activation.moved
    assert "was already using" in activation.summary


def test_a_display_that_refused_the_default_reports_what_it_said() -> None:
    store = FakeProfileStore(installed=(NAME,), associated=(NAME,), default=VENDOR_PROFILE)
    store.refuse("make_default", "the display is not responding")
    with pytest.raises(SystemProfileError) as caught:
        activate_profile(store, DISPLAY_ID, NAME)
    assert "did not accept" in str(caught.value)
    assert "the display is not responding" in str(caught.value)
    assert store.default[DISPLAY_ID] == VENDOR_PROFILE


def test_a_default_the_store_accepted_without_moving_is_not_reported_as_moved() -> None:
    """The false-success control on the activation.

    ``make_default`` returns success and leaves the display where it was. That
    is the case which would otherwise tell an operator their calibration is in
    effect while the panel is still running on the vendor profile.
    """
    store = FakeProfileStore(installed=(NAME, VENDOR_PROFILE), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)
    store.ignore("make_default")
    activation = activate_profile(store, DISPLAY_ID, NAME)
    assert not activation.accepted and not activation.moved
    assert f"reports {VENDOR_PROFILE} as its default, not {NAME}" in activation.summary


def test_activating_a_second_profile_moves_the_display_off_the_first() -> None:
    store = FakeProfileStore(installed=(NAME, OTHER), associated=(NAME,), default=NAME)
    activation = activate_profile(store, DISPLAY_ID, OTHER)
    assert activation.accepted and activation.moved
    assert store.default[DISPLAY_ID] == OTHER
    assert store.associated[DISPLAY_ID] == [NAME, OTHER]
