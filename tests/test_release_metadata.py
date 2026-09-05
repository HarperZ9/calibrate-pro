from __future__ import annotations

import ast
from fnmatch import fnmatch
from glob import glob
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from calibrate_pro import __version__
from calibrate_pro.verification.reports import ReportMetadata

ROOT = Path(__file__).resolve().parents[1]


def test_release_version_matches_the_declaration_this_release_ships() -> None:
    assert __version__ == "2.0.0"


def test_verification_report_uses_release_version() -> None:
    metadata = ReportMetadata(title="Report", display_name="Display", profile_name="Profile")
    assert metadata.software_version == f"Calibrate Pro {__version__}"


def test_pyproject_reads_version_dynamically() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in text
    assert 'version = {attr = "calibrate_pro.__version__"}' in text
    # A static `version` beside `dynamic` breaks the build backend, and the
    # failure mode is a wheel named after whichever one the tooling read first.
    assert "version" not in tomllib.loads(text)["project"]


def test_no_independent_application_version_assignment() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "calibrate_pro").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"APP_VERSION", "__version__"}:
                    if path != ROOT / "calibrate_pro" / "__init__.py":
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_all_extra_is_gui_tray_sensor_union() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        optional_dependencies = tomllib.load(stream)["project"]["optional-dependencies"]

    expected = optional_dependencies["gui"] + optional_dependencies["tray"] + optional_dependencies["sensor"]
    assert optional_dependencies["all"] == expected
    assert len(optional_dependencies["all"]) == len(set(optional_dependencies["all"]))


def test_every_extra_the_doctor_names_is_one_pip_can_resolve() -> None:
    """The fix command doctor prints has to reach an extra pyproject declares.

    That table is written by hand beside the dependency names, so a renamed
    extra would keep printing the old name and send every reader who follows
    the command to an install that fails.
    """
    from calibrate_pro.diagnostics import DEPENDENCIES

    with (ROOT / "pyproject.toml").open("rb") as stream:
        declared = set(tomllib.load(stream)["project"]["optional-dependencies"])
    named = {extra for _, _, extra in DEPENDENCIES if extra}

    assert named, "no dependency names an extra"
    assert named <= declared, f"extras pyproject does not declare: {sorted(named - declared)}"


def test_metadata_tests_retain_python_3_10_toml_support() -> None:
    with (ROOT / "pyproject.toml").open("rb") as stream:
        optional_dependencies = tomllib.load(stream)["project"]["optional-dependencies"]

    requirement = "tomli>=2; python_version<'3.11'"
    assert requirement in optional_dependencies["test"]
    assert requirement in optional_dependencies["dev"]


def package_files() -> list[str]:
    """Every file the package ships that is not source, as posix paths."""
    package = ROOT / "calibrate_pro"
    return sorted(
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path.suffix != ".py" and "__pycache__" not in path.parts
    )


def test_the_wheel_carries_every_file_the_package_reads_at_runtime() -> None:
    """Package data is measured against the directory rather than a suffix list.

    Naming ``resources/*.ico`` and ``resources/*.png`` left the action manifest
    out of every non-editable install, so the package imported and then had no
    manifest to build a surface from. A suffix is the wrong thing to gate on,
    because the next resource added has whichever suffix it happens to have.
    """
    with (ROOT / "pyproject.toml").open("rb") as stream:
        patterns = tomllib.load(stream)["tool"]["setuptools"]["package-data"]["calibrate_pro"]

    package = ROOT / "calibrate_pro"
    covered = {
        Path(match).relative_to(package).as_posix()
        for pattern in patterns
        for match in glob(str(package / pattern), recursive=True)
    }

    assert [name for name in package_files() if name not in covered] == []


def test_the_sdist_carries_the_same_files_the_wheel_does() -> None:
    """One directive names the suffixes, applied at every depth beneath the package."""
    text = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    directive = next(line for line in text.splitlines() if line.startswith("recursive-include calibrate_pro "))
    patterns = directive.split()[2:]

    unmatched = [
        name for name in package_files() if not any(fnmatch(name.rsplit("/", 1)[-1], pattern) for pattern in patterns)
    ]

    assert unmatched == []


def test_sdist_manifest_allowlists_the_complete_release_source() -> None:
    text = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    required = (
        "include calibrate-pro.spec",
        "recursive-include tests *.py *.json",
        "recursive-include packaging *.json *.lock *.in *.py",
        "recursive-include scripts *.py *.ps1",
        "recursive-include installer *.iss",
        "recursive-include THIRD_PARTY_LICENSES *",
        "recursive-include dwm_lut *",
        "recursive-include docs *",
        "recursive-include examples *.py",
    )
    for directive in required:
        assert directive in text

    assert "global-exclude *.pyc" in text
    assert "prune build" in text
    assert "prune dist" in text
