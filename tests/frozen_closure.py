"""Which first-party modules a frozen entry point can reach, read from source.

The spec file turns every first-party module absent from the allowlist into a
PyInstaller exclude, so an unlisted module is not merely left out of the hidden
imports, it is refused when something else pulls it in. A closure computed here
is what the allowlist is measured against, and it is read out of the source tree
rather than out of a build, so the gate runs without freezing anything.

Three things a plain import walk would get wrong are handled. A lazily imported
module is imported all the same, so import statements inside function bodies
count. A module named only as a string, handed to ``import_module`` or held in a
module-level lookup table, is imported through that name, so those strings count
too. A name imported under ``if TYPE_CHECKING`` never executes, so it does not.

One module in the closure cannot ship: ``patterns.display`` imports ``tkinter``
at module level and the spec excludes ``tkinter``. That is a property of the
module rather than of the guard around its one call site, so it is derived here
the same way, by reading which module-level imports the frozen graph refuses.
Separating the two is what lets the allowlist gate demand everything reachable
while the blocked-import gate demands that whatever cannot ship is only ever
imported behind a handler.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = "calibrate_pro"

#: Exception names whose handler makes a failed import survivable. A missing
#: module raises ``ModuleNotFoundError``, so catching that name counts too.
_IMPORT_HANDLERS = frozenset({"BaseException", "Exception", "ImportError", "ModuleNotFoundError"})

#: Callables whose first string argument names a module to import.
_DYNAMIC_IMPORTS = frozenset({"__import__", "import_module"})

_CONTAINERS = (ast.Dict, ast.List, ast.Set, ast.Tuple)

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


class ImportSite:
    """One import statement, with the two facts that decide what it means."""

    __slots__ = ("guarded", "names", "run_on_import")

    def __init__(self, names: set[str], *, guarded: bool, run_on_import: bool) -> None:
        self.names = names
        self.guarded = guarded
        self.run_on_import = run_on_import


def source_of(root: Path, module: str) -> Path | None:
    """The file a dotted first-party name is read from, or None if it is not one."""
    relative = Path(*module.split("."))
    for candidate in (root / relative.with_suffix(".py"), root / relative / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _containing_package(module: str, source: Path, level: int) -> str | None:
    """Which package a relative import counts up from, given where it was written."""
    parts = module.split(".")
    if source.name != "__init__.py":
        parts = parts[:-1]
    kept = len(parts) - (level - 1)
    return ".".join(parts[:kept]) if kept > 0 else None


def _statement_names(node: ast.Import | ast.ImportFrom, module: str, source: Path) -> set[str]:
    """The dotted names one import statement reaches, relative forms resolved."""
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names}
    if node.level:
        package = _containing_package(module, source, node.level)
        if package is None:
            return set()
        resolved = f"{package}.{node.module}" if node.module else package
    elif node.module:
        resolved = node.module
    else:
        return set()
    return {resolved, *(f"{resolved}.{alias.name}" for alias in node.names)}


def _handles_import_error(node: ast.Try) -> bool:
    """Whether one ``try`` block is written to carry on without the module."""
    for handler in node.handlers:
        caught = handler.type
        named = list(caught.elts) if isinstance(caught, ast.Tuple) else [caught]
        if any(isinstance(item, ast.Name) and item.id in _IMPORT_HANDLERS for item in named):
            return True
    return False


def _is_type_checking(test: ast.expr) -> bool:
    """Whether an ``if`` guards a block that only a type checker ever reads."""
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _named_in_strings(node: ast.AST) -> set[str]:
    """Module names written as strings rather than as import statements."""
    names: set[str] = set()
    for statement in ast.iter_child_nodes(node):
        value = getattr(statement, "value", None)
        if isinstance(statement, ast.Assign | ast.AnnAssign) and isinstance(value, _CONTAINERS):
            names.update(
                inner.value
                for inner in ast.walk(value)
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str)
            )
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call) or not inner.args:
            continue
        called = inner.func.attr if isinstance(inner.func, ast.Attribute) else getattr(inner.func, "id", None)
        first = inner.args[0]
        if called in _DYNAMIC_IMPORTS and isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.add(first.value)
    return names


def _visit(node: ast.AST, module: str, source: Path, *, guarded: bool, top: bool, into: list[ImportSite]) -> None:
    """Read one node, carrying down whether imports below it are guarded.

    ``top`` is whether the node runs when the module is imported. It survives a
    class body and an ``if``, and it is dropped inside a function, because an
    import written there does not run until something calls it.
    """
    if isinstance(node, ast.Import | ast.ImportFrom):
        into.append(ImportSite(_statement_names(node, module, source), guarded=guarded, run_on_import=top))
        return
    if isinstance(node, ast.If) and _is_type_checking(node.test):
        children: list[ast.AST] = list(node.orelse)
    elif isinstance(node, ast.Try) and _handles_import_error(node):
        guarded = True
        children = list(ast.iter_child_nodes(node))
    else:
        if isinstance(node, _FUNCTIONS):
            top = False
        children = list(ast.iter_child_nodes(node))
    for child in children:
        _visit(child, module, source, guarded=guarded, top=top, into=into)


def import_sites(source: Path, module: str) -> list[ImportSite]:
    """Every import one module performs, each with its guard and its timing.

    The string-named modules are reported as one guarded site that does not run
    on import. A lookup table is consulted rather than executed, so its entries
    are reachable without being anything the module itself fails to import.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    sites: list[ImportSite] = []
    _visit(tree, module, source, guarded=False, top=True, into=sites)
    strings = _named_in_strings(tree)
    if strings:
        sites.append(ImportSite(strings, guarded=True, run_on_import=False))
    return sites


