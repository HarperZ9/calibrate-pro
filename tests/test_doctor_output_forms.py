"""``doctor`` answers a person and answers support automation, in two forms.

The command declared ``--json`` in both dispatchers and in both usage listings,
and printed compact JSON either way, so the flag documented a difference the
command did not make. The two dispatchers also hand the command different
things, a parsed namespace and a raw argument list, which is why reading the
flag from one of them would have left the other still ignoring it. Both shapes
are driven here.

The readable form is where a capability could quietly become a device claim, so
what it says about probing is checked rather than assumed.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from calibrate_pro.commands.doctor import json_requested, render_doctor_text, run
from calibrate_pro.diagnostics import render_doctor_json

#: A whole report with one of everything the readable form has a branch for: a
#: dependency that is present and one that is not, a failing check, a packaged
#: distribution missing a file, and a capability the installation cannot offer.
UNHEALTHY_REPORT: dict[str, Any] = {
    "schema_version": 1,
    "version": "9.9.9",
    "distribution_mode": "frozen",
    "application_root": r"C:\Program Files\Calibrate Pro",
    "dependencies": {
        "numpy": {"distribution": "numpy", "installed": True, "version": "2.4.5"},
        "scipy": {"distribution": "scipy", "installed": False, "version": None},
    },
    "qt": {"api_name": "PySide6", "ok": False},
    "pq": {"ok": False},
    "resources": {
        "applicable": True,
        "ok": False,
        "policy_error": "component policy is unreadable",
        "required": [
            {"path": "resources/one.json", "present": True},
            {"path": "resources/two.json", "present": False},
        ],
    },
    "capabilities": {
        "ddc_ci": {
            "software_supported": False,
            "device_presence": "not_probed",
            "probe": "library_symbol",
            "detail": "Dxva2.dll/GetVCPFeatureAndVCPFeatureReply",
        },
    },
    "ok": False,
}


def test_the_plain_form_is_for_a_person_rather_than_a_parser() -> None:
    """Running the command with no flag stops handing an operator raw JSON."""
    rendered = render_doctor_text(UNHEALTHY_REPORT)

    assert not rendered.startswith("{")
    assert "Calibrate Pro 9.9.9" in rendered
    assert r"C:\Program Files\Calibrate Pro" in rendered


def test_the_readable_form_says_no_device_was_probed() -> None:
    """A capability is what the installation supports, never what is attached.

    ``supported`` beside ``ddc_ci`` would otherwise read as a monitor that
    answered, which is the one thing this report never establishes.
    """
    rendered = render_doctor_text(UNHEALTHY_REPORT)

    assert "No display, colorimeter," in rendered
    assert "or bus was probed" in rendered
    assert "not_probed" not in rendered


def test_the_readable_form_names_what_failed() -> None:
    """Each failing part of the report is visible without reading the JSON."""
    rendered = render_doctor_text(UNHEALTHY_REPORT)

    assert "scipy" in rendered and "MISSING" in rendered
    assert "resources/two.json" in rendered
    assert "component policy is unreadable" in rendered
    assert "NOT SUPPORTED" in rendered
    assert rendered.rstrip().splitlines()[-2] == "Result: NOT OK"


def test_a_healthy_report_says_so_and_a_present_file_is_not_listed() -> None:
    """The complete case states the verdict and lists no missing path."""
    healthy = {**UNHEALTHY_REPORT, "ok": True}
    healthy["resources"] = {
        **UNHEALTHY_REPORT["resources"],
        "required": [{"path": "resources/one.json", "present": True}],
        "policy_error": None,
    }

    rendered = render_doctor_text(healthy)

    assert "Result: ok" in rendered
    assert "resources/one.json" not in rendered
    assert "MISSING" in rendered  # scipy is still absent; only the resource list is complete


def test_the_flag_is_read_from_both_shapes_the_dispatchers_pass() -> None:
    """One dispatcher parses first and one does not, so both shapes are read."""
    assert json_requested(argparse.Namespace(json=True)) is True
    assert json_requested(argparse.Namespace(json=False)) is False
    assert json_requested(["--json"]) is True
    assert json_requested([]) is False
    assert json_requested(None) is False


def test_the_json_form_is_the_schema_report_from_either_dispatcher(capsys: Any) -> None:
    """What automation reads is unchanged, whichever dispatcher asked for it."""
    assert run(argparse.Namespace(json=True)) in {0, 1}
    from_namespace = capsys.readouterr().out

    assert run(["--json"]) in {0, 1}
    from_arguments = capsys.readouterr().out

    assert json.loads(from_namespace)["schema_version"] == 1
    assert from_namespace == from_arguments
    assert from_namespace.strip() == render_doctor_json(report=json.loads(from_namespace))


def test_running_without_the_flag_prints_the_readable_form(capsys: Any) -> None:
    """The regression, driven through the command rather than the renderer."""
    assert run(argparse.Namespace(json=False)) in {0, 1}
    printed = capsys.readouterr().out

    assert printed.startswith("Calibrate Pro ")
    assert "Run with --json" in printed
