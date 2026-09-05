"""What the fake composition refuses to build, and what it reads.

The composition writes files, so where it is allowed to write is a rule rather
than a convention. These tests hold it to that rule and confirm the synthetic
display it detects comes from the bundled resource and nowhere else.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from calibrate_pro.application import composition
from calibrate_pro.application.composition import (
    FAKE_DISPLAY_RESOURCE,
    FAKE_JOURNAL_DIRNAME,
    build_fake_acceptance_service,
    contained_path,
    load_fake_display,
)


def test_an_output_root_holding_files_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "occupied"
    root.mkdir()
    (root / "leftover.txt").write_text("from an earlier run", encoding="utf-8")
    with pytest.raises(ValueError, match="must be empty"):
        build_fake_acceptance_service(root)


def test_an_output_root_that_is_a_file_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "not-a-directory"
    root.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a directory"):
        build_fake_acceptance_service(root)


def test_paths_that_escape_the_output_root_are_refused(tmp_path: Path) -> None:
    root = (tmp_path / "root").resolve()
    root.mkdir()
    assert contained_path(root, FAKE_JOURNAL_DIRNAME) == root / FAKE_JOURNAL_DIRNAME
    with pytest.raises(ValueError, match="inside the output root"):
        contained_path(root, "..", "elsewhere")


def test_the_fake_display_comes_only_from_the_bundled_resource() -> None:
    resource = Path(composition.__file__).resolve().parents[1] / "resources" / FAKE_DISPLAY_RESOURCE
    document = json.loads(resource.read_text(encoding="utf-8"))
    assert document["schema_version"] == 1
    display = load_fake_display()
    for name, expected in document["display"].items():
        assert getattr(display, name) == expected
