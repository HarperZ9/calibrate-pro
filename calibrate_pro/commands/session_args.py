"""The arguments a session command takes, written once for two entry points.

The developer command line offers every one of these as a subcommand of one
parser. The frozen binary chooses a single command per run and has no developer
parser to route through, so it reads this same table for that one command. A
flag added for either entry point arrives at the other, rather than being
written twice in two places that then drift.

Nothing here reaches the action layer. The developer parser is built before a
command has been chosen, so a ``--help`` and a rejected flag would otherwise pay
for a module neither of them reads.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

#: Every command the session driver answers to, named for a parser to offer.
COMMANDS = frozenset({"detect", "diagnostics", "generate-profiles", "profiles", "status", "verify"})


def add_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Give every session command the arguments it needs, and nothing spare.

    A target is required rather than defaulted. A default here would be a second
    copy of a preset name, and the one place a preset name belongs is the table
    the action layer selects from.
    """
    subparsers.add_parser("detect", help="Observe attached displays and report what was read")
    status = subparsers.add_parser("status", help="Report which actions this session can run")
    status.add_argument("--closed", action="store_true", help="Show only the actions that are unavailable")
    for name, summary in (
        ("verify", "Generate a plan and report its predicted accuracy"),
        ("generate-profiles", "Write one calibration bundle into a directory"),
    ):
        command = subparsers.add_parser(name, help=summary)
        if name == "generate-profiles":
            command.add_argument("output", help="Directory the bundle is written into")
            command.add_argument("--dry-run", action="store_true", help="Stop at the plan and write nothing")
        command.add_argument("--target", required=True, help="Calibration target; see 'list-targets'")
        command.add_argument("--display", help="Platform display id; the detected display is used by default")
    profiles = subparsers.add_parser("profiles", help="List published bundles and check each one's seal")
    profiles.add_argument("directory", help="Directory holding published bundles")
    bundle = subparsers.add_parser("diagnostics", help="List the session journal and publish it for support")
    bundle.add_argument("--bundle", help="File path to publish the diagnostic bundle at")
    bundle.add_argument("--open", action="store_true", help="Open the folder the journal is kept in")


def parse(command: str, argv: Sequence[str]) -> argparse.Namespace:
    """Read one command's arguments, from a parser built off the same table.

    The command has already been chosen by the time this is called, so its name
    goes back in front of the arguments and is parsed with them. That is what
    keeps a single definition of what each command accepts, and it keeps the
    usage line argparse prints on a mistake naming the program that was run.
    """
    parser = argparse.ArgumentParser(description="Calibrate Pro - least-privilege display calibration")
    subparsers = parser.add_subparsers(dest="command")
    add_parsers(subparsers)
    return parser.parse_args([command, *argv])


__all__ = ["COMMANDS", "add_parsers", "parse"]