def spec_excludes(spec: Path) -> set[str]:
    """The names a frozen build refuses outright, read from the spec's own literal.

    Reading the spec rather than restating its list is what keeps the two from
    drifting: an exclude added there changes what counts as blocked here.
    """
    tree = ast.parse(spec.read_text(encoding="utf-8"), filename=str(spec))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "fixed_excludes" for target in node.targets
        ):
            return set(ast.literal_eval(node.value))
    raise AssertionError("the spec has no literal fixed_excludes assignment")


def ancestors(module: str) -> set[str]:
    """Every package above a module, which a frozen import needs alongside it."""
    parts = module.split(".")
    return {".".join(parts[:depth]) for depth in range(1, len(parts))}


def reachable_modules(root: Path, entry_points: list[str]) -> set[str]:
    """Walk out from the frozen entry points and report what they can import."""
    found: set[str] = set()
    pending = list(entry_points)
    while pending:
        module = pending.pop()
        if module in found or not module.startswith(PACKAGE):
            continue
        source = source_of(root, module)
        if source is None:
            continue
        found.add(module)
        for site in import_sites(source, module):
            pending.extend(name for name in site.names if name.startswith(PACKAGE))
        pending.extend(ancestors(module))
    return found


def _refused(name: str, refused: set[str]) -> bool:
    """Whether a frozen build refuses this name, package prefixes included."""
    parts = name.split(".")
    return any(".".join(parts[: depth + 1]) in refused for depth in range(len(parts)))


def blocked_modules(root: Path, modules: set[str], excluded: set[str]) -> set[str]:
    """Which of these modules a frozen build cannot import at all.

    A module is blocked when something it imports on the way in is excluded from
    the build and nothing catches the failure, and blocking travels outward: a
    module that imports a blocked one the same way is blocked in turn.
    """
    blocked = set(excluded)
    while True:
        found = {
            module
            for module in modules
            if module not in blocked
            and any(
                site.run_on_import and not site.guarded and any(_refused(name, blocked) for name in site.names)
                for site in import_sites(source_of(root, module), module)
            )
        }
        if not found:
            return blocked - excluded
        blocked |= found


def unguarded_importers(root: Path, modules: set[str], blocked: set[str]) -> dict[str, set[str]]:
    """Which modules import something the build cannot supply, with no handler."""
    offenders: dict[str, set[str]] = {}
    for module in sorted(modules - blocked):
        reached = {
            name
            for site in import_sites(source_of(root, module), module)
            if not site.guarded
            for name in site.names
            if _refused(name, blocked)
        }
        if reached:
            offenders[module] = reached
    return offenders


__all__ = [
    "PACKAGE",
    "ImportSite",
    "ancestors",
    "blocked_modules",
    "import_sites",
    "reachable_modules",
    "source_of",
    "spec_excludes",
    "unguarded_importers",
]
