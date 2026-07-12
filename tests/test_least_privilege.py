"""Least-privilege release gates for application startup and monitoring."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.test_actuator_boundary import (
    DISPLAY_WRITER_CALLS,
    PACKAGE_ROOT,
    REPOSITORY_ROOT,
    BoundaryViolation,
    _attribute_parts,
    analyze_source,
    application_analyses,
    application_source_paths,
    format_violations,
)

ELEVATION_CALLS = frozenset({"IsUserAnAdmin", "ShellExecuteW", "run_as_admin"})
REGISTRY_WRITE_CALLS = frozenset(
    {
        "CreateKey",
        "CreateKeyEx",
        "DeleteKey",
        "DeleteKeyEx",
        "DeleteValue",
        "RegCreateKeyExA",
        "RegCreateKeyExW",
        "RegDeleteKeyA",
        "RegDeleteKeyW",
        "RegDeleteValueA",
        "RegDeleteValueW",
        "RegSetValueExA",
        "RegSetValueExW",
        "SetValue",
        "SetValueEx",
    }
)
CANONICAL_STARTUP_REGISTRY_WRITER = "calibrate_pro/utils/startup_manager.py"


def _relative(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def _resolved_terminal(node: ast.expr, aliases: dict[str, str]) -> tuple[str, str]:
    if isinstance(node, ast.Name):
        resolved = aliases.get(node.id, node.id)
        return resolved, resolved.rsplit(".", 1)[-1]
    parts = _attribute_parts(node)
    if not parts:
        rendered = ast.dump(node, include_attributes=False)
        return rendered, rendered
    imported = aliases.get(parts[0])
    resolved = ".".join((imported, *parts[1:])) if imported else ".".join(parts)
    return resolved, resolved.rsplit(".", 1)[-1]


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                aliases[local_name] = alias.name if alias.asname else local_name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                aliases[alias.asname or alias.name] = ".".join(part for part in (module, alias.name) if part)
    return aliases


def _owner_by_node(tree: ast.AST) -> dict[ast.AST, str]:
    owners: dict[ast.AST, str] = {}

    def walk(node: ast.AST, classes: tuple[str, ...], functions: tuple[str, ...]) -> None:
        next_classes = classes
        next_functions = functions
        if isinstance(node, ast.ClassDef):
            next_classes = (*classes, node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            next_functions = (*functions, node.name)
        owner = ".".join((*next_classes, *next_functions)) or "<module>"
        owners[node] = owner
        for child in ast.iter_child_nodes(node):
            walk(child, next_classes, next_functions)

    walk(tree, (), ())
    return owners


def _elevation_violations(path: Path) -> list[BoundaryViolation]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases = _import_aliases(tree)
    owners = _owner_by_node(tree)
    relative_path = _relative(path)
    violations: list[BoundaryViolation] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_as_admin":
            violations.append(
                BoundaryViolation(relative_path, node.lineno, owners[node], "defines elevation helper", node.name)
            )
        elif isinstance(node, ast.Call):
            resolved, terminal = _resolved_terminal(node.func, aliases)
            if terminal in ELEVATION_CALLS:
                violations.append(
                    BoundaryViolation(relative_path, node.lineno, owners[node], "requests process elevation", resolved)
                )
        elif (
            isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.strip().casefold() == "runas"
        ):
            violations.append(
                BoundaryViolation(relative_path, node.lineno, owners[node], "contains elevation verb", repr(node.value))
            )
    return sorted(set(violations))


def _contains_startup_registry_key(tree: ast.AST) -> bool:
    marker = "\\microsoft\\windows\\currentversion\\run"
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and marker in node.value.replace("/", "\\").casefold()
        for node in ast.walk(tree)
    )


def _startup_registry_write_violations(path: Path) -> list[BoundaryViolation]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    if not _contains_startup_registry_key(tree):
        return []
    aliases = _import_aliases(tree)
    owners = _owner_by_node(tree)
    relative_path = _relative(path)
    violations: list[BoundaryViolation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        resolved, terminal = _resolved_terminal(node.func, aliases)
        if terminal in REGISTRY_WRITE_CALLS and relative_path != CANONICAL_STARTUP_REGISTRY_WRITER:
            violations.append(
                BoundaryViolation(relative_path, node.lineno, owners[node], "writes Windows registry", resolved)
            )
    return sorted(set(violations))


def test_app_facing_sources_never_request_process_elevation() -> None:
    violations = [violation for path in application_source_paths() for violation in _elevation_violations(path)]

    assert not violations, format_violations(
        "Calibrate Pro must run as a standard user and request narrow capabilities only",
        violations,
    )


def test_constructors_never_mutate_display_state() -> None:
    violations: list[BoundaryViolation] = []
    for analysis in application_analyses():
        dangerous_owners = analysis.dangerous_owner_names()
        for call in analysis.call_sites:
            is_constructor = call.owner.rsplit(".", 1)[-1] == "__init__"
            reaches_writer = call.directly_writes or call.local_target in dangerous_owners
            if is_constructor and reaches_writer:
                violations.append(
                    BoundaryViolation(
                        path=analysis.relative_path,
                        line=call.line,
                        owner=call.owner,
                        kind="constructor display mutation",
                        target=call.resolved_target,
                    )
                )

    assert not violations, format_violations(
        "Constructors may wire dependencies but must never actuate a display",
        violations,
    )


def test_calibration_guard_is_monitor_only() -> None:
    guard = PACKAGE_ROOT / "services" / "calibration_guard.py"
    analysis = analyze_source(guard)
    violations = [*analysis.import_violations, *analysis.call_violations()]

    assert not violations, format_violations(
        "CalibrationGuard is monitor-only; restoration requires a fresh confirmed plan",
        violations,
    )


def test_only_canonical_startup_manager_writes_the_startup_registry() -> None:
    canonical = REPOSITORY_ROOT / CANONICAL_STARTUP_REGISTRY_WRITER
    assert canonical.is_file(), f"missing canonical startup registry writer: {CANONICAL_STARTUP_REGISTRY_WRITER}"

    violations = [
        violation
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        for violation in _startup_registry_write_violations(path)
    ]

    assert not violations, format_violations(
        f"Windows startup registry writes must be consolidated in {CANONICAL_STARTUP_REGISTRY_WRITER}",
        violations,
    )


def test_display_writer_name_set_covers_least_privilege_primitives() -> None:
    """Pin the primitives used by the constructor and monitor-only gates."""
    assert ELEVATION_CALLS <= DISPLAY_WRITER_CALLS
    assert {
        "DDCCIController",
        "SetDeviceGammaRamp",
        "apply_saved_calibrations",
        "load_lut_file",
        "set_vcp",
    } <= DISPLAY_WRITER_CALLS
