"""Reading a published bundle back, and proving its files are the ones it names.

The page this supports used to describe files it found by globbing a folder the
application never writes to, printing a white point and a gamma nobody had
recorded and a gamut taken from a substring of the filename. A published bundle
already carries a manifest naming every file, the digest of each one, and the
target the assets were generated for, so these tests publish real bundles and
ask the reader what it makes of them.

Three properties are held down. A manifest this build cannot read is reported as
unreadable with its reason rather than filled in from a default, a bundle counts
as intact only when every file it names still hashes to the digest recorded for
it, and a directory nobody chose reads differently from an empty one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from calibrate_pro.application.assets import MANIFEST_FILENAME
from calibrate_pro.application.profiles import (
    ManifestError,
    ProfileInspection,
    discover_profiles,
    read_manifest,
    reparse_profile,
)
from tests.profile_support import CUBE, manifest_of, publish, rewrite_manifest

#: Every key the reader requires. A manifest missing any one of them describes a
#: bundle this build cannot report on, which is a different thing from a bundle
#: it can report on incompletely.
REQUIRED_FIELDS = (
    "display_id",
    "panel_key",
    "panel_name",
    "characterization_kind",
    "evidence_kind",
    "lut_size",
    "preset_id",
    "target",
)


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    return publish(tmp_path / "exports" / "srgb")


def test_a_manifest_is_read_back_as_the_generator_wrote_it(bundle: Path) -> None:
    """Every figure on the record comes from the document, field by field."""
    document = manifest_of(bundle)
    record = read_manifest(bundle)

    assert record.name == bundle.name
    assert record.directory == str(bundle)
    assert record.display_id == document["display_id"]
    assert record.panel_key == document["panel_key"]
    assert record.panel_name == document["panel_name"]
    assert record.characterization_kind == document["characterization_kind"]
    assert record.evidence_kind == document["evidence_kind"]
    assert record.lut_size == document["lut_size"]
    assert record.target.preset_id == document["preset_id"]
    assert record.target.gamut_mode == document["target"]["gamut_mode"]
    assert record.target.white_point == document["target"]["white_point"]
    assert record.target.tone_response == document["target"]["tone_response"]
    assert record.target.applied_gamma_exponent == document["target"]["applied_gamma_exponent"]
    assert [asset.filename for asset in record.assets] == [entry["filename"] for entry in document["assets"]]
    assert record.byte_count == sum(entry["bytes"] for entry in document["assets"])


def test_the_digest_on_a_record_is_the_digest_of_the_manifest_file(bundle: Path) -> None:
    """The seal on a bundle is the manifest itself, so it is hashed as read.

    A copy carries these bytes rather than a manifest rewritten at the far end,
    and this digest is what lets both bundles be checked against one record.
    """
    raw = (bundle / MANIFEST_FILENAME).read_bytes()

    assert read_manifest(bundle).manifest_sha256 == hashlib.sha256(raw).hexdigest()


def test_a_manifest_from_a_schema_this_build_does_not_read_is_refused(bundle: Path) -> None:
    document = manifest_of(bundle)
    document["schema"] = 2
    rewrite_manifest(bundle, document)

    with pytest.raises(ManifestError, match="schema"):
        read_manifest(bundle)


@pytest.mark.parametrize("field", REQUIRED_FIELDS)
def test_a_manifest_missing_a_field_is_refused_rather_than_defaulted(bundle: Path, field: str) -> None:
    """A default here would reach a surface as a figure presented as recorded.

    That is the defect this reader exists to end, so a manifest that does not
    record something is reported as unreadable instead of being completed.
    """
    document = manifest_of(bundle)
    del document[field]
    rewrite_manifest(bundle, document)

    with pytest.raises(ManifestError, match=field):
        read_manifest(bundle)


def test_a_manifest_naming_no_assets_is_refused(bundle: Path) -> None:
    """A bundle with no files is not a bundle, and it would seal as intact."""
    document = manifest_of(bundle)
    document["assets"] = []
    rewrite_manifest(bundle, document)

    with pytest.raises(ManifestError, match="no assets"):
        read_manifest(bundle)


def test_a_manifest_that_is_not_an_object_is_refused(bundle: Path) -> None:
    rewrite_manifest(bundle, [manifest_of(bundle)])

    with pytest.raises(ManifestError, match="not a JSON object"):
        read_manifest(bundle)


def test_a_whole_number_field_holding_a_boolean_is_refused(bundle: Path) -> None:
    """``True`` counts as an integer in Python and is not a LUT size anywhere."""
    document = manifest_of(bundle)
    document["lut_size"] = True
    rewrite_manifest(bundle, document)

    with pytest.raises(ManifestError, match="lut_size"):
        read_manifest(bundle)


def test_nowhere_to_look_reads_differently_from_an_empty_directory(tmp_path: Path) -> None:
    """A surface reporting both the same way says the bundles are gone.

    Nobody had said where the bundles were. The listing keeps the two answers
    apart so a page can say which of them happened.
    """
    unset = discover_profiles(None)
    assert not unset.searched
    assert unset.directory is None
    assert unset.profiles == ()

    empty = discover_profiles(tmp_path)
    assert empty.searched
    assert empty.directory == str(tmp_path)
    assert empty.profiles == ()


def test_a_path_with_nothing_at_it_reads_differently_from_a_directory_that_was_read(tmp_path: Path) -> None:
    """Three answers end in no profiles, and the listing keeps all three apart.

    A directory that was read and held none is a fact about the bundles. A path
    with nothing at it is a fact about the path, and reporting it as a zero tells
    an operator their bundles are gone from a folder nobody ever opened. The
    directory an export wrote to can stop being there between the export and the
    next reading, so this is the answer a stale export directory gives.
    """
    absent = tmp_path / "gone"

    listing = discover_profiles(absent)

    assert listing.searched
    assert listing.directory == str(absent)
    assert not listing.existed
    assert listing.profiles == ()
    assert discover_profiles(tmp_path).existed
    assert not discover_profiles(None).existed


def test_a_bundle_is_found_at_the_chosen_directory_and_one_level_below(tmp_path: Path) -> None:
    """Both depths are depths this application publishes at.

    A whole-bundle export writes its manifest into the chosen directory, and a
    single-format export writes one into a subdirectory named for the format.
    """
    root = publish(tmp_path / "exports")
    child = publish(root / "cube")

    listing = discover_profiles(root)

    assert [record.directory for record in listing.profiles] == [str(root), str(child)]


def test_a_bundle_deeper_than_this_application_writes_is_not_listed(tmp_path: Path) -> None:
    """Walking further would list bundles this build did not produce."""
    root = tmp_path / "exports"
    root.mkdir()
    publish(root / "one" / "two")

    assert discover_profiles(root).profiles == ()


def test_a_bundle_this_build_cannot_read_stays_in_the_listing_with_its_reason(tmp_path: Path) -> None:
    """A bundle that has become unreadable is something an operator needs to see.

    Dropping it would make it look as though it had never been published, so it
    is reported beside the readable ones, named, with what went wrong attached.
    """
    root = publish(tmp_path / "exports")
    broken = publish(root / "broken")
    (broken / MANIFEST_FILENAME).write_text("{ not json", encoding="utf-8")

    listing = discover_profiles(root)

    assert [record.directory for record in listing.profiles] == [str(root)]
    assert [entry.directory for entry in listing.unreadable] == [str(broken)]
    assert listing.unreadable[0].name == "broken"
    assert listing.unreadable[0].reason


def test_an_untouched_bundle_reports_every_file_matched(bundle: Path) -> None:
    inspection = reparse_profile(read_manifest(bundle))

    assert inspection.sealed
    assert inspection.broken == ()
    assert [check.filename for check in inspection.checks] == [asset.filename for asset in inspection.record.assets]
    assert all(check.actual_sha256 == check.expected_sha256 for check in inspection.checks)


def test_a_changed_file_is_named_with_the_digest_it_now_has(bundle: Path) -> None:
    """Both digests are reported, because which file moved is the useful part."""
    record = read_manifest(bundle)
    (bundle / CUBE).write_bytes(b"drifted")

    inspection = reparse_profile(record)
    changed = inspection.broken

    assert not inspection.sealed
    assert [check.filename for check in changed] == [CUBE]
    assert changed[0].present
    assert changed[0].actual_sha256 == hashlib.sha256(b"drifted").hexdigest()
    assert changed[0].actual_sha256 != changed[0].expected_sha256


def test_a_missing_file_is_reported_missing_rather_than_changed(bundle: Path) -> None:
    """The two answers are different and a surface says which one it got."""
    record = read_manifest(bundle)
    (bundle / CUBE).unlink()

    gone = reparse_profile(record).broken[0]

    assert gone.filename == CUBE
    assert not gone.present
    assert gone.actual_sha256 is None


def test_a_reading_that_checked_nothing_is_not_sealed(bundle: Path) -> None:
    """``all(())`` is true, so none has to be ruled out from being all.

    Without that, an inspection holding no checks would report a bundle intact
    on the strength of having read nothing, and open the copy behind it.
    """
    assert not ProfileInspection(record=read_manifest(bundle), checks=()).sealed
