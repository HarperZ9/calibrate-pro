"""How the command line decides what to do with a name an operator typed.

Every name the parser offers falls into one of three groups, and this holds the
groups apart. A driven command reaches the session a window drives, a declined
one names the action behind it and quotes the resolver on that action, and a
name with no capability declared anywhere says so without inventing one.

Two failures are worth naming because both read as working software. A name
offered by the parser with nothing behind it raises a lookup error at the moment
an operator uses it, and a name in two groups at once takes whichever branch is
written first, which makes the printed policy depend on the order of an if.

The last test here is about startup rather than behaviour. The parser is built
without the action layer, so a ``--help`` and a rejected flag do not pay for a
module they never read. A command that pulled it in at import time would undo
that quietly, which is why the probe runs in an interpreter of its own.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap

import pytest

from calibrate_pro import main
from calibrate_pro.application.actions import ActionRegistry
from calibrate_pro.application.composition import build_production_service
from calibrate_pro.commands import session
from calibrate_pro.commands.catalog import REFERENCE_HEADING


def parser_commands() -> set[str]:
    """Every subcommand the parser offers, read off the parser it builds."""
    parser = main._build_parser()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    return set(subparsers.choices)


def test_every_driven_command_the_parser_offers_has_a_driver() -> None:
    """The names are written out to keep the parser off the action layer.

    Holding the two lists equal is what makes that safe. A driver added without
    a parser entry is unreachable, and a parser entry without a driver raises a
    lookup error in front of whoever typed it.
    """
    assert set(session.COMMANDS) == main._SESSION_COMMANDS


def test_every_declined_command_names_an_action_this_build_declares() -> None:
    """A refusal cites the manifest, so the action it cites has to be in it."""
    declared = ActionRegistry.load_default().action_ids

    assert set(main._DECLARED_REFUSALS.values()) <= declared


def test_no_command_belongs_to_two_groups_at_once() -> None:
    """Three groups, no overlap, and together they are what the parser offers."""
    groups = (main._SESSION_COMMANDS, main._CONFIRMATION_COMMANDS, set(main._HANDLERS))

    for index, group in enumerate(groups):
        for other in groups[index + 1 :]:
            assert not group & other

    assert set().union(*groups) == parser_commands()


def test_a_declined_command_quotes_the_resolver_rather_than_a_sentence_of_its_own(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One decision, one place it is worded, whichever surface reads it back."""
    resolved = build_production_service().resolve("display.restore_defaults")

    code = main.main(["restore"])

    printed = capsys.readouterr().out
    assert code == main.REFUSED
    assert "restore" in printed
    assert "display.restore_defaults" in printed
    assert f"{resolved.disposition.value}: {resolved.reason}" in printed
    assert main._UNTOUCHED in printed


def test_a_name_with_nothing_behind_it_says_so_without_naming_an_action(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An honest null. There is no action to cite, so none is invented to cite."""
    code = main.main(["match"])

    printed = capsys.readouterr().out
    assert code == main.REFUSED
    assert "This build declares no" in printed
    assert main._UNTOUCHED in printed
    assert not any(action_id in printed for action_id in main._DECLARED_REFUSALS.values())


def test_an_unrecognized_flag_is_rejected_before_anything_is_dispatched(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A flag nothing read is an error, not something quietly refused with it.

    Accepting it and then declining the command reads as though the flag had
    been understood, which is the reading that matters when the flag is the one
    that would have made the command act.
    """
    with pytest.raises(SystemExit) as raised:
        main.main(["restore", "--now"])

    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert "unrecognized arguments: --now" in captured.err
    assert captured.out == ""


def test_a_calibration_command_requires_the_target_it_would_calibrate_to() -> None:
    """No default target. A default here would be a second copy of a preset name."""
    with pytest.raises(SystemExit) as raised:
        main.main(["verify"])

    assert raised.value.code == 2


def test_list_targets_leads_with_the_targets_a_session_can_be_set_to(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The catalogue below is reference material, and it is labelled as such.

    Leading with the definitions listed a vocabulary no session can be set to,
    which reads as a list of choices. The selectable targets come first now, and
    they are read off the same table the action layer selects from.
    """
    code = main.main(["list-targets"])

    printed = capsys.readouterr().out
    assert code == 0
    assert REFERENCE_HEADING in printed
    for name in session.preset_names():
        assert printed.index(name) < printed.index(REFERENCE_HEADING)


def test_building_the_parser_loads_neither_the_action_layer_nor_a_driver() -> None:
    """Startup cost is a product property, so it is measured rather than assumed."""
    probe = textwrap.dedent(
        """
        import json, sys
        from calibrate_pro import main
        main._build_parser()
        watched = ("calibrate_pro.application.actions", "calibrate_pro.commands.session")
        print(json.dumps([name for name in watched if name in sys.modules]))
        """
    )

    completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)

    assert json.loads(completed.stdout.strip().splitlines()[-1]) == []
