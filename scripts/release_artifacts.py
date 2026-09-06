"""Fail-closed, final-byte release tooling for Calibrate Pro Windows artifacts."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

try:  # imported as `scripts.release_artifacts` from the test suite
    from scripts.product_version import PORTABLE_NAME, SDIST_NAME
except ModuleNotFoundError:  # run as `python scripts/release_artifacts.py`
    from product_version import PORTABLE_NAME, SDIST_NAME

MAXIMUM_BYTES = 350 * 1024 * 1024
_NATIVE_SUFFIXES = {".dll", ".exe", ".pyd"}
_FORBIDDEN_PATH_PARTS = {
    "_internal/ada92cb5d92a588d1b93__mypyc",
    "_internal/api-ms-win-",
    "_internal/charset_normalizer/",
    "_internal/psutil",
    "_internal/pyside6/opengl32sw.dll",
    "_internal/pyside6/plugins/iconengines/qsvgicon.dll",
    "_internal/pyside6/plugins/imageformats/qpdf.dll",
    "_internal/pyside6/plugins/imageformats/qsvg.dll",
    "_internal/pyside6/qt6pdf.dll",
    "_internal/pyside6/qt6svg.dll",
    "_internal/pyside6/translations/",
    "_internal/pyside6_addons-",
    "_internal/pywin32",
    "_internal/ucrtbase.dll",
    "pyqt5",
    "pyqt6",
    "torch",
    "transformers",
    "pandas",
    "jupyter",
    "opencv",
    "cv2",
}


Policy = str | Path | Mapping[str, Any]


def _load_policy(policy: Policy) -> tuple[dict[str, Any], Path | None]:
    if isinstance(policy, Mapping):
        return dict(policy), None
    path = Path(policy).resolve()
    return json.loads(path.read_text(encoding="utf-8")), path


def _validate_fail_closed_policy(data: Mapping[str, Any], label: str) -> None:
    if data.get("schema_version") != 1 or data.get("default") != "reject":
        raise RuntimeError(f"{label} policy must be schema 1 with default=reject")


def _validate_literal_policy(data: Mapping[str, Any], label: str) -> None:
    if data.get("schema_version") != 2 or data.get("default") != "reject" or data.get("path_mode") != "literal-posix":
        raise RuntimeError(f"{label} policy must be schema 2 with default=reject and path_mode=literal-posix")


def _literal_posix_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{label} must be a non-empty literal POSIX path")
    if "\\" in value:
        raise RuntimeError(f"{label} must use POSIX separators, not backslashes: {value}")
    if any(character in value for character in "*?[]"):
        raise RuntimeError(f"{label} contains a wildcard instead of a literal path: {value}")
    if value.startswith("/") or (len(value) >= 2 and value[1] == ":"):
        raise RuntimeError(f"{label} cannot be absolute: {value}")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise RuntimeError(f"{label} contains traversal or a non-canonical segment: {value}")
    normalized = PurePosixPath(value).as_posix()
    if normalized != value:
        raise RuntimeError(f"{label} is not a canonical literal POSIX path: {value}")
    return value


def _named_lock_components(data: Mapping[str, Any], label: str) -> set[str]:
    if data.get("schema_version") != 1:
        raise RuntimeError(f"{label} provenance policy must be schema 1")
    entries = data.get("components")
    if not isinstance(entries, list):
        raise RuntimeError(f"{label} provenance policy components must be a list")
    names: set[str] = set()
    folded: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("name"), str) or not entry["name"]:
            raise RuntimeError(f"{label} provenance component lacks a name")
        name = str(entry["name"])
        if name.casefold() in folded:
            raise RuntimeError(f"duplicate {label} provenance component: {name}")
        names.add(name)
        folded.add(name.casefold())
    return names


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolved_directories(staged_dir: str | Path, release_dir: str | Path) -> tuple[Path, Path]:
    staged = Path(staged_dir).resolve()
    release = Path(release_dir).resolve()
    if not staged.is_dir():
        raise FileNotFoundError(f"staged directory does not exist: {staged}")
    try:
        release.relative_to(staged)
    except ValueError:
        pass
    else:
        raise ValueError("release directory cannot be inside the staged tree")
    return staged, release


def _iter_files(root: Path) -> list[Path]:
    return sorted(
        (path for path in root.rglob("*") if path.is_file()), key=lambda path: path.relative_to(root).as_posix()
    )


def _toc_entries(value: object) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    type_codes = {
        "BINARY",
        "DATA",
        "DEPENDENCY",
        "EXTENSION",
        "PYMODULE",
        "PYMODULE-1",
        "PYMODULE-2",
        "PYSOURCE",
        "PYSOURCE-1",
        "PYSOURCE-2",
    }

    def visit(node: object) -> None:
        if isinstance(node, (list, tuple)):
            if (
                len(node) >= 3
                and isinstance(node[0], str)
                and isinstance(node[1], str)
                and isinstance(node[-1], str)
                and node[-1] in type_codes
            ):
                entries.append((node[0], node[1], node[-1]))
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            for key, item in node.items():
                visit(key)
                visit(item)

    visit(value)
    return entries


def audit_analysis_toc(analysis_toc: str | Path, module_policy: Policy) -> dict[str, Any]:
    """Reject unapproved first-party modules and forbidden GUI/binding roots.

    The first-party checks read every entry in the analysis table of contents,
    so they hold wherever the build ran. The distribution-roots check does not.
    It can only name the distribution a dependency came from by reading the
    path segment after ``site-packages``, so a build whose dependencies resolve
    from anywhere else contributes no observed roots and the check passes on an
    empty set. That covers an editable install, a ``pip install --target``
    directory, and a layout that imports from a directory not named
    ``site-packages``. Read a pass as bounding the dependency set only for a
    build run inside the locked release virtual environment.
    """
    toc_path = Path(analysis_toc).resolve()
    try:
        toc_value = ast.literal_eval(toc_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        raise RuntimeError(f"could not parse analysis TOC {toc_path}: {exc}") from exc
    policy, _ = _load_policy(module_policy)
    _validate_fail_closed_policy(policy, "module")
    required = set(policy.get("first_party_exact", []))
    optional = set(policy.get("optional_first_party_exact", []))
    approved = required | optional
    if any("*" in name for name in approved):
        raise RuntimeError("module policy contains a wildcard")

    toc_entries = _toc_entries(toc_value)
    observed = {name for name, _, _ in toc_entries}
    prohibited = sorted(
        name
        for name in observed
        if name in {"PyQt5", "PyQt6", "build_color.gui"} or name.startswith(("PyQt5.", "PyQt6.", "build_color.gui."))
    )
    if prohibited:
        raise RuntimeError("forbidden analysis modules: " + ", ".join(prohibited))
    observed_first_party = {name for name in observed if name == "calibrate_pro" or name.startswith("calibrate_pro.")}
    unexpected = sorted(observed_first_party - approved)
    if unexpected:
        raise RuntimeError("unapproved first-party modules: " + ", ".join(unexpected))
    missing = sorted(required - observed_first_party)
    if missing:
        raise RuntimeError("required first-party modules absent from analysis: " + ", ".join(missing))
    roots = policy.get("distribution_roots")
    if not isinstance(roots, list) or any(not isinstance(root, str) or not root for root in roots):
        raise RuntimeError("module policy distribution_roots must be a list of non-empty names")
    allowed_roots = set(roots)
    if any(any(character in root for character in "*?[]") for root in allowed_roots):
        raise RuntimeError("module policy distribution_roots contains a wildcard")
    observed_distribution_roots: set[str] = set()
    pure_types = {"PYMODULE", "PYMODULE-1", "PYMODULE-2", "PYSOURCE", "PYSOURCE-1", "PYSOURCE-2"}
    for _, source_path, type_code in toc_entries:
        parts = source_path.replace("\\", "/").split("/")
        folded_parts = [part.casefold() for part in parts]
        if type_code not in pure_types or "site-packages" not in folded_parts:
            continue
        site_packages_index = folded_parts.index("site-packages")
        if site_packages_index + 1 >= len(parts) or not parts[site_packages_index + 1]:
            raise RuntimeError(f"site-packages TOC entry lacks a distribution root: {source_path}")
        root = parts[site_packages_index + 1]
        if "." in root:
            root = PurePosixPath(root).stem
        if root == "calibrate_pro":
            continue
        observed_distribution_roots.add(root)
    unexpected_roots = sorted(observed_distribution_roots - allowed_roots)
    if unexpected_roots:
        raise RuntimeError("unapproved site-packages distribution roots: " + ", ".join(unexpected_roots))
    return {
        "schema_version": 1,
        "analysis_toc": toc_path.name,
        "first_party_modules": sorted(observed_first_party),
        "distribution_roots": sorted(observed_distribution_roots),
        "module_count": len(observed),
    }


def _requires_component_classification(relative: str) -> bool:
    path = PurePosixPath(relative)
    if path.suffix.casefold() in _NATIVE_SUFFIXES:
        return True
    if any(part.casefold().endswith(".dist-info") for part in path.parts):
        return True
    return relative == "_internal/base_library.zip"


def _notice_exists(staged: Path, notice_dir: Path | None, notice_path: str) -> bool:
    relative = PurePosixPath(notice_path)
    candidates = [staged.joinpath(*relative.parts), staged.joinpath("_internal", *relative.parts)]
    if notice_dir is not None:
        candidates.append(notice_dir.joinpath(*relative.parts))
        candidates.append(notice_dir.parent.joinpath(*relative.parts))
        if relative.parts and relative.parts[0].casefold() == "third_party_licenses":
            candidates.append(notice_dir.joinpath(*relative.parts[1:]))
    return any(candidate.is_file() for candidate in candidates)


def _component_catalog(
    policy: Mapping[str, Any],
    *,
    source_names: set[str],
    binary_names: set[str],
) -> dict[str, dict[str, Any]]:
    _validate_literal_policy(policy, "component")
    unexpected_policy_fields = sorted(
        set(policy) - {"schema_version", "default", "path_mode", "components", "artifacts"}
    )
    if unexpected_policy_fields:
        raise RuntimeError("component policy has unknown fields: " + ", ".join(unexpected_policy_fields))
    entries = policy.get("components")
    if not isinstance(entries, list):
        raise RuntimeError("component policy components must be a list")
    catalog: dict[str, dict[str, Any]] = {}
    folded_ids: set[str] = set()
    required_fields = {"id", "owner", "version", "license", "notice_paths", "provenance"}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise RuntimeError("component entries must be objects")
        missing_fields = sorted(required_fields - set(entry))
        if missing_fields:
            raise RuntimeError("component entry lacks " + ", ".join(missing_fields))
        unexpected_fields = sorted(set(entry) - required_fields - {"qt_component"})
        if unexpected_fields:
            raise RuntimeError("component entry has unknown fields: " + ", ".join(unexpected_fields))
        for field in ("id", "owner", "version", "license"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                raise RuntimeError(f"component entry lacks {field}")
        component_id = str(entry["id"])
        if component_id.casefold() in folded_ids:
            raise RuntimeError(f"duplicate component id or casefold collision: {component_id}")
        if "qt_component" in entry and entry["qt_component"] is not True:
            raise RuntimeError(f"component {component_id} qt_component may only be true when present")

        raw_notices = entry.get("notice_paths")
        if not isinstance(raw_notices, list) or not raw_notices:
            raise RuntimeError(f"component {component_id} notice_paths must be a non-empty list")
        notice_paths: list[str] = []
        notice_folds: set[str] = set()
        for raw_notice in raw_notices:
            notice = _literal_posix_path(raw_notice, f"component {component_id} notice path")
            if (
                notice != "LICENSE"
                and not notice.startswith("THIRD_PARTY_LICENSES/")
                and notice not in {"dwm_lut/LICENSE", "dwm_lut/LICENSE-THIRD-PARTY"}
            ):
                raise RuntimeError(
                    f"component {component_id} notice path is outside the approved notice roots: {notice}"
                )
            if notice.casefold() in notice_folds:
                raise RuntimeError(f"duplicate notice path for component {component_id}: {notice}")
            notice_paths.append(notice)
            notice_folds.add(notice.casefold())

        raw_provenance = entry.get("provenance")
        if not isinstance(raw_provenance, list) or not raw_provenance:
            raise RuntimeError(f"component {component_id} provenance must be a non-empty list")
        provenance: list[dict[str, str]] = []
        seen_references: set[tuple[str, str]] = set()
        for reference in raw_provenance:
            if not isinstance(reference, Mapping) or set(reference) != {"kind", "name"}:
                raise RuntimeError(f"component {component_id} has a malformed provenance reference")
            kind = reference.get("kind")
            name = reference.get("name")
            if kind not in {"source", "binary", "release_source"} or not isinstance(name, str) or not name:
                raise RuntimeError(f"component {component_id} has an invalid provenance reference")
            key = (kind, name)
            if key in seen_references:
                raise RuntimeError(f"component {component_id} has duplicate provenance reference {kind}:{name}")
            if kind == "source" and name not in source_names:
                raise RuntimeError(f"source provenance missing for component {component_id}: {name}")
            if kind == "binary" and name not in binary_names:
                raise RuntimeError(f"binary provenance missing for component {component_id}: {name}")
            if kind == "release_source" and (name != SDIST_NAME or entry["owner"] != "calibrate-pro"):
                raise RuntimeError(f"release_source is restricted to calibrate-pro and {SDIST_NAME}")
            provenance.append({"kind": str(kind), "name": name})
            seen_references.add(key)
        if entry["owner"] == "calibrate-pro" and not any(
            reference["kind"] == "release_source" for reference in provenance
        ):
            raise RuntimeError(f"first-party component {component_id} lacks release_source provenance")

        normalized: dict[str, Any] = {
            "id": component_id,
            "owner": str(entry["owner"]),
            "version": str(entry["version"]),
            "license": str(entry["license"]),
            "notice_paths": notice_paths,
            "provenance": provenance,
        }
        if entry.get("qt_component") is True:
            normalized["qt_component"] = True
        catalog[component_id] = normalized
        folded_ids.add(component_id.casefold())
    return catalog


def _artifact_assignments(
    policy: Mapping[str, Any],
    *,
    label: str,
    valid_component_ids: set[str],
) -> dict[str, list[str]]:
    _validate_literal_policy(policy, label)
    expected_policy_fields = {"schema_version", "default", "path_mode", "artifacts"}
    if label == "component":
        expected_policy_fields.add("components")
    unexpected_policy_fields = sorted(set(policy) - expected_policy_fields)
    if unexpected_policy_fields:
        raise RuntimeError(f"{label} policy has unknown fields: " + ", ".join(unexpected_policy_fields))
    entries = policy.get("artifacts")
    if not isinstance(entries, list):
        raise RuntimeError(f"{label} policy artifacts must be a list")
    assignments: dict[str, list[str]] = {}
    folded_paths: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"paths", "component_ids"}:
            raise RuntimeError(f"{label} artifact entries require only paths and component_ids")
        raw_paths = entry.get("paths")
        component_ids = entry.get("component_ids")
        if not isinstance(raw_paths, list) or not raw_paths:
            raise RuntimeError(f"{label} artifact paths must be a non-empty list")
        if not isinstance(component_ids, list) or not component_ids:
            raise RuntimeError(f"{label} artifact component_ids must be a non-empty list")
        if any(not isinstance(item, str) or not item for item in component_ids):
            raise RuntimeError(f"{label} artifact component_ids must contain non-empty strings")
        if len(component_ids) != len(set(component_ids)):
            raise RuntimeError(f"{label} artifact has duplicate component ids")
        unknown_ids = sorted(set(component_ids) - valid_component_ids)
        if unknown_ids:
            raise RuntimeError(f"{label} artifact references unknown components: {', '.join(unknown_ids)}")
        for raw_path in raw_paths:
            path = _literal_posix_path(raw_path, f"{label} artifact path")
            folded = path.casefold()
            if folded in folded_paths:
                raise RuntimeError(
                    f"{label} artifact path duplicate or casefold collision: {folded_paths[folded]} and {path}"
                )
            assignments[path] = list(component_ids)
            folded_paths[folded] = path
    return assignments


def audit_staged_tree(
    staged_dir: str | Path,
    *,
    component_policy: Policy,
    qt_policy: Policy,
    source_policy: Policy,
    binary_policy: Policy,
    notice_dir: str | Path | None = None,
    analysis_toc: str | Path | None = None,
    module_policy: Policy | None = None,
) -> dict[str, Any]:
    """Audit native ownership, notices, provenance, Qt classification, and size."""
    staged = Path(staged_dir).resolve()
    if not staged.is_dir():
        raise FileNotFoundError(staged)
    if analysis_toc is not None:
        if module_policy is None:
            raise ValueError("module policy is required with an analysis TOC")
        audit_analysis_toc(analysis_toc, module_policy)

    components, component_path = _load_policy(component_policy)
    qt_components, _ = _load_policy(qt_policy)
    sources, _ = _load_policy(source_policy)
    binaries, _ = _load_policy(binary_policy)
    source_names = _named_lock_components(sources, "source")
    binary_names = _named_lock_components(binaries, "binary")
    catalog = _component_catalog(components, source_names=source_names, binary_names=binary_names)
    assignments = _artifact_assignments(
        components,
        label="component",
        valid_component_ids=set(catalog),
    )
    referenced_component_ids = {
        component_id for component_ids in assignments.values() for component_id in component_ids
    }
    dead_components = sorted(set(catalog) - referenced_component_ids)
    if dead_components:
        raise RuntimeError("unreferenced component definitions: " + ", ".join(dead_components))
    qt_assignments = _artifact_assignments(
        qt_components,
        label="Qt",
        valid_component_ids=set(catalog),
    )
    expected_qt_assignments = {
        path: [component_id for component_id in component_ids if catalog[component_id].get("qt_component") is True]
        for path, component_ids in assignments.items()
    }
    expected_qt_assignments = {
        path: component_ids for path, component_ids in expected_qt_assignments.items() if component_ids
    }
    if qt_assignments != expected_qt_assignments:
        raise RuntimeError("Qt artifact policy does not exactly match explicitly flagged qt_component ownership")
    notice_root = Path(notice_dir).resolve() if notice_dir is not None else None
    if notice_root is None and component_path is not None:
        candidate = component_path.parent.parent / "THIRD_PARTY_LICENSES"
        if candidate.is_dir():
            notice_root = candidate

    files = _iter_files(staged)
    actual_paths = [path.relative_to(staged).as_posix() for path in files]
    actual_by_fold: dict[str, str] = {}
    for relative in actual_paths:
        folded = relative.casefold()
        if folded in actual_by_fold:
            raise RuntimeError(f"staged path casefold collision: {actual_by_fold[folded]} and {relative}")
        actual_by_fold[folded] = relative
    actual_path_set = set(actual_paths)
    missing_declared = sorted(set(assignments) - actual_path_set)
    if missing_declared:
        raise RuntimeError("declared component paths do not exist: " + ", ".join(missing_declared))
    required_paths = {relative for relative in actual_paths if _requires_component_classification(relative)}
    missing_required = sorted(required_paths - set(assignments))
    if missing_required:
        raise RuntimeError("required staged paths lack component ownership: " + ", ".join(missing_required))
    total_bytes = sum(path.stat().st_size for path in files)
    if total_bytes > MAXIMUM_BYTES:
        raise RuntimeError(f"staged tree exceeds {MAXIMUM_BYTES} bytes: {total_bytes}")

    classified: list[dict[str, Any]] = []
    for path in files:
        relative = path.relative_to(staged).as_posix()
        lower = relative.casefold()
        forbidden = sorted(part for part in _FORBIDDEN_PATH_PARTS if part in lower)
        if forbidden:
            raise RuntimeError(f"forbidden staged path {relative}: {', '.join(forbidden)}")
        if b"UPX!" in path.read_bytes()[: 1024 * 1024]:
            raise RuntimeError(f"UPX marker found in {relative}")

        component_ids = assignments.get(relative)
        if component_ids is None:
            continue
        normalized_components = [catalog[component_id] for component_id in component_ids]
        for component in normalized_components:
            for notice_path in component["notice_paths"]:
                if not _notice_exists(staged, notice_root, str(notice_path)):
                    raise RuntimeError(f"notice missing for {relative}: {notice_path}")

        record = {
            "path": relative,
            "components": normalized_components,
            "qt_component_ids": qt_assignments.get(relative, []),
            "size": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        classified.append(record)

    return {
        "schema_version": 2,
        "total_bytes": total_bytes,
        "file_count": len(files),
        "classified": sorted(classified, key=lambda item: item["path"]),
    }


def _zip_timestamp(epoch: int) -> tuple[int, int, int, int, int, int]:
    minimum = int(datetime(1980, 1, 1, tzinfo=timezone.utc).timestamp())
    maximum = int(datetime(2107, 12, 31, 23, 59, 58, tzinfo=timezone.utc).timestamp())
    moment = datetime.fromtimestamp(max(minimum, min(maximum, int(epoch))), timezone.utc)
    return (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second - moment.second % 2)


def write_reproducible_zip(
    staged_dir: str | Path,
    output_path: str | Path,
    *,
    epoch: int,
) -> str:
    """Write a stable compressed archive with one safe top-level directory."""
    staged = Path(staged_dir).resolve()
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _zip_timestamp(epoch)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in _iter_files(staged):
            relative = path.relative_to(staged).as_posix()
            info = zipfile.ZipInfo(f"CalibratePro/{relative}", date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return _sha256_file(output)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _staged_inventory(staged: Path, classified: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_path = {str(item["path"]): item for item in classified}
    records: list[dict[str, Any]] = []
    for path in _iter_files(staged):
        relative = path.relative_to(staged).as_posix()
        record = {
            "path": relative,
            "size": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        component = by_path.get(relative)
        if component is not None:
            record.update(
                {
                    "components": component["components"],
                    "qt_component_ids": component["qt_component_ids"],
                }
            )
        records.append(record)
    return {"schema_version": 2, "files": records}


def _copy_notices(notice_dir: str | Path | None, staged: Path) -> None:
    if notice_dir is None:
        return
    source = Path(notice_dir).resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"notice directory does not exist: {source}")
    for destination in (
        staged / "THIRD_PARTY_LICENSES",
        staged / "_internal" / "THIRD_PARTY_LICENSES",
    ):
        shutil.copytree(source, destination, dirs_exist_ok=True)
    repository_license = source.parent / "LICENSE"
    if not repository_license.is_file():
        raise FileNotFoundError(f"repository LICENSE does not exist: {repository_license}")
    shutil.copy2(repository_license, staged / "LICENSE")
    shutil.copy2(repository_license, staged / "_internal" / "LICENSE")


def _stage_runtime_policies(
    staged: Path,
    *,
    component_policy: Policy,
    qt_policy: Policy,
    module_policy: Policy,
    source_policy: Policy,
    binary_policy: Policy,
) -> None:
    """Put the audited policies where the frozen runtime and recipients can read them."""
    internal_packaging = staged / "_internal" / "packaging"
    for filename, policy in (
        ("components-win64.json", component_policy),
        ("qt-components.json", qt_policy),
        ("frozen-modules.json", module_policy),
        ("source-provenance.lock.json", source_policy),
        ("binary-provenance.lock.json", binary_policy),
    ):
        data, _ = _load_policy(policy)
        _write_json(internal_packaging / filename, data)

    source_data, _ = _load_policy(source_policy)
    for destination in (
        staged / "THIRD_PARTY_LICENSES" / "source-provenance.json",
        staged / "_internal" / "THIRD_PARTY_LICENSES" / "source-provenance.json",
    ):
        _write_json(destination, source_data)

    binary_data, _ = _load_policy(binary_policy)
    for destination in (
        staged / "THIRD_PARTY_LICENSES" / "binary-provenance.json",
        staged / "_internal" / "THIRD_PARTY_LICENSES" / "binary-provenance.json",
    ):
        _write_json(destination, binary_data)


def stage(
    staged_dir: str | Path,
    release_dir: str | Path,
    *,
    analysis_toc: str | Path,
    component_policy: Policy,
    qt_policy: Policy,
    module_policy: Policy,
    source_policy: Policy,
    binary_policy: Policy,
    notice_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Copy notices and emit a pre-sign audit without final inventories or ZIP."""
    staged, release = _resolved_directories(staged_dir, release_dir)
    release.mkdir(parents=True, exist_ok=True)
    _copy_notices(notice_dir, staged)
    _stage_runtime_policies(
        staged,
        component_policy=component_policy,
        qt_policy=qt_policy,
        module_policy=module_policy,
        source_policy=source_policy,
        binary_policy=binary_policy,
    )
    toc_receipt = audit_analysis_toc(analysis_toc, module_policy)
    tree_receipt = audit_staged_tree(
        staged,
        component_policy=component_policy,
        qt_policy=qt_policy,
        source_policy=source_policy,
        binary_policy=binary_policy,
        notice_dir=notice_dir,
    )
    receipt = {
        "schema_version": 1,
        "phase": "pre-sign",
        "analysis": toc_receipt,
        "staged": tree_receipt,
    }
    _write_json(release / "pre-sign-audit.json", receipt)
    return receipt


