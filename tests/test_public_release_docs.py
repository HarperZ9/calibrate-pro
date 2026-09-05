"""Public release documentation must describe the 1.1 safety contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_identifies_the_current_release_and_qt_binding() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "version-1.1.0" in text
    assert "Release:** Calibrate Pro 1.1.0" in text
    assert "PySide6" in text
    assert "PyQt6" not in text
    assert 'src="https://raw.githubusercontent.com/HarperZ9/calibrate-pro/v1.1.0/' in text
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


def test_release_notes_are_for_1_1_and_name_the_evidence_boundary() -> None:
    text = (ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")

    assert text.startswith("# Calibrate Pro v1.1.0\n")
    assert "Not measured" in text
    assert "PySide6" in text
    assert "PyQt6" not in text
    assert "not Authenticode-signed" in text


def test_usage_guide_matches_the_1_1_command_and_privilege_contract() -> None:
    text = (ROOT / "USAGE.md").read_text(encoding="utf-8")

    assert "Calibrate Pro 1.1" in text
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
    """The block of legacy names is read back off the dispatcher that declines them.

    It was a hand-kept list, and it named five commands that run now. A guide that
    tells an operator a working command exits 2 reads as a reason not to try it,
    which is the failure this catches rather than a typo in a table.
    """
    from calibrate_pro.main import _CONFIRMATION_COMMANDS

    text = (ROOT / "USAGE.md").read_text(encoding="utf-8")
    section = text.split("## Proposal-only legacy commands", 1)[1]
    listed = section.split("```text", 1)[1].split("```", 1)[0]

    assert set(listed.split()) == set(_CONFIRMATION_COMMANDS)


def test_enterprise_readiness_describes_the_shipped_boundary() -> None:
    text = (ROOT / "docs" / "ENTERPRISE-READINESS.md").read_text(encoding="utf-8")

    assert "Calibrate Pro 1.1" in text
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


def test_public_site_matches_the_1_1_operator_and_evidence_boundaries() -> None:
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
