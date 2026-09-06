"""Holding the action manifest to the code it names.

Every action declares the modules its handler needs. Nothing imported them. The
loader checks each name has the shape of a dotted identifier and stops there, so
``calibrate_pro.application.diagnostics`` sat in the manifest across a green
suite while no such file existed, and three actions the manifest called
available named a module an operator's build could not have loaded.

Shape is not existence. These gates import what the manifest names and read the
frozen policy back against it, which is the difference between a declaration
that parses and a declaration that is true.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: A policy value meaning the action is offered in that build, either outright
#: or once its predicate is satisfied. Either way an operator can reach it, so
#: the module behind it has to be there.
LIVE_POLICIES = frozenset({"enabled", "conditional"})

#: A name chosen to be absent. It is used to prove a gate below reports what it
#: is looking for rather than passing over an empty set.
ABSENT_MODULE = "calibrate_pro.application.no_such_module"


def manifest() -> dict:
    """The manifest the shipped registry loads, read as plain data."""
    path = ROOT / "calibrate_pro/resources/action-capabilities.json"
    return json.loads(path.read_text(encoding="utf-8"))


def frozen_policy() -> dict:
    """The module policy the binary is built against."""
    path = ROOT / "packaging/frozen-modules.json"
    return json.loads(path.read_text(encoding="utf-8"))


def declared_modules(*, frozen_only: bool = False) -> set[str]:
    """Every module the manifest requires, optionally only for the binary."""
    return {
        module
        for action in manifest()["actions"]
        if not frozen_only or action["frozen_policy"] in LIVE_POLICIES
        for module in action["required_modules"]
    }


def unimportable(modules: Iterable[str]) -> list[str]:
    """The names in this set that Python cannot import right now."""
    missing = []
    for name in sorted(set(modules)):
        try:
            import_module(name)
        except ImportError:
            missing.append(name)
    return missing


def actions_requiring(module: str) -> list[str]:
    """Which actions named one module, so a failure says whose it is."""
    return sorted(action["action_id"] for action in manifest()["actions"] if module in action["required_modules"])


def test_every_module_the_manifest_requires_can_be_imported() -> None:
    """A declared module that does not import is an action nobody wrote."""
    missing = unimportable(declared_modules())

    assert missing == [], {name: actions_requiring(name) for name in missing}


def test_the_import_gate_reports_a_module_that_is_not_there() -> None:
    """The check on the check: the gate above passes on existence, not on emptiness."""
    assert declared_modules(), "the manifest declared no modules at all"
    assert unimportable([*declared_modules(), ABSENT_MODULE]) == [ABSENT_MODULE]


def test_every_module_a_shipped_action_requires_is_approved_unconditionally() -> None:
    """An optional module is one the build may omit, and a required one is not.

    The allowlist gate walks imports, so it covers a module some other module
    imports. This one covers the other direction: a module the manifest requires
    for an action the binary offers, which nothing happens to import yet.
    """
    policy = frozen_policy()
    approved = set(policy["first_party_exact"])
    optional = set(policy["optional_first_party_exact"])
    unapproved = sorted(declared_modules(frozen_only=True) - approved)

    assert unapproved == [], {
        name: ("optional in the frozen policy" if name in optional else "absent from the frozen policy")
        for name in unapproved
    }


def test_the_frozen_approval_gate_reports_a_module_the_policy_omits() -> None:
    """The check on the check above, against a name no policy lists."""
    approved = set(frozen_policy()["first_party_exact"])
    required = declared_modules(frozen_only=True)

    assert required, "no action is offered in the frozen build"
    assert sorted({*required, ABSENT_MODULE} - approved) == [ABSENT_MODULE]
