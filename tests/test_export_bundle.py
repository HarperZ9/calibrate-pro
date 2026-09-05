"""Deterministic asset generation and all-or-nothing export publication.

These tests pin the two behaviors the export surface previously faked: a file
is either written with the exact bytes its digest names, or nothing is written
at all and the caller is told why.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from calibrate_pro.application.assets import (
    AssetFormat,
    AssetGenerator,
    AssetRequest,
    BundlePublishError,
    publish_bundle,
)
from calibrate_pro.application.contracts import CharacterizationKind
from calibrate_pro.verification.provenance import EvidenceKind

ALL_FORMATS = tuple(AssetFormat)
DISPLAY_ID = "\\\\.\\DISPLAY1"
MATCHED_PANEL_KEY = "AW3423DW"


@pytest.fixture(scope="module")
def generator() -> AssetGenerator:
    return AssetGenerator()


@pytest.fixture(scope="module")
def request_all_formats() -> AssetRequest:
    return AssetRequest(
        display_id=DISPLAY_ID,
        panel_key=MATCHED_PANEL_KEY,
        preset_id="calibration.preset.srgb_web",
        formats=ALL_FORMATS,
        lut_size=17,
        basename="Calibrate_Pro_Test",
    )


@pytest.fixture(scope="module")
def generated(generator: AssetGenerator, request_all_formats: AssetRequest):
    return generator.generate(request_all_formats)


def test_every_requested_format_is_generated(generated, request_all_formats):
    assert set(generated.assets) == set(request_all_formats.formats)
    for payload in generated.assets.values():
        assert isinstance(payload, bytes)
        assert payload, "an asset must never be published as zero bytes"


def test_generation_is_byte_deterministic(generator, request_all_formats, generated):
    again = generator.generate(request_all_formats)
    for fmt, payload in generated.assets.items():
        assert again.assets[fmt] == payload, f"{fmt.value} generation is not deterministic"


def test_icc_does_not_embed_wall_clock(generated):
    icc = generated.assets[AssetFormat.ICC]
    # ICC dateTimeNumber lives at header offset 24..36 as six big-endian shorts.
    stamp = tuple(int.from_bytes(icc[24 + 2 * i : 26 + 2 * i], "big") for i in range(6))
    assert stamp == (2026, 1, 1, 0, 0, 0)


def test_text_assets_use_lf_newlines(generated):
    for fmt, payload in generated.assets.items():
        if fmt in AssetFormat.text_formats():
            assert b"\r\n" not in payload, f"{fmt.value} must be newline-normalized"


def test_lut_assets_share_one_grid(generated, request_all_formats):
    cube = generated.assets[AssetFormat.CUBE].decode("utf-8")
    assert f"LUT_3D_SIZE {request_all_formats.lut_size}" in cube


def test_sensorless_generation_is_labeled_estimated(generated):
    assert generated.evidence_kind is EvidenceKind.ESTIMATED
    assert generated.evidence_kind is not EvidenceKind.MEASURED


def test_unknown_panel_is_reported_not_silently_substituted(generator):
    unmatched = AssetRequest(
        display_id=DISPLAY_ID,
        panel_key="no-such-panel-key",
        preset_id="calibration.preset.srgb_web",
        formats=(AssetFormat.CUBE,),
        lut_size=17,
    )
    result = generator.generate(unmatched)
    assert result.characterization_kind is CharacterizationKind.EXPLICIT_GENERIC
    assert result.panel_name


def test_matched_panel_reports_matched_characterization(generated):
    assert generated.characterization_kind is CharacterizationKind.MATCHED


def test_unsupported_format_is_rejected(generator):
    with pytest.raises(TypeError):
        AssetRequest(
        display_id=DISPLAY_ID,
            panel_key=MATCHED_PANEL_KEY,
            preset_id="calibration.preset.srgb_web",
            formats=("cube",),  # strings are not AssetFormat members
            lut_size=17,
        )


def test_publish_writes_every_file_and_a_manifest(tmp_path: Path, generated):
    destination = tmp_path / "bundle"
    bundle = publish_bundle(generated, destination)

    assert Path(bundle.directory) == destination
    for asset in bundle.assets:
        written = destination / asset.filename
        assert written.is_file()
        assert hashlib.sha256(written.read_bytes()).hexdigest() == asset.sha256
        assert written.stat().st_size == asset.byte_count

    manifest_path = destination / bundle.manifest_filename
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == 1
    assert {entry["filename"] for entry in manifest["assets"]} == {a.filename for a in bundle.assets}
    assert manifest["evidence_kind"] == "estimated"


def test_publish_leaves_no_staging_directory(tmp_path: Path, generated):
    destination = tmp_path / "bundle"
    bundle = publish_bundle(generated, destination)
    published = {asset.filename for asset in bundle.assets} | {bundle.manifest_filename}
    assert {entry.name for entry in destination.iterdir()} == published


def test_publish_refuses_to_overwrite_by_default(tmp_path: Path, generated):
    destination = tmp_path / "bundle"
    publish_bundle(generated, destination)
    with pytest.raises(BundlePublishError) as excinfo:
        publish_bundle(generated, destination)
    assert "already exist" in str(excinfo.value)


def test_publish_overwrites_only_when_asked(tmp_path: Path, generated):
    destination = tmp_path / "bundle"
    first = publish_bundle(generated, destination)
    second = publish_bundle(generated, destination, overwrite=True)
    assert [a.sha256 for a in first.assets] == [a.sha256 for a in second.assets]


def test_failed_publish_writes_nothing(tmp_path: Path, generated, monkeypatch):
    destination = tmp_path / "bundle"
    import calibrate_pro.application.assets as assets_module

    calls = {"count": 0}
    real_replace = assets_module.os.replace

    def failing_replace(src, dst):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated publish failure")
        return real_replace(src, dst)

    monkeypatch.setattr(assets_module.os, "replace", failing_replace)
    with pytest.raises(BundlePublishError):
        publish_bundle(generated, destination)

    leftovers = [] if not destination.exists() else list(destination.iterdir())
    assert leftovers == [], f"a failed publish left partial output: {leftovers}"


def test_publish_rejects_a_file_where_the_directory_belongs(tmp_path: Path, generated):
    destination = tmp_path / "not-a-directory"
    destination.write_text("occupied", encoding="utf-8")
    with pytest.raises(BundlePublishError):
        publish_bundle(generated, destination)


def test_manifest_digest_covers_the_manifest_body(tmp_path: Path, generated):
    destination = tmp_path / "bundle"
    bundle = publish_bundle(generated, destination)
    body = (destination / bundle.manifest_filename).read_bytes()
    assert hashlib.sha256(body).hexdigest() == bundle.manifest_sha256
