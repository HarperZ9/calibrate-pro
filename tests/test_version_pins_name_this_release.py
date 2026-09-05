"""Every surface that names the release must name the one it is building.

`calibrate_pro/__init__.py` declares the version. `pyproject.toml`, the release
scripts and the build workflow read it. What remains are surfaces a program
cannot compute for itself: prose, badge URLs, a data lock, and the tag a human
types into the dispatch form. Those are literals, and a literal is what goes
stale. Each one is checked here against the declaration, so a bump that misses a
file fails a test instead of shipping a page that names the previous release.

The version pin in `test_release_metadata.py` is deliberate and is the one place
a version change has to be acknowledged by hand. This module is what makes that
single acknowledgement sufficient.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from calibrate_pro import __version__
from scripts.product_version import (
    INSTALLER_NAME,
    PORTABLE_NAME,
    PRODUCT_VERSION,
    SDIST_NAME,
    WHEEL_NAME,
    read_product_version,
)

ROOT = Path(__file__).resolve().parents[1]

#: `1.1` out of `1.1.0`. Contract prose names the release series, not the patch.
SERIES = ".".join(__version__.split(".")[:2])

#: A version string attached to this product's own name. A dependency URL that
#: happens to end in `/v3.8` is somebody else's version and is left alone; a
#: `/v` here has to sit on this repository's own path.
_OWN_VERSION_SHAPED = re.compile(
    r"(?:CalibratePro-|calibrate_pro-|calibrate-pro-|version-|Calibrate Pro |calibrate-pro/v)(\d+\.\d+(?:\.\d+)?)"
)

#: Surfaces that name a version other than this one on purpose. Plan and spec
#: documents record what a past release did. The changelog is a history by
#: definition. Test modules build synthetic versions to drive the code under
#: test, and their real pins are covered by the structural checks above.
_HISTORICAL = (
    "docs/superpowers/",
    "CHANGELOG.md",
    "tests/",
)


def _tracked_text_files() -> list[Path]:
    wanted = {".md", ".txt", ".html", ".yml", ".yaml", ".json", ".py", ".ps1", ".iss", ".toml"}
    skip_dirs = {".git", "build", "dist", "__pycache__", ".venv", "node_modules", ".ruff_cache", ".pytest_cache"}
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in wanted:
            continue
        if skip_dirs & set(path.relative_to(ROOT).parts):
            continue
        found.append(path)
    return found


def test_the_reader_returns_what_the_package_declares() -> None:
    """The reader is what every other surface trusts, so it is checked first."""
    assert __version__ == PRODUCT_VERSION
    assert read_product_version() == __version__


def test_the_four_artifact_names_carry_the_declared_version() -> None:
    assert f"CalibratePro-{__version__}-Setup.exe" == INSTALLER_NAME
    assert f"CalibratePro-{__version__}-win64.zip" == PORTABLE_NAME
    assert f"calibrate_pro-{__version__}-py3-none-any.whl" == WHEEL_NAME
    assert f"calibrate_pro-{__version__}.tar.gz" == SDIST_NAME


def test_the_powershell_reader_agrees_with_the_python_reader() -> None:
    """Two languages read the same declaration, so both patterns are checked
    against it here rather than trusted to stay in step.
    """
    declaration = (ROOT / "calibrate_pro" / "__init__.py").read_text(encoding="utf-8")
    for script in ("scripts/build_windows.ps1", "scripts/verify_reproducibility.ps1"):
        text = (ROOT / script).read_text(encoding="utf-8")
        embedded = re.search(r"\[regex\]::Match\(\$versionDeclaration, '([^']+)'\)", text)
        assert embedded is not None, f"{script} no longer reads __version__ from the package"
        found = re.search(embedded.group(1).replace("(?m)", ""), declaration, re.MULTILINE)
        assert found is not None, f"{script} pattern matches nothing in calibrate_pro/__init__.py"
        assert found.group(1) == __version__, f"{script} would read {found.group(1)!r}"


def test_the_release_workflow_dispatch_default_names_this_release() -> None:
    """The default tag is what a human accepts without reading. It has to be right."""
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert f"default: v{__version__}" in text
    assert "VERSION=" + chr(34) + "$(python scripts/product_version.py)" + chr(34) in text


def test_the_component_lock_records_this_release_as_its_own_component() -> None:
    """The lock is data the build reads, so a stale version there names an
    artifact the build never produced.
    """
    data = json.loads((ROOT / "packaging/components-win64.json").read_text(encoding="utf-8"))
    ours = [entry for entry in data["components"] if entry["owner"] == "calibrate-pro"]
    assert ours, "the component lock does not describe calibrate-pro"
    for entry in ours:
        assert entry["version"] == __version__, f"{entry['id']} pins {entry['version']}"
        assert entry["id"] == f"calibrate-pro-{__version__}"
        for record in entry["provenance"]:
            if record["kind"] == "release_source":
                assert record["name"] == SDIST_NAME


def test_no_tracked_file_still_names_a_previous_release() -> None:
    """The sweep. A version-shaped string anywhere outside the historical record
    has to be this release, whatever surface it sits on.
    """
    stale: list[str] = []
    for path in _tracked_text_files():
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(_HISTORICAL):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _OWN_VERSION_SHAPED.finditer(text):
            found = match.group(1)
            if found in {__version__, SERIES}:
                continue
            line = text.count(chr(10), 0, match.start()) + 1
            stale.append(f"{relative}:{line} names {found} in {match.group(0)!r}")
    assert stale == [], "these name a release this build is not:" + chr(10) + chr(10).join(stale)
