"""What importing the verification package costs, and what it still offers.

The package is a table of names, and each one is read from its module the first
time something asks for it. Two things have to hold for that to be worth doing.
Importing the package may load none of those modules, or the table is decoration
over the cost it was written to avoid. Every name the package offers has to keep
resolving to the object its module holds, because a table that goes stale breaks
a caller when that caller runs rather than when the table changed.

The last test is why the table exists at all. The gamut analysis imports scipy,
which costs most of a second, and the action layer reaches this package for one
dataclass. Every headless command paid that second before printing a line.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from importlib import import_module

from calibrate_pro import verification


def modules_after(statement: str) -> list[str]:
    """Which modules one import leaves behind, measured in a fresh interpreter."""
    probe = textwrap.dedent(
        f"""
        import json, sys
        {statement}
        watched = ("calibrate_pro.verification.", "scipy")
        print(json.dumps(sorted(n for n in sys.modules if n.startswith(watched))))
        """
    )
    completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_importing_the_package_imports_none_of_the_modules_behind_it() -> None:
    """The package is the table and nothing else until a name is asked for."""
    assert modules_after("import calibrate_pro.verification") == []


def test_asking_for_a_name_imports_the_one_module_that_name_needs() -> None:
    """A grayscale caller pays for the grayscale module, and for nothing else."""
    loaded = modules_after("from calibrate_pro.verification import GrayscaleVerifier")

    assert "calibrate_pro.verification.grayscale" in loaded
    assert "calibrate_pro.verification.gamut_volume" not in loaded
    assert "scipy" not in loaded


def test_every_name_it_offers_resolves_to_the_object_its_module_holds() -> None:
    """A renamed attribute fails here rather than at the call site that wanted it."""
    assert set(verification.__all__) == set(verification._EXPORTS) | {"grade_to_string"}

    for name, (module_name, attribute) in verification._EXPORTS.items():
        assert getattr(verification, name) is getattr(import_module(module_name), attribute)


def test_the_action_layer_reaches_no_scientific_stack_to_declare_its_actions() -> None:
    """The startup cost every headless command pays, held down where it was found."""
    loaded = modules_after("import calibrate_pro.application.actions")

    assert not [name for name in loaded if name.startswith("scipy")]
