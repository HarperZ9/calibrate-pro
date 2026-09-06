"""The five profile commands a terminal runs, end to end over a fake store.

These drive `calibrate_pro.commands.session` the way a shell does, so what they
prove is the whole path: the parsed arguments, the detection pass, the store
reading, the gate the resolver keeps, the transaction, and the exit code. The
transaction layer is tested on its own elsewhere. What is tested here is that a
terminal reaches it, and that a run which changed nothing says so.

Two rules the family is written to keep are asserted in every group. A run
without ``--confirm`` writes nothing at all, and the exit code follows the
reading taken after the write rather than the call that asked for it.
"""

from __future__ import annotations

from pathlib import Path

from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.commands.session_profiles import NOTHING_WRITTEN
from tests.session_support import build_cli_service, field, run
from tests.system_profile_support import (
    DISPLAY_ID,
    INSTRUMENT,
    VENDOR_PROFILE,
    FakeProfileStore,
    build_profile_service,
    install_bundle,
    publish_bundle,
)

UNHELD = "Calibrate Pro 0123456789abcdef.icc"


def session(
    root: Path,
    store: FakeProfileStore | None,
    name: str = "session",
    **wiring: bool,
) -> FunctionalRecoveryService:
    """One session over the fake store, journalled under its own directory."""
    return build_profile_service(root / name, store, **wiring)


def writes(store: FakeProfileStore) -> list[str]:
    """The operations that changed the store, in order, with the reads dropped."""
    return [call[0] for call in store.calls if call[0] != "read"]


# -- reading -----------------------------------------------------------------


def test_reading_names_the_store_the_display_and_what_it_holds(tmp_path: Path) -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)

    code, text = run("system-profiles", session(tmp_path, store))

    assert code == 0
    assert f"{INSTRUMENT} on {DISPLAY_ID}" in text
    assert VENDOR_PROFILE in text
    assert "default" in text
    assert writes(store) == []


def test_reading_names_a_profile_the_display_lists_that_the_machine_lost(tmp_path: Path) -> None:
    """The case an installed-profile list alone would show nothing wrong for."""
    store = FakeProfileStore(associated=(UNHELD,), default=UNHELD)

    code, text = run("system-profiles", session(tmp_path, store))

    assert code == 0
    assert "the machine holds no file under this name" in text


def test_a_session_with_no_profile_port_is_offered_no_reading(tmp_path: Path) -> None:
    code, text = run("system-profiles", build_cli_service(tmp_path / "unwired"))

    assert code == 2
    assert text.startswith("system-profiles: ")


def test_a_machine_whose_colour_directory_cannot_be_written_is_offered_no_reading(tmp_path: Path) -> None:
    """The route is wired and the probe is closed, which is a real machine.

    An account that cannot write the colour directory would be shown a store it
    could read and every write refused one call later. The gate is held at the
    reading instead, so nothing is offered that cannot be carried out.
    """
    store = FakeProfileStore()

    code, text = run("system-profiles", session(tmp_path, store, profile_write=False))

    assert code == 2
    assert store.calls == []
    assert text.startswith("system-profiles: ")


def test_a_store_that_will_not_open_is_refused_with_what_it_said(tmp_path: Path) -> None:
    code, text = run("system-profiles", session(tmp_path, None))

    assert code == 2
    assert "no fake store was wired" in text


# -- installing ---------------------------------------------------------------


def test_an_install_without_confirmation_writes_nothing(tmp_path: Path) -> None:
    store = FakeProfileStore()
    bundle = publish_bundle(tmp_path)

    code, text = run("install-profile", session(tmp_path, store), bundle=str(bundle))

    assert code == 0
    assert NOTHING_WRITTEN in text
    assert writes(store) == []
    assert store.installed == []


def test_an_unconfirmed_install_still_names_what_it_would_write(tmp_path: Path) -> None:
    """The dry run is only useful if it names the profile the write would occupy."""
    store = FakeProfileStore()
    bundle = publish_bundle(tmp_path)

    _, text = run("install-profile", session(tmp_path, store), bundle=str(bundle))

    assert field(text, "installs as").startswith("Calibrate Pro ")
    assert "not installed on this machine" in text


def test_a_confirmed_install_registers_the_sealed_bytes_and_attaches_them(tmp_path: Path) -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)

    bundle, name = install_bundle(tmp_path, store)

    icc = next(Path(bundle).glob("*.icc"))
    assert store.payloads[name] == icc.read_bytes()
    assert name in store.associated[DISPLAY_ID]
    assert writes(store) == ["install", "associate"]


def test_an_install_leaves_the_display_using_the_profile_it_was_using(tmp_path: Path) -> None:
    """Attaching is not activating, and the command line keeps them apart."""
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)

    install_bundle(tmp_path, store)

    assert store.default[DISPLAY_ID] == VENDOR_PROFILE
    assert store.named("make_default") == []


def test_an_install_asked_to_activate_moves_the_display_onto_it(tmp_path: Path) -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)

    _, name = install_bundle(tmp_path, store, activate=True)

    assert store.default[DISPLAY_ID] == name


