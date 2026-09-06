"""How the command line decides what to do with a name an operator typed.

Every name the parser offers falls into one of three groups, and this holds the
groups apart. A driven command reaches the session a window drives, a declined
one names the action behind it and quotes the resolver on that action, and a
name with no capability declared anywhere says so without inventing one.

Two failures are worth naming because both read as working software. A name
offered by the parser with nothing behind it raises a lookup error at the moment
an operator uses it, and a name in two groups at once takes whichever branch is
written first, which makes the printed policy depend on the order of an if.

The frozen build answers a subset of these names and refuses the rest by saying
which package they are in. That split is written down in the packaging policy,
and a name in neither half of it reaches an operator as an unknown command, so
the two halves are held against what the parser actually offers.

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
from pathlib import Path

import pytest

from calibrate_pro import main
from calibrate_pro.application.actions import ActionDisposition, ActionRegistry
from calibrate_pro.application.composition import build_production_service
from calibrate_pro.application.pattern_catalogue import CATALOGUE
from calibrate_pro.commands import session, session_args, session_ddc
from calibrate_pro.commands.list_targets import REFERENCE_HEADING

ROOT = Path(__file__).resolve().parents[1]


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


# Builds the production service, whose journal root is the Windows
# per-user application directory. Running it where that directory does not
# exist would test a faked environment rather than the shipped one.
@pytest.mark.windows
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
    assert resolved.reason in printed
    assert main._UNTOUCHED in printed


def test_listing_the_patterns_answers_from_the_catalogue_and_not_the_viewer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The catalogue is a table of numbers, so listing it needs no machine.

    This name used to be declined while a fullscreen tkinter viewer sat behind
    the window menu with no resolver in front of it. One question had two
    answers and the surface that acted was the ungated one. The name now runs
    the shipped lane, and the assertion that kept the two apart is kept: the
    legacy viewer stays unimported, so a later reader can tell which surface
    answered rather than guessing from the printed lines.
    """
    code = main.main(["patterns"])

    printed = capsys.readouterr().out
    assert code == 0
    for pattern in CATALOGUE:
        assert pattern.pattern_id in printed
        assert pattern.decision in printed
    assert "calibrate_pro.patterns.display" not in sys.modules


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


def test_the_frozen_build_places_every_name_the_parser_offers_in_one_list() -> None:
    """A name is shipped in the binary, held back to the wheel, or declined everywhere.

    No list is derived from the parser, which is what makes this a check rather
    than a restatement of one table in another. A name in none of the three is
    answered by the frozen binary as an unknown command, which reads to an
    operator as a typo rather than as a command that exists elsewhere.
    """
    features = json.loads((ROOT / "packaging/frozen-features.json").read_text(encoding="utf-8"))
    shipped = set(features["commands"])
    withheld = set(features["developer_only_commands"])
    declined = set(features["declined_commands"])

    assert not shipped & withheld
    assert not shipped & declined
    assert not withheld & declined
    assert shipped | withheld | declined == parser_commands()


def test_the_frozen_build_sends_nobody_to_a_wheel_that_declines_the_same_name() -> None:
    """The packaged binary named 21 commands as living in the developer wheel.

    Fourteen of them are refused by that wheel. An operator who typed one read
    an instruction to install Python and a package, did it, and met the same
    refusal at the end. The two halves are split here against the refusal table
    itself, so a name can only be advertised as available elsewhere while the
    wheel still runs it.
    """
    features = json.loads((ROOT / "packaging/frozen-features.json").read_text(encoding="utf-8"))

    assert features["declined_commands"] == sorted(main._CONFIRMATION_COMMANDS)
    assert not set(features["developer_only_commands"]) & main._CONFIRMATION_COMMANDS


@pytest.mark.windows
def test_every_declined_name_refuses_in_the_same_shape(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A tester who types a legacy name reads one answer, not two.

    Half the names the parser offers are declined, and they arrive by two code
    paths. One quotes the resolver on the action behind the name, the other says
    no capability is declared. Both are answering the same question, so both owe
    the reader the same shape: what will not run, and that nothing was touched.
    """
    for command in sorted(main._CONFIRMATION_COMMANDS):
        code = main.main([command])
        printed = capsys.readouterr().out

        assert code == main.REFUSED, f"{command} did not refuse"
        assert command in printed, f"{command} does not name itself"
        assert main._UNTOUCHED in printed, f"{command} does not say nothing was touched"


@pytest.mark.windows
def test_no_declined_name_answers_with_an_internal_disposition_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``hidden`` is how the capability model classifies an action, not English.

    Printing it beside a refusal told a reader the command was hidden while the
    same reader had just seen it listed in ``--help``. The reason string carries
    the meaning already, so the classification stays on the surface that reports
    the model.
    """
    tokens = {member.value for member in ActionDisposition}

    for command in sorted(main._CONFIRMATION_COMMANDS):
        main.main([command])
        printed = capsys.readouterr().out
        leaked = {token for token in tokens if f"{token}:" in printed}
        assert leaked == set(), f"{command} printed {sorted(leaked)}"


@pytest.mark.windows
def test_the_status_report_still_classifies_each_action() -> None:
    """The control for the gate above, which a blanket ban would pass silently.

    Removing the vocabulary everywhere would satisfy the previous test and lose
    the report that makes a support conversation possible, so this holds the one
    surface whose job is to name the disposition.
    """
    service = build_production_service()
    lines = session._action_lines(service, closed_only=True)

    assert lines, "no action is closed in a default session"
    named = {line.split()[0] for line in lines if not line.startswith("           ")}
    assert named <= {member.value for member in ActionDisposition}
    assert named & {ActionDisposition.HIDDEN.value, ActionDisposition.DISABLED.value}


def test_the_display_control_flags_name_the_controls_the_session_can_stage() -> None:
    """The parser's control list is held against the one the session stages from.

    The parser writes its eight flags out by hand so that building it stays off
    the application layer, which a ``--help`` should not pay for. That is a
    second copy of the control table, and a copy with nothing holding it is a
    copy that drifts. So the flags are read off the built parser and compared
    against flags derived from the staging actions themselves: a control added
    to the application and not to the parser is unreachable from a terminal, and
    a flag with no staging action behind it fails at the moment somebody uses it.
    """
    parser = main._build_parser()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    calibrate = subparsers.choices["ddc-calibrate"]

    offered = {option for action in calibrate._actions for option in action.option_strings}

    assert set(session_ddc.control_flags()) <= offered
    assert {f"--{flag}" for flag, _label in session_args.DISPLAY_CONTROLS} == set(session_ddc.control_flags())
