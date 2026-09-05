"""Repository gates for the single confirmed display-actuation boundary.

These tests intentionally inspect source instead of importing GUI or Windows
modules.  That keeps the release gate deterministic and hardware-free while
still catching aliases and same-file wrapper methods around display writers.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPOSITORY_ROOT / "calibrate_pro"

APPLICATION_DIRECTORIES = (
    PACKAGE_ROOT / "gui",
    PACKAGE_ROOT / "services",
    PACKAGE_ROOT / "tray",
    PACKAGE_ROOT / "startup",
    PACKAGE_ROOT / "commands",
)
APPLICATION_ENTRYPOINTS = (
    PACKAGE_ROOT / "main.py",
    PACKAGE_ROOT / "app.py",
    PACKAGE_ROOT / "frozen_main.py",
)

# Each module below exposes a path that can change Windows display or monitor
# state.  Application code must use ActuationCoordinator and its injected
# adapter instead of reaching through these legacy modules.
WRITER_CAPABLE_MODULES = frozenset(
    {
        "calibrate_pro.calibration.hardware_first",
        "calibrate_pro.core.vcgt",
        "calibrate_pro.hardware",
        "calibrate_pro.hardware.ddc_ci",
        "calibrate_pro.hardware.hardware_calibration",
        "calibrate_pro.hardware.sensorless_calibration",
        "calibrate_pro.lut_system",
        "calibrate_pro.lut_system.color_loader",
        "calibrate_pro.lut_system.dwm_lut",
        "calibrate_pro.lut_system.per_display_calibration",
        "calibrate_pro.lut_system.vcgt_calibration",
        "calibrate_pro.panels.detection",
        "calibrate_pro.profiles",
        "calibrate_pro.profiles.profile_installer",
        "calibrate_pro.profiles.vcgt",
        "calibrate_pro.sensorless.auto_calibration",
        "calibrate_pro.startup.calibration_loader",
        "calibrate_pro.startup.lut_autoload",
        "calibrate_pro.utils.auto_calibration",
    }
)

# Exact callable names only: a helper such as ``_set_vcp_safe`` is discovered
# through the local call graph, not by substring matching.
DISPLAY_WRITER_CALLS = frozenset(
    {
        "AutoCalibrationEngine",
        "ColorLoader",
        "DDCCIController",
        "DwmLutController",
        "HardwareCalibrationEngine",
        "IsUserAnAdmin",
        "SetDeviceGammaRamp",
        "ShellExecuteW",
        "apply_gamma_ramp",
        "apply_saved_calibrations",
        "apply_vcgt_windows",
        "auto_calibrate",
        "auto_calibrate_all",
        "auto_setup_for_calibration",
        "clear_lut",
        "get_color_loader",
        "install_profile",
        "load_icc_profile",
        "load_identity",
        "load_lut",
        "load_lut_file",
        "remove_lut",
        "reset_gamma_ramp",
        "reset_vcgt_windows",
        "run_as_admin",
        "run_hardware_calibration",
        "run_hardware_first_calibration",
        "set_display_profile",
        "set_gamma_ramp",
        "set_lut",
        "set_vcp",
        "start_dwm_lut_gui",
        "try_set_vcp",
        "uninstall_profile",
        "unload_lut",
    }
)

# Reading an instrument is not a display mutation, so nothing above catches it.
# It is still a measurement. A surface that opens the device for itself produces
# one outside the session that decides whether a measurement may be taken, gives
# it an evidence kind and a receipt, and records that it happened. The prefix is
# used rather than a list of submodule names so that a driver added later is
# covered on the day it lands.
INSTRUMENT_READER_PREFIXES = ("calibrate_pro.hardware",)
INSTRUMENT_READER_MODULES = frozenset({"calibrate_pro.sensorless.camera_calibration"})


def reads_an_instrument(module: str) -> bool:
    """Whether importing this name puts a colorimeter or camera read within reach."""
    if module in INSTRUMENT_READER_MODULES:
        return True
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in INSTRUMENT_READER_PREFIXES)


@dataclass(frozen=True, order=True)
class BoundaryViolation:
    """One stable source location that crosses the actuation boundary."""

    path: str
    line: int
    owner: str
    kind: str
    target: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.owner}: {self.kind}: {self.target}"


@dataclass(frozen=True)
class CallSite:
    """A resolved call and, when possible, its same-file call-graph edge."""

    line: int
    owner: str
    raw_target: str
    resolved_target: str
    local_target: str | None
    directly_writes: bool


@dataclass(frozen=True)
class SourceAnalysis:
    """Boundary facts derived from one parsed application module."""

    path: Path
    import_violations: tuple[BoundaryViolation, ...]
    call_sites: tuple[CallSite, ...]
    reader_violations: tuple[BoundaryViolation, ...]

    @property
    def relative_path(self) -> str:
        return self.path.relative_to(REPOSITORY_ROOT).as_posix()

    def dangerous_owner_names(self) -> frozenset[str]:
        """Return owners that write directly or call a local writer wrapper."""
        dangerous = {site.owner for site in self.call_sites if site.directly_writes}
        changed = True
        while changed:
            changed = False
            for site in self.call_sites:
                if site.local_target in dangerous and site.owner not in dangerous:
                    dangerous.add(site.owner)
                    changed = True
        return frozenset(dangerous)

    def call_violations(self) -> tuple[BoundaryViolation, ...]:
        """Return direct writes plus calls through same-file writer wrappers."""
        dangerous_owners = self.dangerous_owner_names()
        violations: list[BoundaryViolation] = []
        for site in self.call_sites:
            if site.directly_writes:
                kind = "direct display writer call"
                target = site.resolved_target
            elif site.local_target in dangerous_owners:
                kind = "local wrapper reaches display writer"
                target = site.local_target or site.raw_target
            else:
                continue
            violations.append(
                BoundaryViolation(
                    path=self.relative_path,
                    line=site.line,
                    owner=site.owner,
                    kind=kind,
                    target=target,
                )
            )
        return tuple(sorted(set(violations)))


def application_source_paths() -> tuple[Path, ...]:
    """Return the frozen application-surface scan set, including future entrypoints."""
    sources = {
        source for directory in APPLICATION_DIRECTORIES if directory.is_dir() for source in directory.rglob("*.py")
    }
    sources.update(source for source in APPLICATION_ENTRYPOINTS if source.is_file())
    return tuple(sorted(sources))


def _attribute_parts(node: ast.expr) -> tuple[str, ...]:
    parts: list[str] = []
    cursor: ast.expr = node
    while isinstance(cursor, ast.Attribute):
        parts.append(cursor.attr)
        cursor = cursor.value
    if isinstance(cursor, ast.Name):
        parts.append(cursor.id)
        return tuple(reversed(parts))
    return tuple(reversed(parts))


class _BoundaryVisitor(ast.NodeVisitor):
    """Resolve import aliases, exact actuator calls, and local call edges."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.relative_path = path.relative_to(REPOSITORY_ROOT).as_posix()
        self.import_aliases: dict[str, str] = {}
        self.import_violations: list[BoundaryViolation] = []
        self.reader_violations: list[BoundaryViolation] = []
        self.call_sites: list[CallSite] = []
        self._classes: list[str] = []
        self._functions: list[str] = []

    @property
    def owner(self) -> str:
        if self._functions:
            names = [*self._classes, *self._functions]
            return ".".join(names)
        return "<module>"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802 - ast visitor API
        self._classes.append(node.name)
        self.generic_visit(node)
        self._classes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802 - ast visitor API
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802 - ast visitor API
        self._functions.append(node.name)
        self.generic_visit(node)
        self._functions.pop()

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802 - ast visitor API
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            resolved = alias.name if alias.asname else local_name
            self.import_aliases[local_name] = resolved
            if alias.name in WRITER_CAPABLE_MODULES:
                self._record_import(node.lineno, alias.name)
            elif reads_an_instrument(alias.name):
                self._record_reader_import(node.lineno, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802 - ast visitor API
        module = node.module or ""
        for alias in node.names:
            local_name = alias.asname or alias.name
            resolved = ".".join(part for part in (module, alias.name) if part)
            self.import_aliases[local_name] = resolved
            if module in WRITER_CAPABLE_MODULES:
                self._record_import(node.lineno, resolved)
            elif reads_an_instrument(module):
                self._record_reader_import(node.lineno, resolved)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast visitor API
        raw_target = self._raw_callable(node.func)
        resolved_target = self._resolve_callable(node.func)
        terminal = resolved_target.rsplit(".", 1)[-1]
        directly_writes = terminal in DISPLAY_WRITER_CALLS and not self._is_safe_call(node, terminal)
        self.call_sites.append(
            CallSite(
                line=node.lineno,
                owner=self.owner,
                raw_target=raw_target,
                resolved_target=resolved_target,
                local_target=self._local_target(node.func),
                directly_writes=directly_writes,
            )
        )
        self.generic_visit(node)

    def _record_import(self, line: int, target: str) -> None:
        self.import_violations.append(
            BoundaryViolation(
                path=self.relative_path,
                line=line,
                owner=self.owner,
                kind="imports writer-capable module",
                target=target,
            )
        )

    def _record_reader_import(self, line: int, target: str) -> None:
        self.reader_violations.append(
            BoundaryViolation(
                path=self.relative_path,
                line=line,
                owner=self.owner,
                kind="imports an instrument-reading module",
                target=target,
            )
        )

    @staticmethod
    def _raw_callable(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        parts = _attribute_parts(node)
        return ".".join(parts) if parts else ast.dump(node, include_attributes=False)

    def _resolve_callable(self, node: ast.expr) -> str:
        parts = _attribute_parts(node)
        if isinstance(node, ast.Name):
            return self.import_aliases.get(node.id, node.id)
        if not parts:
            return ast.dump(node, include_attributes=False)
        imported = self.import_aliases.get(parts[0])
        if imported is None:
            return ".".join(parts)
        return ".".join((imported, *parts[1:]))

    def _local_target(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            if node.id in self.import_aliases:
                return None
            return node.id
        parts = _attribute_parts(node)
        if len(parts) == 2 and parts[0] in {"self", "cls"} and self._classes:
            return f"{self._classes[-1]}.{parts[1]}"
        return None

    def _is_safe_call(self, node: ast.Call, terminal: str) -> bool:
        """Allow only the named in-memory preview/status operations."""
        if self.relative_path == "calibrate_pro/gui/lut_preview.py":
            if self.owner in {"LUTPreviewWidget.load_lut", "LUTPreviewWidget.load_identity"}:
                return terminal in {"load_identity", "load_lut", "set_lut"}

        if self.relative_path == "calibrate_pro/gui/workers.py":
            if self.owner in {"ColorManagementStatus.set_lut", "ColorManagementStatus.clear_lut"}:
                return terminal in {"clear_lut", "set_lut"}

        if self.relative_path == "calibrate_pro/gui/main_window.py" and terminal in {"clear_lut", "set_lut"}:
            return _attribute_parts(node.func) in {
                ("self", "cm_status", "clear_lut"),
                ("self", "cm_status", "set_lut"),
            }
        return False


def analyze_source(path: Path) -> SourceAnalysis:
    """Parse one source file without importing or executing it."""
    return analyze_text(path, path.read_text(encoding="utf-8"))


def analyze_text(path: Path, source: str) -> SourceAnalysis:
    """Analyze an in-memory module, including virtual paths used by scanner tests."""
    tree = ast.parse(source, filename=str(path))
    visitor = _BoundaryVisitor(path)
    visitor.visit(tree)
    return SourceAnalysis(
        path=path,
        import_violations=tuple(sorted(set(visitor.import_violations))),
        call_sites=tuple(visitor.call_sites),
        reader_violations=tuple(sorted(set(visitor.reader_violations))),
    )


def application_analyses() -> tuple[SourceAnalysis, ...]:
    return tuple(analyze_source(path) for path in application_source_paths())


def format_violations(title: str, violations: list[BoundaryViolation] | tuple[BoundaryViolation, ...]) -> str:
    rendered = "\n".join(f"  - {violation.render()}" for violation in sorted(set(violations)))
    return f"{title} ({len(set(violations))}):\n{rendered}"


def test_only_injected_adapter_may_import_writer_capable_modules() -> None:
    violations = [violation for analysis in application_analyses() for violation in analysis.import_violations]

    assert not violations, format_violations(
        "Application surfaces must not import writer-capable low-level modules; use ActuationCoordinator",
        violations,
    )


def test_application_surfaces_have_no_direct_or_wrapped_display_writer_calls() -> None:
    violations = [violation for analysis in application_analyses() for violation in analysis.call_violations()]

    assert not violations, format_violations(
        "Application surfaces must route every display mutation through confirmed actuation",
        violations,
    )


def test_startup_modules_never_call_display_writers() -> None:
    startup_root = PACKAGE_ROOT / "startup"
    violations = [
        violation
        for analysis in application_analyses()
        if analysis.path.is_relative_to(startup_root)
        for violation in analysis.call_violations()
    ]

    assert not violations, format_violations(
        "Startup code may observe state but must not mutate a display automatically",
        violations,
    )


def test_scanner_resolves_aliases_and_local_wrappers_without_substrings() -> None:
    analysis = analyze_text(
        PACKAGE_ROOT / "gui" / "boundary_probe.py",
        """
from calibrate_pro.lut_system.dwm_lut import remove_lut as remove_display_lut

def restore():
    remove_display_lut(0)

class Page:
    def apply(self):
        self._set_vcp_safe()

    def _set_vcp_safe(self):
        controller.set_vcp({}, 0x10, 50)
""",
    )
    aliased_remove = next(call for call in analysis.call_sites if call.raw_target == "remove_display_lut")
    assert aliased_remove.resolved_target == "calibrate_pro.lut_system.dwm_lut.remove_lut"
    assert aliased_remove.directly_writes is True

    wrapper_call = next(call for call in analysis.call_sites if call.raw_target == "self._set_vcp_safe")
    assert wrapper_call.raw_target == "self._set_vcp_safe"
    assert wrapper_call.directly_writes is False
    assert wrapper_call.local_target == "Page._set_vcp_safe"
    assert any(
        violation.owner == "Page.apply" and violation.kind == "local wrapper reaches display writer"
        for violation in analysis.call_violations()
    )


def test_lut_name_exceptions_are_limited_to_preview_and_in_memory_status_calls() -> None:
    preview = analyze_text(
        PACKAGE_ROOT / "gui" / "lut_preview.py",
        """
class LUTPreviewWidget:
    def load_lut(self, lut):
        self.cube_view.set_lut(lut)

    def load_identity(self):
        self.load_lut(object())

class ActuatingWidget:
    def load_lut(self, lut):
        self.controller.set_lut(lut)
""",
    )
    preview_lut_calls = [
        call for call in preview.call_sites if call.resolved_target.rsplit(".", 1)[-1] in DISPLAY_WRITER_CALLS
    ]
    assert [call.directly_writes for call in preview_lut_calls] == [False, False, True]

    status = analyze_text(
        PACKAGE_ROOT / "gui" / "main_window.py",
        """
class MainWindow:
    def refresh(self):
        self.cm_status.set_lut('primary', 'preview.cube')
        self.cm_status.clear_lut('primary')
        self.controller.clear_lut('primary')
""",
    )
    status_lut_calls = [
        call for call in status.call_sites if call.resolved_target.rsplit(".", 1)[-1] in DISPLAY_WRITER_CALLS
    ]
    assert [call.directly_writes for call in status_lut_calls] == [False, False, True]


def test_no_application_surface_opens_an_instrument_for_itself() -> None:
    """A measurement belongs to the session, including the decision to take one.

    Three surfaces reached past it. A dashboard card polled a colorimeter over
    raw HID every 800ms and painted each reply as luminance, correlated colour
    temperature and tristimulus values, behind an action the manifest declares
    hidden. A welcome dialog opened the bus for a product string. A DDC page's
    detect button enumerated devices through ArgyllCMS and reported the first
    one as found. None of the three produced an evidence kind, a receipt or a
    journal entry, and the availability each claimed was its own.

    The writer boundary above did not cover any of them, because reading an
    instrument changes no display state. That is why this is a separate gate
    rather than another entry in the writer list.
    """
    violations = [violation for analysis in application_analyses() for violation in analysis.reader_violations]

    assert not violations, format_violations(
        "Application surfaces must let the session take measurements; they may not open an instrument",
        violations,
    )


def test_the_reader_gate_fires_on_a_driver_import_and_leaves_the_sensorless_engine_alone() -> None:
    """A false-success control. A gate nothing can trip is not evidence.

    The first two imports are the ones deleted from the shipped surfaces, so
    this fails if the check stops recognising them. The third is the sensorless
    engine, which computes from a panel model and opens nothing, so a gate that
    flagged it would push a page toward measuring to get its number back.
    """
    analysis = analyze_text(
        PACKAGE_ROOT / "gui" / "reader_probe.py",
        """
from calibrate_pro.hardware.i1d3_native import I1D3Driver
from calibrate_pro.hardware.argyll_backend import ArgyllBackend
from calibrate_pro.sensorless.neuralux import SensorlessEngine
""",
    )

    assert [violation.target for violation in analysis.reader_violations] == [
        "calibrate_pro.hardware.i1d3_native.I1D3Driver",
        "calibrate_pro.hardware.argyll_backend.ArgyllBackend",
    ]
    assert all(violation.kind == "imports an instrument-reading module" for violation in analysis.reader_violations)


def test_a_writer_module_is_reported_once_rather_than_under_both_boundaries() -> None:
    """Two names for one import reads as two problems and hides the count."""
    analysis = analyze_text(
        PACKAGE_ROOT / "gui" / "double_probe.py",
        "from calibrate_pro.hardware.ddc_ci import DDCCIController\n",
    )

    assert len(analysis.import_violations) == 1
    assert analysis.reader_violations == ()
