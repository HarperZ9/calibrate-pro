"""A session shaped like the one a terminal drives, over a display nobody owns.

The commands in `calibrate_pro.commands.session` drive the production
composition, whose acknowledgement confirms a plan without applying it. The
fake-acceptance composition acknowledges differently, entering the apply stage
and minting a token, so verification there waits on an apply no terminal
performs. Driving the commands against that composition would hold down an
ordering the shipped product never uses.

The service is therefore wired here by hand: production collaborators, the
production acknowledgement, and the bundled synthetic display in place of an
enumerator that would open a real one. It reaches no hardware and writes only
inside the directory it is handed.

It is built in the tests rather than in the package on purpose. A shipped build
able to construct this would be a build able to report a confirmed session over
a panel that does not exist, which is the one thing the withheld fixture
resource exists to prevent.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from calibrate_pro.application.composition import (
    FAKE_DISPLAY_RESOURCE,
    _engine_and_generator,
    _runner,
    load_fake_display,
)
from calibrate_pro.application.detection import DeniedCapabilityProbe, DisplayDetector
from calibrate_pro.application.journal import DiagnosticJournal
from calibrate_pro.application.service import FunctionalRecoveryService
from calibrate_pro.application.session import SessionState
from calibrate_pro.commands import session as commands
from calibrate_pro.panels.database import get_database

#: Named the way the production enumerator is named, so a journal record says
#: where the display came from rather than leaving it to be inferred.
ENUMERATOR_NAME = f"tests.session_support:{FAKE_DISPLAY_RESOURCE}"

_PROBE_REASON = "no capability is probed under test"

#: The target every command test asks for unless it is testing target handling.
PRESET = "srgb_web"


def build_cli_service(root: Path) -> FunctionalRecoveryService:
    """Build the session a terminal drives, journalled under `root`."""
    display = load_fake_display()
    state = SessionState()
    journal = DiagnosticJournal(root / "diagnostics")
    database = get_database()
    engine, generator = _engine_and_generator(database)
    detector = DisplayDetector(
        enumerator=lambda: (display,),
        capability_probe=DeniedCapabilityProbe(_PROBE_REASON),
        database=database,
        enumerator_name=ENUMERATOR_NAME,
    )
    return FunctionalRecoveryService(
        state=state,
        runner=_runner(state, journal),
        detector=detector,
        generator=generator,
        engine=engine,
    )


def arguments(**fields: Any) -> SimpleNamespace:
    """The parsed arguments one command reads, with the target already chosen."""
    return SimpleNamespace(**{"target": PRESET, **fields})


def run(command: str, service: FunctionalRecoveryService, **fields: Any) -> tuple[int, str]:
    """Drive one command and hand back its exit code beside what it printed."""
    printed = io.StringIO()
    with redirect_stdout(printed):
        code = commands.run(command, arguments(**fields), service=service)
    return code, printed.getvalue()


def lines(text: str) -> list[str]:
    """The printed lines, blank ones dropped, so a test names what it reads."""
    return [line for line in text.splitlines() if line.strip()]


def field(text: str, name: str) -> str:
    """The value printed beside one indented field name, or a failure naming it."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(name):
            return stripped[len(name) :].strip()
    raise AssertionError(f"no {name!r} line in:\n{text}")


__all__ = [
    "ENUMERATOR_NAME",
    "PRESET",
    "arguments",
    "build_cli_service",
    "field",
    "lines",
    "run",
]
