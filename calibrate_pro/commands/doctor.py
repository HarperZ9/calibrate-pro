"""The read-only installation report, in the two forms the command line offers.

``--json`` is the schema-versioned form support automation reads, and it is the
one every packaged script and every test asks for. It was also the only form
this command produced: the flag was declared by both dispatchers, documented in
both usage listings, and read by neither, so an operator running ``doctor`` to
see whether the installation is sound got a single line of compact JSON.

The two dispatchers hand this module different things. The developer command
line parses first and passes a namespace; the frozen dispatcher passes the
arguments after the command name, unparsed. Both are read here, because the
flag means the same thing in both and neither caller should have to know that.

Nothing in this module probes a device. The capability block says so on its own
line rather than leaving ``supported`` to be read as a display, a colorimeter,
or a bus that was found.
"""

from __future__ import annotations

from typing import Any

#: Widths that hold the longest name each block emits without measuring the
#: report first, so a short report and a long one line up the same way.
_NAME_COLUMN = 22
_STATE_COLUMN = 19


def json_requested(args: Any) -> bool:
    """Read the flag from a parsed namespace or from raw arguments."""
    if args is None:
        return False
    if isinstance(args, (list, tuple)):
        return "--json" in args
    return bool(getattr(args, "json", False))


def _row(name: str, state: str, detail: str = "") -> str:
    line = f"  {name.ljust(_NAME_COLUMN)}{state.ljust(_STATE_COLUMN)}{detail}"
    return line.rstrip()


def _dependency_lines(dependencies: dict[str, Any]) -> list[str]:
    lines = ["Dependencies"]
    for name in sorted(dependencies):
        entry = dependencies[name]
        installed = bool(entry.get("installed"))
        version = str(entry.get("version") or "")
        lines.append(_row(name, "installed" if installed else "MISSING", version))
    return lines


def _check_lines(report: dict[str, Any]) -> list[str]:
    """The three whole-installation verdicts, each with the verdict in one column."""
    qt = report.get("qt", {})
    pq = report.get("pq", {})
    resources = report.get("resources", {})
    lines = [
        "Checks",
        _row("Qt binding", "ok" if qt.get("ok") else "FAILED", str(qt.get("api_name") or "")),
        _row("PQ reference math", "ok" if pq.get("ok") else "FAILED"),
    ]
    if not resources.get("applicable"):
        lines.append(_row("Packaged resources", "not applicable", "this distribution packages none"))
        return lines
    missing = [item["path"] for item in resources.get("required", ()) if not item.get("present")]
    lines.append(_row("Packaged resources", "complete" if not missing else f"{len(missing)} MISSING"))
    lines.extend(_row("", "", path) for path in missing)
    policy_error = resources.get("policy_error")
    if policy_error:
        lines.append(_row("Component policy", "ERROR", str(policy_error)))
    return lines


def _capability_lines(capabilities: dict[str, Any]) -> list[str]:
    lines = [
        "Capabilities",
        "  This reports what the installation supports. No display, colorimeter,",
        "  or bus was probed, so none of these lines says a device is present.",
    ]
    for name in sorted(capabilities):
        entry = capabilities[name]
        supported = "supported" if entry.get("software_supported") else "NOT SUPPORTED"
        presence = str(entry.get("device_presence") or "")
        if presence != "not_probed":
            supported = f"{supported}, device {presence}"
        lines.append(_row(name, supported, str(entry.get("detail") or "")))
    return lines


def render_doctor_text(report: dict[str, Any]) -> str:
    """Render the report for a person reading a terminal."""
    lines = [
        f"Calibrate Pro {report.get('version')}",
        f"Distribution          {report.get('distribution_mode')}",
        f"Installation          {report.get('application_root')}",
        "",
        *_dependency_lines(report.get("dependencies", {})),
        "",
        *_check_lines(report),
        "",
        *_capability_lines(report.get("capabilities", {})),
        "",
        f"Result: {'ok' if report.get('ok') is True else 'NOT OK'}",
        "Run with --json for the schema-1 report support automation reads.",
    ]
    return "\n".join(lines)


def run(args: Any = None) -> int:
    """Print the report in the requested form and return its truthful status."""
    from calibrate_pro.diagnostics import build_doctor_report, doctor_exit_code, render_doctor_json

    report = build_doctor_report()
    print(render_doctor_json(report=report) if json_requested(args) else render_doctor_text(report))
    return doctor_exit_code(report)