def test_an_install_the_display_would_not_accept_as_default_fails_the_run(tmp_path: Path) -> None:
    """The false-success control, driven from a terminal.

    ``make_default`` returns success and moves nothing, which is the case that
    would otherwise end with an exit code of zero and a display still running
    on its vendor profile.
    """
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)
    store.ignore("make_default")
    bundle = publish_bundle(tmp_path)

    code, text = run(
        "install-profile",
        session(tmp_path, store),
        bundle=str(bundle),
        confirm=True,
        activate=True,
    )

    assert code == 1
    assert f"reports {VENDOR_PROFILE} as its default" in text
    assert store.default[DISPLAY_ID] == VENDOR_PROFILE


def test_an_install_the_display_would_not_list_fails_the_run(tmp_path: Path) -> None:
    store = FakeProfileStore()
    store.refuse("associate", "access is denied")
    bundle = publish_bundle(tmp_path)

    code, text = run("install-profile", session(tmp_path, store), bundle=str(bundle), confirm=True)

    assert code == 1
    assert "still there to associate" in text
    assert "access is denied" in text


def test_naming_a_directory_of_bundles_lists_the_ones_under_it(tmp_path: Path) -> None:
    store = FakeProfileStore()
    publish_bundle(tmp_path / "parent", "child")

    code, text = run("install-profile", session(tmp_path, store), bundle=str(tmp_path / "parent"), confirm=True)

    assert code == 2
    assert "Bundles were found under it" in text
    assert "child" in text
    assert writes(store) == []


def test_naming_a_directory_that_is_not_there_reads_nothing(tmp_path: Path) -> None:
    store = FakeProfileStore()

    code, text = run("install-profile", session(tmp_path, store), bundle=str(tmp_path / "nowhere"), confirm=True)

    assert code == 2
    assert "No directory at" in text
    assert writes(store) == []


# -- switching ----------------------------------------------------------------


def test_switching_to_a_profile_the_machine_does_not_hold_lists_what_it_does(tmp_path: Path) -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,))

    code, text = run("switch-profile", session(tmp_path, store), name=UNHELD, confirm=True)

    assert code == 2
    assert f"Installed: {VENDOR_PROFILE}" in text
    assert writes(store) == []


def test_switching_without_confirmation_writes_nothing(tmp_path: Path) -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,))

    code, text = run("switch-profile", session(tmp_path, store), name=VENDOR_PROFILE)

    assert code == 0
    assert NOTHING_WRITTEN in text
    assert writes(store) == []


def test_switching_names_the_profile_the_display_hands_out(tmp_path: Path) -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,))
    _, name = install_bundle(tmp_path, store, activate=True)

    code, text = run("switch-profile", session(tmp_path, store, "switch"), name=VENDOR_PROFILE, confirm=True)

    assert code == 0
    assert store.default[DISPLAY_ID] == VENDOR_PROFILE
    assert f"It was using {name}" in text


# -- removing -----------------------------------------------------------------


def test_removing_without_confirmation_writes_nothing(tmp_path: Path) -> None:
    store = FakeProfileStore()
    bundle, name = install_bundle(tmp_path, store)
    store.calls.clear()

    code, text = run("remove-profile", session(tmp_path, store, "remove"), bundle=str(bundle))

    assert code == 0
    assert NOTHING_WRITTEN in text
    assert writes(store) == []
    assert store.installed == [name]


def test_removing_takes_the_profile_off_the_display_and_the_machine(tmp_path: Path) -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)
    bundle, name = install_bundle(tmp_path, store, activate=True)

    code, text = run("remove-profile", session(tmp_path, store, "remove"), bundle=str(bundle), confirm=True)

    assert code == 0
    assert name not in store.installed
    assert store.installed == [VENDOR_PROFILE]
    assert store.default[DISPLAY_ID] == VENDOR_PROFILE
    assert f"{name} is gone" in text


# -- restoring ----------------------------------------------------------------


def test_restoring_a_display_carrying_nothing_of_ours_takes_nothing_off_it(tmp_path: Path) -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)

    code, text = run("restore-profiles", session(tmp_path, store), confirm=True)

    assert code == 0
    assert "lists no profile from this product" in text
    assert writes(store) == []


def test_restoring_without_confirmation_writes_nothing(tmp_path: Path) -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)
    _, name = install_bundle(tmp_path, store, activate=True)
    store.calls.clear()

    code, text = run("restore-profiles", session(tmp_path, store, "restore"))

    assert code == 0
    assert NOTHING_WRITTEN in text
    assert writes(store) == []
    assert store.default[DISPLAY_ID] == name


def test_restoring_hands_the_display_back_to_the_profile_it_had(tmp_path: Path) -> None:
    store = FakeProfileStore(installed=(VENDOR_PROFILE,), associated=(VENDOR_PROFILE,), default=VENDOR_PROFILE)
    _, name = install_bundle(tmp_path, store, activate=True)

    code, text = run("restore-profiles", session(tmp_path, store, "restore"), confirm=True)

    assert code == 0
    assert store.associated[DISPLAY_ID] == [VENDOR_PROFILE]
    assert store.default[DISPLAY_ID] == VENDOR_PROFILE
    assert store.installed == [VENDOR_PROFILE, name]
    assert f"no longer lists {name}" in text
