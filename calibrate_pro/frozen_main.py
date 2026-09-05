"""Minimal positive-allowlisted dispatcher for frozen Calibrate Pro binaries."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path

from calibrate_pro import __version__
from calibrate_pro.commands.session_args import COMMANDS as _SESSION_COMMANDS

#: The commands that are one module each, named as strings so that choosing one
#: is what imports it. Opening a window is a heavy import; running a diagnostic
#: is not, and neither should pay for the other.
_COMMANDS = {
    "doctor": "calibrate_pro.commands.doctor",
    "gui": "calibrate_pro.commands.gui",
    "hdr": "calibrate_pro.commands.hdr",
}

#: Names the developer command line offers that this build does not ship. They
#: are listed rather than inferred from what is missing, so a command added
#: there is refused here until somebody says which of the two lists it is in.
_DEVELOPER_ONLY_COMMANDS = {
    "auto",
    "calibrate",
    "ddc-calibrate",
    "ddc-info",
    "disable-startup",
    "enable-startup",
    "export-panel",
    "hdr-status",
    "import-panel",
    "info",
    "list-panels",
    "list-targets",
    "match",
    "mcp",
    "native-calibrate",
    "patterns",
    "plugins",
    "refine",
    "restore",
    "tray",
    "uniformity",
}

_DEVELOPER_ONLY_MESSAGE = "This command is available only in the developer wheel"

_USAGE_LINES = (
    "Calibrate Pro frozen commands:",
    "  doctor [--json]        Run read-only dependency and resource diagnostics",
    "  gui                    Open the main desktop application",
    "  hdr                    Open the HDR proposal application",
    "  detect                 Report the displays this machine presents",
    "  status [--closed]      Report which actions this session can run",
    "  verify --target NAME   Generate a plan and report its predicted accuracy",
    "  generate-profiles DIR --target NAME",
    "                         Write one calibration bundle into a directory",
    "  profiles DIR           List published bundles and check each one's seal",
    "  diagnostics [--bundle PATH] [--open]",
    "                         List the session journal and publish it for support",
    "",
    "Add --help to any of these for the arguments it takes.",
)


def _usage() -> str:
    return "\n".join(_USAGE_LINES) + "\n"


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

    if command in _SESSION_COMMANDS:
        from calibrate_pro.commands.session import run_argv

        return run_argv(command, arguments[1:])

    module_name = _COMMANDS.get(command)
    if module_name is None:
        print(f"Unknown frozen command: {arguments[0]}", file=sys.stderr)
        print(_usage(), file=sys.stderr)
        return 2
    command_module = import_module(module_name)
    return int(command_module.run(arguments[1:]))


if __name__ == "__main__":  # pragma: no cover - executable boundary
    raise SystemExit(main())
