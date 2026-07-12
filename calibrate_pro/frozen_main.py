"""Minimal positive-allowlisted dispatcher for frozen Calibrate Pro binaries."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path

from calibrate_pro import __version__

_COMMANDS = {
    "doctor": "calibrate_pro.commands.doctor",
    "gui": "calibrate_pro.commands.gui",
    "hdr": "calibrate_pro.commands.hdr",
}

_DEVELOPER_ONLY_COMMANDS = {
    "auto",
    "calibrate",
    "ddc-calibrate",
    "ddc-info",
    "detect",
    "disable-startup",
    "enable-startup",
    "export-panel",
    "hdr-status",
    "import-panel",
    "info",
    "list-panels",
    "list-targets",
    "match",
    "native-calibrate",
    "patterns",
    "plugins",
    "profiles-generate",
    "refine",
    "restore",
    "status",
    "tray",
    "uniformity",
    "verify",
}

_DEVELOPER_ONLY_MESSAGE = "This command is available only in the developer wheel"


def _usage() -> str:
    return (
        "Calibrate Pro frozen commands:\n"
        "  doctor [--json]  Run read-only dependency and resource diagnostics\n"
        "  gui              Open the main desktop application\n"
        "  hdr              Open the HDR proposal application\n"
    )


def main(argv: Sequence[str] | None = None, *, program: str | None = None) -> int:
    """Dispatch one explicitly approved frozen command."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    executable = Path(program or sys.argv[0]).stem.casefold()

    if not arguments:
        if executable == "calibrateprocli":
            print(_usage())
            return 0
        arguments = ["gui"]

    command = arguments[0].casefold()
    if command in {"-h", "--help", "help"}:
        print(_usage())
        return 0
    if command in {"-v", "--version"}:
        print(f"Calibrate Pro {__version__}")
        return 0
    if command in _DEVELOPER_ONLY_COMMANDS:
        print(_DEVELOPER_ONLY_MESSAGE, file=sys.stderr)
        return 2

    module_name = _COMMANDS.get(command)
    if module_name is None:
        print(f"Unknown frozen command: {arguments[0]}", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 2
    command_module = import_module(module_name)
    return int(command_module.run(arguments[1:]))


if __name__ == "__main__":  # pragma: no cover - executable boundary
    raise SystemExit(main())