def package(
    staged_dir: str | Path,
    release_dir: str | Path,
    *,
    epoch: int,
    analysis_toc: str | Path,
    component_policy: Policy,
    qt_policy: Policy,
    module_policy: Policy,
    source_policy: Policy,
    binary_policy: Policy,
    notice_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Regenerate final inventories and ZIP from the current post-sign bytes."""
    staged, release = _resolved_directories(staged_dir, release_dir)
    release.mkdir(parents=True, exist_ok=True)
    toc_receipt = audit_analysis_toc(analysis_toc, module_policy)
    tree_receipt = audit_staged_tree(
        staged,
        component_policy=component_policy,
        qt_policy=qt_policy,
        source_policy=source_policy,
        binary_policy=binary_policy,
        notice_dir=notice_dir,
    )
    inventory = _staged_inventory(staged, tree_receipt["classified"])
    _write_json(release / "staged-inventory.json", inventory)
    _write_json(
        release / "component-inventory.json",
        {"schema_version": 2, "components": tree_receipt["classified"]},
    )
    _write_json(
        release / "qt-module-inventory.json",
        {
            "schema_version": 2,
            "components": [item for item in tree_receipt["classified"] if item["qt_component_ids"]],
        },
    )
    source_data, _ = _load_policy(source_policy)
    _write_json(release / "source-provenance.json", source_data)
    binary_data, _ = _load_policy(binary_policy)
    _write_json(release / "binary-provenance.json", binary_data)
    archive = release / PORTABLE_NAME
    archive_hash = write_reproducible_zip(staged, archive, epoch=epoch)
    receipt = {
        "schema_version": 1,
        "phase": "package",
        "analysis": toc_receipt,
        "staged": tree_receipt,
        "portable_zip": archive.name,
        "portable_sha256": archive_hash,
    }
    _write_json(release / "package-receipt.json", receipt)
    return receipt


def probe_authenticode(path: str | Path) -> dict[str, Any]:
    """Return a stable JSON projection of Windows Authenticode state."""
    target = Path(path).resolve()
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$securityModule = Join-Path $PSHOME "
        "'Modules\\Microsoft.PowerShell.Security\\Microsoft.PowerShell.Security.psd1'; "
        "Import-Module -Name $securityModule -Force -ErrorAction Stop; "
        "$target = $env:CALIBRATE_PRO_AUTHENTICODE_TARGET; "
        "if ([string]::IsNullOrWhiteSpace($target)) { throw 'missing Authenticode target' }; "
        "$signature = Get-AuthenticodeSignature -LiteralPath $target; "
        "$signerThumbprint = if ($null -ne $signature.SignerCertificate) "
        "{ $signature.SignerCertificate.Thumbprint } else { $null }; "
        "$signerSubject = if ($null -ne $signature.SignerCertificate) "
        "{ $signature.SignerCertificate.Subject } else { $null }; "
        "$timestampThumbprint = if ($null -ne $signature.TimeStamperCertificate) "
        "{ $signature.TimeStamperCertificate.Thumbprint } else { $null }; "
        "[ordered]@{Status=$signature.Status.ToString(); SignerThumbprint=$signerThumbprint; "
        "SignerSubject=$signerSubject; "
        "TimestampThumbprint=$timestampThumbprint} | ConvertTo-Json -Compress"
    )
    environment = os.environ.copy()
    environment.pop("PSModulePath", None)
    environment["CALIBRATE_PRO_AUTHENTICODE_TARGET"] = str(target)
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload.get("Status"), str):
        raise RuntimeError(f"invalid Authenticode status for {target}")
    return payload


def write_sha256s(release_dir: str | Path) -> Path:
    """Write sorted hashes for all release files except the checksum file itself."""
    release = Path(release_dir).resolve()
    checksum_path = release / "SHA256SUMS.txt"
    records = []
    for path in _iter_files(release):
        if path == checksum_path:
            continue
        relative = path.relative_to(release).as_posix()
        records.append((relative, _sha256_file(path)))
    lines = [f"{digest}  {relative}" for relative, digest in sorted(records)]
    checksum_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return checksum_path


def finalize(
    staged_dir: str | Path,
    release_dir: str | Path,
    *,
    installer: str | Path | None,
    expected_signer_thumbprint: str | None = None,
) -> dict[str, Any]:
    """Verify final artifact sizes, embedded EXE bytes, signatures, and hashes."""
    staged, release = _resolved_directories(staged_dir, release_dir)
    installer_path = Path(installer).resolve() if installer is not None else None
    archive = release / PORTABLE_NAME
    artifacts = [archive]
    if installer_path is not None:
        artifacts.append(installer_path)
    for path in artifacts:
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size > MAXIMUM_BYTES:
            raise RuntimeError(f"release artifact exceeds {MAXIMUM_BYTES} bytes: {path.name}")

    staged_hashes = {name: _sha256_file(staged / name) for name in ("CalibratePro.exe", "CalibrateProCLI.exe")}
    with zipfile.ZipFile(archive) as zipped:
        for name, expected in staged_hashes.items():
            actual = hashlib.sha256(zipped.read(f"CalibratePro/{name}")).hexdigest()
            if actual != expected:
                raise RuntimeError(f"portable ZIP contains stale bytes for {name}")
    signature_paths = {
        "CalibratePro.exe": probe_authenticode(staged / "CalibratePro.exe"),
        "CalibrateProCLI.exe": probe_authenticode(staged / "CalibrateProCLI.exe"),
    }
    if installer_path is not None:
        signature_paths[installer_path.name] = probe_authenticode(installer_path)

    if expected_signer_thumbprint is not None:
        expected = expected_signer_thumbprint.replace(" ", "").upper()
        if not expected:
            raise ValueError("expected signer thumbprint must be non-empty")
        for name, signature in signature_paths.items():
            signer = str(signature.get("SignerThumbprint") or "").replace(" ", "").upper()
            if signature.get("Status") != "Valid":
                raise RuntimeError(f"signature is not Valid for {name}: {signature.get('Status')}")
            if signer != expected:
                raise RuntimeError(f"unexpected signer thumbprint for {name}")
            if not signature.get("TimestampThumbprint"):
                raise RuntimeError(f"trusted timestamp is missing for {name}")

    receipt = {
        "schema_version": 1,
        "signing_required": expected_signer_thumbprint is not None,
        "signatures": signature_paths,
    }
    _write_json(release / "signature-inventory.json", receipt)
    write_sha256s(release)
    return receipt


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--staged-dir", required=True)
    parser.add_argument("--release-dir", required=True)
    parser.add_argument("--analysis-toc", required=True)
    parser.add_argument("--component-policy", required=True)
    parser.add_argument("--qt-policy", required=True)
    parser.add_argument("--module-policy", required=True)
    parser.add_argument("--source-policy", required=True)
    parser.add_argument("--binary-policy", required=True)
    parser.add_argument("--notice-dir")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    stage_parser = commands.add_parser("stage")
    _common_arguments(stage_parser)
    package_parser = commands.add_parser("package")
    _common_arguments(package_parser)
    package_parser.add_argument("--source-date-epoch", type=int, required=True)
    finalize_parser = commands.add_parser("finalize")
    finalize_parser.add_argument("--staged-dir", required=True)
    finalize_parser.add_argument("--release-dir", required=True)
    finalize_parser.add_argument("--installer")
    finalize_parser.add_argument("--expected-signer-thumbprint")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "finalize":
        finalize(
            args.staged_dir,
            args.release_dir,
            installer=args.installer,
            expected_signer_thumbprint=args.expected_signer_thumbprint,
        )
        return 0
    common = {
        "analysis_toc": args.analysis_toc,
        "component_policy": args.component_policy,
        "qt_policy": args.qt_policy,
        "module_policy": args.module_policy,
        "source_policy": args.source_policy,
        "binary_policy": args.binary_policy,
        "notice_dir": args.notice_dir,
    }
    if args.command == "stage":
        stage(args.staged_dir, args.release_dir, **common)
    elif args.command == "package":
        package(
            args.staged_dir,
            args.release_dir,
            epoch=args.source_date_epoch,
            **common,
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
