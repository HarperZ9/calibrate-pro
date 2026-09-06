"""Public release documentation must describe the shipped safety contract.

Most of what is checked here is that a sentence is present. The last four are a
different kind of check: they read a number or a list off the code and require
the README to agree with it, so that adding a panel or moving a command between
the two builds fails here rather than leaving a page that quietly stops being
true. A count carried forward by hand is the drift these are for.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

import pytest

from calibrate_pro import __version__

ROOT = Path(__file__).resolve().parents[1]

#: The release these pages describe. Derived, because a page that names a
#: version the build no longer has is the drift this module exists to catch.
VERSION = __version__
SERIES = ".".join(__version__.split(".")[:2])

#: The heading whose first fenced block a reader runs before anything else.
TRY_IT_HEADING = "## Try it"

#: The sentence introducing the names only the developer wheel answers.
DEVELOPER_ONLY_INTRO = "These names exist only in the developer wheel"

#: The heading over the table of commands that drive a session from a terminal.
HEADLESS_HEADING = "## Headless calibration commands"

#: Every page a reader outside the repository can reach. A claim about what this
#: build does has to hold on all of them, because a reader arrives at one.
PUBLIC_SURFACES = (
    "README.md",
    "USAGE.md",
    "RELEASE_NOTES.md",
    "docs/ENTERPRISE-READINESS.md",
    "docs/TECHNICAL.md",
    "docs/index.html",
)

#: The two actions that decide whether this build measures anything.
MEASURED_ACTIONS = frozenset({"calibration.method.measured", "verification.measured"})

#: Said on a page where a reader will meet the measured mode. The wording differs
#: per page; this is the part every one of them shares.
CLOSURE_MARKER = f"closed in {SERIES}"

#: Reads as though buying the instrument is what stands between a reader and a
#: measured result. It is not: both actions are disabled whatever is plugged in.
HARDWARE_IS_THE_ONLY_GATE = re.compile(
    r"(?:requires|needs)\s+a\s+supported\s+(?:colorimeter|instrument|sensor)",
    re.IGNORECASE,
)


def readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def fenced_commands(text: str, after: str) -> list[str]:
    """The command names in the first fenced block following a heading.

    The anchor and the fence are checked before they are used, because a page
    that lost the whole section would otherwise fail with an index error rather
    than with the thing that is wrong.
    """
    parts = text.split(after, 1)
    assert len(parts) == 2, f"the README no longer contains {after!r}"
    fences = parts[1].split("```")
    assert len(fences) >= 3, f"no fenced block follows {after!r}"
    block = fences[1]
    names = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped.startswith("calibrate-pro "):
            continue
        names.append(stripped.split()[1])
    return names


def table_commands(text: str, after: str) -> set[str]:
    """The command names in the first table following a heading.

    A row is read the way a reader reads it, off the code span in the first
    column, so a command documented only in the prose beneath the table does not
    count as documented here.
    """
    parts = text.split(after, 1)
    assert len(parts) == 2, f"the guide no longer contains {after!r}"
    names = set()
    for line in parts[1].splitlines():
        row = re.match(r"\|\s*`calibrate-pro ([a-z-]+)", line)
        if row is not None:
            names.add(row.group(1))
        elif names and not line.startswith("|"):
            break
    return names


def frozen_features() -> dict[str, list[str]]:
    return json.loads((ROOT / "packaging/frozen-features.json").read_text(encoding="utf-8"))


def test_readme_identifies_the_current_release_and_qt_binding() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert f"version-{VERSION}" in text
    assert f"Release:** Calibrate Pro {VERSION}" in text
    assert "PySide6" in text
    assert "PyQt6" not in text
    assert f'src="https://raw.githubusercontent.com/HarperZ9/calibrate-pro/v{VERSION}/' in text
    assert f"The {VERSION} Windows artifacts are not Authenticode-signed" in text
    assert "](LICENSE)" not in text
    assert "](USAGE.md)" not in text


def test_readme_documents_proposal_only_legacy_commands_and_unelevated_launch() -> None:
    """Both ways in are named, and the README keeps them apart.

    These three commands were checked for their absence while they exited 2. They
    run now, so the same three names are checked for the opposite reason: someone
    who reads only this file should find the headless run without having to install
    the package first to discover it exists.
    """
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Detect -> Method -> Preview -> Apply -> Verify -> Save/Report" in text
    assert "Launch `calibrate-pro gui`" in text
    assert "select a display" in text
    assert "review the exact plan" in text
    assert "proposal-only" in text
    assert "starts unelevated" in text
    assert "Requests admin" not in text
    assert "not Authenticode-signed" in text
    assert "SHA256SUMS.txt" in text
    assert "Run `calibrate-pro detect`" in text
    assert "Run `calibrate-pro status`" in text
    assert "Run `calibrate-pro verify --target srgb_web`" in text


def test_readme_names_both_nano_ips_models() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "**Nano-IPS (2)**" in text
    assert "LG UltraGear 27GP950-B" in text
    assert "LG UltraGear 27GP850-B" in text


def test_release_notes_are_for_this_release_and_name_the_evidence_boundary() -> None:
    text = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")

    assert text.startswith(f"# Calibrate Pro v{VERSION}\n")
    assert f"The {VERSION} Windows artifacts are not Authenticode-signed" in text
    assert "Not measured" in text
    assert "PySide6" in text
    assert "PyQt6" not in text
    assert "not Authenticode-signed" in text


def test_usage_guide_matches_the_shipped_command_and_privilege_contract() -> None:
    text = (ROOT / "USAGE.md").read_text(encoding="utf-8")

    assert f"Calibrate Pro {SERIES}" in text
    assert "calibrate-pro doctor --json" in text
    assert "returns exit code 2 without changing display state" in text
    assert "starts unelevated" in text
    assert "PySide6" in text
    assert "CalibrateProCLI.exe hdr" in text
    assert "CalibratePro-HDR.exe" not in text
    assert "PyQt6" not in text
    assert "Fully automatic calibration of all displays" not in text
    assert "requests admin rights" not in text


def test_the_usage_guide_lists_exactly_the_names_this_build_declines() -> None:
    """The block of declined names is read back off the dispatcher that declines them.

    It was a hand-kept list, and it named five commands that run now. A guide that
    tells an operator a working command exits 2 reads as a reason not to try it,
    which is the failure this catches rather than a typo in a table. It also missed
    a name going the other way, when `patterns` stopped opening its viewer.
    """
    from calibrate_pro.main import _CONFIRMATION_COMMANDS

    text = (ROOT / "USAGE.md").read_text(encoding="utf-8")
    section = text.split("## Commands this build declines", 1)[1]
    listed = section.split("```text", 1)[1].split("```", 1)[0]

    assert set(listed.split()) == set(_CONFIRMATION_COMMANDS)


def test_enterprise_readiness_describes_the_shipped_boundary() -> None:
    text = (ROOT / "docs" / "ENTERPRISE-READINESS.md").read_text(encoding="utf-8")

    assert f"Calibrate Pro {SERIES}" in text
    assert "FSL-1.1-MIT" in text
    assert "PySide6" in text
    assert "proposal-only" in text
    assert "Not measured" in text
    assert "PyQt6" not in text
    assert "Fair-Source License 1.0" not in text


def test_architecture_describes_the_confirmation_bound_adapter() -> None:
    text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert "DefaultWindowsDisplayAdapter" in text
    assert "Detect -> Method -> Preview -> Apply -> Verify -> Save/Report" in text
    assert "proposal-only" in text
    assert "PySide6" in text
    assert "CalibrateProCLI.exe" in text
    assert "CalibratePro-HDR.exe" not in text
    assert "PyQt6" not in text
    assert "CLI and MCP expose the same surface" not in text


def test_security_and_changelog_do_not_promise_unshipped_automation() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "read-only startup monitor" in security
    assert "Automatic reapply is disabled" in security
    assert "fresh plan" in security
    assert "explicit confirmation" in security
    assert "Calibration can be re-applied on login" not in security
    assert "telos.display.calibration" not in changelog


def test_public_site_matches_the_shipped_operator_and_evidence_boundaries() -> None:
    text = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")

    assert "https://github.com/HarperZ9/calibrate-pro/releases" in text
    assert "https://github.com/HarperZ9/calibrate-pro" in text
    assert "PySide6" in text
    assert "proposal-only" in text
    assert "exit code 2" in text
    assert "estimated" in text
    assert "Not measured" in text
    assert "github.com/zain-harper" not in text
    assert "PyQt6" not in text
    assert "predicted dE &lt; 1.0 accuracy" not in text
    assert "measured primaries, installed automatically" not in text
    assert "watchdog prevents Windows" not in text
    assert "Persists across reboots" not in text
    assert "Calibrate all displays" not in text


def test_technical_guide_does_not_turn_characterization_into_measurement() -> None:
    text = (ROOT / "docs" / "TECHNICAL.md").read_text(encoding="utf-8")

    assert "nominal characterization primaries" in text
    assert "not a measurement of the attached unit" in text
    assert "fresh plan" in text
    assert "explicit confirmation" in text
    assert "stores measured primaries" not in text
    assert "actual primaries" not in text
    assert "Get you within predicted dE < 1.0" not in text
    assert "calibrate-pro refine" not in text


def test_read_only_example_routes_actions_to_the_confirmed_gui_workflow() -> None:
    text = (ROOT / "examples" / "inspect_panels.py").read_text(encoding="utf-8")

    assert "Legacy action names are proposal-only and exit with code 2" in text
    assert "calibrate-pro gui" in text
    assert "preview and explicitly confirm" in text
    assert "require hardware / admin" not in text
    assert "automatic calibration of all displays" not in text
    assert "commands that DO touch hardware/system state" not in text


def test_the_readme_panel_counts_are_read_off_the_panel_database() -> None:
    """A panel added to the database without touching this page fails here.

    The totals were 58 and 20 while the database held 59 and 21, which is what a
    number transcribed once and then carried forward does. Both the total and
    every per-technology count are derived here, so the page cannot drift again
    without the drift being the failure.
    """
    from calibrate_pro.panels.database import get_builtin_panels

    panels = get_builtin_panels()
    counts = collections.Counter(panel.panel_type for panel in panels.values())
    text = readme()

    assert f"{len(panels)} characterized panels" in text
    for technology, count in sorted(counts.items()):
        assert f"- **{technology} ({count})**" in text, f"{technology} is listed as something other than {count}"


def test_every_command_the_readme_offers_first_is_answered_by_the_packaged_binary() -> None:
    """The first block on the page runs against the build the page recommends.

    It offered list-targets and list-panels while recommending the release
    build, which answers neither. Someone following the page in order met an
    error on the second line.
    """
    shipped = set(frozen_features()["commands"])

    offered = fenced_commands(readme(), TRY_IT_HEADING)

    assert offered, "the Try it block names no commands"
    assert set(offered) <= shipped, f"not in the packaged build: {sorted(set(offered) - shipped)}"


def test_the_readme_sorts_the_developer_only_names_the_way_the_packaging_does() -> None:
    """Two lists, one policy. A name that moves between them moves on this page.

    The names are checked against the packaging file rather than against each
    other, because a name dropped from both halves of the README reads as a
    command that does not exist rather than as one that lives elsewhere.
    """
    features = frozen_features()
    shipped = set(features["commands"])
    withheld = set(features["developer_only_commands"])
    text = readme()

    listed = set(fenced_commands(text, DEVELOPER_ONLY_INTRO))

    assert listed, "the developer-wheel block names no commands"
    assert not listed & shipped, f"the packaged build does answer: {sorted(listed & shipped)}"
    assert listed == withheld, f"the page and the packaging disagree: {sorted(listed ^ withheld)}"
    assert "exit code 2" in text
    assert "available only in the developer wheel" in text


def test_the_readme_does_not_offer_the_wheel_for_a_command_the_wheel_declines() -> None:
    """The block recommending an install may name only commands that install works for.

    It named every command absent from the packaged binary, two thirds of which
    the wheel refuses. The page is checked against the declined list rather than
    against the developer-only list, so a name that stops running in the wheel
    has to leave this block instead of quietly becoming bad advice.
    """
    declined = set(frozen_features()["declined_commands"])

    listed = set(fenced_commands(readme(), DEVELOPER_ONLY_INTRO))

    assert not listed & declined, f"the wheel declines these too: {sorted(listed & declined)}"


def test_the_readme_does_not_offer_a_measured_mode_the_manifest_declares_disabled() -> None:
    """The page says closed for exactly as long as the manifest says disabled.

    The mode table read as a choice between two methods, and the driver section
    read as a shipped capability, while both measured actions were disabled in
    the wheel and in the frozen binary. The check runs in both directions: it
    fails if the README stops saying closed, and it fails if the manifest opens
    the actions while the README still says they are closed.
    """
    manifest = json.loads((ROOT / "calibrate_pro/resources/action-capabilities.json").read_text(encoding="utf-8"))
    measured = {
        action["action_id"]: action
        for action in manifest["actions"]
        if action["action_id"] in {"calibration.method.measured", "verification.measured"}
    }
    assert len(measured) == 2, "the measured actions are not both declared"
    policies = {policy for action in measured.values() for policy in (action["source_policy"], action["frozen_policy"])}

    text = readme()
    says_closed = (
        f"**Measured calibration is closed in {SERIES}.**" in text and f"No surface in {SERIES} opens it." in text
    )

    assert says_closed is (policies == {"disabled"}), (
        f"README says closed={says_closed} while the manifest policies are {sorted(policies)}"
    )
    if says_closed:
        assert not re.search(r"\|\s*Measured\s*\|[^|]*\|\s*Instrument observations", text)


def measured_policies() -> set[str]:
    """Every policy the manifest declares for the two measured actions."""
    manifest = json.loads((ROOT / "calibrate_pro/resources/action-capabilities.json").read_text(encoding="utf-8"))
    declared = [action for action in manifest["actions"] if action["action_id"] in MEASURED_ACTIONS]
    assert {action["action_id"] for action in declared} == MEASURED_ACTIONS
    return {policy for action in declared for policy in (action["source_policy"], action["frozen_policy"])}


def test_no_public_page_makes_owning_an_instrument_the_thing_that_opens_measurement() -> None:
    """Four pages said a measured workflow requires a supported instrument.

    Each was true of the design and false of the build. Both measured actions are
    declared disabled in the wheel and in the frozen binary, so an operator who
    bought the colorimeter the page named would find the method still closed,
    with a reason that never mentions hardware. The gate is conditional on the
    manifest so that the sentence becomes sayable again on the day it is true.
    """
    if measured_policies() != {"disabled"}:
        return

    offenders = [
        name for name in PUBLIC_SURFACES if HARDWARE_IS_THE_ONLY_GATE.search((ROOT / name).read_text(encoding="utf-8"))
    ]

    assert offenders == [], f"these pages gate measurement on hardware alone: {offenders}"


def test_every_public_page_says_measured_calibration_is_closed_while_it_is() -> None:
    """One build, one answer, whichever page a reader arrived on.

    Checking the pages against the manifest rather than against each other is
    what makes this catch the case that matters: the manifest opens the actions
    and six pages go on saying closed, or it stays shut and a page quietly drops
    the sentence during an edit.
    """
    closed = measured_policies() == {"disabled"}

    said = {name for name in PUBLIC_SURFACES if CLOSURE_MARKER in (ROOT / name).read_text(encoding="utf-8")}

    expected = set(PUBLIC_SURFACES) if closed else set()
    assert said == expected, f"manifest closed={closed}; pages saying so: {sorted(said)}"


def test_the_usage_guide_documents_every_command_a_terminal_can_run() -> None:
    """The headless table is read back off the table the parsers are built from.

    Every check above this one asks whether a sentence is still there. This asks
    the other question, which is whether a command that now runs has a row at all.
    A command absent from the guide is a command an operator never learns about,
    and the guide has no way to notice that it went quiet.
    """
    from calibrate_pro.commands.session_args import COMMANDS

    text = (ROOT / "USAGE.md").read_text(encoding="utf-8")

    assert table_commands(text, HEADLESS_HEADING) == set(COMMANDS)


def test_the_headless_table_reader_reports_a_command_with_no_row() -> None:
    """The check on the check above, against a table one row short."""
    text = (ROOT / "USAGE.md").read_text(encoding="utf-8")
    documented = table_commands(text, HEADLESS_HEADING)
    thinned = text.replace("| `calibrate-pro detect` ", "| `calibrate-pro` ", 1)

    assert "detect" in documented
    assert table_commands(thinned, HEADLESS_HEADING) == documented - {"detect"}


def _referenced_issue_templates(text: str) -> set[str]:
    """Every issue form a document sends a reader to, by file name."""
    return set(re.findall(r"issues/new[?]template=([A-Za-z0-9_.-]+[.]yml)", text))


def test_every_issue_form_a_document_links_to_exists() -> None:
    """A link to a template that is not there opens a blank form, and the report
    arrives without the diagnostics the form would have required. Discussions was
    linked from the template config while the repository had them switched off,
    which is the same defect one layer along.
    """
    folder = ROOT / ".github" / "ISSUE_TEMPLATE"
    present = {path.name for path in folder.glob("*.yml")} - {"config.yml"}

    assert present, "the repository offers no issue forms"
    for surface in PUBLIC_SURFACES:
        text = (ROOT / surface).read_text(encoding="utf-8")
        missing = _referenced_issue_templates(text) - present
        assert missing == set(), f"{surface} links to issue forms that do not exist: {sorted(missing)}"


def test_every_issue_form_requires_the_diagnostics_that_make_it_actionable() -> None:
    """A report without `doctor --json` cannot tell a driver problem apart from a
    defect here, so the field is required rather than suggested. The form also has
    to keep saying what the command does and does not read, because that claim is
    what makes pasting it into a public issue safe.
    """
    # The release build verifies this source tree from a hash-locked environment
    # that carries only what the binary needs, and a parser for one docs gate is
    # not that. Every CI lane installs the test extra, which declares it, so the
    # gate runs there. test_release_metadata keeps that declaration honest.
    yaml = pytest.importorskip("yaml")

    folder = ROOT / ".github" / "ISSUE_TEMPLATE"
    forms = sorted(path for path in folder.glob("*.yml") if path.name != "config.yml")

    assert forms, "the repository offers no issue forms"
    for path in forms:
        body = yaml.safe_load(path.read_text(encoding="utf-8"))["body"]
        doctor = [field for field in body if field.get("id") == "doctor"]
        assert doctor, f"{path.name} does not ask for doctor output"
        assert doctor[0]["validations"]["required"] is True, f"{path.name} does not require it"
        described = doctor[0]["attributes"]["description"]
        assert "doctor --json" in described
        assert "no hardware" in described or "packaged" in described
