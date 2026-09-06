"""Listing, checking, and copying published bundles through the session.

A published bundle is finished work, so these actions sit beside the calibration
session rather than inside it. What they owe an operator is a gate: a profile may
be copied only after its files have been read back and matched against the
manifest that came with them, and that answer is recomputed on every selection
rather than remembered from an earlier one.

The bundles here are published directly instead of calibrated for, because what
is under test is what the session does with a bundle that already exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from calibrate_pro.application.actions import ActionDisposition
from calibrate_pro.application.assets import MANIFEST_FILENAME
from calibrate_pro.application.fake_acceptance import FakeAcceptanceService
from tests.fake_acceptance_support import build_service, disposition, refused, succeeded
from tests.profile_support import CUBE, manifest_of, publish, rewrite_manifest

BUNDLE = "srgb"


@pytest.fixture
def exports(tmp_path: Path) -> Path:
    """A directory holding one published bundle, ready to be listed."""
    return publish(tmp_path / "exports" / BUNDLE).parent


@pytest.fixture
def service(tmp_path: Path, exports: Path) -> FakeAcceptanceService:
    """A session pointed at that directory, having detected and nothing more.

    Listing and checking are open from the first stage. A bundle published
    earlier is not part of the calibration being run now, and closing the list
    until a calibration finished would hide work the operator already has.
    """
    built = build_service(tmp_path)
    succeeded(built.detect())
    succeeded(built.set_export_directory(str(exports)))
    return built


def only_profile(service: FakeAcceptanceService) -> object:
    """List, and return the single record the directory holds."""
    listing = succeeded(service.list_profiles())
    assert len(listing.profiles) == 1, f"expected one bundle, found {listing.profiles}"
    return listing.profiles[0]


def test_a_listing_with_nowhere_to_look_says_so_rather_than_reporting_none(tmp_path: Path) -> None:
    """No directory chosen is not the same answer as a directory holding none."""
    built = build_service(tmp_path)
    succeeded(built.detect())

    listing = succeeded(built.list_profiles())

    assert not listing.searched
    assert listing.profiles == ()


def test_the_listing_reports_the_bundle_by_what_its_manifest_recorded(
    service: FakeAcceptanceService,
    exports: Path,
) -> None:
    """Nothing in the record is looked up, guessed, or read off a filename."""
    document = manifest_of(exports / BUNDLE)
    record = only_profile(service)

    assert record.name == BUNDLE
    assert record.directory == str(exports / BUNDLE)
    assert record.panel_name == document["panel_name"]
    assert record.evidence_kind == document["evidence_kind"]
    assert record.target.white_point == document["target"]["white_point"]


def test_checking_a_profile_outside_the_listing_is_refused(service: FakeAcceptanceService, tmp_path: Path) -> None:
    """The session checks bundles it has listed, not paths it is handed."""
    only_profile(service)

    outcome = refused(service.inspect_profile(str(tmp_path / "elsewhere")))

    assert outcome.code == "NO_SELECTED_PROFILE"
    assert outcome.effect_state == "none"


def test_a_copy_stays_closed_until_a_profile_has_been_checked(service: FakeAcceptanceService) -> None:
    """Listing a bundle is not evidence that its files are the ones it names."""
    only_profile(service)

    assert disposition(service, "profile.export") is ActionDisposition.DISABLED
    assert service.resolve("profile.export").reason


def test_checking_a_profile_opens_the_copy(service: FakeAcceptanceService) -> None:
    record = only_profile(service)

    inspection = succeeded(service.inspect_profile(record.directory))

    assert inspection.sealed
    assert disposition(service, "profile.export") is ActionDisposition.ENABLED


def test_a_profile_that_failed_its_check_never_opens_the_copy(
    service: FakeAcceptanceService,
    exports: Path,
) -> None:
    """The check reports what it found, and a bundle that failed stays closed.

    Reading a broken bundle is a successful read. What it produces is a verdict,
    and the gate is on the verdict rather than on the reading having run.
    """
    (exports / BUNDLE / CUBE).write_bytes(b"drifted")
    record = only_profile(service)

    inspection = succeeded(service.inspect_profile(record.directory))

    assert not inspection.sealed
    assert [check.filename for check in inspection.broken] == [CUBE]
    assert disposition(service, "profile.export") is ActionDisposition.DISABLED


def test_a_copy_carries_the_manifest_that_seals_the_original(
    service: FakeAcceptanceService,
    exports: Path,
    tmp_path: Path,
) -> None:
    """Every file arrives byte for byte, under the digest the source records.

    The copy is not published afresh at the far end. It carries the original
    manifest, so one record describes both bundles and either can be checked
    against it.
    """
    record = only_profile(service)
    succeeded(service.inspect_profile(record.directory))
    destination = tmp_path / "copy"

    bundle = succeeded(service.export_profile(str(destination)))
    written = destination / BUNDLE

    assert bundle.directory == str(written)
    assert bundle.manifest_sha256 == record.manifest_sha256
    assert sorted(path.name for path in written.iterdir()) == sorted(
        [MANIFEST_FILENAME, *(asset.filename for asset in record.assets)]
    )
    for asset in record.assets:
        assert (written / asset.filename).read_bytes() == (exports / BUNDLE / asset.filename).read_bytes()


def test_a_bundle_that_changed_after_it_was_checked_is_not_copied(
    service: FakeAcceptanceService,
    exports: Path,
    tmp_path: Path,
) -> None:
    """Files can move between the check and the copy, so the copy checks again.

    A surface can only report the answer it last drew. Re-hashing on the way out
    is what keeps a stale verdict from producing a second bundle whose manifest
    describes files it does not contain.
    """
    record = only_profile(service)
    succeeded(service.inspect_profile(record.directory))
    (exports / BUNDLE / CUBE).write_bytes(b"drifted")
    destination = tmp_path / "copy"

    outcome = refused(service.export_profile(str(destination)))

    assert outcome.code == "PROFILE_SEAL_BROKEN"
    assert outcome.effect_state == "none"
    assert not destination.exists()


def test_a_destination_that_cannot_be_written_is_refused_before_anything_is_read(
    service: FakeAcceptanceService,
    tmp_path: Path,
) -> None:
    """A path whose parent does not exist fails the same check a chosen one does."""
    record = only_profile(service)
    succeeded(service.inspect_profile(record.directory))
    unusable = tmp_path / "missing" / "deeper"

    outcome = refused(service.export_profile(str(unusable)))

    assert outcome.code == "NO_EXPORT_DIRECTORY"
    assert not unusable.exists()


def test_a_refresh_drops_a_selection_that_changed_underneath_it(
    service: FakeAcceptanceService,
    exports: Path,
) -> None:
    """A rewritten manifest is a different record, and the gate closes with it.

    Keeping the selection would leave the session holding a verdict about bytes
    that are no longer there, which is the state the copy would then be gated
    on.
    """
    record = only_profile(service)
    succeeded(service.inspect_profile(record.directory))
    rewrite_manifest(exports / BUNDLE, manifest_of(exports / BUNDLE))

    refreshed = succeeded(service.list_profiles())

    assert len(refreshed.profiles) == 1
    assert refreshed.profiles[0] != record
    assert disposition(service, "profile.export") is ActionDisposition.DISABLED


def test_a_refresh_that_finds_the_same_bundle_keeps_the_copy_open(service: FakeAcceptanceService) -> None:
    """Reading the directory again is not a reason to discard a good check."""
    record = only_profile(service)
    succeeded(service.inspect_profile(record.directory))

    refreshed = succeeded(service.list_profiles())

    assert refreshed.profiles[0] == record
    assert disposition(service, "profile.export") is ActionDisposition.ENABLED
