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

import ast
import json
import re
from pathlib import Path

from calibrate_pro import __release_series__, __version__
from scripts.product_version import (
    INSTALLER_NAME,
    PORTABLE_NAME,
    PRODUCT_VERSION,
    SDIST_NAME,
    WHEEL_NAME,
    read_product_version,
)

ROOT = Path(__file__).resolve().parents[1]

#: `2.0` out of `2.0.0`. Contract prose names the release series, not the patch.
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
    # Generated package metadata. `git check-ignore` reports `*.egg-info/`,
    # so an editable install leaves a stale name here that no release ships.
    found: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in wanted:
            continue
        parts = set(path.relative_to(ROOT).parts)
        if skip_dirs & parts or any(part.endswith(".egg-info") for part in parts):
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


#: A release number written into a string the product shows. `disabled in 1.1`,
#: `version 2.0`, `the 1.1 ApplyPlan`. Every one of these now derives from the
#: single declaration, so a literal here is a hardcode whatever number it names,
#: and the next bump would leave it behind. Gamma ranges and stimulus values are
#: numbers in prose too, so a release word or a release noun has to sit beside it.
_RELEASE_NUMBER_IN_PROSE = re.compile(
    r"(?:disabled in|enabled in|closed in|deferred to|[Vv]ersion|[Rr]elease)\s+v?\d+\.\d+"
    r"|\bthe\s+\d+\.\d+\s+(?:ApplyPlan|application|release|shell|build|surface|contract|installer|package)"
)

#: The em-dash. Written by codepoint because the rule that bans it applies to
#: this file too.
_EM_DASH = chr(8212)


def _shipped_strings() -> list[tuple[str, int, str]]:
    """Every string constant in the package, with where it was written.

    Read through the parser rather than by line, so a string spanning several
    lines is examined whole and a number in code is not mistaken for prose.
    """
    found: list[tuple[str, int, str]] = []
    for path in sorted((ROOT / "calibrate_pro").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        relative = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append((relative, node.lineno, node.value))
    return found


def test_no_shipped_string_hardcodes_a_release_number() -> None:
    """The window said `disabled in 1.1` through the whole of 1.1 and would have
    said it in 2.0. The sweep above could not see it: a bare series carries no
    product name to anchor on. This reads the strings themselves.
    """
    hardcoded = [
        f"{relative}:{lineno} writes {match.group(0)!r} into {value.strip()[:60]!r}"
        for relative, lineno, value in _shipped_strings()
        if (match := _RELEASE_NUMBER_IN_PROSE.search(value))
    ]
    assert hardcoded == [], (
        "these name a release in a string instead of deriving it from "
        "calibrate_pro.__release_series__:" + chr(10) + chr(10).join(hardcoded)
    )


def test_the_hardcode_detector_fires_on_the_strings_that_shipped() -> None:
    """A sweep that matches nothing passes whether or not the defect is there.
    These are the strings the product actually displayed, and a current-release
    hardcode, which is just as stale one bump from now.
    """
    for shipped in (
        "Status: disabled in 1.1; no command sent",
        "Raw VCP scanning is disabled in version 1.1; no command was sent.",
        "Brightness is not representable by the 1.1 ApplyPlan",
        "Keep arbitrary VCP probing outside the 1.1 application surface.",
        "Version 1.1 keeps conversion disabled until its exporter is isolated.",
        f"Measured calibration is closed in {SERIES}.",
    ):
        assert _RELEASE_NUMBER_IN_PROSE.search(shipped), f"detector missed {shipped!r}"

    for prose in (
        "clamped into the 1.8 to 3.0 a display produces",
        "the gamma of 2.2 was assumed, not read",
        "test LUT at contrast 1.15 and saturation 1.1",
    ):
        assert not _RELEASE_NUMBER_IN_PROSE.search(prose), f"detector fired on {prose!r}"


def test_no_shipped_string_carries_an_em_dash() -> None:
    """The prose rule reaches the strings a tester reads in the window, not only
    the documents. Nineteen of these were in the shipped GUI.
    """
    offenders = [
        f"{relative}:{lineno}: {value.strip()[:70]!r}"
        for relative, lineno, value in _shipped_strings()
        if _EM_DASH in value
    ]
    assert offenders == [], "an em-dash reaches the user here:" + chr(10) + chr(10).join(offenders)


def test_the_series_the_product_shows_derives_from_the_declaration() -> None:
    assert __release_series__ == SERIES
    assert __version__.startswith(__release_series__ + ".")


def test_the_changelog_has_a_dated_section_for_this_release() -> None:
    """The changelog is the one surface deliberately exempt from the sweep,
    because a history names old releases on purpose. That exemption also lets a
    release ship with its own entries still sitting under `Unreleased`, which is
    what a reader checks first. The heading for this version has to exist.
    """
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]

    assert headings, "the changelog has no release headings"
    assert headings[0].startswith(f"## v{__version__} ("), (
        f"the newest changelog heading is {headings[0]!r}, not this release"
    )
    assert not any(line.strip() == "## Unreleased" for line in headings), (
        "an Unreleased section is still open at release time"
    )
