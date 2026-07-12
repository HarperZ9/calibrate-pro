"""Read-only doctor command."""

from __future__ import annotations

from typing import Any


def run(args: Any) -> int:
    """Print a deterministic diagnostic report and return its truthful status."""
    from calibrate_pro.diagnostics import build_doctor_report, doctor_exit_code, render_doctor_json

    report = build_doctor_report()
    print(render_doctor_json(report=report))
    return doctor_exit_code(report)
